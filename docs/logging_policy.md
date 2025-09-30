---
title: "ログ出力ポリシー"
status: "Draft"
version: "0.1.0"
language: "ja"
---

# ログ出力ポリシー

本ドキュメントでは、Google Ads予算アラートシステムにおけるロギングの統一ポリシーと、運用時に記録すべき主要イベントを定義する。

## ログレベルと使い分け

- **INFO**: 正常系の進行状況を記録する。例: 設定ロード完了、予測スナップショット生成、通知送信完了、スケジューラ設定完了。
- **WARNING**: リカバリ可能な例外やユーザーキャンセルなど、注意喚起すべき事象を記録する。例: Ctrl+C によるスケジューラ停止。
- **ERROR**: 処理が失敗した場合に記録する。例: 設定読み込みエラー、Slack送信失敗、スケジュールプレビュー失敗。
- **CRITICAL**: 重大障害発生時に使用する。現在は自動では利用していないが、複数サービスへの影響がある場合に発砲する。
- **DEBUG**: 詳細なデバッグ情報。デフォルトでは出力しないが、`GOOGLE_ADS_LOG_LEVEL=DEBUG` を設定することで有効化できる。

## フォーマットとタイムゾーン

- 既定のフォーマット: `%(asctime)s %(levelname)-8s %(name)s %(message)s`
- 日付フォーマット: `YYYY-MM-DD HH:MM:SS JST`
- タイムゾーン: `Asia/Tokyo`（`ZoneInfo` データベースが提供する名称）
- いずれも `LoggingConfig` を通じて変更可能。CLI 実行時は環境変数で上書きできる。

## 出力先

- デフォルトでは標準エラー (`stderr`) に出力する。
- `LoggingConfig` に `stream` を指定することで任意の出力先へ切り替え可能。
- 外部ローテーションツールと連携する際は `logging.StreamHandler` を差し替えるカスタムロガーを構築する。

## CLI コマンドでの適用

- `python -m google_ads_alert` で起動する CLI は、初期化時に `LoggingConfig` を基にロガーを自動構成する。
- 利用可能な環境変数:
  - `GOOGLE_ADS_LOG_LEVEL`: `INFO`（既定）、`DEBUG`、`WARNING` など。
  - `GOOGLE_ADS_LOG_TIMEZONE`: 例 `Asia/Tokyo`。無効値は黙って既定値へフォールバックする。
  - `GOOGLE_ADS_LOG_FORMAT`: 独自のログフォーマット文字列。
  - `GOOGLE_ADS_LOG_DATEFMT`: `datetime.strftime` 形式の日時フォーマット。
- CLI は主要イベントを INFO ログとして出力し、エラー時にはスタックトレースを含む `logger.exception` を利用する。

## 主要イベントのロギング

| コンテキスト | ログレベル | 内容 |
| --- | --- | --- |
| 設定ロード | INFO | `.env` または環境変数からの読み込み成功を記録 |
| Doctor コマンド | INFO | 検証開始・完了、および失敗内容を記録 |
| Schedule プレビュー | INFO | プレビュー生成開始・完了、入力エラー時は ERROR |
| 単発実行 (`run`) | INFO | 予測スナップショットの作成、通知結果、ドライラン判定 |
| Slack送信失敗 | ERROR | `logger.exception` によりスタックトレース付きで記録 |
| スケジューラ (`serve`) | INFO | ジョブ登録状況、開始、停止、異常終了を記録 |
| ユーザー割り込み | WARNING | Ctrl+C による停止を検知して記録 |

## ログ出力の確認方法

1. CLI コマンドを実行する際、標準エラーにログが出力されることを確認する。
2. `GOOGLE_ADS_LOG_LEVEL=DEBUG` を設定した上で `python -m google_ads_alert run --dry-run` を実行し、詳細ログが出ることを確認する。
3. 本番運用時は外部監視基盤（例: Cloud Logging、Datadog）へ `stderr` を取り込む設定を行う。

## 実装メモ

- `google_ads_alert.logging_utils.configure_logging` がロガーの単一初期化を担う。
- CLI 以外のモジュールからログ出力する場合も、`get_logger("component")` を利用して `google_ads_alert` の子ロガーを取得する。
- ログメッセージには機密情報（認証情報、顧客名など）を含めないこと。
