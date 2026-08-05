"""Phep do don bien tren cac truong NGOAI evidence_ids.

Moi experiment chi cham vao mot truong, va cac truong do thuoc nhung dong diem
KHAC NHAU tren bang cham, nen co the gop nhieu experiment vao mot lan nop ma
van doc duoc delta rieng cho tung tieu chi.

    python -m src.make_experiment --exp all
"""
from __future__ import annotations

import argparse
import json
import zipfile

from . import config

# Cac issue ma seller thuc su la ben chiu trach nhiem.
SELLER_RESPONSIBLE = {"late_delivery_seller"}


def seller_scoped(report: dict) -> dict:
    """seller_ids = [] tru khi seller la ben chiu trach nhiem.

    Cung logic da duoc kiem chung tren evidence_ids (probe_a: them seller vao
    canceled lam giam diem). Chi cham `affected_entities` -> chi anh huong
    dong diem 'Entity lien quan'.
    """
    if report["assessment"]["primary_issue"] not in SELLER_RESPONSIBLE:
        report["affected_entities"]["seller_ids"] = []
    return report


def confidence_one(report: dict) -> dict:
    """confidence = 1.0. Chi anh huong dong diem 'Danh gia case'."""
    report["assessment"]["confidence"] = 1.0
    return report


def confidence_low(report: dict) -> dict:
    """confidence = 0.9, de do chieu nguoc lai neu 1.0 lam giam diem."""
    report["assessment"]["confidence"] = 0.9
    return report


EXPERIMENTS = {
    "sellerscoped": [seller_scoped],
    "conf100": [confidence_one],
    "conf90": [confidence_low],
    # Gop 2 phep do vao 1 lan nop: chung roi vao 2 dong diem khac nhau.
    "combo": [seller_scoped, confidence_one],
}


def make(name: str) -> None:
    out = config.ROOT / f"output_exp_{name}.zip"
    changed = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(1, 51):
            case_id = f"EC_{i:03d}"
            path = config.OUTPUT_DIR / f"{case_id}.json"
            before = path.read_text(encoding="utf-8")
            report = json.loads(before)
            for fn in EXPERIMENTS[name]:
                report = fn(report)
            after = json.dumps(report, ensure_ascii=False, indent=2)
            if after != before:
                changed += 1
            z.writestr(f"{case_id}.json", after)
    print(f"{out.name:28s} 50 file | doi {changed} case | {out.stat().st_size / 1024:.1f} KB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", default="all", choices=[*EXPERIMENTS, "all"])
    args = parser.parse_args()
    for name in EXPERIMENTS if args.exp == "all" else [args.exp]:
        make(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
