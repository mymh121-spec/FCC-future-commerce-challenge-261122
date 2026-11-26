"""고객별 선호와 상품 피드백을 서버의 SQLite에 보관한다."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from product_quotes import UNAVAILABLE

CURRENCIES = ("KRW", "USD", "JPY", "EUR", "CNH", "GBP", "AUD", "TWD")
PRIORITIES = ("가격 우선", "도착일 우선")
FEEDBACK = ("찾던 상품", "다른 상품", "배송 정보 부족")


def database_path():
    folder = Path(os.environ.get("FCC_BUYER_DB_DIR") or Path.home() / ".local/share/fcc-server")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder / "buyers.sqlite3"


@contextmanager
def connection():
    path = database_path()
    os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        yield db


def initialize():
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS preference (
                buyer_id TEXT NOT NULL, name TEXT NOT NULL,
                value TEXT NOT NULL, saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (buyer_id, name));
            CREATE TABLE IF NOT EXISTS feedback (
                buyer_id TEXT NOT NULL, product_key TEXT NOT NULL,
                reason TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (buyer_id, product_key));
            CREATE TABLE IF NOT EXISTS quote (
                buyer_id TEXT NOT NULL, quote_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (buyer_id, quote_id));
            CREATE INDEX IF NOT EXISTS quote_buyer_saved ON quote(buyer_id, saved_at);
        """)


def product_key(item):
    # A price refresh does not change the identity of this seller's listing.
    ref = [item.get("market"), item.get("seller"), item["url"]]
    return hashlib.sha256(json.dumps(ref, ensure_ascii=False).encode()).hexdigest()


def memory(owner):
    with connection() as db:
        prefs = dict(db.execute("SELECT name,value FROM preference WHERE buyer_id=?", (owner,)))
        ratings = dict(db.execute("SELECT product_key,reason FROM feedback WHERE buyer_id=?", (owner,)))
    return prefs, ratings


def set_preference(owner, name, value):
    allowed = {"shoe_size_mm": range(100, 401), "currency": CURRENCIES, "priority": PRIORITIES}
    if name not in allowed or (value is not None and value not in allowed[name]):
        raise ValueError("지원하는 선호 항목과 값을 입력하세요.")
    if name == "shoe_size_mm" and value is not None and type(value) is not int:
        raise ValueError("사이즈는 mm 단위 정수로 입력하세요.")
    with connection() as db:
        if value is None:
            db.execute("DELETE FROM preference WHERE buyer_id=? AND name=?", (owner, name))
        else:
            db.execute("""INSERT INTO preference(buyer_id,name,value) VALUES (?,?,?)
                          ON CONFLICT(buyer_id,name) DO UPDATE SET value=excluded.value,
                          updated_at=CURRENT_TIMESTAMP""", (owner, name, value))


def set_feedback(owner, key, reason):
    if not re.fullmatch(r"[a-f0-9]{64}", key) or (reason is not None and reason not in FEEDBACK):
        raise ValueError("상품과 피드백 항목을 확인하세요.")
    with connection() as db:
        if reason is None:
            db.execute("DELETE FROM feedback WHERE buyer_id=? AND product_key=?", (owner, key))
        else:
            db.execute("""INSERT INTO feedback(buyer_id,product_key,reason) VALUES (?,?,?)
                          ON CONFLICT(buyer_id,product_key) DO UPDATE SET reason=excluded.reason,
                          updated_at=CURRENT_TIMESTAMP""", (owner, key, reason))


def save_quote(owner, quote_id, quote):
    if not owner or quote["stock"] in UNAVAILABLE:
        raise ValueError("구매자와 옵션 재고를 확인하세요.")
    with connection() as db:
        db.execute("""INSERT INTO quote(buyer_id,quote_id,snapshot) VALUES (?,?,?)
                      ON CONFLICT(buyer_id,quote_id) DO NOTHING""",
                   (owner, quote_id, json.dumps(quote, ensure_ascii=False)))


def saved_quotes(owner):
    with connection() as db:
        rows = db.execute("""SELECT quote_id,snapshot FROM quote WHERE buyer_id=?
                             ORDER BY saved_at DESC,rowid DESC LIMIT 50""", (owner,))
        return [(key, json.loads(data)) for key, data in rows]
