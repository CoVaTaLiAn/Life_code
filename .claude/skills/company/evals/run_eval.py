#!/usr/bin/env python3
"""Jev の判定を正解付きの例で確かめる。部署やチェック表を変えたら実行する。

  python3 run_eval.py route   振り分け（route_cases.json。質問の調整に使った例）
  python3 run_eval.py route route_holdout.json   調整に使っていない例（こちらの数字を信用する）
  python3 run_eval.py check   一次チェック（docs/ と check_cases.json）
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JEV = HERE.parent / "scripts" / "jev.py"


def run(*args):
    r = subprocess.run([sys.executable, str(JEV), *args], capture_output=True, text=True)
    if r.returncode == 2:
        sys.exit("Jev を呼べない: " + r.stderr)
    return json.loads(r.stdout)


def route():
    cases = json.loads((HERE / (sys.argv[2] if len(sys.argv) > 2 else "route_cases.json")).read_text(encoding="utf-8"))
    tp = fp = fn = 0
    ok = {"team": 0, "multi": 0, "outward": 0, "unclear": 0}
    usd = 0
    for c in cases:
        o = run("route", c["text"])
        usd += o["usd"]
        want, got = set(c["team"]), set(o["team"])
        tp += len(want & got); fp += len(got - want); fn += len(want - got)
        e_team = want == got
        e_multi = o["multi"] == c["multi"]
        e_out = (o["outward_action"] >= 0.5) == c["outward"]
        e_unc = (o["clarity"] < 1.0) == c.get("unclear", False)
        for k, e in zip(ok, (e_team, e_multi, e_out, e_unc)):
            ok[k] += e
        mark = "".join("o" if e else "x" for e in (e_team, e_multi, e_out, e_unc))
        print("%s %s\n     team=%s 余分=%s 不足=%s multi=%s out=%.2f clarity=%.2f" % (
            mark, c["text"][:44], sorted(got), sorted(got - want), sorted(want - got),
            o["multi"], o["outward_action"], o["clarity"]))
    n = len(cases)
    print("\n編成が完全一致 %d/%d ／ 部署単位の適合率 %.2f 再現率 %.2f" % (
        ok["team"], n, tp / max(tp + fp, 1), tp / max(tp + fn, 1)))
    print("規模 %d/%d ／ 外に出る操作 %d/%d ／ 曖昧さ %d/%d ／ 費用 $%.5f" % (
        ok["multi"], n, ok["outward"], n, ok["unclear"], n, usd))


def check():
    cases = json.loads((HERE / "check_cases.json").read_text(encoding="utf-8"))
    tp = fp = fn = 0
    usd = 0
    for c in cases:
        args = ["check", str(HERE / "docs" / c["file"]), "--kind", c.get("kind", "")]
        if c.get("goal"):
            args += ["--goal", c["goal"]]
        o = run(*args)
        usd += o["usd"]
        want, got = set(c["flags"]), {r["check"] for r in o["flagged"]}
        tp += len(want & got); fp += len(got - want); fn += len(want - got)
        print("%s %-22s %s 余分=%s 見逃し=%s" % (
            "o" if want == got else "x", c["file"], o["verdict"],
            {r["check"]: r["p"] for r in o["flagged"] if r["check"] in got - want}, sorted(want - got)))
    print("\n指摘単位の適合率 %.2f 再現率 %.2f ／ 費用 $%.5f" % (
        tp / max(tp + fp, 1), tp / max(tp + fn, 1), usd))


if __name__ == "__main__":
    {"route": route, "check": check}[sys.argv[1] if len(sys.argv) > 1 else "route"]()
