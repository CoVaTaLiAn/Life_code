# Gmail 自動振り分け：これまでの記録

2026年10月末〜11月に Claude Code と作った仕組みの経緯と、今の状態のメモ。

## 目的

- ただの通知・宣伝は既読にして片付ける。明らかなスパムは迷惑メールへ
- 読むべきものは未読のまま残す
- 判断を自動化しつつ、迷うものだけ自分で決める（トークンは迷ったものだけに使う）

## 仕組み（GAS）

コード：`gas/gmail-sorter/Code.gs`（使い方は同じフォルダの `README.md`）

1時間ごとに未読メールを振り分け、毎朝7時に要約メールを自分宛てに送る。
振り分けは **既読／残す／迷惑メール** の3つだけ（2026-11-10 に単純化）。判定は4段階。

1. **ルール**：送信元・キーワード・自分が過去に決めた送信元で判定（無料）
2. **確率**：ルールで決まらないものだけ「スパム確率」「既読でよい確率」を出す。Jev（キー登録時）か、ログから学ぶ簡易計算（無料）。95%以上なら自動処理
3. **Claude**：残りはシート「判断待ち」へ。Claude Code で「Gmailの判断待ちを見て」と頼むと、行の情報だけで提案を書く
4. **自分**：シートの「あなたの判断」列か Gmail の「既読」「残す」ラベルで決める。GAS が処理し、その送信元を覚える

判定結果はすべてスプレッドシート「Gmail振り分けログ」に記録される。

| ラベル | 処理 |
|---|---|
| 既読 | 既読（受信箱に残す） |
| 残す | 未読のまま |
| 要判断 | 未読のまま、シートと要約で聞く |
| （迷惑メール） | 既読にして迷惑メールへ |
| （ラベルなし） | Contract One など `trashSenders` の送信元は既読にしてゴミ箱へ |

## 決めたこと

- **振り分けは単純に**（2026-11-10）：転職メールの注目／その他、広告、要確認、要返信の区別はやめ、既読／残す／迷惑メールの3つにした

- **トークン（費用）を抑える**：Claude Code に毎回振り分けさせるのではなく、GAS でルール中心に動かす
- **Claude API の自動判定はやめた**（2026-11-10）：迷ったものは Claude Code で頼んだときだけ Claude が提案し、決めるのは自分
- **Jev（TypeSafe AI の判断特化モデル）で確率を出す**（2026-11-10）：呼び出し先 `api.typesafe.ai/v1/systemone`・`Authorization: Bearer`・返答 `answers.<質問名>.noul` を公式資料（docs.typesafe.ai）で確認。キーがなければ簡易計算で代わりに確率を出す
- **Gmail フィルタ**：Claude から作るツールが使えなかったため未作成。必要なら Gmail の設定画面で手動作成する（条件は `gas/gmail-sorter/README.md` のルールを参考）

## 状態（2026-11-01 時点）

- [x] Gmail を Claude に接続し、受信箱の未読を一度手動で振り分け
- [x] GAS のコード作成（ルール → AI → 自分の3段階、判断の記憶、ログ）
- [x] リポジトリに Claude 用の許可設定（`.claude/settings.json`：Gmail の閲覧・ラベル・下書き、Drive の読み取り）
- [x] GAS に最新コードを反映（以後は main 更新で自動反映）
- [x] GAS エディタで `setup` を実行（2026-11-01。ラベル作成・トリガー登録・初回の振り分けまで確認済み）
- [x] GitHub から GAS への自動反映（2026-11-01 設定完了。手順：`gas/SETUP_PC.md`）
- [x] ブランチ `claude/gas-gmail-sorter` を main にマージ（自動反映は設定が済むまでスキップされる）

- [ ] サブの Gmail にも同じ GAS を設置（2026-11-10 に対応コード追加。手順：`gas/gmail-sorter/README.md`「サブの Gmail でも使う」）
- [ ] Jev の API キーを登録して `testJev` で返答を確認（未）
- [ ] Claude 用の許可設定に Google スプレッドシートの読み書き（`mcp__Google_Sheets__get_values`・`update_values`）を追加（未。追加しないと毎回確認が出る）

## つまずいた点

- **iPhone の Claude Code から Obsidian が読めない**：iPhone のセッションはクラウドで動くため、Mac の iCloud に届かない。Mac で `claude remote-control` を使えば iPhone から Mac のセッションを操作できる
- **Remote Control で Mac のフォルダが使えない**：フォルダが `~/Library`（iCloud）の中にある、または Git リポジトリの最上位でないと、クラウドのセッションからは使えない。`~/Projects` などに clone し直して追加する
- **Google Drive の Obsidian コピーが 10/23 で更新停止**：Mac の同期スクリプト（`Blog/obsidian_icloud_gdrive`）が止まっている可能性あり。未調査
- **GAS の「This application was created by a Google Apps Script user」**：ウェブアプリとして開いたときに Google が出す注意書き。このスクリプトはウェブアプリ不要なので無視してよい
