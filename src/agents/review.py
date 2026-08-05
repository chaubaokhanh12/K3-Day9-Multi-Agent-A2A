"""IndependentReviewAgent - kiem chung cheo doc lap.

Agent nay nhan cac Finding va bang policy, tu suy luan ra primary_issue MA
KHONG duoc nhin thay ket luan cua PolicyAgent. Muc dich khong phai de quyet
dinh ket qua, ma de sinh mot tin hieu doc lap cho viec hieu chinh confidence.
"""
from __future__ import annotations

import json

from ..policy_engine import PRIMARY_ISSUES
from .base import Finding

_POLICY_TABLE = """EC_POLICY_V1 - xet theo dung thu tu, rule dau tien khop thi dung:
1. canceled_order_paid      : order_status = canceled VA tong payment > 0
2. unavailable_order_paid   : order_status = unavailable VA tong payment > 0
3. late_delivery_seller     : giao sau estimated date VA carrier nhan hang sau shipping_limit_date
4. late_delivery_logistics  : giao sau estimated date VA carrier nhan hang khong muon hon shipping_limit_date
5. valid_split_payment      : co tu 2 payment row VA tong payment khop item + freight trong sai so 0.10 BRL
6. unsupported_late_claim   : giao khong muon hon estimated date VA payment khop"""

_SYSTEM = (
    "Ban la thanh vien hoi dong phuc tham doc lap cua he thong xu ly khieu nai "
    "thuong mai dien tu. Ban nhan ket qua doi soat tu cac bo phan va phai TU "
    "MINH ap dung bang policy de chon dung mot primary_issue. Chi dua tren su "
    "kien duoc cung cap, khong bia them. Neu su kien khong du de ket luan, dat "
    'insufficient_evidence = true. Tra ve JSON dung dang: {"primary_issue": '
    '"<mot trong cac ma>", "reasoning": "<mot cau>", "insufficient_evidence": '
    "true|false}"
)


class IndependentReviewAgent:
    name = "IndependentReviewAgent"

    def __init__(self, llm):
        self.llm = llm

    def run(self, findings: list[Finding]) -> dict:
        if not self.llm.available:
            return {
                "available": False,
                "primary_issue": None,
                "reasoning": "",
                "error": "LLM khong san sang",
                "latency_ms": 0,
            }

        payload = {
            "policy": _POLICY_TABLE,
            "ma_hop_le": PRIMARY_ISSUES,
            "ket_qua_doi_soat": {f.agent: f.computed for f in findings},
        }
        result = self.llm.complete_json(
            _SYSTEM,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        if not result.ok:
            return {
                "available": True,
                "primary_issue": None,
                "reasoning": "",
                "error": result.error,
                "latency_ms": result.latency_ms,
            }

        issue = result.data.get("primary_issue")
        if issue not in PRIMARY_ISSUES:
            issue = None
        return {
            "available": True,
            "primary_issue": issue,
            "reasoning": str(result.data.get("reasoning", ""))[:400],
            "insufficient_evidence": bool(result.data.get("insufficient_evidence")),
            "error": "" if issue else "primary_issue tra ve khong hop le",
            "latency_ms": result.latency_ms,
        }
