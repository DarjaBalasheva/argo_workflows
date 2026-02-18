## Структура проекта
- tests_yaml/ - директория с тестовыми сценариями для Argo Workflow
- workflow/ - директория с Argo Workflow манифестами
- python_test_interface - файл с кодом для запуска тестов на Python

## Для запуска тестов необходимо выполнить следующие шаги:
1. Положить тестовые сценарии в директорию `tests_yaml/`
2. Положить Argo Workflow манифесты в директорию `workflow/`
3. Запустить контейнер с тестами, который будет использовать Argo Workflow для выполнения тестов.

## Запуск контейнера с тестами
```bash
docker compose up --build argo-installer test-runner
```
Argo Workflow UI будет доступен по адресу https://127.0.0.1:32746
