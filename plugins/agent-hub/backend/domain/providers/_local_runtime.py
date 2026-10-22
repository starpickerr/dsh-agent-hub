"""Local CLI probing, minimal environment and managed goal files."""

from __future__ import annotations

import os
import subprocess
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_SANDBOX = ContextVar('host_execution_sandbox', default=None)


@contextmanager
def execution_sandbox(plan):
    token = _SANDBOX.set(plan)
    try:
        yield
    finally:
        _SANDBOX.reset(token)


def bound_command(argv):
    plan = _SANDBOX.get()
    if not isinstance(plan, dict) or plan.get('mode') != 'isolated' or not plan.get('prefix'):
        raise PermissionError('Core execution sandbox required')
    env = sanitized_env()
    env.update(plan.get('env') or {})
    return [*plan['prefix'], *argv], env


def sanitized_env() -> dict[str, str]:
    """Minimal env: PATH + locale only — no credential dump."""
    keep = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "HOME", "TMPDIR", "TEMP", "TMP")
    env = {k: v for k in keep if (v := os.environ.get(k))}
    # Allow explicit auth markers without copying secrets wholesale.
    for key in ("CODEX_HOME", "CURSOR_API_KEY", "ANTHROPIC_API_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_version_probe(argv: list[str], *, timeout: float = 8.0) -> dict[str, Any]:
    try:
        argv, env = bound_command(argv)
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "binary_missing"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "probe_timeout"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    out = (result.stdout or result.stderr or "").strip()
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": out[:500],
    }


def write_goal_file(workspace: Path, goal: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / ".stella-agent-hub-goal.md"
    path.write_text(goal.strip() + "\n", encoding="utf-8")
    return path


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
