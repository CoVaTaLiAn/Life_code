"""設定ファイルと台帳（CSV）の読み書き。

データの置き場所（ルート）は次の順で決まる。
1. コマンドの --root
2. 環境変数 SOLO_ROOT
3. リポジトリ直下の company/
"""

from __future__ import annotations

import csv
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 台帳ごとの列（順番もこのとおりに書き出す）
SCHEMAS: dict[str, list[str]] = {
    "sales": ["請求番号", "請求日", "取引先", "内容", "税抜金額", "消費税", "税込金額", "入金予定日", "入金日", "備考"],
    "expenses": ["日付", "支払先", "内容", "勘定科目", "税込金額", "消費税", "支払方法", "証憑", "備考"],
    "pipeline": ["案件名", "相手先", "担当者", "段階", "見込金額", "受注確度(%)", "次の行動", "次の行動日", "最終更新", "備考"],
    "contracts": ["相手先", "契約名", "締結日", "開始日", "終了日", "自動更新", "解約予告期限", "保管場所", "備考"],
    "kpi": ["月", "売上", "経費", "利益", "新規商談数", "受注数", "手元資金", "備考"],
    "recurring": ["名前", "金額", "頻度", "支払日", "支払月", "開始", "終了", "備考"],
    "account_rules": ["キーワード", "勘定科目"],
}

PATHS: dict[str, str] = {
    "sales": "finance/sales.csv",
    "expenses": "finance/expenses.csv",
    "recurring": "finance/recurring.csv",
    "pipeline": "sales/pipeline.csv",
    "contracts": "admin/contracts.csv",
    "kpi": "strategy/kpi.csv",
    "account_rules": "config/account_rules.csv",
}


@dataclass
class Store:
    root: Path

    @classmethod
    def open(cls, root: str | os.PathLike | None = None) -> "Store":
        r = root or os.environ.get("SOLO_ROOT") or REPO / "company"
        return cls(Path(r).resolve())

    # ---- 設定 ----
    @property
    def config(self) -> dict:
        p = self.root / "config.toml"
        if not p.exists():
            return {}
        with p.open("rb") as f:
            return tomllib.load(f)

    def cfg(self, dotted: str, default=None):
        cur = self.config
        for key in dotted.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    # ---- 台帳 ----
    def path(self, name: str) -> Path:
        return self.root / PATHS[name]

    def read(self, name: str) -> list[dict[str, str]]:
        p = self.path(name)
        if not p.exists():
            return []
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in rows]

    def write(self, name: str, rows: list[dict[str, str]]) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = SCHEMAS[name]
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:  # BOM付き：Excelで開いても文字化けしない
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        tmp.replace(p)

    def append(self, name: str, row: dict[str, str]) -> None:
        rows = self.read(name)
        rows.append(row)
        self.write(name, rows)


def yen(v) -> int:
    """'¥12,300' や '12300' を整数にする。空なら0。"""
    if v is None:
        return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace("−", "-").strip()
    if not s:
        return 0
    return int(round(float(s)))


def fmt(n: int) -> str:
    return f"{n:,}" if n >= 0 else f"−{-n:,}"


def money(n: int) -> str:
    """¥表記。マイナスは −¥1,000 のように書く。"""
    return f"¥{n:,}" if n >= 0 else f"−¥{-n:,}"
