# T2 開発報告

## やったこと（3行以内）
天気予報を毎朝取得して通知するスクリプトを作った。API キーは環境変数から読む。

## 変更・追加したファイル
- 2026-11-12_weather-notify/src/notify.py
- 2026-11-12_weather-notify/examples/config.example.json（値はダミー）

## 動作確認（実行したコマンドと結果）
- `python3 src/notify.py --dry-run` → 「東京: 晴れ 18℃」と表示。終了コード 0
- `python3 -m pytest tests/` → 4 passed

## 未確認・制限
- 実際の通知送信は、鍵がないため確かめていない。

## 使い方
1. 環境変数 `WEATHER_API_KEY` に鍵を入れる
2. `python3 src/notify.py` を cron に登録する
