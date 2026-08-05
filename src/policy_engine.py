"""Rule engine EC_POLICY_V1 - thuan code, khong LLM.

Day la nguon chan ly cua he thong. Cac rule duoc xet theo dung thu tu uu tien
trong de bai; rule dau tien khop se dung lai.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .data_store import money
from .facts import VerifiedFacts

PRIMARY_ISSUES = [
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
]


@dataclass
class Verdict:
    primary_issue: str
    case_status: str
    root_causes: list[str] = field(default_factory=list)
    responsible_parties: list[dict[str, str]] = field(default_factory=list)
    recommended_refund_brl: float = 0.0
    actions: list[str] = field(default_factory=list)
    rule_id: str = ""
    rationale: str = ""
    unresolved: bool = False


class PolicyAgent:
    """Ap dung thang uu tien EC_POLICY_V1 len VerifiedFacts."""

    name = "PolicyAgent"

    def run(self, f: VerifiedFacts) -> Verdict:
        for rule in (
            self._canceled_order_paid,
            self._unavailable_order_paid,
            self._late_delivery_seller,
            self._late_delivery_logistics,
            self._valid_split_payment,
            self._unsupported_late_claim,
        ):
            verdict = rule(f)
            if verdict is not None:
                return verdict
        return self._fallback(f)

    # -- rule 1 -----------------------------------------------------------
    def _canceled_order_paid(self, f: VerifiedFacts) -> Verdict | None:
        if f.order_status != "canceled" or not f.has_payment:
            return None
        return Verdict(
            primary_issue="canceled_order_paid",
            case_status="action_required",
            root_causes=["ORDER_CANCELED_AFTER_PAYMENT"],
            responsible_parties=[
                {"party_type": "platform", "party_id": config.PLATFORM_PARTY_ID}
            ],
            recommended_refund_brl=f.payment_total_brl,
            actions=["issue_full_refund"],
            rule_id="R1_CANCELED_PAID",
            rationale=(
                f"order_status=canceled va tong payment {f.payment_total_brl} BRL > 0 "
                f"=> hoan toan bo so tien da thanh toan."
            ),
        )

    # -- rule 2 -----------------------------------------------------------
    def _unavailable_order_paid(self, f: VerifiedFacts) -> Verdict | None:
        if f.order_status != "unavailable" or not f.has_payment:
            return None
        return Verdict(
            primary_issue="unavailable_order_paid",
            case_status="action_required",
            root_causes=["ORDER_UNAVAILABLE_AFTER_PAYMENT"],
            responsible_parties=[
                {"party_type": "platform", "party_id": config.PLATFORM_PARTY_ID}
            ],
            recommended_refund_brl=f.payment_total_brl,
            actions=["issue_full_refund"],
            rule_id="R2_UNAVAILABLE_PAID",
            rationale=(
                f"order_status=unavailable va tong payment {f.payment_total_brl} BRL > 0 "
                f"=> hoan toan bo so tien da thanh toan."
            ),
        )

    # -- rule 3 -----------------------------------------------------------
    def _late_delivery_seller(self, f: VerifiedFacts) -> Verdict | None:
        if not f.delivered_late or not f.seller_handoff_late:
            return None
        parties = [
            {"party_type": "seller", "party_id": sid}
            for sid in f.late_sellers[: config.MAX_RESPONSIBLE_PARTIES]
        ]
        return Verdict(
            primary_issue="late_delivery_seller",
            case_status="action_required",
            # EC_POLICY_V1 anh xa 1:1 giua 6 primary issue va 6 root cause code.
            # Them CARRIER_DELIVERED_AFTER_ESTIMATE o day se thanh false positive
            # vi ma do thuoc ve late_delivery_logistics.
            root_causes=["SELLER_HANDOFF_AFTER_LIMIT"],
            responsible_parties=parties,
            recommended_refund_brl=f.freight_total_brl,
            actions=["refund_freight"],
            rule_id="R3_LATE_SELLER",
            rationale=(
                f"Giao luc {f.delivered_ts} > han du kien {f.estimated_ts}; carrier nhan hang "
                f"luc {f.carrier_ts} muon hon shipping_limit_date cua seller "
                f"{', '.join(f.late_sellers)} => seller chiu trach nhiem, hoan freight."
            ),
        )

    # -- rule 4 -----------------------------------------------------------
    def _late_delivery_logistics(self, f: VerifiedFacts) -> Verdict | None:
        if not f.delivered_late or f.seller_handoff_late:
            return None
        return Verdict(
            primary_issue="late_delivery_logistics",
            case_status="action_required",
            root_causes=["CARRIER_DELIVERED_AFTER_ESTIMATE"],
            responsible_parties=[
                {"party_type": "logistics_provider", "party_id": config.LOGISTICS_PARTY_ID}
            ],
            recommended_refund_brl=f.freight_total_brl,
            actions=["refund_freight"],
            rule_id="R4_LATE_LOGISTICS",
            rationale=(
                f"Giao luc {f.delivered_ts} > han du kien {f.estimated_ts}, nhung carrier nhan "
                f"hang luc {f.carrier_ts} khong muon hon shipping_limit_date => trach nhiem "
                f"thuoc don vi van chuyen, hoan freight."
            ),
        )

    # -- rule 5 -----------------------------------------------------------
    def _valid_split_payment(self, f: VerifiedFacts) -> Verdict | None:
        if f.payment_row_count < config.MIN_SPLIT_PAYMENT_ROWS or not f.payment_reconciles:
            return None
        return Verdict(
            primary_issue="valid_split_payment",
            case_status="no_action",
            root_causes=["MULTIPLE_PAYMENTS_RECONCILED"],
            responsible_parties=[],
            recommended_refund_brl=0.0,
            actions=["explain_valid_split_payment"],
            rule_id="R5_SPLIT_PAYMENT",
            rationale=(
                f"{f.payment_row_count} payment row, tong {f.payment_total_brl} BRL khop "
                f"item {f.item_total_brl} + freight {f.freight_total_brl} (lech "
                f"{f.payment_delta_brl} BRL, trong nguong {config.PAYMENT_TOLERANCE_BRL}) "
                f"=> thanh toan tach hop le, khong hoan tien."
            ),
        )

    # -- rule 6 -----------------------------------------------------------
    def _unsupported_late_claim(self, f: VerifiedFacts) -> Verdict | None:
        if f.delivered_late is not False or not f.payment_reconciles:
            return None
        return Verdict(
            primary_issue="unsupported_late_claim",
            case_status="no_action",
            root_causes=["DELIVERY_WITHIN_ESTIMATE"],
            responsible_parties=[],
            recommended_refund_brl=0.0,
            actions=["reject_late_refund"],
            rule_id="R6_UNSUPPORTED_CLAIM",
            rationale=(
                f"Giao luc {f.delivered_ts} khong muon hon han du kien {f.estimated_ts} va "
                f"payment khop item + freight => khieu nai giao tre khong co can cu."
            ),
        )

    # -- khong rule nao khop ----------------------------------------------
    def _fallback(self, f: VerifiedFacts) -> Verdict:
        """Khong duoc kich hoat tren bo 50 case chinh thuc.

        Chon nhanh an toan nhat: neu giao dung han thi bac claim, nguoc lai quy
        trach nhiem cho logistics (rule co dieu kien long nhat trong nhom late).
        """
        if f.delivered_late:
            v = self._late_delivery_logistics(f) or Verdict(
                primary_issue="late_delivery_logistics",
                case_status="action_required",
                root_causes=["CARRIER_DELIVERED_AFTER_ESTIMATE"],
                responsible_parties=[
                    {"party_type": "logistics_provider", "party_id": config.LOGISTICS_PARTY_ID}
                ],
                recommended_refund_brl=f.freight_total_brl,
                actions=["refund_freight"],
            )
        else:
            v = Verdict(
                primary_issue="unsupported_late_claim",
                case_status="no_action",
                root_causes=["DELIVERY_WITHIN_ESTIMATE"],
                responsible_parties=[],
                recommended_refund_brl=0.0,
                actions=["reject_late_refund"],
            )
        v.rule_id = "R0_FALLBACK"
        v.unresolved = True
        v.rationale = (
            "Khong rule EC_POLICY_V1 nao khop truc tiep; dung nhanh an toan nhat. "
            + v.rationale
        )
        return v


def financials(f: VerifiedFacts, v: Verdict) -> dict[str, float | str]:
    return {
        "currency": config.CURRENCY,
        "item_total_brl": money(f.item_total_brl),
        "freight_total_brl": money(f.freight_total_brl),
        "payment_total_brl": money(f.payment_total_brl),
        "recommended_refund_brl": money(v.recommended_refund_brl),
    }
