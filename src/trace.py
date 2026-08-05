"""Ghi trace.jsonl - mot dong JSON cho moi buoc handoff giua cac agent.

File duoc TRUNCATE khi bat dau moi lan chay (de bai yeu cau chi giu lan chay
moi nhat, khong append chong len lan truoc).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import config


class TraceWriter:
    def __init__(self, path: Path | None = None):
        self.path = path or config.TRACE_PATH
        self._fh = None
        self.count = 0

    def __enter__(self) -> "TraceWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")  # truncate
        return self

    def __exit__(self, *exc) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def emit(
        self,
        case_id: str,
        agent: str,
        step: int,
        event: str,
        handoff_to: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "case_id": case_id,
            "step": step,
            "agent": agent,
            "event": event,
            "handoff_to": handoff_to,
            "payload": payload or {},
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        self.count += 1
