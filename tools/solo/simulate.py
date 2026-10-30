"""損益分岐点と価格の試算。"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class BreakEven:
    price: int              # 1件（1個・1か月）あたりの売上（税抜）
    variable_rate: float    # 売上に対する変動費の割合（外注費・材料費など）0〜1
    fixed: int              # 月の固定費（役員報酬・社会保険料・家賃・ツール代など）
    target_profit: int = 0  # 月に残したい利益
    hours_per_unit: float = 0.0

    @property
    def margin(self) -> float:
        return self.price * (1 - self.variable_rate)

    @property
    def units(self) -> int:
        if self.margin <= 0:
            raise ValueError("変動費が売上以上なので、何件売っても利益が出ません")
        return math.ceil((self.fixed + self.target_profit) / self.margin)

    @property
    def sales(self) -> int:
        return self.units * self.price

    def to_markdown(self) -> str:
        L = [
            "| 前提 | 値 |", "|---|---:|",
            f"| 単価（税抜） | {self.price:,}円 |",
            f"| 変動費率 | {self.variable_rate:.0%} |",
            f"| 月の固定費 | {self.fixed:,}円 |",
            f"| 目標利益 | {self.target_profit:,}円 |", "",
            f"**必要な件数：月 {self.units} 件（売上 {self.sales:,}円）**", "",
            f"- 1件あたりの粗利：{int(self.margin):,}円",
        ]
        if self.hours_per_unit:
            h = self.units * self.hours_per_unit
            L.append(f"- 必要な作業時間：月 {h:.0f} 時間（1件 {self.hours_per_unit:g} 時間）")
            L.append(f"- 時間あたりの粗利：{int(self.margin / self.hours_per_unit):,}円")
            if h > 140:
                L.append("- ⚠ 1人で回すには時間が足りない可能性。単価を上げるか作業を減らす")
        L += ["", "単価を変えた場合：", "", "| 単価 | 必要件数 | 売上 |", "|---:|---:|---:|"]
        for f in (0.8, 1.0, 1.2, 1.5):
            p = int(self.price * f)
            try:
                b = BreakEven(p, self.variable_rate, self.fixed, self.target_profit)
                L.append(f"| {p:,} | {b.units} | {b.sales:,} |")
            except ValueError:
                L.append(f"| {p:,} | 利益が出ない | - |")
        L += ["", "※ 税金・社会保険料は固定費に含めた前提の概算。"]
        return "\n".join(L) + "\n"


def runway(balance: int, monthly_fixed: int, monthly_sales: int = 0) -> float:
    """手元資金で何か月もつか（売上がこのまま続く前提）。"""
    burn = monthly_fixed - monthly_sales
    return math.inf if burn <= 0 else balance / burn
