"""EvidenceCuratorAgent - chon evidence va entity set.

Toi uu cho PRECISION: chi lay ID co trong EvidenceRegistry (tuc la dung sinh
tu CSV), sap theo do lien quan voi primary_issue roi cat theo cap. ID khong
nam trong registry bi loai bo im lang - day la lop chan hallucination cuoi
cung truoc Verifier.
"""
from __future__ import annotations

from .. import config
from ..facts import VerifiedFacts
from ..policy_engine import Verdict


class EvidenceCuratorAgent:
    name = "EvidenceCuratorAgent"

    def run(self, f: VerifiedFacts, v: Verdict) -> dict:
        registry = f.registry

        # Seller chi duoc dua vao evidence khi seller CHINH LA ben chiu trach
        # nhiem. Voi cac issue ma trach nhiem thuoc platform hoac don vi van
        # chuyen, seller khong tham gia lap luan nen dua vao se lam giam do
        # chinh xac cua tap bang chung.
        seller_is_responsible = any(
            p.get("party_type") == "seller" for p in v.responsible_parties
        )

        groups = {
            "order": registry.order,
            "items": registry.items,
            "payments": registry.payments,
            "sellers": registry.sellers if seller_is_responsible else [],
            # Chi lay policy code thuoc ranked cause, khong lay ca 6 ma.
            "policy": [f"policy:{c}" for c in v.root_causes],
        }

        # Thu tu chuan theo vi du output trong de bai:
        # order -> item -> payment -> seller -> policy (policy dat cuoi cung).
        order_of_groups = ["order", "items", "payments", "sellers", "policy"]

        evidence: list[str] = []
        for group in order_of_groups:
            for eid in groups.get(group, []):
                if eid not in evidence and registry.contains(eid):
                    evidence.append(eid)

        # Neu phai cat bot, ma policy cua root cause hang 1 van phai duoc giu.
        if len(evidence) > config.MAX_EVIDENCE_IDS and v.root_causes:
            must_keep = f"policy:{v.root_causes[0]}"
            evidence = evidence[: config.MAX_EVIDENCE_IDS - 1] + [must_keep]
        evidence = evidence[: config.MAX_EVIDENCE_IDS]

        return {
            "evidence_ids": evidence,
            "affected_entities": {
                "order_ids": f.entity_order_ids[: config.MAX_ENTITY_IDS],
                "item_ids": f.entity_item_ids[: config.MAX_ENTITY_IDS],
                "seller_ids": f.entity_seller_ids[: config.MAX_ENTITY_IDS],
                "payment_ids": f.entity_payment_ids[: config.MAX_ENTITY_IDS],
            },
            "dropped": max(
                0,
                sum(len(groups[g]) for g in groups) + 1 - len(evidence),
            ),
        }
