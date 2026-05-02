# ピラティス実績エージェント

## 設定情報(再構築時の参照)

### Notion DB IDs
- 振り返りDB(生データ): `34faf68b-7a63-8132-8db0-c185cdba580d`
- ノウハウ集: `34faf68b-7a63-812b-b6f4-d06b27f70338`
- 受信箱: `351af68b-7a63-8197-9a48-e884c12404e1`
- 成功事例集: `351af68b-7a63-81a8-8897-f1cb1421f540`
- トークスクリプト集: `351af68b-7a63-81f4-912f-c016214ba83d`

### Spreadsheets
- メイン: `1W3OUR8sxb_MhBgPJoHnsY9thfDQOdUdzEYErUVutrw4` (店舗事業_課題発見RAG)
- ダッシュボード: `1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA` (ピラティス実績全部)

### Slack
- Webhook: 環境変数 SLACK_WEBHOOK_URL
- 振り返りChannel: `C0B0L805YKT`
- 松崎User ID: `U05J3802C9H`
- Bot ID: `U0B11U5HQMN`

### 復旧方法
1. `config/.env` を別途復元(GPGなどで暗号化保管推奨)
2. `config/credentials.json` を別途復元(サービスアカウントキー)
3. `config/slack_bot_token.txt`, `slack_webhook.txt` 復元
4. `pip3 install gspread google-auth python-dotenv requests`
5. `crontab -l` で cron 設定確認
6. `bash scripts/run_daily.sh` 等で動作テスト

## ファイル構成
- `src/`: Python スクリプト
- `scripts/`: cron用シェルスクリプト
- `config/`: 設定ファイル(認証情報含む・gitignore対象)
- `data/`: state files
- `output/logs/`: 実行ログ
