"""Kieu du lieu chung cho cac agent va co che handoff."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    """Ket qua mot domain agent ban giao cho tang sau.

    `computed` luon do code tinh. `attestation` la phan dien giai cua LLM va
    KHONG duoc phep anh huong toi con so nao.
    """

    agent: str
    claim: str
    computed: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)
    attestation: str = ""
    llm_ok: bool = False
    llm_error: str = ""
    llm_latency_ms: int = 0

    def to_trace(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "claim": self.claim,
            "computed": self.computed,
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
            "flags": self.flags,
            "attestation": self.attestation,
            "llm_ok": self.llm_ok,
            "llm_error": self.llm_error,
            "llm_latency_ms": self.llm_latency_ms,
        }


class DomainAgent:
    """Agent phan tich mot domain.

    Moi agent chi nhin thay lat cat du lieu cua rieng minh (`project`), day la
    ranh gioi quyen truy cap duoc mo ta trong architecture.md.
    """

    name = "DomainAgent"
    system_prompt = ""

    def __init__(self, llm):
        self.llm = llm

    def project(self, facts) -> dict[str, Any]:
        raise NotImplementedError

    def analyze(self, facts) -> Finding:
        raise NotImplementedError

    def run(self, facts) -> Finding:
        finding = self.analyze(facts)
        if not self.llm.available:
            finding.llm_error = "LLM khong san sang - dung ket qua deterministic"
            return finding
        import json

        result = self.llm.complete_json(
            self.system_prompt,
            "Su kien da kiem chung (JSON):\n"
            + json.dumps(self.project(facts), ensure_ascii=False, indent=2)
            + "\n\nKet luan do rule engine tinh: "
            + finding.claim,
        )
        finding.llm_ok = result.ok
        finding.llm_latency_ms = result.latency_ms
        if result.ok:
            finding.attestation = str(result.data.get("attestation", ""))[:400]
            if result.data.get("contradiction"):
                finding.flags.append("llm_contradiction")
        else:
            finding.llm_error = result.error
        return finding
