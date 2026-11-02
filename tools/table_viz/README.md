# table_viz — 表データの統計可視化

CSV / TSV / Excel を渡すと、統計サマリーとグラフをまとめた `report.html` を作ります。

## 準備
```
pip install -r requirements.txt
```

## 使い方
```
python table_viz.py data.csv                         # 全体の傾向を見る
python table_viz.py data.xlsx --target 群 --exclude ID  # 群ごとの差を見る
```

| オプション | 内容 |
|---|---|
| `--target 列名` | 群分け列（例: 患者/対照）。群間検定と色分けを行う。連続値なら四分位で4群化 |
| `--exclude 列…` | ID など除外する列 |
| `--sheet 名前` | Excel のシート |
| `--out フォルダ` | 出力先（既定 `<ファイル名>_viz/`） |
| `--max-levels N` | 種類が N 以下の数値列はカテゴリ扱い（既定 10） |
| `--max-pair N` | ペアプロットの最大列数（既定 6） |

## 出力
- 記述統計（平均・中央値・歪度・外れ値数・正規性検定）
- 欠損率 / 分布（ヒスト+KDE）/ 箱ひげ図 / カテゴリ内訳
- 相関ヒートマップ（Pearson・Spearman）と相関の強いペアの散布図
- ペアプロット / PCA（寄与率・スコア・負荷量）
- `--target` 指定時: 群間検定（t検定/Mann-Whitney、ANOVA/Kruskal、カイ二乗）、効果量、BH補正 q値、関連の強さランキング
