"""Ba domain agent chay song song, moi agent mot lat cat du lieu rieng."""
from __future__ import annotations

from typing import Any

from ..facts import VerifiedFacts
from .base import DomainAgent, Finding

_ATTEST_SYSTEM = (
    "Ban la mot chuyen vien doi soat du lieu thuong mai dien tu. Ban CHI duoc "
    "dua tren cac su kien JSON duoc cung cap; tuyet doi khong bia them su kien, "
    "ID hay so lieu. Nhiem vu: viet mot cau tieng Viet giai thich su kien, va "
    "bao co mau thuan noi tai hay khong. Tra ve JSON dung dang: "
    '{"attestation": "<mot cau>", "contradiction": true|false}'
)


class OrderIntegrityAgent(DomainAgent):
    """Quyen truy cap: trang thai don, item, seller. KHONG thay du lieu thanh toan."""

    name = "OrderIntegrityAgent"
    system_prompt = _ATTEST_SYSTEM

    def project(self, f: VerifiedFacts) -> dict[str, Any]:
        return {
            "order_id": f.order_id,
            "order_found_in_csv": f.order_found,
            "order_status": f.order_status,
            "order_purchase_timestamp": f.purchase_ts,
            "order_approved_at": f.approved_ts,
            "item_count": f.item_count,
            "seller_ids": f.seller_ids,
        }

    def analyze(self, f: VerifiedFacts) -> Finding:
        flags: list[str] = []
        if not f.order_found:
            flags.append("order_not_found")
        if f.item_count == 0:
            flags.append("no_item_rows")
        if len(f.seller_ids) > 1:
            flags.append("multi_seller_order")

        claim = (
            f"Don {f.order_id} co trang thai '{f.order_status}', {f.item_count} item row, "
            f"{len(f.seller_ids)} seller."
        )
        evidence = list(f.registry.order) + list(f.registry.items) + list(f.registry.sellers)
        return Finding(
            agent=self.name,
            claim=claim,
            computed={
                "order_status": f.order_status,
                "item_count": f.item_count,
                "seller_ids": f.seller_ids,
                "has_item_rows": f.item_count > 0,
            },
            evidence_ids=evidence,
            confidence=1.0 if f.order_found else 0.0,
            flags=flags,
        )


class DeliveryTimelineAgent(DomainAgent):
    """Quyen truy cap: cac moc thoi gian. KHONG thay so tien."""

    name = "DeliveryTimelineAgent"
    system_prompt = _ATTEST_SYSTEM

    def project(self, f: VerifiedFacts) -> dict[str, Any]:
        return {
            "order_id": f.order_id,
            "order_status": f.order_status,
            "order_delivered_carrier_date": f.carrier_ts,
            "order_delivered_customer_date": f.delivered_ts,
            "order_estimated_delivery_date": f.estimated_ts,
            "delivered_after_estimated_date": f.delivered_late,
            "carrier_pickup_after_any_shipping_limit": f.seller_handoff_late,
            "sellers_that_handed_off_late": f.late_sellers,
        }

    def analyze(self, f: VerifiedFacts) -> Finding:
        flags: list[str] = []
        if f.delivered_late is None:
            flags.append("delivery_timeline_incomplete")
        if f.delivered_late and f.seller_handoff_late is None:
            flags.append("handoff_timeline_incomplete")

        if f.delivered_late is None:
            claim = f"Don {f.order_id} khong co du moc thoi gian de danh gia tre giao."
        elif f.delivered_late:
            who = "seller ban giao muon" if f.seller_handoff_late else "seller ban giao dung han"
            claim = (
                f"Giao luc {f.delivered_ts} muon hon han du kien {f.estimated_ts}; {who}."
            )
        else:
            claim = f"Giao luc {f.delivered_ts} khong muon hon han du kien {f.estimated_ts}."

        evidence = list(f.registry.order) + list(f.registry.items)
        if f.late_sellers:
            evidence += [f"seller:{sid}" for sid in f.late_sellers]
        return Finding(
            agent=self.name,
            claim=claim,
            computed={
                "delivered_late": f.delivered_late,
                "seller_handoff_late": f.seller_handoff_late,
                "late_sellers": f.late_sellers,
            },
            evidence_ids=evidence,
            confidence=1.0 if f.delivered_late is not None or not f.is_delivered else 0.6,
            flags=flags,
        )


class PaymentReconciliationAgent(DomainAgent):
    """Quyen truy cap: tien va payment row. KHONG thay moc giao hang."""

    name = "PaymentReconciliationAgent"
    system_prompt = _ATTEST_SYSTEM

    def project(self, f: VerifiedFacts) -> dict[str, Any]:
        return {
            "order_id": f.order_id,
            "payment_row_count": f.payment_row_count,
            "item_total_brl": f.item_total_brl,
            "freight_total_brl": f.freight_total_brl,
            "payment_total_brl": f.payment_total_brl,
            "delta_brl": f.payment_delta_brl,
            "reconciles_within_0.10": f.payment_reconciles,
        }

    def analyze(self, f: VerifiedFacts) -> Finding:
        flags: list[str] = []
        if not f.payment_reconciles:
            flags.append("payment_mismatch")
        if f.payment_row_count == 0:
            flags.append("no_payment_rows")
        if f.payment_row_count >= 2:
            flags.append("split_payment")

        claim = (
            f"Tong payment {f.payment_total_brl} BRL tren {f.payment_row_count} row so voi "
            f"item {f.item_total_brl} + freight {f.freight_total_brl} "
            f"(lech {f.payment_delta_brl} BRL, "
            f"{'khop' if f.payment_reconciles else 'khong khop'})."
        )
        evidence = list(f.registry.order) + list(f.registry.payments) + list(f.registry.items)
        return Finding(
            agent=self.name,
            claim=claim,
            computed={
                "payment_row_count": f.payment_row_count,
                "item_total_brl": f.item_total_brl,
                "freight_total_brl": f.freight_total_brl,
                "payment_total_brl": f.payment_total_brl,
                "payment_reconciles": f.payment_reconciles,
                "has_payment": f.has_payment,
            },
            evidence_ids=evidence,
            confidence=1.0,
            flags=flags,
        )
