#!/usr/bin/env python3
"""案件の進捗ログ・トークン予算・決裁待ち箱を1コマンドで扱う。company スキル用。

止まっても続きから再開できるように、社長は一手ごとに log を打つ。

  ledger.py start  <案件フォルダ> "目的" [--budget 600000]   案件を始める
  ledger.py log    <案件フォルダ> "やったこと" [--task T1] [--status 発注|受領|途中|差し戻し|失敗|済]
                   [--tokens 12345] [--model sonnet]            1行追記し、予算の状態を返す
  ledger.py status <案件フォルダ>                             どこまで進んだか・予算・モード
  ledger.py decide <案件フォルダ> "お願いしたい決裁" [--detail "補足"] [--file パス]   決裁待ち箱に入れる
  ledger.py inbox                                             決裁待ち箱の未処理を一覧
  ledger.py resolve <番号> 承認|却下|保留 [--note "メモ"]      決裁の結果を書く
  ledger.py open                                              終わっていない案件を一覧（再開用）

状態: 既定は「途中」。「済」は検収を通った時だけ明示して付ける（再開時、済でないタスクはやり直しの対象になる）。

モード（log と status が返す）:
  通常   … 予算の 70% 未満
  節約   … 70% 以上。モデルを1段軽くし、検収は Jev の一次チェック＋社長の目視にする
  打切り … 100% 以上。新しい発注をやめ、今あるもので報告をまとめる
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # リポジトリの直下
COMPANY = ROOT / "company"
INBOX = COMPANY / "DECISIONS.md"
LOG = COMPANY / "LOG.md"
STATUSES = ["発注", "受領", "途中", "差し戻し", "失敗", "済"]
DEFAULT_BUDGET = 600_000  # 1案件で部署に使わせるトークンの目安


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def case_dir(arg):
    p = Path(arg)
    if not p.is_absolute():
        p = (COMPANY / arg) if not arg.startswith("company") else (ROOT / arg)
    return p


def read_state(d):
    f = d / "state.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"budget": DEFAULT_BUDGET, "tokens": 0, "steps": 0, "done": False, "goal": "", "tasks": {}}


def write_state(d, st):
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mode(st):
    r = st["tokens"] / max(st["budget"], 1)
    return "打切り" if r >= 1.0 else ("節約" if r >= 0.7 else "通常")


def summary(st):
    return {
        "mode": mode(st),
        "tokens": st["tokens"],
        "budget": st["budget"],
        "used": "%d%%" % round(100 * st["tokens"] / max(st["budget"], 1)),
        "tasks": st["tasks"],
        "done": st["done"],
    }


def cmd_start(a):
    d = case_dir(a.case)
    d.mkdir(parents=True, exist_ok=True)
    st = read_state(d)
    st.update({"budget": a.budget, "goal": a.goal, "started": now()})
    write_state(d, st)
    p = d / "progress.md"
    if not p.exists():
        p.write_text("# 進捗ログ: %s\n\n- 目的: %s\n- 予算: %d トークン\n\n| 時刻 | タスク | 状態 | 内容 | トークン | モデル |\n|---|---|---|---|---|---|\n"
                     % (d.name, a.goal, a.budget), encoding="utf-8")
    print(json.dumps({"case": str(d), **summary(st)}, ensure_ascii=False, indent=2))


def cmd_log(a):
    d = case_dir(a.case)
    if not d.exists():
        sys.exit("案件フォルダがない。先に start する: %s" % d)
    st = read_state(d)
    st["tokens"] += a.tokens
    st["steps"] += 1
    if a.task:
        st["tasks"][a.task] = a.status
    if a.done:
        st["done"] = True
    write_state(d, st)
    with (d / "progress.md").open("a", encoding="utf-8") as f:
        f.write("| %s | %s | %s | %s | %s | %s |\n" % (
            now(), a.task or "-", a.status, a.text.replace("|", "／").replace("\n", " "),
            a.tokens or "", a.model or ""))
    if st["done"]:
        COMPANY.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write("- %s %s: %s（%d トークン）\n" % (now(), d.name, a.text.replace("\n", " "), st["tokens"]))
    out = summary(st)
    if out["mode"] == "節約":
        out["advice"] = "節約モード。jev.py tier に --save を付ける。検収は jev.py check と社長の目視で済ませる"
    elif out["mode"] == "打切り":
        out["advice"] = "予算超過。新しい発注をやめ、今ある成果物で report.md をまとめる。残りは決裁待ち箱へ"
    print(json.dumps(out, ensure_ascii=False))


def cmd_status(a):
    d = case_dir(a.case)
    st = read_state(d)
    tail = (d / "progress.md").read_text(encoding="utf-8").splitlines()[-8:] if (d / "progress.md").exists() else []
    print(json.dumps({"case": str(d), "goal": st.get("goal", ""), **summary(st), "last_steps": tail},
                     ensure_ascii=False, indent=2))


ROW = re.compile(r"^\| (\d+) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$")
HEAD = ("# 決裁待ち箱\n\nオーナーの判断が必要なことを、仕事を止めずにここへためる。まとめて処理する。\n\n"
        "| # | 受付 | 案件 | お願いしたいこと | 補足・ファイル | 結果 | メモ |\n|---|---|---|---|---|---|---|\n")


def rows():
    if not INBOX.exists():
        return []
    return [list(m.groups()) for m in map(ROW.match, INBOX.read_text(encoding="utf-8").splitlines()) if m]


def save_rows(rs):
    COMPANY.mkdir(exist_ok=True)
    INBOX.write_text(HEAD + "".join("| " + " | ".join(r) + " |\n" for r in rs), encoding="utf-8")


def clean(s):
    return (s or "").replace("|", "／").replace("\n", " ").strip() or "-"


def cmd_decide(a):
    rs = rows()
    n = max([int(r[0]) for r in rs], default=0) + 1
    d = case_dir(a.case)
    extra = " ".join(x for x in (a.detail, a.file) if x)
    rs.append([str(n), now(), d.name, clean(a.text), clean(extra), "未処理", "-"])
    save_rows(rs)
    if d.exists():
        with (d / "progress.md").open("a", encoding="utf-8") as f:
            f.write("| %s | - | 決裁待ち | 決裁待ち箱 #%d: %s |  |  |\n" % (now(), n, clean(a.text)))
    print(json.dumps({"id": n, "pending": sum(r[5] == "未処理" for r in rs)}, ensure_ascii=False))


def cmd_inbox(a):
    rs = [r for r in rows() if a.all or r[5] in ("未処理", "保留")]
    print(json.dumps([dict(zip(("id", "at", "case", "ask", "detail", "result", "note"), r)) for r in rs],
                     ensure_ascii=False, indent=2))


def cmd_resolve(a):
    rs = rows()
    hit = [r for r in rs if r[0] == str(a.id)]
    if not hit:
        sys.exit("番号 %s は決裁待ち箱にない" % a.id)
    hit[0][5] = a.result
    hit[0][6] = clean(a.note)
    save_rows(rs)
    print(json.dumps({"id": a.id, "result": a.result, "pending": sum(r[5] == "未処理" for r in rs)}, ensure_ascii=False))


def cmd_open(a):
    out = []
    if COMPANY.exists():
        for d in sorted(COMPANY.iterdir()):
            if d.is_dir() and (d / "state.json").exists():
                st = read_state(d)
                if not st.get("done"):
                    out.append({"case": d.name, "goal": st.get("goal", ""), **summary(st),
                                "todo": [t for t, s in st["tasks"].items() if s != "済"]})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="案件の進捗ログ・予算・決裁待ち箱")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("case"); p.add_argument("goal")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("log"); p.add_argument("case"); p.add_argument("text")
    p.add_argument("--task", default="")
    p.add_argument("--status", default="途中", choices=STATUSES,
                   help="済は検収を通った時だけ明示して付ける")
    p.add_argument("--tokens", type=int, default=0); p.add_argument("--model", default="")
    p.add_argument("--done", action="store_true", help="案件の完了を記録する"); p.set_defaults(fn=cmd_log)
    p = sub.add_parser("status"); p.add_argument("case"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("decide"); p.add_argument("case"); p.add_argument("text")
    p.add_argument("--detail", default=""); p.add_argument("--file", default=""); p.set_defaults(fn=cmd_decide)
    p = sub.add_parser("inbox"); p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_inbox)
    p = sub.add_parser("resolve"); p.add_argument("id", type=int)
    p.add_argument("result", choices=["承認", "却下", "保留"]); p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_resolve)
    p = sub.add_parser("open"); p.set_defaults(fn=cmd_open)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
