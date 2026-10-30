"""経費の記帳：1件ずつの追加、カード・銀行明細CSVの取り込み、勘定科目の自動判定。"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from . import dates
from .store import Store, yen

UNKNOWN = "要確認"

# よく使う勘定科目（これ以外も使えるが、チェック時に注意を出す）
ACCOUNTS = [
    "通信費", "旅費交通費", "消耗品費", "会議費", "接待交際費", "支払手数料", "外注費",
    "地代家賃", "水道光熱費", "広告宣伝費", "新聞図書費", "研修費", "荷造運賃", "租税公課",
    "支払報酬", "福利厚生費", "法定福利費", "役員報酬", "保険料", "雑費", "工具器具備品",
]


def classify(store: Store, text: str) -> str:
    """支払先・内容に含まれるキーワードから勘定科目を決める。長いキーワードを優先する。"""
    rules = sorted(store.read("account_rules"), key=lambda r: -len(r["キーワード"]))
    low = text.lower()
    for r in rules:
        if r["キーワード"] and r["キーワード"].lower() in low:
            return r["勘定科目"]
    return UNKNOWN


def tax_estimate(store: Store, amount: int, rate: int = 10) -> str:
    """課税事業者なら税込金額から消費税を概算（内税）。免税事業者なら空欄。"""
    if not store.cfg("tax.consumption_taxable", False):
        return ""
    return str(amount * rate // (100 + rate))


def add(store: Store, date: dt.date, payee: str, desc: str, amount: int, account: str | None = None,
        method: str = "", voucher: str = "", note: str = "") -> dict:
    row = {
        "日付": date.isoformat(),
        "支払先": payee,
        "内容": desc,
        "勘定科目": account or classify(store, f"{payee} {desc}"),
        "税込金額": str(amount),
        "消費税": tax_estimate(store, amount),
        "支払方法": method,
        "証憑": voucher or "証憑なし",
        "備考": note,
    }
    store.append("expenses", row)
    return row


def _key(r: dict) -> tuple:
    return (r["日付"], r["支払先"], yen(r["税込金額"]))


def import_csv(store: Store, path: Path, date_col: str, payee_col: str, amount_col: str,
               method: str = "", encoding: str = "utf-8-sig", desc_col: str | None = None,
               dry_run: bool = False) -> tuple[list[dict], int]:
    """カード・銀行の明細CSVを取り込む。同じ日付・支払先・金額の行はとばす。

    戻り値：(追加した行, 重複でとばした件数)
    """
    with path.open(encoding=encoding, newline="") as f:
        src = list(csv.DictReader(f))
    if src and any(c not in src[0] for c in (date_col, payee_col, amount_col)):
        raise KeyError(f"列名が見つかりません。CSVの列：{list(src[0].keys())}")

    existing = {_key(r) for r in store.read("expenses")}
    added, skipped = [], 0
    for s in src:
        if not (s.get(date_col) or "").strip():
            continue
        amount = yen(s[amount_col])
        if amount <= 0:  # 返金・入金は経費にしない
            continue
        payee = s[payee_col].strip()
        desc = (s.get(desc_col) or "").strip() if desc_col else ""
        row = {
            "日付": dates.parse(s[date_col]).isoformat(),
            "支払先": payee,
            "内容": desc,
            "勘定科目": classify(store, f"{payee} {desc}"),
            "税込金額": str(amount),
            "消費税": tax_estimate(store, amount),
            "支払方法": method,
            "証憑": "明細のみ（領収書を確認）",
            "備考": f"取込:{path.name}",
        }
        if _key(row) in existing:
            skipped += 1
            continue
        existing.add(_key(row))
        added.append(row)
    if not dry_run and added:
        rows = store.read("expenses") + added
        rows.sort(key=lambda r: r["日付"])
        store.write("expenses", rows)
    return added, skipped
