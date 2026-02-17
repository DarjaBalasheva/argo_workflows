import os
import subprocess
import time

NS = os.getenv("ARGO_NAMESPACE", "argo")
WF_FILE = os.getenv("WORKFLOW_YAML", "workflows/hello-workflow.yaml")

def run_workflow(cmd: list[str], timeout: int = 120, check: bool = True) -> str:
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\nOutput:\n{p.stdout}")
    return p.stdout

def wait_workflow(wf_name: str, max_seconds: int = 90) -> str:
    deadline = time.time() + max_seconds
    last_phase = ""
    while time.time() < deadline:
        phase = run_workflow(
            ["kubectl", "get", "wf", "-n", NS, wf_name, "-o", "jsonpath={.status.phase}"],
            timeout=30
        ).strip()

        if phase and phase != last_phase:
            print("Phase:", phase)
            last_phase = phase

        if phase in ("Succeeded", "Failed", "Error"):
            return phase

        time.sleep(2)

    return last_phase or "Unknown"


def test_workflow_succeeds_and_prints_hello_world():
    print(f"NS={NS} WF_FILE={WF_FILE}")

    run_workflow(["argo", "version"], timeout=30)

    wf_name = run_workflow(["argo", "submit", "-n", NS, "--output", "name", WF_FILE], timeout=60).strip()
    assert wf_name, "Workflow name is empty"
    print("Submitted:", wf_name)

    try:
        print("Waiting (polling status.phase)...")
        phase = wait_workflow(wf_name, max_seconds=90)
        assert phase == "Succeeded", f"Workflow did not succeed: phase={phase}"

        logs = run_workflow(["argo", "logs", "-n", NS, wf_name], timeout=60)
        assert "hello world" in logs, f"Expected 'hello world' in logs, got:\n{logs}"

    finally:
        run_workflow(["argo", "delete", "-n", NS, wf_name, "--yes"], timeout=30, check=False)