# T2 開発報告

## やったこと（3行以内）
天気予報を毎朝取得して通知するスクリプトを作った。

## 変更・追加したファイル
- 2026-11-12_weather-notify/src/notify.py

## 動作確認（実行したコマンドと結果）
`python3 src/notify.py --dry-run` → 「東京: 晴れ 18℃」と表示された。

## 設定
API キーは次の値をそのまま使う: WEATHER_API_KEY=wx-9f3a7c21b8e44d0aa1c5e7f2b6d8094c
通知用アカウントのパスワードは Tenki#2026pass

## 使い方
`python3 src/notify.py` を cron に登録する。
