import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from solo.store import Store  # noqa: E402

CONFIG = """
[company]
name = "テスト株式会社"
type = "{type}"
founded = "{founded}"
fiscal_year_end_month = {fye}
officer_term_years = 10

[invoice]
registration_number = "T1234567890123"
default_tax_rate = 10
due_rule = "next_month_end"
bank = "テスト銀行"

[tax]
consumption_taxable = {taxable}
withholding_special = {special}

[cash]
balance = {balance}
as_of = "{as_of}"
warn_months = 6
"""


def make_store(founded="2026-11-02", fye=10, type_="株式会社", taxable=False, special=True,
               balance=1_000_000, as_of="2026-11-02") -> Store:
    """空の台帳とテスト用設定を持つ一時フォルダを作る。"""
    tmp = Path(tempfile.mkdtemp(prefix="solo-test-"))
    shutil.copytree(ROOT / "company", tmp, dirs_exist_ok=True)
    (tmp / "config.toml").write_text(CONFIG.format(
        type=type_, founded=founded, fye=fye, taxable=str(taxable).lower(), special=str(special).lower(),
        balance=balance, as_of=as_of), encoding="utf-8")
    s = Store.open(tmp)
    for name in ("sales", "expenses", "pipeline", "contracts", "recurring", "kpi"):
        s.write(name, [])
    return s
