#!/bin/sh
set -e

echo "Installing Argo Workflows..."

kubectl create ns argo || true

kubectl apply -n argo \
  -f https://github.com/argoproj/argo-workflows/releases/download/v3.7.6/install.yaml

kubectl patch svc argo-server -n argo \
  -p '{"spec":{"type":"NodePort","ports":[{"port":2746,"targetPort":2746,"nodePort":2746}]}}'

kubectl create serviceaccount argo-workflow -n argo || true

echo "Argo Workflows installed"
