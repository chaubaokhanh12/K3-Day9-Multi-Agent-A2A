"""AdjudicatorAgent - doi chieu verdict deterministic voi phuc tham doc lap.

Quy tac bat di bat dich: verdict cua PolicyAgent LUON thang. Phuc tham chi
duoc phep tac dong len `confidence`, va muc phat cung duoc gioi han nho de mot
ket luan dung khong bi keo xuong chi vi LLM doan sai.
"""
from __future__ import annotations

from .. import config
from ..facts import VerifiedFacts
from ..policy_engine import Verdict
from .base import Finding


# Dieu kien CAN cua tung primary_issue. Neu de xuat cua phuc tham vi pham
# dieu kien can cua chinh no thi de xuat do da bi du lieu bac bo.
_PRECONDITIONS = {
    "canceled_order_paid": lambda f: f.order_status == "canceled" and f.has_payment,
    "unavailable_order_paid": lambda f: f.order_status == "unavailable" and f.has_payment,
    "late_delivery_seller": lambda f: bool(f.delivered_late) and bool(f.seller_handoff_late),
    "late_delivery_logistics": lambda f: bool(f.delivered_late) and not f.seller_handoff_late,
    "valid_split_payment": lambda f: f.payment_row_count >= 2 and f.payment_reconciles,
    "unsupported_late_claim": lambda f: f.delivered_late is False and f.payment_reconciles,
}


# Cac primary_issue ma tung co canh bao thuc su co y nghia.
# None = luon co y nghia bat ke rule nao khop.
_BLOCKING_FLAG_SCOPE: dict[str, set[str] | None] = {
    "order_not_found": None,
    "payment_mismatch": {"valid_split_payment", "unsupported_late_claim"},
    "multi_seller_order": {"late_delivery_seller"},
}


def is_refuted(issue: str, facts: VerifiedFacts) -> bool:
    """True neu su kien da kiem chung loai tru issue nay."""
    check = _PRECONDITIONS.get(issue)
    return True if check is None else not check(facts)


class AdjudicatorAgent:
    name = "AdjudicatorAgent"

    def run(
        self,
        facts: VerifiedFacts,
        verdict: Verdict,
        findings: list[Finding],
        review: dict,
    ) -> dict:
        confidence = config.CONFIDENCE_BASE
        notes: list[str] = []

        # Phuc tham vang mat hoac loi thi KHONG tru confidence: no khong lam du
        # lieu kem day du hon, cung khong lam rule khop kem di. Neu tru o day
        # thi mot loi API thoang qua se lam doi gia tri trong file nop, khien
        # cung mot input cho ra hai ket qua khac nhau giua hai lan chay.
        # Van ghi vao trace de con dau vet.
        if not review.get("available"):
            notes.append("phuc_tham_khong_kha_dung")
            agreement = "unavailable"
        elif review.get("primary_issue") is None:
            notes.append("phuc_tham_loi")
            agreement = "error"
        elif review["primary_issue"] == verdict.primary_issue:
            agreement = "agree"
            notes.append("phuc_tham_dong_thuan")
        elif is_refuted(review["primary_issue"], facts):
            # De xuat cua phuc tham vi pham dieu kien can cua chinh no => da bi
            # du lieu bac bo, khong mang thong tin nen khong tru confidence.
            agreement = "disagree_refuted"
            notes.append(
                f"phuc_tham_bat_dong(de_xuat={review['primary_issue']}) "
                f"- bi su kien bac bo, khong tinh phat"
            )
        else:
            confidence -= config.CONFIDENCE_PENALTY_REVIEW_DISAGREE
            agreement = "disagree"
            notes.append(
                f"phuc_tham_bat_dong(de_xuat={review['primary_issue']}) "
                f"- khong bac bo duoc, giu verdict deterministic nhung ha confidence"
            )

        if facts.data_gaps:
            confidence -= config.CONFIDENCE_PENALTY_MISSING_FACT * len(facts.data_gaps)
            notes.append("thieu_du_lieu:" + ",".join(facts.data_gaps))

        if verdict.unresolved:
            confidence -= 0.15
            notes.append("khong_rule_nao_khop_truc_tiep")

        # Cho canh bao anh huong confidence CHI khi no lien quan toi rule da khop.
        # Vi du: order 'unavailable' khong co item row thi payment_mismatch bat len
        # theo dinh nghia (item + freight = 0), nhung rule 2 khong he phu thuoc
        # vao doi soat payment => khong duoc tru confidence.
        for f in findings:
            for flag in f.flags:
                if flag not in _BLOCKING_FLAG_SCOPE:
                    continue
                scope = _BLOCKING_FLAG_SCOPE[flag]
                if scope is not None and verdict.primary_issue not in scope:
                    notes.append(f"canh_bao_khong_lien_quan:{f.agent}:{flag}")
                    continue
                confidence -= config.CONFIDENCE_PENALTY_MISSING_FACT
                notes.append(f"canh_bao:{f.agent}:{flag}")

        confidence = max(
            config.CONFIDENCE_FLOOR, min(config.CONFIDENCE_CEILING, confidence)
        )
        return {
            "agreement": agreement,
            "confidence": round(confidence, 2),
            "notes": notes,
            "review_issue": review.get("primary_issue"),
            "final_issue": verdict.primary_issue,
            "authority": "deterministic_policy_engine",
        }
