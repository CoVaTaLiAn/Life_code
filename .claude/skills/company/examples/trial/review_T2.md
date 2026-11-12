# R2（T2 改善提案書）検収

## 判定: 条件付き合格

## 理由（3行以内）
- 合格基準（各提案に根拠・変更先・効果と手間）は5案すべて満たし、実物に照らした「現状の問題」の指摘も正確（ledger.py 188行の既定「済」、reviewer の tools、paper-researcher の Agent を確認）。
- ただし提案2の前提「サブエージェントは CLAUDE.md を見られない」は公式ドキュメントと食い違う（カスタムのサブエージェントは既定で CLAUDE.md を読み込む）。T1 の誤りをそのまま引き継いでいる。
- 提案4の案A（reviewer から Bash を外す）は今の検収手順を壊すうえ、目的（成果物を書き換えさせない）も果たせない。この2点をオーナーに注記すれば使える。

## 指摘（重い順）
| # | 重さ | 場所 | 問題 | 直し方の提案 |
|---|---|---|---|---|
| 1 | 重要 | 提案2 ①問題・③根拠（T1 §1「文脈の欠落」） | 「サブエージェントは CLAUDE.md 全体も見えない」は誤り。sub-agents ページには「Explore と Plan は CLAUDE.md なしで始まる。他の組み込みとカスタムのサブエージェントは `omitClaudeMd` を設定しない限り両方を読み込む」とある。「規則は発注プロンプトで再掲する」という助言は、Explore・Plan・`omitClaudeMd` を付けた部署に向けたもの。うちの8部署はどれも `omitClaudeMd` を設定していないので、CLAUDE.md は届いている。 | 【守る規則】欄の根拠を書き直す。CLAUDE.md の再掲としてではなく、「サブエージェントは呼び出し済みのスキル（company/SKILL.md など）と会話履歴を見ない（同ページに記述あり）。スキル側にしかない規則と案件固有の規則を再掲する」とする。効果「大」も見直す（範囲・労力の欄は根拠が別なので残る）。T1 の該当行にも訂正の注記が要る。 |
| 2 | 重要 | 提案4 ②案A | Bash を外すと、reviewer.md の手順が2か所動かなくなる。(a) 冒頭の「Jev の一次チェックを走らせる」、(b) 確かめること 5「コードなら実際に動かす（テスト・サンプル実行）」。提案書は (a) の付け替えにしか触れておらず、(b) が抜けている。そもそも Write が残る限り、どのファイルでも上書きできる。Bash を外しても「成果物を編集しない」の裏打ちにはならない。 | 案A を取り下げるか、「効果は限定的で、コード検収ができなくなる」と明記する。裏打ちには案B（hook）を本命として推す。 |
| 3 | 軽微 | 提案4【要確認】hook の書式 | T1 では未取得だが、公式に例がある。sub-agents ページによると、hooks は部署定義のフロントマターに直接書け、その部署が動いている間だけ効く。`PreToolUse` に `matcher` を付け、スクリプトが exit 2 を返すと操作を止められる（db-reader の例）。注意点もある。スクリプトに実行権限がないとブロックせずに失敗する。フォルダを信頼するまではフロントマターの hooks が無視される。 | 【要確認】を「書式は公式例あり。`Write\|Edit` を matcher にし、パスが `review_*.md` 以外なら exit 2 を返す。実行権限とフォルダ信頼の2点を要確認」に直す。 |
| 4 | 軽微 | 提案1 ②変更案 | 直すのは手順3の「受領」の例だけ。原則2は「発注」のときにもログを打つと定めており、`--task T1` を付けて発注を記録すると、既定値によって発注した時点で「済」になる。同じ穴が残る。また `--status` は自由入力（choices なし）なので、打ち間違えても弾かれない。 | 「発注・受領のログは `--status 途中`」と原則2にも明記する。ledger.py の既定値を `途中` に変える案（済は明示したときだけ）を代替として併記する。ledger.py の変更は1行で、既存の呼び出しへの影響は「済」の付け忘れが増えることだけ。 |
| 5 | 軽微 | 提案3 ②変更案 | 差し替え文の「正しさに影響する抜け・誤りだけ」「文体・好みは除外」が、残す予定の確かめること 4（安全：個人情報・無断の送信）と 6（読みやすさ）とぶつかる。安全の確認が対象外だと読まれるおそれがある。根拠にした best-practices の一文は、SPEC.md に照らしたコードレビューの例。調査報告や下書きの検収に当てはめるのは拡大解釈。 | 「正しさと安全に影響するもの」とし、6 は「オーナーの判断を妨げる場合だけ」と言い換える。根拠欄には「元はコードレビューの例」と一言添える。 |
| 6 | 軽微 | 提案5 ②変更案 | 部分結果の印（partial）が付くには Claude Code v2.1.246 以上が要ると公式にある。触れていない。「使わない場面」がないのは engineer.md だけではなく、data-analyst.md も同じ。 | バージョン要件を【要確認】に足す。data-analyst.md も対象に加える。 |

