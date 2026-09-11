#!/usr/bin/env bash
# Bring the whole stack up locally with docker-compose and smoke-test it.
set -euo pipefail

docker compose up -d --build
echo "==> waiting for gateway to become ready"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8000/health > /dev/null; then
    break
  fi
  sleep 1
done

echo "==> submitting a test job"
curl -s -X POST http://localhost:8000/jobs -H 'content-type: application/json' \
  -d '{"payload": {"simulate": "slow", "duration_s": 1}}' | tee /dev/stderr

echo
echo "==> gateway metrics: http://localhost:8000/metrics"
echo "==> worker metrics:  http://localhost:9100"
echo "==> tail logs with: docker compose logs -f"
