# 組織図

```text
オーナー（ユーザー）… 決裁：送信・登録・公開・お金
  └ 社長（メインの Claude / company スキル）… 受付・計画・発注・検収・統合
      ├ 調査部
      │   ├ web-researcher     … Web 調査・市場/製品/制度の比較
      │   ├ paper-researcher   … 論文調査（PubMed）
      │   └ patent-search      … 特許・先行技術調査
      ├ 分析部
      │   └ data-analyst       … CSV・表データの分析と予測モデル
      ├ 開発部
      │   └ engineer           … スクリプト・自動化・GAS・ツール作成
      ├ 編集部
      │   └ writer             … ブログ・資料・メール文面・要約
      ├ 秘書室
      │   └ secretary          … Gmail・カレンダー・Drive の確認と下書き
      ├ 品質管理部
      │   └ reviewer           … 検収・ファクトチェック・コードレビュー
      └ 判定係（Jev。エージェントではなく scripts/jev.py）
          … 振り分け・モデル選び・成果物の一次チェック・候補の絞り込み
```

## 部署一覧（subagent_type として使う名前）

モデルは発注のたびに `jev.py tier` で決める。下の「既定」は指定しなかった時の値、「下限」は節約モードでもこれより軽くしない値。

| 部署 | エージェント | 頼むこと | 頼まないこと | 主な出力 |
|---|---|---|---|---|
| 調査部 | `web-researcher` | Web での情報収集、比較表、相場・制度・手順の確認 | 論文・特許（専門部署へ） | `<ID>_research.md`（出典URL付き） |
| 調査部 | `paper-researcher` | 先行研究・文献レビュー（論文が多いと内部で子エージェントを並列に動かすので、トークンを多く使う） | 一般 Web 情報 | `research/<日付>_<テーマ>/report.md` |
| 調査部 | `patent-search` | 先行技術・侵害予防・出願動向 | 法的判断 | `<ID>_patent.md` |
| 分析部 | `data-analyst` | CSV の EDA・特徴量・ベースラインモデル | データ収集 | `analysis/<日付>_<課題>/report.md` |
| 開発部 | `engineer` | コードを書く・直す・動かして確かめる | push・本番反映 | リポジトリ内のプロジェクト＋`<ID>_dev.md` |
| 編集部 | `writer` | 文章の執筆・推敲・要約・構成 | 事実の新規調査 | `<ID>_draft.md` |
| 秘書室 | `secretary` | メール・予定・Drive の確認、返信や予定の下書き | 送信・予定登録・共有 | `<ID>_secretary.md`＋Gmail 下書き |
| 品質管理部 | `reviewer` | 成果物の検収（根拠・抜け・誤り・リスク） | 成果物の書き直し | `review_<ID>.md` |

| エージェント | 既定のモデル | 下限 |
|---|---|---|
| `secretary` | haiku | haiku |
| `web-researcher` / `writer` | sonnet | haiku |
| `engineer` | sonnet | sonnet |
| `data-analyst` / `paper-researcher` / `patent-search` | 社長と同じ | sonnet |
| `reviewer` | 社長と同じ | sonnet |

## よくある編成

| 依頼の例 | 編成（→ は依存、/ は並列） |
|---|---|
| 「〇〇を始めたい。調べて計画を立てて」 | web-researcher / paper-researcher → writer（計画書）→ reviewer |
| 「このデータで〇〇を予測して、ブログ記事にして」 | data-analyst → writer → reviewer |
| 「〇〇を自動化するツールを作って」 | web-researcher（既存手段の調査）→ engineer → reviewer |
| 「このアイデア、もう特許や論文ある？」 | patent-search / paper-researcher → writer（まとめ）→ reviewer |
| 「今週のメールと予定を整理して、返信案を作って」 | secretary → writer（返信文の推敲）→ 社長が検収 |
