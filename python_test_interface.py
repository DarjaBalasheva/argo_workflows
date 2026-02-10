import argparse
import glob
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


import yaml
from kubernetes import client, config

ARGO_GROUP = "argoproj.io"
ARGO_VERSION = "v1alpha1"
ARGO_PLURAL = "workflows"


# ---------------- duration helpers ----------------
def parse_duration_to_seconds(s: str) -> int:
    s = str(s).strip().lower()
    if s.endswith("ms"):
        return max(1, int(int(s[:-2]) / 1000))
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    return int(s)


# ---------------- scenario model ----------------
@dataclass
class TestScenario:
    path: Path
    name: str
    description: str
    tags: List[str]
    timeout_seconds: int
    namespace: str
    expect: Dict[str, Any]
    workflow_inline: Optional[Dict[str, Any]] = None
    workflow_file: Optional[Path] = None


def load_scenarios_from_dir(tests_dir: str | Path) -> List[TestScenario]:
    tests_dir = Path(tests_dir).resolve()
    paths = sorted(Path(p).resolve() for p in glob.glob(str(tests_dir / "*.yaml")))
    if not paths:
        raise FileNotFoundError(f"No *.yaml scenarios found in: {tests_dir}")

    scenarios: List[TestScenario] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        wf_inline = data.get("workflow")
        wf_file_raw = data.get("workflowFile")
        wf_file = (path.parent / wf_file_raw).resolve() if wf_file_raw else None

        # ровно один источник workflow
        if (wf_inline is None) == (wf_file is None):
            raise ValueError(f"{path}: define exactly one of workflow OR workflowFile")

        scenarios.append(
            TestScenario(
                path=path,
                name=data["name"],
                description=data.get("description", ""),
                tags=data.get("tags", []),
                timeout_seconds=parse_duration_to_seconds(data.get("timeout", "10m")),
                namespace=data.get("namespace", "argo"),
                expect=data.get("expect", {}),
                workflow_inline=wf_inline,
                workflow_file=wf_file,
            )
        )

    return scenarios


def load_workflow_manifest(s: TestScenario) -> Dict[str, Any]:
    if s.workflow_inline is not None:
        return s.workflow_inline

    assert s.workflow_file is not None
    with s.workflow_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------- argo/k8s ops ----------------
def submit_workflow(custom: client.CustomObjectsApi, namespace: str, wf: Dict[str, Any]) -> Dict[str, Any]:
    return custom.create_namespaced_custom_object(
        group=ARGO_GROUP,
        version=ARGO_VERSION,
        namespace=namespace,
        plural=ARGO_PLURAL,
        body=wf,
    )


def get_workflow(custom: client.CustomObjectsApi, namespace: str, name: str) -> Dict[str, Any]:
    return custom.get_namespaced_custom_object(
        group=ARGO_GROUP,
        version=ARGO_VERSION,
        namespace=namespace,
        plural=ARGO_PLURAL,
        name=name,
    )


def wait_workflow(custom: client.CustomObjectsApi, namespace: str, name: str, timeout_seconds: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_phase = None

    while time.time() < deadline:
        wf = get_workflow(custom, namespace, name)
        phase = ((wf.get("status") or {}).get("phase")) or "Unknown"
        if phase != last_phase:
            print(f"    phase={phase}")
            last_phase = phase

        if phase in ("Succeeded", "Failed", "Error"):
            return wf

        time.sleep(2)

    raise TimeoutError(f"Workflow {namespace}/{name} did not finish within {timeout_seconds}s")


def read_pod_logs(core: client.CoreV1Api, namespace: str, pod_name: str) -> str:
    """Read logs from *all* containers in a Pod.

    Argo pods usually have multiple containers (e.g. 'main' + 'wait').
    If you read logs without specifying a container, Kubernetes may return logs
    for a non-business container (often 'wait'), so we aggregate logs from each
    container to make assertions reliable.
    """
    pod = core.read_namespaced_pod(name=pod_name, namespace=namespace)

    containers = [c.name for c in (pod.spec.containers or [])]
    init_containers = [c.name for c in (pod.spec.init_containers or [])]

    # Prefer 'main' first; keep everything else afterwards.
    def _order(names: list[str]) -> list[str]:
        if "main" in names:
            return ["main"] + [n for n in names if n != "main"]
        return names

    ordered_containers = _order(containers)
    ordered_inits = _order(init_containers)

    chunks: list[str] = []

    # Init containers first (rarely useful for business logs, but great for debugging)
    for cname in ordered_inits:
        try:
            log = core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=cname,
                timestamps=False,
            )
        except Exception as e:
            log = f"<failed to read init container logs: {e}>"
        chunks.append(f" --- initContainer: {cname} --- {log}")

    # Regular containers
    for cname in ordered_containers:
        try:
            log = core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=cname,
                timestamps=False,
            )
        except Exception as e:
            log = f"<failed to read container logs: {e}>"
        chunks.append(f" --- container: {cname} --- {log}")

    return "".join(chunks).lstrip()


