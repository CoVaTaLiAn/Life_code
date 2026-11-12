#!/usr/bin/env python3
"""Jev（TypeSafe AI）で、安く早く済む判定を済ませる。company スキル用。

Jev は文章を書かない。「はい/いいえ（noul）」「選択（choice）」「採点（score）」の確率だけを返す。
1回 0.5 秒前後・入力 100万トークンあたり約 $0.04 なので、振り分け・一次チェック・関連度の採点に使う。

使い方:
  jev.py route  "依頼文"                     どの部署の仕事か・会社を動かす規模か・依頼が明確か
  jev.py check  成果物.md --goal "目的"      成果物の一次チェック（問題がありそうな項目を返す）
  jev.py rank   候補.txt --goal "目的"       候補（1行1件 or JSONL）を目的との関連度で並べる
  jev.py ask    状態.txt 質問.json           質問を自由に指定（公式の questions 形式）

終了コード: 0=成功 / 1=check で要注意あり / 2=Jev を呼べなかった（Claude の判断に切り替える）
鍵: 環境変数 TYPESAFE_API_KEY。Claude Code のクラウド環境ではプロキシが付けるので不要。
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
CHUNK = 6000  # 1回に渡す文字数（1質問あたり 32k トークンの上限に十分収まる大きさ）
HERE = Path(__file__).resolve().parent
DEPARTMENTS = HERE.parent / "references" / "departments.json"
CHECKLISTS = HERE.parent / "references" / "checklists.json"


class JevError(Exception):
    pass


def call(state, questions, retries=3):
    """Jev を1回呼ぶ。返り値は (answers, usage)。"""
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode("utf-8")
    key = os.environ.get("TYPESAFE_API_KEY", "proxy-injected")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    last = ""
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("answers", {}), data.get("usage", {})
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
            if e.code not in (429, 529, 500, 502, 503):
                break
        except Exception as e:  # 通信エラーなど
            last = "%s: %s" % (type(e).__name__, e)
        time.sleep(1.5 * (i + 1))
    raise JevError(last)


def chunks(text):
    return [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]


def add_usage(total, usage):
    total["input_tokens"] = total.get("input_tokens", 0) + usage.get("input_tokens", 0)
    total["calls"] = total.get("calls", 0) + 1


def cost(total):
    # jev-1.14.0: 入力 $0.042 / 100万トークン、出力は無料
    return round(total.get("input_tokens", 0) * 0.042 / 1_000_000, 6)


# ---------- route: 依頼の振り分け ----------

def cmd_route(args):
    depts = json.loads(DEPARTMENTS.read_text(encoding="utf-8"))
    request = args.text if args.text != "-" else sys.stdin.read()
    questions = {
        "lead": {
            "type": "choice",
            "instructions": "この依頼で最初に動くべき担当はどれか。",
            "criteria": {k: v["does"] for k, v in depts.items()},
        },
        "trivial": {
            "type": "noul",
            "instructions": "この依頼は、知識だけでその場で答えられる質問か、1か所を直すだけの小さな修正か？",
            "criteria": {
                "true": "言葉や概念の説明を求める質問、誤字や1行の修正など、数分で終わるもの",
                "false": "調べる・分析する・作る・まとめるなど、まとまった作業が要るもの。本人のメールや予定など、見に行かないと分からないもの",
            },
        },
        "outward": {
            "type": "noul",
            "instructions": "この依頼をやり遂げるには、本人の代わりに外へ働きかける操作（メールやメッセージを送る、予定を登録・変更する、ネットに公開する、他人と共有する、申し込む、支払う）が必要か？",
            "criteria": {
                "true": "今回、送る・登録する・公開する・共有する・申し込む・買う、のどれかまでやってほしいと頼んでいる",
                "false": "調べる・分析する・作る・書く・整理する・下書きを作る、までで終わる。送信や通知をするプログラムを作るだけの場合も含む",
            },
        },
        "clarity": {
            "type": "score",
            "instructions": "依頼の明確さ。",
            "criteria": [
                "何をしてほしいのか分からない",
                "やりたいことは分かるが、最後に何を渡せばよいかが曖昧",
                "目的も、最後に渡すものも分かる",
            ],
        },
    }
    for name, d in depts.items():
        questions["need_" + name] = {
            "type": "noul",
            "instructions": "この依頼は、次の仕事をはっきり求めているか？ 仕事: " + d["does"],
            "criteria": {
                "true": "依頼の文面が、この仕事そのものを求めている",
                "false": "依頼の文面はこの仕事を求めていない。別の仕事のついでに少し発生するだけの場合も含む",
            },
        }
    ans, usage = call("依頼: " + request, questions)
    total = {}
    add_usage(total, usage)
    need = {n: round(ans["need_" + n]["noul"], 2) for n in depts}
    team = [n for n, p in sorted(need.items(), key=lambda x: -x[1]) if p >= args.threshold]
    trivial = round(ans["trivial"]["noul"], 2)
    if trivial >= 0.5:
        team = []
    out = {
        "lead": ans["lead"]["choice"],
        "lead_confidence": round(ans["lead"]["confidence"], 2),
        "team": team,
        "need": need,
        "trivial": trivial,
        "multi": len(team) >= 2,
        "outward_action": round(ans["outward"]["noul"], 2),
        "clarity": round(ans["clarity"]["score"], 2),
        "advice": [],
        "usage": total,
        "usd": cost(total),
    }
    if out["clarity"] < 1.0:
        out["advice"].append("依頼が曖昧。発注の前にオーナーへ質問する")
    if not team:
        out["advice"].append("部署はいらない。社長がその場で処理する")
    elif len(team) == 1:
        out["advice"].append("1部署で済む。plan.md は省略形にして直接発注する")
    if out["outward_action"] >= 0.5:
        out["advice"].append("外に出る操作を含みそう。決裁事項として plan.md に書く")
    if team and out["lead_confidence"] < 0.6:
        out["advice"].append("担当の確信が低い。社長が自分で編成を決める")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ---------- check: 成果物の一次チェック ----------

def cmd_check(args):
    lists = json.loads(CHECKLISTS.read_text(encoding="utf-8"))
    kinds = ["common"] + [k for k in args.kind.split(",") if k and k != "common"]
    items = {}
    for k in kinds:
        if k not in lists:
            raise SystemExit("種類が不明: %s（使えるもの: %s）" % (k, ", ".join(lists)))
        items.update(lists[k])
    if not args.goal:
        items = {k: v for k, v in items.items() if not v.get("needs_goal")}
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    parts = chunks(text)
    goal = "【この成果物の目的】" + args.goal + "\n" if args.goal else ""

    def build(scope_filter):
        qs = {}
        for name, it in items.items():
            if it.get("scope", "any") in scope_filter:
                qs[name] = {
                    "type": "noul",
                    "instructions": it["q"],
                    "criteria": {"true": it["yes"], "false": it["no"]},
                }
        return qs

    jobs = []  # (位置, state, questions)
    head_qs = build({"head", "any"})
    rest_qs = build({"any"})
    jobs.append((0, goal + "【成果物（冒頭）】\n" + parts[0], head_qs))
    for i, p in enumerate(parts[1:], 1):
        if rest_qs:
            jobs.append((i, goal + "【成果物（続き %d/%d）】\n" % (i + 1, len(parts)) + p, rest_qs))

    total, worst = {}, {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(call, s, q): i for i, s, q in jobs}
        for f in cf.as_completed(futs):
            ans, usage = f.result()
            add_usage(total, usage)
            for name, a in ans.items():
                p = a.get("noul", 0.0)
                if p > worst.get(name, (-1, 0))[0]:
                    worst[name] = (p, futs[f])

    flagged, passed = [], []
    for name, it in items.items():
        p, where = worst.get(name, (0.0, 0))
        row = {"check": name, "label": it["label"], "p": round(p, 2), "severity": it.get("severity", "重要")}
        if p >= it.get("threshold", args.threshold):
            row["near"] = "先頭から約 %d 字付近" % (where * CHUNK)
            flagged.append(row)
        else:
            passed.append(row)
    flagged.sort(key=lambda r: -r["p"])
    fatal = [r for r in flagged if r["severity"] == "致命"]
    verdict = "差し戻し候補" if fatal else ("要注意" if flagged else "一次チェック通過")
    out = {
        "file": args.file,
        "chars": len(text),
        "verdict": verdict,
        "flagged": flagged,
        "passed": [r["check"] for r in passed],
        "note": "Jev は事実の正しさを確かめない。形と明らかな不備だけを見る一次チェック",
        "usage": total,
        "usd": cost(total),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if flagged else 0


# ---------- rank: 関連度で並べる ----------

def cmd_rank(args):
    raw = Path(args.file).read_text(encoding="utf-8", errors="replace").splitlines()
    items = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                items.append((obj.get("id", len(items) + 1), obj.get("text") or json.dumps(obj, ensure_ascii=False)))
                continue
            except json.JSONDecodeError:
                pass
        items.append((len(items) + 1, line))
    question = {
        "rel": {
            "type": "score",
            "instructions": "次の目的に対して、この候補はどれくらい役に立つか。目的: " + args.goal,
            "criteria": [
                "関係ない",
                "話題は近いが、目的には直接役立たない",
                "目的の一部に役立つ",
                "目的にそのまま役立つ中心的な情報",
            ],
        }
    }
    total, rows = {}, []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(call, text[:CHUNK], question): (i, text) for i, text in items}
        for f in cf.as_completed(futs):
            i, text = futs[f]
            ans, usage = f.result()
            add_usage(total, usage)
            rows.append({"id": i, "score": round(ans["rel"]["score"], 2), "text": text[:120]})
    rows.sort(key=lambda r: -r["score"])
    if args.top:
        rows = rows[:args.top]
    print(json.dumps({"scale": "0=関係ない 〜 3=中心的", "ranked": rows, "usage": total, "usd": cost(total)},
                     ensure_ascii=False, indent=2))
    return 0


# ---------- ask: 自由な質問 ----------

def cmd_ask(args):
    state = Path(args.state).read_text(encoding="utf-8", errors="replace")[: CHUNK * 4]
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    ans, usage = call(state, questions)
    total = {}
    add_usage(total, usage)
    print(json.dumps({"answers": ans, "usage": total, "usd": cost(total)}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Jev で安く早く判定する（company スキル用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("route", help="依頼の振り分け")
    p.add_argument("text", help='依頼文（"-" で標準入力）')
    p.add_argument("--threshold", type=float, default=0.5, help="この確率以上の部署を編成に入れる")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("check", help="成果物の一次チェック")
    p.add_argument("file")
    p.add_argument("--goal", default="", help="成果物の目的（あると「目的に答えているか」も見る）")
    p.add_argument("--kind", default="", help="追加のチェック表: research,code,draft,mail（カンマ区切り）")
    p.add_argument("--threshold", type=float, default=0.6, help="この確率以上を要注意にする")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("rank", help="候補を関連度で並べる")
    p.add_argument("file", help="1行1件のテキスト、または JSONL（id, text）")
    p.add_argument("--goal", required=True)
    p.add_argument("--top", type=int, default=0)
    p.set_defaults(fn=cmd_rank)

    p = sub.add_parser("ask", help="質問を自由に指定")
    p.add_argument("state")
    p.add_argument("questions")
    p.set_defaults(fn=cmd_ask)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except JevError as e:
        print(json.dumps({"error": "Jev を呼べなかった: %s" % e, "fallback": "Claude の判断で進める"},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
