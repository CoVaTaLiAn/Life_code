# company スキル 作業ログ

止まっても続きから再開できるように、区切りごとに追記する（新しいものが下）。

## 2026-11-12

- [済] 部署エージェント5つを追加: web-researcher / engineer / writer / secretary / reviewer（既存: data-analyst / paper-researcher / patent-search）
- [済] 社長の手順 `SKILL.md`、組織図 `references/org-chart.md`、書類の型 `references/templates.md`
- [済] Jev の仕様確認（判定専用: noul / choice / score。文章は書けない。入力 $0.042/100万トークン、1回 約0.4秒）
- [済] `scripts/jev.py`（route / check / rank / ask）、`references/departments.json`、`references/checklists.json`
- [済] 振り分けの実測 `evals/run_eval.py route`: 1回目 8/16 → 質問を直して 12/16（部署単位の適合率 1.00・再現率 0.80）
- [途中] 振り分けの残り: 「その場で答えられる」判定が秘書室の仕事を消してしまう
- [未] check の実測（良い例・悪い例の文書を作って確かめる）
- [未] タスクの難しさ → モデル選択（jev.py tier）、部署ごとの既定モデル
- [未] 決裁待ち箱・進捗ログ（progress.md）を SKILL.md に入れる
- [未] reviewer に Jev の一次チェックを組み込む
- [未] 通しの試運転、README 追記
