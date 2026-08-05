"""Cau hinh tap trung cho pipeline EC_POLICY_V1.

Ten model duoc khai bao ngay trong source (theo yeu cau de bai), khong dat trong .env.
Chi API key moi nam trong .env.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
TRACE_PATH = ROOT / "trace.jsonl"
METADATA_PATH = ROOT / "metadata.json"

# --- Model ---------------------------------------------------------------
# Endpoint theo chuan OpenAI-compatible => doi provider chi can sua 3 dong nay.
MODEL_NAME = "gpt-4o-mini"
MODEL_PARAM_SIZE = "~8B (undisclosed by vendor, duoi nguong 10B)"
MODEL_BASE_URL = None  # None = api.openai.com; vd Groq: "https://api.groq.com/openai/v1"
MODEL_TEMPERATURE = 0.0
MODEL_MAX_TOKENS = 700
MODEL_TIMEOUT_S = 30
MODEL_MAX_RETRIES = 2

# --- Policy EC_POLICY_V1 -------------------------------------------------
CURRENCY = "BRL"
MONEY_PRECISION = 2
# Sai so cho phep khi doi soat payment voi item + freight.
PAYMENT_TOLERANCE_BRL = 0.10
MIN_SPLIT_PAYMENT_ROWS = 2

PLATFORM_PARTY_ID = "OLIST_PLATFORM"
LOGISTICS_PARTY_ID = "LOGISTICS_PROVIDER"

# --- Gioi han schema output ----------------------------------------------
MAX_ENTITY_IDS = 5
MAX_EVIDENCE_IDS = 10
MAX_ROOT_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_ACTIONS = 5

# --- Hieu chinh confidence ----------------------------------------------
# Muc nen la 1.0 vi khi mot rule EC_POLICY_V1 khop truc tiep tren du lieu day
# du thi ket luan la SUY DIEN chu khong phai uoc luong xac suat: moi dieu kien
# cua rule deu kiem tra duoc tuyet doi tu CSV. Bao duoi 1.0 trong tinh huong do
# la tu ha thap mot ket luan chac chan.
# Cac khoan phat ben duoi van giu nguyen va van kich hoat trong nhung truong hop
# bat dinh that: thieu du lieu, khong rule nao khop truc tiep, hoac phuc tham
# bat dong ma khong bac bo duoc bang su kien.
CONFIDENCE_BASE = 1.0
CONFIDENCE_PENALTY_REVIEW_DISAGREE = 0.05
CONFIDENCE_PENALTY_MISSING_FACT = 0.04
CONFIDENCE_PENALTY_LLM_UNAVAILABLE = 0.02
CONFIDENCE_FLOOR = 0.50
CONFIDENCE_CEILING = 1.0

CSV_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
}
