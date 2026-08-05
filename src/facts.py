"""FactExtractor - tang 0 cua pipeline.

Bien CaseBundle tho thanh mot tap su kien da kiem chung (VerifiedFacts) kem
mot EVIDENCE REGISTRY dong: moi ID hop le deu duoc dung san tu CSV tai day.
Cac agent phia sau chi duoc CHON tu registry nay, khong duoc tu sinh ID.
Nho vay hallucination evidence bi chan bang cau truc chu khong bang prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config
from .data_store import CaseBundle, money

# Root cause code hop le theo EC_POLICY_V1
ROOT_CAUSE_CODES = {
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}


@dataclass
class EvidenceRegistry:
    """Tap dong cac evidence ID dung duoc, kem thu tu uu tien theo tung nhom."""

    order: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    payments: list[str] = field(default_factory=list)
    sellers: list[str] = field(default_factory=list)
    policies: list[str] = field(default_factory=list)

    def all_ids(self) -> set[str]:
        return set(self.order + self.items + self.payments + self.sellers + self.policies)

    def contains(self, evidence_id: str) -> bool:
        return evidence_id in self.all_ids()


@dataclass
class VerifiedFacts:
    """Su kien da tinh bang code. Khong truong nao den tu LLM."""

    case_id: str
    order_id: str
    order_found: bool

    order_status: str | None = None
    purchase_ts: str | None = None
    approved_ts: str | None = None
    carrier_ts: str | None = None
    delivered_ts: str | None = None
    estimated_ts: str | None = None

    item_count: int = 0
    payment_row_count: int = 0
    seller_ids: list[str] = field(default_factory=list)

    item_total_brl: float = 0.0
    freight_total_brl: float = 0.0
    payment_total_brl: float = 0.0
    payment_delta_brl: float = 0.0
    payment_reconciles: bool = False

    has_payment: bool = False
    is_delivered: bool = False
    delivered_late: bool | None = None
    seller_handoff_late: bool | None = None
    late_sellers: list[str] = field(default_factory=list)

    entity_order_ids: list[str] = field(default_factory=list)
    entity_item_ids: list[str] = field(default_factory=list)
    entity_payment_ids: list[str] = field(default_factory=list)
    entity_seller_ids: list[str] = field(default_factory=list)

    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    data_gaps: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        """Ban rut gon dua cho LLM - chi su kien, khong goi y ket luan."""
        return {
            "order_id": self.order_id,
            "order_status": self.order_status,
            "order_delivered_carrier_date": self.carrier_ts,
            "order_delivered_customer_date": self.delivered_ts,
            "order_estimated_delivery_date": self.estimated_ts,
            "item_count": self.item_count,
            "payment_row_count": self.payment_row_count,
            "item_total_brl": self.item_total_brl,
            "freight_total_brl": self.freight_total_brl,
            "payment_total_brl": self.payment_total_brl,
            "payment_reconciles_within_0.10": self.payment_reconciles,
            "delivered_after_estimated_date": self.delivered_late,
            "carrier_pickup_after_shipping_limit": self.seller_handoff_late,
            "seller_ids": self.seller_ids,
        }


class FactExtractor:
    """Agent 0: thuan code, khong goi LLM."""

    name = "FactExtractor"

    def run(self, case_id: str, bundle: CaseBundle) -> VerifiedFacts:
        f = VerifiedFacts(
            case_id=case_id, order_id=bundle.order_id, order_found=bundle.order_found
        )
        if not bundle.order_found:
            f.data_gaps.append("order_not_found_in_csv")
            return f

        o = bundle.order
        f.order_status = o["order_status"]
        f.purchase_ts = o["order_purchase_timestamp"]
        f.approved_ts = o["order_approved_at"]
        f.carrier_ts = o["order_delivered_carrier_date"]
        f.delivered_ts = o["order_delivered_customer_date"]
        f.estimated_ts = o["order_estimated_delivery_date"]

        f.item_count = len(bundle.items)
        f.payment_row_count = len(bundle.payments)
        f.seller_ids = [s["seller_id"] for s in bundle.sellers]

        f.item_total_brl = money(sum(i["price"] for i in bundle.items))
        f.freight_total_brl = money(sum(i["freight_value"] for i in bundle.items))
        f.payment_total_brl = money(sum(p["payment_value"] for p in bundle.payments))
        f.payment_delta_brl = money(
            f.payment_total_brl - (f.item_total_brl + f.freight_total_brl)
        )
        f.payment_reconciles = abs(f.payment_delta_brl) <= config.PAYMENT_TOLERANCE_BRL
        f.has_payment = f.payment_total_brl > 0

        f.is_delivered = f.order_status == "delivered"

        # So sanh timestamp theo dung gia tri chuoi trong CSV (ISO => so sanh
        # chuoi tuong duong so sanh thoi gian). Khong doi mui gio.
        if f.delivered_ts and f.estimated_ts:
            f.delivered_late = f.delivered_ts > f.estimated_ts
        elif f.is_delivered:
            f.data_gaps.append("delivered_status_without_timestamps")

        if f.carrier_ts and bundle.items:
            late = [
                i["seller_id"]
                for i in bundle.items
                if i["shipping_limit_date"] and f.carrier_ts > i["shipping_limit_date"]
            ]
            f.late_sellers = list(dict.fromkeys(late))
            f.seller_handoff_late = bool(f.late_sellers)
        elif f.delivered_late and not f.carrier_ts:
            f.data_gaps.append("missing_carrier_handoff_timestamp")

        # -- entity set (da co thu tu, cat theo cap o tang Verifier) --------
        f.entity_order_ids = [bundle.order_id]
        f.entity_item_ids = [
            f"{i['order_id']}:{i['order_item_id']}" for i in bundle.items
        ]
        f.entity_payment_ids = [
            f"{p['order_id']}:{p['payment_sequential']}" for p in bundle.payments
        ]
        f.entity_seller_ids = list(f.seller_ids)

        # -- evidence registry dong ----------------------------------------
        f.registry = EvidenceRegistry(
            order=[f"order:{bundle.order_id}"],
            items=[f"item:{eid}" for eid in f.entity_item_ids],
            payments=[f"payment:{eid}" for eid in f.entity_payment_ids],
            sellers=[f"seller:{sid}" for sid in f.seller_ids],
            policies=[f"policy:{code}" for code in sorted(ROOT_CAUSE_CODES)],
        )
        return f
