# 検索式を作らせるプロンプト（無料のAIチャット用）

ChatGPT・Gemini・Claude などの無料版にそのまま貼る。`【 】` の中だけ書き換える。
出てきた CSV を `pubmed_inputdata.csv` として保存し（メモ帳で可、文字コードは UTF-8）、ノートブックの `INPUT_FILE` をその名前にする。

---

```text
あなたは医学図書館員です。PubMed の検索式を作ってください。

# 調べたいこと
【例：子宮頸がんを、血液・尿などの体液中の miRNA（miR-126-3p, miR-451a, miR-144-3p, miR-20b-5p, miR-155-5p）で検出できるか】

# 作り方
1. 目的を「概念ブロック」に分ける（例：疾患 / 分子 / 検体 / 評価）。
2. 各ブロックは OR でつなぐ。中身は次のとおり。
   - MeSH 用語は [Mesh] を付ける。MeSH に本当に存在する用語だけを使う
     （例：子宮頸がんは "Uterine Cervical Neoplasms"[Mesh]。"Cervical Neoplasms" は存在しない）
   - 自由語には必ず [tiab] を付ける（タグなしは PubMed が勝手に広げるため禁止）
   - 同義語・略語・単数/複数・英米綴りを入れる。語尾の変化は diagnos*[tiab] のように * を使う
   - miRNA は腕の表記あり/なしの両方を入れる（例："miR-126-3p"[tiab] OR "miR-126"[tiab] OR "microRNA-126"[tiab] OR "miRNA-126"[tiab] OR "MIR126"[tiab]）
   - 同じブロックに同じ語を2回入れない。括弧と " の数を合わせる
3. ブロックを AND でつなぎ、広い順に段階的に作る。
   - 対象（例：miRNA）ごとに：①分子×疾患 ②＋検体 ③＋評価（診断性能など）
   - 全体用：疾患×分子×検体、それのレビュー・メタ解析版（review[pt] OR systematic review[pt] OR meta-analysis[pt]）
   - 年で絞る場合は AND 2021:2026[dp]
4. 1本の検索式は1行。改行を入れない。

# 出力形式
CSV だけを1つのコードブロックで出す。説明文は不要。
列：No,Target,Category,PubMed Query,Query Intent
- PubMed Query と Query Intent は必ず " で囲む。検索式の中の " は "" と2つ重ねる
- Query Intent は日本語で、何を調べる検索式か（広い/検体/診断 の段階も書く）
```

---

## うまくいかないとき

ノートブックを実行したあと、Excel の `Summary` シートを見る。

| 列 | 見るところ | 対処 |
|---|---|---|
| `PubMed Warning` | `QuotedPhraseNotFound` に出た語は PubMed が無視している | その語を直すようAIに頼む（MeSH名の誤りが多い） |
| `Query Check` | 括弧・" の数の不一致、重複した語 | AIに直させる |
| `Query Translation` | PubMed が実際にどう解釈したか | 意図と違えばAIに見せて直させる |
| `Hit Count` | 50件超が多い / 0件ばかり | 50件超：条件ブロックを AND で足す・年で分ける。0件：同義語を足す |

直すときは、`Summary` シートの No・Hit Count・PubMed Warning をAIに貼って「この結果を見て、50件超のものは絞った版、0件のものは広げた版を追加して」と頼むとよい。
