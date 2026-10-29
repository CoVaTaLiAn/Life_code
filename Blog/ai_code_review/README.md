# AI コードレビュー CLI

Claude API を使って、git の差分やファイルを自動でコードレビューするツールです。
指摘は重要度（Critical〜Info）・カテゴリ付きの日本語 Markdown レポートで出力されます。

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."   # https://console.anthropic.com で発行
```

## 使い方

```bash
# 未コミットの変更（新規ファイル含む）をレビュー
python src/code_review.py

# main ブランチからの差分をレビュー（PR と同じ範囲）
python src/code_review.py --base main

# ステージ済みの変更だけ
python src/code_review.py --staged

# ファイル・フォルダを丸ごとレビュー
python src/code_review.py src/app.py lib/

# 観点を指定してファイルに保存
python src/code_review.py --base main --focus "セキュリティ重視で" -o review.md
```

## オプション

| オプション | 説明 |
|---|---|
| `--base BRANCH` | 指定ブランチとの差分をレビュー |
| `--staged` | ステージ済みの変更のみ |
| `--focus TEXT` | 特に見てほしい観点 |
| `--min-severity` | 表示する最低の重要度（`critical`/`high`/`medium`/`low`/`info`） |
| `--effort` | レビューの深さ（`low`〜`max`、既定 `high`）。上げるほど丁寧だがコスト増 |
| `--format json` | JSON で出力（他ツール連携用） |
| `-o FILE` | 結果をファイルに保存 |
| `--fail-on LEVEL` | その重要度以上の指摘があれば終了コード 1（CI 用） |

## CI（GitHub Actions）で使う例

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pip install anthropic
- run: python Blog/ai_code_review/src/code_review.py --base origin/main --fail-on critical
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## 仕組み

1. `git diff`（またはファイル本文＋行番号）を集める
2. Claude（`claude-opus-5-5`）に構造化出力（JSON Schema）でレビューを依頼
3. 返ってきた指摘を重要度順に並べて Markdown / JSON で出力

- 安全分類器でリクエストが断られた場合は、サーバー側フォールバック（`fallbacks: "default"`）で自動的に別モデルが再実行します。
- 指摘は漏れなく出させ、`--min-severity` で利用者側で絞り込む設計です。
