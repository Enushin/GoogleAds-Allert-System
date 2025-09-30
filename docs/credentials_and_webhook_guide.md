---
title: "Google Ads API認証・通知Webhook設定ガイド"
status: "Draft"
version: "0.1.0"
language: "ja"
---

# 概要
Google Ads APIの費用データを安全に取得し、Slackなどの通知チャンネルへ確実に連携するために必要な認証情報の整理と秘匿化方針をまとめる。MVP段階で最低限準備すべき資格情報、取得手順、保管方法、運用時のチェックポイントを網羅する。

## Google Ads APIの主要認証要素
- **開発者トークン**: Google Ads APIにアクセスするための必須トークン。Google Ads管理者センター（MCC）に紐づく。
- **OAuth2 クライアントID/クライアントシークレット**: ユーザー同意を得て広告アカウントにアクセスするための資格情報。Google Cloud Consoleで発行。
- **リフレッシュトークン**: 長期的にアクセストークンを再取得するために使用。OAuth2同意画面経由で発行。
- **ログインカスタマID**: MCCアカウントのID。子アカウントのデータ取得時に必要。

## 取得手順の詳細
1. **Google Cloudプロジェクトの準備**
   - Google Cloud Consoleで新規プロジェクトを作成。
   - 「APIとサービス > 有効なAPIとサービス」でGoogle Ads APIを有効化する。
2. **OAuth同意画面の設定**
   - 「APIとサービス > OAuth同意画面」でユーザータイプを「外部」に設定。
   - プロダクト名、サポート連絡先を入力し、スコープに `https://www.googleapis.com/auth/adwords` を追加。
3. **OAuthクライアントIDの発行**
   - 「認証情報 > 認証情報を作成 > OAuthクライアントID」で「デスクトップアプリ」または「ウェブアプリ」を選択。
   - 発行されたクライアントID・クライアントシークレットを安全に保管する。
4. **開発者トークンの申請**
   - Google Ads管理者センターにログインし、「ツールと設定 > 設定 > APIセンター」にアクセス。
   - テストモードの開発者トークンを申請し、承認完了後に本番申請を実施。
5. **リフレッシュトークンの取得**
   - Googleが提供するOAuth2サンプルまたは `google-ads` Pythonライブラリの `generate_refresh_token.py` を利用。
   - ブラウザ認可後に表示される認証コードをコマンドラインへ入力し、リフレッシュトークンを取得。
6. **ログインカスタマIDの確認**
   - MCCのメニューから「設定 > アカウントのアクセス許可」を開き、該当のカスタマーIDを控える。

## 通知Webhook（Slack）の準備
1. **Slack Appの作成**
   - https://api.slack.com/apps で新規アプリを作成し、ワークスペースにインストール。
2. **Incoming Webhookの有効化**
   - アプリ設定の「Incoming Webhooks」をオンにし、通知先チャンネルを選択してWebhook URLを生成。
3. **Webhook URLの保護**
   - URLは秘匿情報として扱い、バージョン管理システムに絶対に含めない。
4. **複数チャンネル対応**
   - 本番・検証環境で異なるWebhookを発行し、環境変数で切り替える運用にする。

## 秘匿化と設定管理ポリシー
- **.envファイル**: ローカル開発では `.env` に資格情報を保存し、`.gitignore` で除外する。
- **環境変数**: 本番環境では `GOOGLE_ADS_DEVELOPER_TOKEN`、`GOOGLE_ADS_CLIENT_ID` など明確なキー名を付与。
- **Secret Manager**: GCPを利用する場合はSecret Managerで集中管理し、Cloud Run/Cloud Functionsにマウントする。
- **監査ログ**: 認証情報のアクセスログを有効化し、異常操作を早期検知する。

## サンプル環境変数レイアウト
```env
GOOGLE_ADS_DEVELOPER_TOKEN="xxxx"
GOOGLE_ADS_CLIENT_ID="xxxx.apps.googleusercontent.com"
GOOGLE_ADS_CLIENT_SECRET="xxxx"
GOOGLE_ADS_REFRESH_TOKEN="xxxx"
GOOGLE_ADS_LOGIN_CUSTOMER_ID="123-456-7890"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
SLACK_FALLBACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

## 運用前チェックリスト
- [ ] すべての認証情報が最新で、期限切れではないことを確認した。
- [ ] テスト用アカウントでAPI呼び出しが成功することを確認した。
- [ ] 通知チャンネルへの送信テストを行い、想定フォーマットで受信できることを確認した。
- [ ] 本番・検証で別々の資格情報を用意し、切り替え手順をドキュメント化した。
- [ ] インシデント対応時の連絡先とローテーション手順をチームに共有した。

