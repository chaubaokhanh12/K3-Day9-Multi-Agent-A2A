"""Entry point: chay toan bo 50 case.

    python -m src.run              # chay day du (co LLM neu co API key)
    python -m src.run --no-llm     # chi chay tang deterministic
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections import Counter

from . import config
from .data_store import store
from .llm_client import LLMClient
from .pipeline import CoordinatorAgent
from .trace import TraceWriter


class _OfflineLLM:
    """Stand-in khi chay --no-llm: moi loi goi deu bao khong kha dung."""

    available = False

    def complete_json(self, system, user):  # pragma: no cover
        from .llm_client import LLMResult

        return LLMResult(ok=False, error="che do --no-llm")


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(config.INPUT_DIR.glob("EC_*.json")):
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    return cases


def write_metadata(llm_available: bool, elapsed_s: float, case_count: int) -> None:
    meta = {
        "model": config.MODEL_NAME,
        "parameter_size": config.MODEL_PARAM_SIZE,
        "provider_base_url": config.MODEL_BASE_URL or "https://api.openai.com/v1",
        "framework": "custom multi-agent orchestrator (Python, openai SDK, pandas)",
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "elapsed_seconds": round(elapsed_s, 2),
            "cases_processed": case_count,
        },
        "decision_authority": "deterministic policy engine (EC_POLICY_V1); LLM chi "
        "dong vai tro dien giai va phuc tham doc lap, khong quyet dinh ket qua",
        "llm_enabled": llm_available,
        "agents": [
            "CoordinatorAgent",
            "FactExtractor",
            "OrderIntegrityAgent",
            "DeliveryTimelineAgent",
            "PaymentReconciliationAgent",
            "PolicyAgent",
            "IndependentReviewAgent",
            "AdjudicatorAgent",
            "EvidenceCuratorAgent",
            "VerifierAgent",
        ],
        "temperature": config.MODEL_TEMPERATURE,
        "policy_version": "EC_POLICY_V1",
    }
    config.METADATA_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="bo qua tang LLM")
    parser.add_argument("--limit", type=int, default=0, help="chi chay N case dau")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("Khong tim thay case nao trong input/", file=sys.stderr)
        return 1

    store.load()
    llm = _OfflineLLM() if args.no_llm else LLMClient()
    if not args.no_llm and not llm.available:
        print("[canh bao] LLM khong kha dung -> chay bang tang deterministic.")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    issues = Counter()
    agreements = Counter()
    failed_verify = []

    with TraceWriter() as trace:
        coordinator = CoordinatorAgent(llm=llm, trace=trace)
        for case in cases:
            result = coordinator.run_case(case)
            report = result["report"]
            path = config.OUTPUT_DIR / f"{report['case_id']}.json"
            payload = json.dumps(report, ensure_ascii=False, indent=2)
            # Ghi roi doc lai de xac nhan noi dung tren dia dung la ban vua sinh.
            # Bat moi truong hop file cu khong bi ghi de.
            for attempt in range(3):
                path.write_text(payload, encoding="utf-8")
                if path.read_text(encoding="utf-8") == payload:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(
                    f"{report['case_id']}: ghi file that bai, noi dung tren dia khong khop"
                )
            issues[report["assessment"]["primary_issue"]] += 1
            agreements[result["adjudication"]["agreement"]] += 1
            if not result["verifier"]["passed"]:
                failed_verify.append(
                    (report["case_id"], result["verifier"]["violations"])
                )
        trace_lines = trace.count

    elapsed = time.time() - started
    write_metadata(getattr(llm, "available", False), elapsed, len(cases))

    print(f"Da xu ly {len(cases)} case trong {elapsed:.1f}s")
    print(f"trace.jsonl: {trace_lines} dong")
    print("Phan bo primary_issue:")
    for issue, n in sorted(issues.items(), key=lambda x: -x[1]):
        print(f"  {issue:26s} {n}")
    print(f"Phuc tham doc lap: {dict(agreements)}")
    if failed_verify:
        print(f"[LOI] {len(failed_verify)} case khong qua Verifier:")
        for cid, violations in failed_verify:
            print(f"  {cid}: {violations}")
        return 1
    print("Tat ca case deu qua Verifier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