def _nodes_with_display_name(nodes: Dict[str, Dict[str, Any]], display_name: str) -> List[str]:
    return [node_id for node_id, n in nodes.items() if n.get("displayName") == display_name]


def _derive_pod_name_from_pod_node(node_id: str, wf_name: str, template_name: Optional[str]) -> Optional[str]:
    """
    В твоём окружении Argo UI показывает:
      node_id:  <wf_name>-<suffix>
      podName:  <wf_name>-<templateName>-<suffix>
    """
    if not template_name:
        return None

    prefix = wf_name + "-"
    if not node_id.startswith(prefix):
        return None

    suffix = node_id[len(prefix):]
    if not suffix:
        return None

    return f"{wf_name}-{template_name}-{suffix}"


def _pod_name_from_node(nodes: Dict[str, Dict[str, Any]], node_id: str, wf_name: str) -> Optional[str]:
    n = nodes.get(node_id) or {}

    # 1) если Argo заполнил podName — берём его
    if n.get("podName"):
        return n["podName"]

    # 2) если это Pod-нода, но podName отсутствует — пробуем вычислить
    if n.get("type") == "Pod":
        return _derive_pod_name_from_pod_node(node_id, wf_name, n.get("templateName"))

    return None


def _find_podname_in_subtree(nodes: Dict[str, Dict[str, Any]], node_id: str, wf_name: str) -> Optional[str]:
    direct = _pod_name_from_node(nodes, node_id, wf_name)
    if direct:
        return direct

    n = nodes.get(node_id) or {}
    for child_id in n.get("children") or []:
        found = _find_podname_in_subtree(nodes, child_id, wf_name)
        if found:
            return found
    return None


def resolve_pod_name(nodes: Dict[str, Dict[str, Any]], wf_name: str, display_name: str) -> str:
    start_ids = _nodes_with_display_name(nodes, display_name)
    if not start_ids:
        available = sorted({n.get("displayName") for n in nodes.values() if n.get("displayName")})
        raise AssertionError(
            f"Node '{display_name}' not found in status.nodes. "
            f"Available displayNames (sample): {available[:30]}"
        )

    for node_id in start_ids:
        pod = _find_podname_in_subtree(nodes, node_id, wf_name)
        if pod:
            return pod

    debug = []
    for node_id in start_ids:
        n = nodes.get(node_id) or {}
        debug.append(
            f"id={node_id} type={n.get('type')} templateName={n.get('templateName')} "
            f"phase={n.get('phase')} children={len(n.get('children') or [])}"
        )
    raise AssertionError(
        f"Node '{display_name}' found, but podName not resolvable via children.\n  - " + "\n  - ".join(debug)
    )




