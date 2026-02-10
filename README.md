## Установка Argo Workflow
 
kubectl create ns argo

kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.7.6/install.yaml

kubectl -n argo get deploy workflow-controller

kubectl -n argo get deploy argo-server

прокдивыем порты для UI
kubectl -n argo port-forward --address 0.0.0.0 svc/argo-server 2746:2746 > /dev/null &

## Установка argo CLI

curl -sLO https://github.com/argoproj/argo-workflows/releases/download/v3.7.6/argo-linux-amd64.gz
gunzip argo-linux-amd64.gz
chmod +x argo-linux-amd64
mv ./argo-linux-amd64 /usr/local/bin/argo

## Создание сервисного аккаунта

kubectl create serviceaccount argo-workflow -n argo


## Создание рабочего процесса
kubectl -n argo apply -f hello-workflow.yaml

## Создание виртуального окружения
sudo apt-get update
sudo apt-get install -y python3-full python3-venv
python3 -m venv ~/venv-argo-test
source ~/venv-argo-test/bin/activate
python -m pip install -U pip
python -m pip install "pytest>=7.0"
pip install pyyaml
pip install kubernetes

## Запуск тестов
Python
pytest -svv test_argo_hello_world.py

Java
mvn -q -Dtest=ArgoHelloWorkflowTest test