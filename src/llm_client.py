"""Client LLM theo chuan OpenAI-compatible.

Nguyen tac: LLM la thanh phan CO THE HONG. Moi loi (thieu key, timeout, JSON
sai) deu tra ve LLMResult(ok=False) thay vi raise, de pipeline van chay tiep
bang ket qua deterministic.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def load_dotenv(path: Path | None = None) -> None:
    """Doc .env thu cong de khong them dependency. Khong ghi de bien da co."""
    path = path or (config.ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    error: str = ""
    latency_ms: int = 0


class LLMClient:
    def __init__(self):
        load_dotenv()
        self.model = config.MODEL_NAME
        self._client = None
        self._init_error = ""
        try:
            from openai import OpenAI

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                self._init_error = "OPENAI_API_KEY chua duoc set trong .env"
            else:
                kwargs = {"api_key": api_key, "timeout": config.MODEL_TIMEOUT_S}
                if config.MODEL_BASE_URL:
                    kwargs["base_url"] = config.MODEL_BASE_URL
                self._client = OpenAI(**kwargs)
        except Exception as exc:  # pragma: no cover - phu thuoc moi truong
            self._init_error = f"khong khoi tao duoc client: {exc}"

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete_json(self, system: str, user: str) -> LLMResult:
        """Goi model va ep ve JSON object. Khong bao gio raise."""
        if not self.available:
            return LLMResult(ok=False, error=self._init_error or "LLM khong san sang")

        started = time.time()
        last_error = ""
        for attempt in range(config.MODEL_MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    temperature=config.MODEL_TEMPERATURE,
                    max_tokens=config.MODEL_MAX_TOKENS,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                raw = (resp.choices[0].message.content or "").strip()
                data = self._parse(raw)
                latency = int((time.time() - started) * 1000)
                if data is None:
                    last_error = "khong parse duoc JSON"
                    continue
                return LLMResult(ok=True, data=data, raw=raw, latency_ms=latency)
            except Exception as exc:
                last_error = str(exc)[:300]
                if attempt < config.MODEL_MAX_RETRIES:
                    time.sleep(1.5 * (attempt + 1))
        return LLMResult(
            ok=False,
            error=last_error,
            latency_ms=int((time.time() - started) * 1000),
        )

    @staticmethod
    def _parse(raw: str) -> dict[str, Any] | None:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
        match = _JSON_BLOCK.search(raw)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
