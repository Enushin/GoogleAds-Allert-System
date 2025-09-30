---
title: "テスト戦略と検証手順"
status: "Draft"
version: "0.1.0"
language: "ja"
---

# 概要
プロジェクト全体の品質を継続的に維持するため、単体テスト・結合テスト・E2E想定テストに向けた方針と、ローカル環境でのスケジューラ検証手順、Google Ads APIサンドボックス連携時の準備内容を整理する。

## 1. テストレイヤー別方針
### 1.1 単体テスト
- **目的**: 個別モジュールのロジック（予測、通知整形、Google Adsクエリ生成、設定読み込み等）が仕様通り動作することを確認する。
- **対象**: `google_ads_alert.forecast`, `google_ads_alert.notification`, `google_ads_alert.schedule`, `google_ads_alert.config`, `google_ads_alert.google_ads_client`。
- **手法**:
  - `pytest` を利用し、各関数・クラスの期待値を明示する。
  - タイムゾーンに依存する処理は `ZoneInfo` を活用した固定値テストで覆う。
  - 金額計算は丸め誤差検証のため `pytest.approx` を使用し、想定許容範囲をコメントで共有する。

### 1.2 モック／スタブ活用方針
- Google Ads との通信は `GoogleAdsSearchTransport` プロトコルをモック実装で置き換え、API呼び出しを伴わないテストを実現する。
- Slack通知は HTTP 実装を追加するまでは、`build_slack_notification_payload` の戻り値を直接アサートする。
- リトライ処理など時間待機が絡むテストでは `sleep` コールバックを差し替え、待機をゼロ化する。

### 1.3 結合テスト（想定）
- 実際の Google Ads API を利用せず、固定レスポンスを返すフェイクトランスポートで `GoogleAdsCostService` → `build_combined_forecast` → `build_slack_notification_payload` の呼び出し連携を検証する。
- 設定読み込み (`load_config_from_env_file`) と予測・通知までのデータフローを通し、欠損値時の例外・警告ログを確認する。

### 1.4 E2E 想定テスト
- 本番接続前に、開発用サンドボックス（後述）と実Webhook URLを利用し、1日の中で少なくとも1回、終端まで通知できるかを確認する。
- スケジューラを経由しない手動実行スクリプト（例: `python -m google_ads_alert.scripts.manual_run` を今後追加予定）で、CLI経由のエラー処理を確認する。

## 2. ローカルスケジューラ検証手順
1. `tests/` の単体テストが全て通ることを確認する: `pytest`。
2. 下記スニペットを `scripts/preview_schedule.py` として作成し、希望する設定で日次スケジュールを確認する。

   ```python
   from datetime import date
   from zoneinfo import ZoneInfo

   from google_ads_alert.schedule import DailyScheduleConfig, generate_daily_schedule

   if __name__ == "__main__":
       config = DailyScheduleConfig(
           timezone=ZoneInfo("Asia/Tokyo"),
           start_hour=8,
           end_hour=20,
           run_count=4,
       )
       for run_time in generate_daily_schedule(date.today(), config):
           print(run_time.isoformat())
   ```

3. 将来的に APScheduler を導入する際は、`BlockingScheduler` に上記 `generate_daily_schedule` の結果を登録し、ローカルでは `python scripts/preview_schedule.py` を `watch` コマンド等で監視して動作確認する。
4. 本番環境との差異を避けるため、タイムゾーンは常に `config.schedule.timezone` を参照し、UTC環境でも日本時間通りに発火することをログで確認する。

## 3. Google Ads API サンドボックス／Mock Transport
- **サンドボックス利用前提**: Google Ads API のテストアカウントと開発者トークンを取得し、`login_customer_id` をサンドボックス専用のものに切り替える。
- **資格情報の切替**: `.env.sandbox` 等の別ファイルに資格情報を保持し、`load_env_file` で読み分ける。
- **Mock Transport 実装**:
  - `GoogleAdsSearchTransport` を実装した `FakeTransport` を `tests/fixtures.py` に追加し、固定レスポンスを返す。
  - レスポンス例: `{"metrics": {"cost_micros": "1230000"}}`。
  - 異常系テストでは例外を送出し、`RetryConfig` の指数バックオフ挙動を検証する。
- **サンドボックスE2E**: フェイクではカバーできないエラー（アクセス権限・スロットリング等）を把握するため、週1回程度サンドボックスに対する実行ジョブを走らせ、ログを保全する。

## 4. 成果物とドキュメント整備
- 本ドキュメントを `docs/next_steps.md` から参照し、チェックリストの完了可否を管理する。
- スケジューラ・サンドボックスの検証ログは `docs/runbooks/` 以下に将来的に蓄積する想定。

