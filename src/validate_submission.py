"""Kiem tra output/ truoc khi nop, roi dong goi thanh zip.

    python -m src.validate_submission          # chi kiem tra
    python -m src.validate_submission --zip    # kiem tra xong thi zip

Kiem tra doc lap voi pipeline: doc lai output tu dia va doi chieu truc tiep
voi CSV, khong dung lai bat ky ket qua trung gian nao.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile

from . import config
from .data_store import money, store
from .facts import ROOT_CAUSE_CODES

EXPECTED_CASES = [f"EC_{i:03d}" for i in range(1, 51)]

_PATTERNS = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]

_VALID_ISSUES = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}
_VALID_ACTIONS = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
}


def _real_ids(order_id: str) -> set[str]:
    b = store.get_case_bundle(order_id)
    ids = {f"order:{order_id}"}
    ids |= {f"item:{order_id}:{i['order_item_id']}" for i in b.items}
    ids |= {f"payment:{order_id}:{p['payment_sequential']}" for p in b.payments}
    ids |= {f"seller:{s['seller_id']}" for s in b.sellers}
    ids |= {f"policy:{c}" for c in ROOT_CAUSE_CODES}
    return ids


def validate() -> list[str]:
    errors: list[str] = []
    store.load()

    present = sorted(p.stem for p in config.OUTPUT_DIR.glob("*.json"))
    extra_files = [
        p.name for p in config.OUTPUT_DIR.iterdir() if p.suffix != ".json" and p.is_file()
    ]
    if extra_files:
        errors.append(f"output/ chua file la: {extra_files}")
    missing = set(EXPECTED_CASES) - set(present)
    unexpected = set(present) - set(EXPECTED_CASES)
    if missing:
        errors.append(f"thieu case: {sorted(missing)}")
    if unexpected:
        errors.append(f"case thua: {sorted(unexpected)}")

    for case_id in EXPECTED_CASES:
        path = config.OUTPUT_DIR / f"{case_id}.json"
        if not path.exists():
            continue
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{case_id}: JSON hong ({exc})")
            continue

        src = json.loads((config.INPUT_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
        order_id = src["customer_request"]["claimed_order_id"]
        real = _real_ids(order_id)
        bundle = store.get_case_bundle(order_id)

        if r.get("case_id") != case_id:
            errors.append(f"{case_id}: case_id trong file khong khop ten file")

        a = r.get("assessment", {})
        if a.get("primary_issue") not in _VALID_ISSUES:
            errors.append(f"{case_id}: primary_issue khong hop le")
        if a.get("case_status") not in {"action_required", "no_action"}:
            errors.append(f"{case_id}: case_status khong hop le")
        conf = a.get("confidence")
        if not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
            errors.append(f"{case_id}: confidence ngoai [0,1]")

        ev = r.get("evidence_ids", [])
        if len(ev) > config.MAX_EVIDENCE_IDS:
            errors.append(f"{case_id}: qua {config.MAX_EVIDENCE_IDS} evidence")
        if len(set(ev)) != len(ev):
            errors.append(f"{case_id}: evidence bi trung lap")
        for eid in ev:
            if not any(p.match(eid) for p in _PATTERNS):
                errors.append(f"{case_id}: evidence sai dinh dang -> {eid}")
            elif eid not in real:
                errors.append(f"{case_id}: evidence khong co trong CSV -> {eid}")

        ents = r.get("affected_entities", {})
        for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            v = ents.get(key)
            if not isinstance(v, list):
                errors.append(f"{case_id}: thieu affected_entities.{key}")
            elif len(v) > config.MAX_ENTITY_IDS:
                errors.append(f"{case_id}: {key} vuot {config.MAX_ENTITY_IDS} ID")

        rca = r.get("root_cause_analysis", {})
        causes = rca.get("ranked_causes", [])
        if not causes:
            errors.append(f"{case_id}: khong co ranked_causes")
        if len(causes) > config.MAX_ROOT_CAUSES:
            errors.append(f"{case_id}: qua {config.MAX_ROOT_CAUSES} root cause")
        for c in causes:
            if c.get("cause_code") not in ROOT_CAUSE_CODES:
                errors.append(f"{case_id}: cause_code la -> {c.get('cause_code')}")
        if len(rca.get("responsible_parties", [])) > config.MAX_RESPONSIBLE_PARTIES:
            errors.append(f"{case_id}: qua {config.MAX_RESPONSIBLE_PARTIES} ben chiu trach nhiem")

        fin = r.get("financial_resolution", {})
        if fin.get("currency") != config.CURRENCY:
            errors.append(f"{case_id}: currency phai la {config.CURRENCY}")
        exp = {
            "item_total_brl": money(sum(i["price"] for i in bundle.items)),
            "freight_total_brl": money(sum(i["freight_value"] for i in bundle.items)),
            "payment_total_brl": money(sum(p["payment_value"] for p in bundle.payments)),
        }
        for key, want in exp.items():
            if fin.get(key) != want:
                errors.append(f"{case_id}: {key}={fin.get(key)} nhung CSV cho {want}")
        refund = fin.get("recommended_refund_brl")
        if not isinstance(refund, (int, float)) or refund < 0:
            errors.append(f"{case_id}: recommended_refund_brl khong hop le")
        elif a.get("case_status") == "no_action" and refund != 0:
            errors.append(f"{case_id}: no_action nhung refund={refund}")
        elif a.get("case_status") == "action_required" and refund <= 0:
            errors.append(f"{case_id}: action_required nhung refund={refund}")

        acts = r.get("resolution_actions", [])
        if not acts:
            errors.append(f"{case_id}: resolution_actions rong")
        if len(acts) > config.MAX_ACTIONS:
            errors.append(f"{case_id}: qua {config.MAX_ACTIONS} action")
        for act in acts:
            if act not in _VALID_ACTIONS:
                errors.append(f"{case_id}: action la -> {act}")

        if bundle.items == [] and (ents.get("item_ids") or ents.get("seller_ids")):
            errors.append(f"{case_id}: order khong co item row nhung item/seller_ids khong rong")

    return errors


def make_zip() -> None:
    target = config.ROOT / "output.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for case_id in EXPECTED_CASES:
            z.write(config.OUTPUT_DIR / f"{case_id}.json", f"{case_id}.json")
    print(f"Da tao {target} ({target.stat().st_size / 1024:.1f} KB, 50 file)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", action="store_true", help="tao output.zip sau khi kiem tra")
    args = parser.parse_args()

    errors = validate()
    if errors:
        print(f"[THAT BAI] {len(errors)} loi:")
        for e in errors[:60]:
            print("  -", e)
        if len(errors) > 60:
            print(f"  ... va {len(errors) - 60} loi khac")
        return 1

    print("[OK] 50/50 case hop le: schema dung, evidence ID ton tai trong CSV, so hoc khop.")
    if args.zip:
        make_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
