FROM python:3.12-slim

WORKDIR /app
COPY services/benchmark-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/benchmark-service /app
COPY benchmarks /app/benchmarks

EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]

