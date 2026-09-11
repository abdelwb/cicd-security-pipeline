# cicd-security-pipeline

A small distributed job-processing app used as a testbed for a CI/CD pipeline
that actually does something: automated tests gating every change, and
vulnerability scanners wired directly into the merge request workflow.

- **Code lives on GitHub:** you're looking at it.
- **Pipeline lives on GitLab:** [gitlab.com/abdelwb/cicd-security-pipeline](https://gitlab.com/abdelwb/cicd-security-pipeline) —
  that's where `.gitlab-ci.yml` actually runs, because the point of this repo
  is demonstrating GitLab CI/CD and MR-integrated security scanning, not just
  writing the YAML for show. GitHub Actions runs a lightweight lint/test/build
  mirror (`.github/workflows/ci.yml`) so this copy stays green too.

## Architecture

```mermaid
flowchart LR
    client[Client] -->|POST /jobs| gateway[FastAPI Gateway]
    gateway -->|breaker-wrapped| redis[(Redis)]
    worker[Worker] -->|BLPOP| redis
    gateway -->|/metrics| prom[Prometheus-format metrics]
    worker -->|/metrics| prom
    client -->|GET /jobs/id| gateway
```

- **gateway** ([gateway/main.py](gateway/main.py)) — FastAPI service. Accepts
  job submissions, applies backpressure once the Redis queue is too long,
  and exposes `/health`, `/ready`, and `/metrics`.
- **worker** ([worker/worker.py](worker/worker.py)) — pulls jobs off the
  Redis list with `BLPOP`, updates job status, and understands a few
  `simulate` directives for testing failure modes (see below).
- **common** ([common/](common/)) — shared settings, Redis client, and the
  circuit breaker both services wrap around every Redis call.

## Run it locally

```bash
docker compose up --build
```

or use the smoke-test script, which also submits a sample job:

```bash
./scripts/run_local.sh
```

- Gateway: http://localhost:8000 (`/health`, `/ready`, `/metrics`, `/jobs`)
- Worker metrics: http://localhost:9100

## Failure-mode demos

Every demo is triggered through the normal `/jobs` API — nothing needs to be
rebuilt.

**Circuit breaker (Redis down).** Stop Redis while the gateway is running:

```bash
docker compose stop redis
curl -i -X POST localhost:8000/jobs -d '{"payload":{}}' -H 'content-type: application/json'
# first few calls fail slowly, then the breaker opens and every call fails
# fast with 503 until the reset timeout elapses and one probe is let through
curl -s localhost:8000/metrics | grep circuit_breaker_state
```

**Backpressure.** Push the queue past `MAX_QUEUE_LENGTH` (default 50) and new
submissions are rejected with `503` + `Retry-After` instead of queuing
forever:

```bash
for i in $(seq 1 60); do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/jobs \
    -d '{"payload":{"simulate":"slow","duration_s":30}}' -H 'content-type: application/json'
done
```

**OOM simulation.** Submit a job that allocates memory in the worker; under
k3s with the memory limit set in [k8s/worker-deployment.yaml](k8s/worker-deployment.yaml),
the kubelet OOMKills the pod and you can watch it restart:

```bash
curl -X POST localhost:8000/jobs -H 'content-type: application/json' \
  -d '{"payload":{"simulate":"oom","size_mb":512}}'
kubectl -n job-pipeline get pods -w
```

## Deploying to k3s

```bash
./scripts/build_images.sh v0.1
kubectl apply -f k8s/namespace.yaml -f k8s/configmap.yaml \
  -f k8s/redis-deployment.yaml -f k8s/gateway-deployment.yaml \
  -f k8s/worker-deployment.yaml -f k8s/hpa.yaml
```

## CI/CD & security automation

This is the part the rest of the repo exists to exercise. `.gitlab-ci.yml`
defines:

| Stage | Job(s) | What it does |
|---|---|---|
| lint | `lint` | `ruff check .` |
| test | `test` | pytest with coverage; JUnit + Cobertura reports surface pass/fail and coverage directly in the MR |
| test | `sast`, `secret_detection`, `dependency_scanning` | GitLab-managed scanners (via `include: template:`), findings shown in the MR Security widget |
| build | `build` | builds & pushes `gateway`/`worker` images to the project's Container Registry |
| security | `container_scanning`, `container_scanning_worker` | scans the two images just built for known CVEs |

The `workflow: rules` block runs this as a **merge request pipeline** whenever
an MR is open (falling back to a branch pipeline on `main` otherwise), which
is what makes GitLab attach scanner results to the MR itself instead of a
report nobody opens — a reviewer sees new/fixed vulnerabilities inline before
approving, the same way they see the diff.

`.github/workflows/ci.yml` runs a smaller lint/test/build job on GitHub so
this mirror's checks stay green; it isn't where the security scanning story
lives.

## Project layout

```
gateway/    FastAPI job-submission service
worker/     Redis-backed job processor + failure-mode simulators
common/     shared settings, Redis client, circuit breaker
tests/      pytest suite (fakeredis-backed, no external services needed)
k8s/        k3s manifests
scripts/    local build/run helpers
```
