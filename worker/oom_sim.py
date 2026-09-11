"""Deliberately allocate memory so an operator can watch k3s OOMKill and
restart the worker pod. Only triggered by an explicit job payload:

    {"simulate": "oom", "size_mb": 512}

Pair this with a low memory limit in k8s/worker-deployment.yaml so the
allocation actually gets killed instead of just pressuring the node.
"""
import time


def allocate_and_hold(size_mb: int) -> None:
    # One byte per element, allocated in one shot so RSS jumps immediately
    # instead of growing gradually (which the kernel/cgroup would otherwise
    # reclaim opportunistically before we ever hit the limit).
    block = bytearray(size_mb * 1024 * 1024)
    # Touch every page so it's actually resident, not just reserved.
    step = 4096
    for i in range(0, len(block), step):
        block[i] = 1
    # Intentionally leak the reference for a few seconds so the pod's RSS
    # stays high long enough for the kubelet to notice and OOMKill it.
    time.sleep(30)
    del block
