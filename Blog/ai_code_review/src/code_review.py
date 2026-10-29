#!/usr/bin/env python3
"""Claude API を使ったコードレビュー CLI。

使い方の例:
    python code_review.py                    # 未コミットの変更 (git diff HEAD) をレビュー
    python code_review.py --base main        # main ブランチとの差分をレビュー
    python code_review.py app.py utils.py    # ファイルを丸ごとレビュー
    python code_review.py --output review.md # 結果をファイルに保存
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"

SEVERITIES = ["critical", "high", "medium", "low", "info"]
SEVERITY_LABEL = {
    "critical": "🔴 Critical",
    "high": "🟠 High",
    "medium": "🟡 Medium",
    "low": "🔵 Low",
    "info": "⚪ Info",
}
CATEGORY_LABEL = {
    "bug": "バグ",
    "security": "セキュリティ",
    "performance": "パフォーマンス",
    "readability": "可読性",
    "maintainability": "保守性",
    "style": "スタイル",
    "test": "テスト",
}

SYSTEM_PROMPT = """\
あなたは経験豊富なシニアエンジニアとして、渡されたコード（または差分）をレビューします。

方針:
- 指摘はすべて日本語で書いてください。
- 見つけた問題は重要度が低くても漏れなく報告してください。重要度は severity で表し、利用者側で絞り込みます。
- 推測ではなく、コードから根拠を示せる指摘をしてください。どんな入力・状況で問題が起きるかを具体的に書いてください。
- 差分レビューの場合は、変更された行とその影響範囲に集中してください。
- line は該当箇所の行番号（新しいファイル側）です。特定できない場合は 0 にしてください。
- suggestion には修正方法を具体的に書いてください（短いコード例を含めても構いません）。
- 良い点があれば good_points に挙げてください。

