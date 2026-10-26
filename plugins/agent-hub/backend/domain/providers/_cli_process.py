"""CLI adapters delegate process ownership to the approved Core runtime."""
from __future__ import annotations

from typing import Any, Iterator

from domain.providers._local_runtime import runtime_call
from domain.providers.base import ProviderAdapter


class ManagedCliProvider(ProviderAdapter):
    def _start_cli(self, argv: list[str], task: dict[str, Any], filename: str) -> dict[str, Any]:
        return runtime_call('start', {'argv': argv, 'filename': filename})

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        yield from runtime_call('observe', {'reference': external_run_ref})

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        return runtime_call('cancel', {'reference': external_run_ref})
