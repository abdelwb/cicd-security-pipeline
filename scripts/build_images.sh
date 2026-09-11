#!/usr/bin/env bash
# Build the gateway + worker images locally, tagged for k3s import.
set -euo pipefail

TAG="${1:-local}"
REGISTRY="${REGISTRY:-cicd-security-pipeline}"

echo "==> building ${REGISTRY}/gateway:${TAG}"
docker build -f gateway/Dockerfile -t "${REGISTRY}/gateway:${TAG}" .

echo "==> building ${REGISTRY}/worker:${TAG}"
docker build -f worker/Dockerfile -t "${REGISTRY}/worker:${TAG}" .

echo "==> done. Import into k3s with:"
echo "    docker save ${REGISTRY}/gateway:${TAG} | sudo k3s ctr images import -"
echo "    docker save ${REGISTRY}/worker:${TAG}  | sudo k3s ctr images import -"
