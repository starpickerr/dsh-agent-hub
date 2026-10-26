"""Local CLI probing, minimal environment and managed goal files."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_SANDBOX = ContextVar('host_execution_sandbox', default=None)


@contextmanager
def execution_sandbox(plan):
    token = _SANDBOX.set(plan)
    try:
        yield
    finally:
        _SANDBOX.reset(token)


def runtime_call(method, payload):
    plan = _SANDBOX.get()
    if method in {'start', 'probe'} and (not isinstance(plan, dict) or plan.get('mode') != 'core'):
        raise PermissionError('Core execution runtime required')
    import stella_host
    result = stella_host.invoke('stella.runtime@1', method, payload)
    if result.get('status') != 'succeeded':
        raise RuntimeError('Core runtime rejected the operation')
    return result['value']


def run_version_probe(argv: list[str], *, timeout: float = 8.0) -> dict[str, Any]:
    return runtime_call('probe', {'argv': argv})


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