## 確かめたこと（何を・どうやって）
- **Jev の一次チェック**: `jev.py check T2_draft.md --kind draft` → 「一次チェック通過」。挙がった項目は0件。
- **合格基準（plan.md）**: 5案すべてに ①問題・②変更案（変更先のファイル）・③根拠（出典 URL）・④効果と手間がある。案の数は3〜5案の範囲内。結論も先に書かれている。
- **現状の問題を実物で確認**:
  - `scripts/ledger.py` 188行に `--status default="済"` がある。`cmd_log` は `st["tasks"][a.task] = a.status` でそのまま上書きする。SKILL.md 95行の受領の例に `--status` はない。「続きをやって」の行には「済でないタスクから再開」とある。提案1の指摘どおり。
  - `agents/reviewer.md` の tools は `Read, Write, Glob, Grep, Bash, WebSearch, WebFetch`。Jev（Bash）とコード実行（確かめること 5）に Bash を使っている。
  - `agents/paper-researcher.md` の tools に `Agent` がある。`pubmed-survey/SKILL.md` の手順3で、60本を超えると general-purpose を並列に起動している。
  - `.claude/agents/` の8ファイルを grep し、`maxTurns`・`disallowedTools`・`hooks` はどれもなかった。`.claude/settings.json` にも hooks はない。
  - templates.md の発注書の欄と SKILL.md 手順3の「必ず入れるもの」は、提案2の記述どおり。
- **根拠が T1 にあるか**: 提案1〜5の③は、いずれも T1 の対応する節（§1・§2・§3・§4・§5）に書かれていた。
- **出典を開いて確認**（WebFetch、2026-11-12）:
  - https://code.claude.com/docs/en/sub-agents
    - 子エージェントの生成: 「既定でサブエージェントは子を生成でき、メイン会話から3階層下まで」「`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`=1 でネストを無効化」「tools から `Agent` を外すか `disallowedTools` に入れると、その部署だけ生成を止められる」。T1・提案5の記述と一致。
    - maxTurns: 上限に達すると partial の印が付き、再開もできる。v2.1.246 以上が必要。
    - CLAUDE.md: カスタムのサブエージェントは既定で読み込む（→ 指摘1）。
    - hooks: フロントマターに書く例と exit 2 の記述を確認（→ 指摘3）。
  - https://code.claude.com/docs/en/best-practices
    - 「report gaps that affect correctness and skip style」「A reviewer that's asked to find problems will always find *something*」「`tools: Read, Grep, Glob` … enforced by Claude Code rather than requested in a prompt」を確認。提案3・4の根拠は実在する。ただし文脈はコードレビュー（→ 指摘5）。
- **確かめていないこと**:
  - anthropic.com/engineering 系の記事は開いていない。対象は multi-agent-research-system（提案2の「範囲・労力の目安」の根拠）と effective-harnesses（提案1の根拠）。
  - 子エージェントのトークンが `subagent_tokens` に含まれるか（提案5の【要確認】）も確かめていない。
  - 提案の変更は、実際にスキルへ反映して動かしてはいない（ファイル変更は禁止のため）。
