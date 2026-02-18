FROM python:3.12

# kubectl (под твою версию k3s 1.29.x)
ARG KUBECTL_VERSION=v1.29.1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates bash \
    && curl -L "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pipenv
COPY Pipfile Pipfile.lock /app/
RUN pipenv install --deploy --system

COPY python_test_interface.py /app/python_test_interface.py
COPY tests_yaml /app/tests_yaml
COPY workflows /app/workflows

ENV PYTHONUNBUFFERED=1
