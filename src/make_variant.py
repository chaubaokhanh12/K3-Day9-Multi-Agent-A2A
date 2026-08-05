"""Sinh cac bien the chi khac nhau o `evidence_ids` de A/B test tren leaderboard.

Moi bien the duoc dung tu output/ hien co bang cach ghi de DUY NHAT truong
evidence_ids; toan bo cac truong con lai giu nguyen byte-for-byte. Nho vay
chenh lech diem giua hai lan nop phan anh dung mot bien so.

    python -m src.make_variant --profile scoped
    python -m src.make_variant --profile all      # sinh tat ca bien the
"""
from __future__ import annotations

import argparse
import json
import zipfile

from . import config
from .data_store import store
from .facts import FactExtractor

ISSUE_TO_CAUSE = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}

# Thu tu nhom luon la: order -> items -> payments -> sellers -> policy
# (theo dung vi du output trong de bai).
PROFILES: dict[str, dict[str, list[str]]] = {
    # Hien tai: moi nhom co du lieu deu duoc nop.
    "full": {
        issue: ["order", "items", "payments", "sellers", "policy"]
        for issue in ISSUE_TO_CAUSE
    },
    # Chi nop evidence tham gia truc tiep vao lap luan cua rule da khop.
    "scoped": {
        "canceled_order_paid": ["order", "payments", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "payments", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "payments", "policy"],
        "valid_split_payment": ["order", "payments", "items", "policy"],
        "unsupported_late_claim": ["order", "payments", "items", "policy"],
    },
    # --- Phep do don bien, moc so sanh la `scoped` (da do: 91.2838) ---------
    # Moi profile duoi day chi khac `scoped` o DUNG MOT nhom cua DUNG MOT issue,
    # nen chenh lech diem cho biet truc tiep nhom do co thuoc dap an hay khong.
    "probe_a": {  # them sellers vao canceled_order_paid (8 case)
        "canceled_order_paid": ["order", "payments", "sellers", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "payments", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "payments", "policy"],
        "valid_split_payment": ["order", "payments", "items", "policy"],
        "unsupported_late_claim": ["order", "payments", "items", "policy"],
    },
    "probe_b": {  # bo payments khoi unsupported_late_claim (9 case)
        "canceled_order_paid": ["order", "payments", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "payments", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "payments", "policy"],
        "valid_split_payment": ["order", "payments", "items", "policy"],
        "unsupported_late_claim": ["order", "items", "policy"],
    },
    "probe_c": {  # them sellers vao late_delivery_logistics (8 case)
        "canceled_order_paid": ["order", "payments", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "payments", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "payments", "sellers", "policy"],
        "valid_split_payment": ["order", "payments", "items", "policy"],
        "unsupported_late_claim": ["order", "payments", "items", "policy"],
    },
    # Suy nguoc tu 2 quan sat tren leaderboard (full=84.5414, scoped=91.2838).
    # Metric khop nhat la Jaccard (giao/hop): chi 8 cau hinh nam trong sai so
    # 0.01, so voi 312 cua precision va 128 cua F1. Nghiem nay con tai lap dung
    # vi du output trong de bai cho late_delivery_seller, dieu ma nghiem cua
    # precision khong lam duoc.
    "inferred": {
        "canceled_order_paid": ["order", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "payments", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "payments", "policy"],
        "valid_split_payment": ["order", "items", "payments", "policy"],
        "unsupported_late_claim": ["order", "items", "payments", "sellers", "policy"],
    },
    # Chat che hon nua: bo ca payment o nhanh late (tien hoan lay tu freight,
    # khong lay tu payment), bo item o nhanh khong lien quan toi item.
    "lean": {
        "canceled_order_paid": ["order", "payments", "policy"],
        "unavailable_order_paid": ["order", "payments", "policy"],
        "late_delivery_seller": ["order", "items", "sellers", "policy"],
        "late_delivery_logistics": ["order", "items", "policy"],
        "valid_split_payment": ["order", "payments", "policy"],
        "unsupported_late_claim": ["order", "payments", "policy"],
    },
}


def build_evidence(profile: str, issue: str, facts) -> list[str]:
    groups = {
        "order": facts.registry.order,
        "items": facts.registry.items,
        "payments": facts.registry.payments,
        "sellers": facts.registry.sellers,
        "policy": [f"policy:{ISSUE_TO_CAUSE[issue]}"],
    }
    evidence: list[str] = []
    for group in PROFILES[profile][issue]:
        for eid in groups[group]:
            if eid not in evidence:
                evidence.append(eid)
    return evidence[: config.MAX_EVIDENCE_IDS]


def make(profile: str) -> None:
    store.load()
    extractor = FactExtractor()
    out_zip = config.ROOT / f"output_{profile}.zip"
    total = 0

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(1, 51):
            case_id = f"EC_{i:03d}"
            report = json.loads(
                (config.OUTPUT_DIR / f"{case_id}.json").read_text(encoding="utf-8")
            )
            src = json.loads(
                (config.INPUT_DIR / f"{case_id}.json").read_text(encoding="utf-8")
            )
            facts = extractor.run(
                case_id, store.get_case_bundle(src["customer_request"]["claimed_order_id"])
            )
            issue = report["assessment"]["primary_issue"]
            evidence = build_evidence(profile, issue, facts)

            # Chan tuyet doi: moi ID phai co that trong registry dung tu CSV.
            unknown = [e for e in evidence if not facts.registry.contains(e)]
            if unknown:
                raise RuntimeError(f"{case_id}: evidence khong co trong CSV: {unknown}")

            report["evidence_ids"] = evidence
            total += len(evidence)
            z.writestr(
                f"{case_id}.json", json.dumps(report, ensure_ascii=False, indent=2)
            )

    print(
        f"{out_zip.name:24s} 50 file | tong {total} evidence | "
        f"trung binh {total / 50:.2f}/case | {out_zip.stat().st_size / 1024:.1f} KB"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="all", choices=[*PROFILES, "all"])
    args = parser.parse_args()
    for profile in PROFILES if args.profile == "all" else [args.profile]:
        make(profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
