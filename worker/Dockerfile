FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY worker/requirements.txt ./worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY common ./common
COPY worker ./worker

USER appuser
EXPOSE 9100

CMD ["python", "-m", "worker.worker"]
