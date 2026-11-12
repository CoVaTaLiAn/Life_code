#!/usr/bin/env python3
"""データクレンジングを段階ごとに実行する。各段階が自分の出力とレポートを残す。

  python3 cleanse.py --input raw.csv --out <出力先> --stage 1      # 1段階ずつ（レポートを見てから次へ）
  python3 cleanse.py --out <出力先> --stage 2                      # 段階2以降は前の段階の出力を読む
  python3 cleanse.py --input raw.csv --out <出力先> --stage all    # 1〜6 を順に（レポートは段階ごとに出る）

段階: 1 構造 → 2 文字の正規化 → 3 型の変換 → 4 カテゴリの統一 → 5 欠損の整理 → 6 外れ値
出力: <出力先>/stage<N>_<名前>/ に data.csv・data.schema.json・report.md・report.html・log.json
      <出力先>/report.md・report.html（全段階のまとめ）、段階6まで終わると cleaned.csv・cleaned.schema.json
各段階の処理は stages/ の別ファイルにある。このファイルは順番の管理・入出力・レポート出力だけを行う。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tabprep_common as tc  # noqa: E402
from stages import s1_structure, s2_text, s3_types, s4_categories, s5_missing, s6_outliers  # noqa: E402

STAGES = [s1_structure, s2_text, s3_types, s4_categories, s5_missing, s6_outliers]
HEAD = ["列", "内容", "件数", "例"]


def stage_dir(out, i):
    return Path(out) / f"stage{i}_{STAGES[i - 1].NAME}"


def shape_of(df):
    return {"rows": len(df), "cols": df.shape[1], "missing": int(df.isna().values.sum())}


def run_stage(i, a):
    mod, d = STAGES[i - 1], stage_dir(a.out, i)
    if i == 1:
        if not a.input:
            sys.exit("段階1には --input が必要です")
        src = Path(a.input)
        df, info = tc.read_raw(src)
        schema = None
    else:
        src = stage_dir(a.out, i - 1) / "data.csv"
        if not src.exists():
            sys.exit(f"段階{i - 1} の出力がありません。先に --stage {i - 1} を実行してください: {src}")
        df, schema, info = tc.load_table(src)
    for j in range(i, len(STAGES) + 1):  # この段階以降の古い出力は無効になるので消す
        if stage_dir(a.out, j).exists():
            shutil.rmtree(stage_dir(a.out, j))
    for f in ("cleaned.csv", "cleaned.schema.json"):
        (Path(a.out) / f).unlink(missing_ok=True)
    before = shape_of(df)
    df, schema, res = mod.run(df, schema, a)
    after = shape_of(df)
    tc.write_table(df, d / "data.csv", schema)
    for name, obj in res.get("files", {}).items():
        tc.jdump(obj, d / name)

    rep = tc.Report(f"クレンジング 段階{i}: {mod.TITLE}", mod.ROLE, {
        "入力": str(src), "出力": str(d / "data.csv"),
        "行 × 列": f"{before['rows']:,} × {before['cols']:,} → {after['rows']:,} × {after['cols']:,}",
        "欠損セル": f"{before['missing']:,} → {after['missing']:,}"})
    rep.h("1. 実施した変更")
    rep.table(HEAD, res["actions"], empty="変更なし（この段階で直すものは見つからなかった）")
    rep.h("2. 要確認（自動では変更していない）")
    rep.table(HEAD, res["review"], empty="なし")
    if res["review"]:
        rep.p("対応するときは、表に書いたオプションを付けてこの段階をやり直す（後の段階の出力は作り直しになる）。")
    rep.h("3. 状況")
    for title, headers, rows in res["tables"]:
        rep.h(title, 3)
        rep.table(headers, rows)
    rep.ul(res["notes"])
    rep.h("4. 次の処理")
    rep.p(mod.NEXT)
    path = rep.save(d)
    tc.jdump({"stage": i, "name": mod.NAME, "title": mod.TITLE, "input": str(src), "before": before, "after": after,
              "actions": res["actions"], "review": res["review"], "args": {k: v for k, v in vars(a).items() if v}},
             d / "log.json")
    if i == len(STAGES):
        tc.write_table(df, Path(a.out) / "cleaned.csv", schema)
    print(f"段階{i} {mod.TITLE}: {before['rows']:,}×{before['cols']} → {after['rows']:,}×{after['cols']}、"
          f"変更 {len(res['actions'])} 種類、要確認 {len(res['review'])} 件 → {path}")


def summary(out):
    logs = [json.loads((stage_dir(out, i) / "log.json").read_text(encoding="utf-8"))
            for i in range(1, len(STAGES) + 1) if (stage_dir(out, i) / "log.json").exists()]
    if not logs:
        return
    done = len(logs) == len(STAGES)
    rep = tc.Report("データクレンジング まとめ", "段階ごとのクレンジング結果を1つにまとめる（詳細は各段階のレポート）", {
        "元データ": logs[0]["input"], "進み具合": f"段階{logs[-1]['stage']} まで実行" + ("（完了）" if done else "（途中）"),
        "出力": str(Path(out) / "cleaned.csv") if done else "段階6まで終わると cleaned.csv ができる"})
    rep.h("1. 段階ごとの結果")
    rep.table(["段階", "行 × 列（前→後）", "欠損セル（前→後）", "変更の種類", "変更したセル・行の数", "要確認", "レポート"],
              [[f"{g['stage']} {g['title']}",
                f"{g['before']['rows']:,}×{g['before']['cols']} → {g['after']['rows']:,}×{g['after']['cols']}",
                f"{g['before']['missing']:,} → {g['after']['missing']:,}", len(g["actions"]),
                sum(int(str(r[2]).replace(",", "")) for r in g["actions"]), len(g["review"]),
                f"stage{g['stage']}_{g['name']}/report.html"] for g in logs])
    rep.h("2. 実施した変更（全段階）")
    rep.table(["段階"] + HEAD, [[g["stage"]] + r for g in logs for r in g["actions"]], empty="変更なし")
    rep.h("3. 要確認のまま残っているもの")
    rep.table(["段階"] + HEAD, [[g["stage"]] + r for g in logs for r in g["review"]], empty="なし")
    rep.h("4. 次の処理")
    rep.ul(["クレンジング後のデータをプロファイリングし直す（`cleaned.csv` を渡す）→ `encoding_plan.json` ができる",
            "その計画でエンコーディングする"] if done else [f"段階{logs[-1]['stage'] + 1} を実行する"])
    rep.save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="元データ（段階1で使う）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", required=True, help="1〜6、または all")
    for mod in STAGES:
        mod.add_args(ap)
    a = ap.parse_args()
    todo = range(1, len(STAGES) + 1) if a.stage == "all" else [int(a.stage)]
    for i in todo:
        run_stage(i, a)
    summary(a.out)
    print(f"まとめ: {Path(a.out) / 'report.html'}")


if __name__ == "__main__":
    main()
