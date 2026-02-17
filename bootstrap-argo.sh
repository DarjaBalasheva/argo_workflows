#!/bin/sh
set -eu

echo "== Wait for cluster API (nodes) =="
for i in $(seq 1 60); do
  if kubectl get nodes >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "== Ensure argo namespace =="
kubectl get ns argo >/dev/null 2>&1 || kubectl create ns argo

echo "== Install/upgrade Argo Workflows v3.7.6 =="
kubectl apply -n argo -f "https://github.com/argoproj/argo-workflows/releases/download/v3.7.6/install.yaml"

echo "== Done =="

echo "== Patch argo-server service to NodePort ${ARGO_NODEPORT} =="
# Важно: патчим конкретно порт web, чтобы не снести другие порты/поля
kubectl -n argo patch svc argo-server --type='merge' -p "{
  \"spec\": {
    \"type\": \"NodePort\",
    \"ports\": [
      {\"name\":\"web\",\"port\":2746,\"targetPort\":2746,\"nodePort\":${ARGO_NODEPORT}}
    ]
  }
}"

echo "== Ensure serviceaccount argo-workflow exists =="
kubectl -n argo get sa argo-workflow >/dev/null 2>&1 || kubectl -n argo create sa argo-workflow


echo "== Add RBAC for workflowtaskresults (safe additive) =="
cat <<'YAML' | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argo-workflowtaskresults-writer
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["workflowtaskresults"]
    verbs: ["create","get","list","watch","patch","update","delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argo-workflowtaskresults-writer-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: argo-workflowtaskresults-writer
subjects:
  - kind: ServiceAccount
    name: argo-workflow
    namespace: argo
YAML

echo "== Verify RBAC (can-i) =="
kubectl -n argo auth can-i create workflowtaskresults.argoproj.io \
  --as=system:serviceaccount:argo:argo-workflow

echo "== Ensure --auth-mode=server on argo-server deployment =="
# если аргумент уже есть — не добавляем
if ! kubectl -n argo get deploy argo-server -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q -- '--auth-mode=server'; then
  kubectl -n argo patch deploy argo-server --type='json' -p='[
    {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--auth-mode=server"}
  ]'
else
  echo "   (already has --auth-mode=server)"
fi

echo "== Restart & wait rollout =="
kubectl -n argo rollout restart deploy/argo-server
kubectl -n argo rollout status deploy/argo-server --timeout=180s

echo "== Generate local kubeconfig (127.0.0.1) =="
# Оригинальный kubeconfig нужен installer внутри сети (k3s-argo:6443),
# для хоста делаем отдельный kubeconfig.local.yaml
if [ -f /kubeconfig/kubeconfig.yaml ]; then
  cp /kubeconfig/kubeconfig.yaml /kubeconfig/kubeconfig.local.yaml
  sed -i 's#https://k3s-argo:6443#https://127.0.0.1:6443#g' /kubeconfig/kubeconfig.local.yaml || true
fi

echo "✅ Argo installed. Host kubeconfig: ./kubeconfig/kubeconfig.local.yaml"
echo "   UI: https://127.0.0.1:${ARGO_NODEPORT}"