severity の目安:
- critical: データ破損・セキュリティ侵害・確実なクラッシュなど、マージしてはいけないもの
- high: 通常の利用で誤動作するバグ
- medium: 特定条件で起きるバグや、将来問題になりやすい設計
- low: 小さな改善点
- info: 参考情報・好みの範囲
"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "レビュー全体の要約（2〜4文）"},
        "good_points": {"type": "array", "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "category": {"type": "string", "enum": list(CATEGORY_LABEL)},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": [
                    "file", "line", "severity", "category", "title", "detail", "suggestion",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "good_points", "findings"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# レビュー対象の収集
# ---------------------------------------------------------------------------

def run_git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} に失敗しました:\n{result.stderr.strip()}")
    return result.stdout


def collect_diff(base: str | None, staged: bool) -> str:
    """git の差分を取得する。"""
    if staged:
        args = ["diff", "--cached"]
    elif base:
        # base から分岐した地点との差分（PR と同じ見え方）
        args = ["diff", f"{base}...HEAD"]
    else:
        args = ["diff", "HEAD"]
    diff = run_git([*args, "--unified=5"])

    # 未追跡の新規ファイルも差分に含める（作業ツリーのレビュー時のみ）
    if not staged and not base:
        untracked = run_git(["ls-files", "--others", "--exclude-standard"]).split()
        for path in untracked:
            text = read_text(Path(path))
            if text is None:
                continue
            lines = text.splitlines()
            body = "\n".join(f"+{line}" for line in lines)
            diff += (
                f"\ndiff --git a/{path} b/{path}\nnew file\n--- /dev/null\n+++ b/{path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
            )
    return diff


def read_text(path: Path) -> str | None:
    """テキストファイルを読む。バイナリなら None。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"[skip] バイナリのようなので除外: {path}", file=sys.stderr)
        return None


def collect_files(paths: list[str]) -> str:
    """指定ファイルを行番号付きで連結する。ディレクトリは中のファイルを再帰的に読む。"""
    parts = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            raise SystemExit(f"ファイルが見つかりません: {raw}")
        files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        for f in files:
            if any(part.startswith(".") for part in f.parts):
                continue  # .git などの隠しフォルダは除外
            text = read_text(f)
            if text is None:
                continue
            numbered = "\n".join(f"{i:>5}| {line}" for i, line in enumerate(text.splitlines(), 1))
            parts.append(f'<file path="{f}">\n{numbered}\n</file>')
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Claude API 呼び出し
# ---------------------------------------------------------------------------

def request_review(content: str, mode: str, extra: str | None, effort: str) -> dict:
    client = anthropic.Anthropic()

    if mode == "diff":
        intro = "以下の git diff をレビューしてください。"
        wrapped = f"<diff>\n{content}\n</diff>"
    else:
        intro = "以下のファイルをレビューしてください。各行の先頭は行番号です。"
        wrapped = content
    user_text = intro + "\n\n" + wrapped
    if extra:
        user_text += f"\n\n<review_focus>\n{extra}\n</review_focus>"

    try:
        # 入力・出力が大きくなりやすいのでストリーミングで受け取る
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": REVIEW_SCHEMA},
            },
            # 安全分類器で断られた場合、サーバー側で別モデルに自動で再実行させる
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise SystemExit("認証に失敗しました。ANTHROPIC_API_KEY を確認してください。")
    except anthropic.RateLimitError:
        raise SystemExit("レート制限に達しました。しばらく待ってから再実行してください。")
    except anthropic.BadRequestError as e:
        raise SystemExit(f"リクエストエラー: {e.message}")
    except anthropic.APIStatusError as e:
        raise SystemExit(f"API エラー ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise SystemExit("API に接続できませんでした。ネットワークを確認してください。")

    if message.stop_reason == "refusal":
        raise SystemExit("Claude がこのリクエストへの回答を断りました。")
    if message.stop_reason == "max_tokens":
        raise SystemExit("出力が上限で途切れました。対象を分けて再実行してください。")

    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise SystemExit("レビュー結果を受け取れませんでした。")
    review = json.loads(text)
    review["_usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return review


# ---------------------------------------------------------------------------
# レポート出力
# ---------------------------------------------------------------------------

def filter_findings(review: dict, min_severity: str) -> list[dict]:
    limit = SEVERITIES.index(min_severity)
    findings = [f for f in review["findings"] if SEVERITIES.index(f["severity"]) <= limit]
    return sorted(findings, key=lambda f: (SEVERITIES.index(f["severity"]), f["file"], f["line"]))


def render_markdown(review: dict, findings: list[dict]) -> str:
    out = ["# コードレビュー結果", "", "## 概要", "", review["summary"], ""]

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    out.append(" / ".join(f"{SEVERITY_LABEL[s]}: {counts[s]}" for s in SEVERITIES))
    out.append("")

    if review.get("good_points"):
        out += ["## 良い点", ""]
        out += [f"- {p}" for p in review["good_points"]]
        out.append("")

    out += ["## 指摘事項", ""]
    if not findings:
        out += ["指摘はありません。", ""]
    for i, f in enumerate(findings, 1):
        loc = f["file"] + (f":{f['line']}" if f["line"] else "")
        category = CATEGORY_LABEL.get(f["category"], f["category"])
        out += [
            f"### {i}. {SEVERITY_LABEL[f['severity']]} [{category}] {f['title']}",
            "",
            f"**場所:** `{loc}`",
            "",
            f["detail"],
            "",
            f"**修正案:** {f['suggestion']}",
            "",
        ]

    usage = review.get("_usage")
    if usage:
        out.append(f"<sub>tokens: input {usage['input_tokens']} / output {usage['output_tokens']}</sub>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Claude でコードレビューを行います。")
    parser.add_argument("paths", nargs="*", help="レビューするファイル/フォルダ（省略時は git diff）")
    parser.add_argument("--base", help="このブランチとの差分をレビュー（例: main）")
    parser.add_argument("--staged", action="store_true", help="ステージ済みの変更だけをレビュー")
    parser.add_argument("--focus", help="特に見てほしい観点（例: 'セキュリティ重視で'）")
    parser.add_argument("--min-severity", choices=SEVERITIES, default="info",
                        help="表示する最低の重要度（既定: info = すべて）")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"],
                        default="high", help="レビューの深さ（既定: high）")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", "-o", help="結果を保存するファイル（省略時は標準出力）")
    parser.add_argument("--fail-on", choices=SEVERITIES,
                        help="この重要度以上の指摘があれば終了コード 1 を返す（CI 用）")
    args = parser.parse_args()

    if args.paths:
        mode, content = "files", collect_files(args.paths)
    else:
        mode, content = "diff", collect_diff(args.base, args.staged)

    if not content.strip():
        print("レビュー対象の変更がありません。")
        return 0

    print(f"レビュー中... ({len(content):,} 文字)", file=sys.stderr)
    review = request_review(content, mode, args.focus, args.effort)
    findings = filter_findings(review, args.min_severity)

    if args.format == "json":
        result = json.dumps({**review, "findings": findings}, ensure_ascii=False, indent=2) + "\n"
    else:
        result = render_markdown(review, findings)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"保存しました: {args.output}", file=sys.stderr)
    else:
        print(result)

    if args.fail_on:
        threshold = SEVERITIES.index(args.fail_on)
        if any(SEVERITIES.index(f["severity"]) <= threshold for f in review["findings"]):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
