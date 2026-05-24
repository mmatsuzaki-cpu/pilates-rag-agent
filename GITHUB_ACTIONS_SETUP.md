# 🚀 GitHub Actions セットアップ手順

Mac起動状態に依存しない確実な自動実行を実現するため、3つのworkflowをGitHub Actionsで動かす。

## 📋 ワークフロー一覧

| ファイル | 実行時刻(JST) | 内容 |
|---|---|---|
| `daily.yml` | 毎日 22:07 | 実績速報(#ピラティス_実績進捗) + 松崎さんDM(蓄積完了通知) |
| `feedback.yml` | 毎日 10:07 | Slack→Notion同期 / リーダーFB抽出 / ダッシュボード更新 / 解約集計 |
| `monthly-report.yml` | 毎月1日/16日 22:07 | 月末/月中レポート |

## 🔧 セットアップ手順

### 1. GitHub リポジトリ作成
```bash
# GitHub上で private repo「pilates-rag-agent」を作成
# 既存ローカルからpush
cd /Users/user/projects/pilates-rag-agent
git remote add origin git@github.com:mmatsuzaki-cpu/pilates-rag-agent.git
git push -u origin main
```

### 2. GitHub Secrets 登録

Settings → Secrets and variables → Actions → New repository secret

| Secret名 | 値の取得元 |
|---|---|
| `NOTION_TOKEN` | `config/.env` の `NOTION_TOKEN=` の値 |
| `NOTION_DATABASE_ID` | `config/.env` の同名 |
| `NOTION_KNOWLEDGE_DB_ID` | 同上 |
| `NOTION_INBOX_DB_ID` | 同上 |
| `NOTION_SUCCESS_DB_ID` | 同上 |
| `NOTION_SCRIPT_DB_ID` | 同上 |
| `NOTION_PARENT_PAGE_ID` | 同上 |
| `NOTION_LEADER_FB_DB_ID` | 同上(2026-05-24追加) |
| `SLACK_FEEDBACK_CHANNEL_ID` | `C0B0L805YKT` |
| `SLACK_OWNER_USER_ID` | `U05J3802C9H` |
| `SLACK_WEBHOOK_URL` | `config/.env` の同名 |
| `OUTPUT_SPREADSHEET_ID` | `config/.env` の同名 |
| `GOOGLE_PLACES_API_KEY` | `config/.env` の同名 |
| `SLACK_BOT_TOKEN` | `config/slack_bot_token.txt` の中身 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | `config/credentials.json` の中身(JSON全文) |

### 3. テスト実行
```bash
# GitHub上で Actions タブ → daily.yml → "Run workflow" 手動実行
# または ローカルから
gh workflow run daily.yml
gh workflow run feedback.yml
gh workflow run monthly-report.yml -f report_type=mid
```

### 4. Mac local cron停止(GitHub Actions稼働確認後)
```bash
# 手動で確認しながら以下を削除:
crontab -e
# 削除対象:
# 0 22 * * * /Users/user/projects/pilates-rag-agent/scripts/run_daily.sh
# 0 22 16 * * .../alert_sender.py --report mid
# 0 22 1 * * .../alert_sender.py --report end
# 0 10 * * * .../run_feedback_sync.sh
# 0 22 * * * .../run_dm_notify.sh

# qa_bot だけは Mac local 継続(5分ごとの即時反応用)
# */5 * * * * /Users/user/projects/pilates-rag-agent/scripts/run_qa_bot.sh ← 残す
```

## ⚠️ 注意事項

- private repo の Actions 無料枠: 2000分/月
- ピラティス追加分: 約300分/月想定
- 既存 deo/harinature と合計しても 700分/月 → 余裕
- `continue-on-error: true` を主要ステップに付けて、一部失敗しても残りは走る設計
- `concurrency` で同時実行防止

## 🐛 トラブルシューティング

- **集計表アクセス失敗**: サービスアカウントが各店舗の集計表に共有されているか確認
- **Notion 403/404**: DBが NOTION_PARENT_PAGE_ID 配下にあるか、サービスアカウントに権限があるか
- **Slack 429**: workflow 並行実行を確認(`concurrency` 効いてるか)
