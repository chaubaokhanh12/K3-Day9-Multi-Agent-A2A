"""VerifierAgent - cong kiem tra cuoi cung truoc khi ghi file.

Tinh LAI toan bo so hoc mot cach doc lap voi PolicyAgent thay vi tin ket qua
duoc ban giao. Chi cac violation thuc su moi duoc bao; violation nao sua duoc
thi sua tai cho va ghi lai vao trace.
"""
from __future__ import annotations

import re

from .. import config
from ..data_store import money
from ..facts import ROOT_CAUSE_CODES, VerifiedFacts

_EVIDENCE_PATTERNS = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]

_ACTIONS = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
}

_REFUND_RULE = {
    "canceled_order_paid": "payment_total_brl",
    "unavailable_order_paid": "payment_total_brl",
    "late_delivery_seller": "freight_total_brl",
    "late_delivery_logistics": "freight_total_brl",
    "valid_split_payment": "zero",
    "unsupported_late_claim": "zero",
}


class VerifierAgent:
    name = "VerifierAgent"

    def run(self, report: dict, f: VerifiedFacts) -> dict:
        violations: list[str] = []
        repairs: list[str] = []

        # -- 1. evidence: dung dinh dang VA ton tai trong registry ---------
        valid_ids = f.registry.all_ids()
        kept = []
        for eid in report.get("evidence_ids", []):
            if not any(p.match(eid) for p in _EVIDENCE_PATTERNS):
                violations.append(f"evidence sai dinh dang: {eid}")
                continue
            if eid.startswith("policy:"):
                if eid.split(":", 1)[1] not in ROOT_CAUSE_CODES:
                    violations.append(f"root cause code khong hop le: {eid}")
                    continue
            elif eid not in valid_ids:
                violations.append(f"evidence khong ton tai trong CSV: {eid}")
                continue
            if eid not in kept:
                kept.append(eid)
        if kept != report.get("evidence_ids"):
            repairs.append("loc lai evidence_ids")
        report["evidence_ids"] = kept[: config.MAX_EVIDENCE_IDS]

        # -- 2. entity set: doi chieu voi facts + cap ----------------------
        expected = {
            "order_ids": f.entity_order_ids,
            "item_ids": f.entity_item_ids,
            "seller_ids": f.entity_seller_ids,
            "payment_ids": f.entity_payment_ids,
        }
        entities = report.setdefault("affected_entities", {})
        for key, allowed in expected.items():
            got = [x for x in entities.get(key, []) if x in allowed]
            if len(got) != len(entities.get(key, [])):
                violations.append(f"{key} chua ID khong co trong du lieu")
                repairs.append(f"loc lai {key}")
            if len(got) > config.MAX_ENTITY_IDS:
                repairs.append(f"cat {key} ve {config.MAX_ENTITY_IDS}")
            entities[key] = got[: config.MAX_ENTITY_IDS]

        # -- 3. tinh lai so hoc doc lap ------------------------------------
        fin = report.setdefault("financial_resolution", {})
        recomputed = {
            "currency": config.CURRENCY,
            "item_total_brl": money(f.item_total_brl),
            "freight_total_brl": money(f.freight_total_brl),
            "payment_total_brl": money(f.payment_total_brl),
        }
        for key, value in recomputed.items():
            if fin.get(key) != value:
                violations.append(f"{key} lech: bao cao {fin.get(key)} vs tinh lai {value}")
                fin[key] = value
                repairs.append(f"ghi de {key}")

        issue = report.get("assessment", {}).get("primary_issue")
        basis = _REFUND_RULE.get(issue)
        if basis == "zero":
            expected_refund = 0.0
        elif basis:
            expected_refund = money(recomputed[basis])
        else:
            expected_refund = fin.get("recommended_refund_brl", 0.0)
            violations.append(f"primary_issue khong hop le: {issue}")
        if fin.get("recommended_refund_brl") != expected_refund:
            violations.append(
                f"refund lech: bao cao {fin.get('recommended_refund_brl')} vs "
                f"quy dinh {expected_refund}"
            )
            fin["recommended_refund_brl"] = expected_refund
            repairs.append("ghi de recommended_refund_brl")

        # -- 4. case_status phai nhat quan voi refund ----------------------
        assessment = report.setdefault("assessment", {})
        expected_status = (
            "action_required" if fin["recommended_refund_brl"] > 0 else "no_action"
        )
        if assessment.get("case_status") != expected_status:
            violations.append(
                f"case_status khong khop refund: {assessment.get('case_status')} "
                f"nhung refund = {fin['recommended_refund_brl']}"
            )
            assessment["case_status"] = expected_status
            repairs.append("ghi de case_status")

        # -- 5. confidence -------------------------------------------------
        conf = assessment.get("confidence")
        if not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
            violations.append(f"confidence ngoai [0,1]: {conf}")
            assessment["confidence"] = config.CONFIDENCE_BASE
            repairs.append("dat lai confidence")
        else:
            assessment["confidence"] = round(float(conf), 2)

        # -- 6. root cause + responsible party ------------------------------
        rca = report.setdefault("root_cause_analysis", {})
        causes = []
        for entry in rca.get("ranked_causes", []):
            if entry.get("cause_code") in ROOT_CAUSE_CODES:
                causes.append(entry)
            else:
                violations.append(f"cause_code khong hop le: {entry.get('cause_code')}")
        causes = causes[: config.MAX_ROOT_CAUSES]
        for i, entry in enumerate(causes, start=1):
            entry["rank"] = i
        rca["ranked_causes"] = causes

        parties = rca.get("responsible_parties", [])[: config.MAX_RESPONSIBLE_PARTIES]
        for p in parties:
            if p.get("party_type") == "seller" and p.get("party_id") not in f.seller_ids:
                violations.append(f"seller chiu trach nhiem khong thuoc don: {p.get('party_id')}")
        rca["responsible_parties"] = parties
        if expected_status == "action_required" and not parties:
            violations.append("action_required nhung khong co ben chiu trach nhiem")

        # -- 7. action ------------------------------------------------------
        actions = [a for a in report.get("resolution_actions", []) if a in _ACTIONS]
        if len(actions) != len(report.get("resolution_actions", [])):
            violations.append("co resolution_action khong hop le")
            repairs.append("loc lai resolution_actions")
        report["resolution_actions"] = actions[: config.MAX_ACTIONS]
        if not report["resolution_actions"]:
            violations.append("resolution_actions rong")

        # -- 8. cac truong bat buoc ----------------------------------------
        for key in (
            "case_id",
            "assessment",
            "affected_entities",
            "root_cause_analysis",
            "evidence_ids",
            "financial_resolution",
            "resolution_actions",
        ):
            if key not in report:
                violations.append(f"thieu truong bat buoc: {key}")

        return {
            "passed": not violations,
            "violations": violations,
            "repairs": repairs,
            "report": report,
        }
