## Установка Argo Workflow
```bash
docker compose up -d
```

Argo Workflow UI будет доступен по адресу http://127.0.0.1:32746

## Запуск тестов
```bash
export KUBECONFIG="$PWD/kubeconfig/kubeconfig.local.yaml" 
python python_test_interface.py --dir tests_yaml
```

## Запуск тестов по тегам
```bash
export KUBECONFIG="$PWD/kubeconfig/kubeconfig.local.yaml" 
python python_test_interface.py --dir tests_yaml --tags "tag1,tag2"
```