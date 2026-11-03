"""CLI adapters delegate process ownership to the approved Core runtime."""
from __future__ import annotations

from typing import Any, Iterator

from domain.providers._local_runtime import runtime_call
from domain.providers.base import ProviderAdapter


class ManagedCliProvider(ProviderAdapter):
    @staticmethod
    def task_prompt(task):
        persona = (task.get('runConfig') or {}).get('persona') or ''
        return (f"任务内人设（不改变权限与审批）：\n{persona}\n\n" if persona else '') + (task.get('goal') or '')

    @staticmethod
    def model_args(task):
        selection = (task.get('runConfig') or {}).get('modelSelection') or {'mode': 'default'}
        if selection.get('mode') != 'explicit':
            return []
        from domain.collaboration import text
        import re
        model = text(selection.get('modelId'), 'modelId', 160)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+\[\]=,-]*', model):
            raise ValueError('invalid modelId')
        return ['--model', model]

    def _start_cli(self, argv: list[str], task: dict[str, Any], filename: str) -> dict[str, Any]:
        return runtime_call('start', {'argv': argv, 'filename': filename})

    def observe(self, external_run_ref: str, after_cursor: int = 0) -> Iterator[dict[str, Any]]:
        yield from runtime_call('observe', {'reference': external_run_ref, 'after_cursor': after_cursor})

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        return runtime_call('cancel', {'reference': external_run_ref})
