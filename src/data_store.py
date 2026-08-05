"""Tang truy cap du lieu Olist.

Day la NGUON DUY NHAT sinh ra ID va so tien. Khong agent nao duoc phep
tu tao ID ngoai nhung gi tang nay tra ve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from . import config


def money(value: Any) -> float:
    """Lam tron 2 chu so thap phan theo half-up (khong dung banker's rounding)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    d = Decimal(str(float(value))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(d)


def _text(value: Any) -> str | None:
    """Chuan hoa o CSV: NaN -> None, con lai -> str da strip."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


@dataclass
class CaseBundle:
    """Toan bo du lieu tho lien quan toi mot order, da chuan hoa."""

    order_id: str
    order_found: bool
    order: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    customer: dict[str, Any] = field(default_factory=dict)
    sellers: list[dict[str, Any]] = field(default_factory=list)


class DataStore:
    """Load 9 CSV mot lan, index san theo order_id de tra cuu O(1)."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or config.DATA_DIR
        self._loaded = False

    def load(self) -> "DataStore":
        if self._loaded:
            return self
        d = self.data_dir
        self.orders = pd.read_csv(d / config.CSV_FILES["orders"], dtype=str)
        self.items = pd.read_csv(d / config.CSV_FILES["order_items"])
        self.payments = pd.read_csv(d / config.CSV_FILES["order_payments"])
        self.customers = pd.read_csv(d / config.CSV_FILES["customers"], dtype=str)
        self.sellers = pd.read_csv(d / config.CSV_FILES["sellers"], dtype=str)

        self._orders_by_id = self.orders.set_index("order_id", drop=False)
        self._items_by_order = {k: v for k, v in self.items.groupby("order_id")}
        self._payments_by_order = {k: v for k, v in self.payments.groupby("order_id")}
        self._customers_by_id = self.customers.set_index("customer_id", drop=False)
        self._sellers_by_id = self.sellers.set_index("seller_id", drop=False)
        self._loaded = True
        return self

    # -- tra cuu ----------------------------------------------------------

    def get_case_bundle(self, order_id: str) -> CaseBundle:
        self.load()
        if order_id not in self._orders_by_id.index:
            return CaseBundle(order_id=order_id, order_found=False)

        row = self._orders_by_id.loc[order_id]
        if isinstance(row, pd.DataFrame):  # phong truong hop order_id trung
            row = row.iloc[0]

        order = {
            "order_id": order_id,
            "customer_id": _text(row.get("customer_id")),
            "order_status": _text(row.get("order_status")),
            "order_purchase_timestamp": _text(row.get("order_purchase_timestamp")),
            "order_approved_at": _text(row.get("order_approved_at")),
            "order_delivered_carrier_date": _text(row.get("order_delivered_carrier_date")),
            "order_delivered_customer_date": _text(row.get("order_delivered_customer_date")),
            "order_estimated_delivery_date": _text(row.get("order_estimated_delivery_date")),
        }

        items = []
        for _, r in self._items_by_order.get(order_id, self.items.iloc[0:0]).iterrows():
            items.append(
                {
                    "order_id": order_id,
                    "order_item_id": int(r["order_item_id"]),
                    "product_id": _text(r["product_id"]),
                    "seller_id": _text(r["seller_id"]),
                    "shipping_limit_date": _text(r["shipping_limit_date"]),
                    "price": money(r["price"]),
                    "freight_value": money(r["freight_value"]),
                }
            )
        items.sort(key=lambda x: x["order_item_id"])

        payments = []
        for _, r in self._payments_by_order.get(order_id, self.payments.iloc[0:0]).iterrows():
            payments.append(
                {
                    "order_id": order_id,
                    "payment_sequential": int(r["payment_sequential"]),
                    "payment_type": _text(r["payment_type"]),
                    "payment_installments": int(r["payment_installments"]),
                    "payment_value": money(r["payment_value"]),
                }
            )
        payments.sort(key=lambda x: x["payment_sequential"])

        customer = {}
        cid = order["customer_id"]
        if cid and cid in self._customers_by_id.index:
            c = self._customers_by_id.loc[cid]
            if isinstance(c, pd.DataFrame):
                c = c.iloc[0]
            customer = {
                "customer_id": cid,
                "customer_unique_id": _text(c.get("customer_unique_id")),
                "customer_city": _text(c.get("customer_city")),
                "customer_state": _text(c.get("customer_state")),
            }

        sellers = []
        for sid in dict.fromkeys(i["seller_id"] for i in items if i["seller_id"]):
            entry = {"seller_id": sid}
            if sid in self._sellers_by_id.index:
                s = self._sellers_by_id.loc[sid]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[0]
                entry["seller_city"] = _text(s.get("seller_city"))
                entry["seller_state"] = _text(s.get("seller_state"))
            sellers.append(entry)

        return CaseBundle(
            order_id=order_id,
            order_found=True,
            order=order,
            items=items,
            payments=payments,
            customer=customer,
            sellers=sellers,
        )

    def seller_exists(self, seller_id: str) -> bool:
        self.load()
        return seller_id in self._sellers_by_id.index


store = DataStore()
