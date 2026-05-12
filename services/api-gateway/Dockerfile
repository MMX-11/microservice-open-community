FROM python:3.12-slim

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    PIP_DEFAULT_TIMEOUT=120
COPY services/api-gateway/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel && python -m pip install --retries 10 --default-timeout 120 "pydantic>=2.11,<3" && python -m pip install --retries 10 --default-timeout 120 -r /app/requirements.txt

COPY services/api-gateway /app
COPY frontend /app/frontend

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