# ---------------- assertions ----------------
def assert_expectations(core: client.CoreV1Api, wf: Dict[str, Any], expect: Dict[str, Any]) -> None:
    status = wf.get("status") or {}
    got_phase = status.get("phase")

    # 1) Workflow phase
    exp_phase = expect.get("workflowPhase")
    if exp_phase and got_phase != exp_phase:
        raise AssertionError(f"Expected workflowPhase={exp_phase}, got {got_phase}")

    # 2) Max duration
    max_d = expect.get("maxDuration")
    if max_d and status.get("startedAt") and status.get("finishedAt"):
        started = datetime.fromisoformat(status["startedAt"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(status["finishedAt"].replace("Z", "+00:00"))
        dur = (finished - started).total_seconds()
        if dur > parse_duration_to_seconds(max_d):
            raise AssertionError(f"Expected duration <= {max_d}, got {dur:.1f}s")

    nodes_expect = expect.get("nodes") or []
    if not nodes_expect:
        return

    wf_ns = wf["metadata"]["namespace"]
    nodes: Dict[str, Dict[str, Any]] = status.get("nodes") or {}

    # Индекс по displayName -> список нод (на всякий случай, если displayName повторяется)
    by_display: Dict[str, List[Dict[str, Any]]] = {}
    for _, node in nodes.items():
        dn = node.get("displayName")
        if dn:
            by_display.setdefault(dn, []).append(node)

    for n in nodes_expect:
        selector = n.get("selector") or {}
        dn = selector.get("displayName") or n.get("displayName")
        if not dn:
            raise AssertionError("Node expect entry missing displayName (use nodes[].selector.displayName)")

        if dn not in by_display:
            available = sorted(by_display.keys())
            raise AssertionError(
                f"Node '{dn}' not found in workflow status.nodes. "
                f"Available displayNames (sample): {available[:30]}"
            )

        # Phase check: считаем ок, если хотя бы одна из нод с этим displayName в нужной фазе
        exp_node_phase = n.get("phase")
        if exp_node_phase:
            phases = [x.get("phase") for x in by_display[dn]]
            if exp_node_phase not in phases:
                raise AssertionError(f"Node '{dn}': expected phase={exp_node_phase}, got phases={phases}")

        # Logs check
        logs_spec = n.get("logs") or {}
        contains = logs_spec.get("contains") or []
        if contains:
            # 1) попробуем найти podName прямо среди нод с этим displayName
            pod_name = None
            for node_obj in by_display[dn]:
                if node_obj.get("podName"):
                    pod_name = node_obj["podName"]
                    break

            # 2) если не нашли — резолвим через children (логическая step-нода -> pod-нода)
            if not pod_name:
                wf_name = wf["metadata"]["name"]
                pod_name = resolve_pod_name(nodes, wf_name, dn)

            logs = read_pod_logs(core, wf_ns, pod_name)

            for needle in contains:
                if needle not in logs:
                    raise AssertionError(
                        f"Node '{dn}': expected logs to contain '{needle}', but not found.\n--- logs ---\n{logs}"
                    )


# ---------------- runner ----------------
def run_one_scenario(
    custom: client.CustomObjectsApi,
    core: client.CoreV1Api,
    s: TestScenario
) -> Tuple[bool, str]:
    print(f"\n=== RUN: {s.name}")
    print(f"  file: {s.path.name}")
    print(f"  tags={s.tags} ns={s.namespace} timeout={s.timeout_seconds}s")

    wf = load_workflow_manifest(s)
    created = submit_workflow(custom, s.namespace, wf)
    wf_name = created["metadata"]["name"]
    print(f"  submitted: {s.namespace}/{wf_name}")

    final_wf = wait_workflow(custom, s.namespace, wf_name, s.timeout_seconds)
    final_phase = ((final_wf.get("status") or {}).get("phase")) or "Unknown"
    print(f"  finished: phase={final_phase}")

    assert_expectations(core, final_wf, s.expect)
    return True, wf_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="tests_yaml", help="Folder with test scenario YAMLs")
    ap.add_argument("--tag", action="append", default=[], help="Run only scenarios containing tag (repeatable)")
    ap.add_argument("--name", default=None, help="Run only scenarios where name contains substring")
    args = ap.parse_args()

    scenarios = load_scenarios_from_dir(args.dir)

    # filters
    if args.name:
        scenarios = [s for s in scenarios if args.name.lower() in s.name.lower()]
    if args.tag:
        need = set(t.lower() for t in args.tag)
        scenarios = [s for s in scenarios if need.issubset(set(t.lower() for t in s.tags))]

    if not scenarios:
        raise SystemExit("No scenarios matched filters")

    # kube auth
    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()

    custom = client.CustomObjectsApi()
    core = client.CoreV1Api()

    passed = 0
    failed = 0

    for s in scenarios:
        try:
            ok, wf_name = run_one_scenario(custom, core, s)
            print(f"✅ PASSED: {s.path.name} (wf={wf_name})")
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {s.path.name}: {e}")
            failed += 1

    print(f"\n=== SUMMARY ===")
    print(f"passed: {passed}")
    print(f"failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
