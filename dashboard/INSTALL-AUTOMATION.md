# 每週一至週五 22:00 自動更新

這個流程會抓取 TAIFEX 官方 OpenAPI 與 TWSE 資料，更新 `sentiment-data.json`／`sentiment-history.json`，驗證 dashboard 後才 commit、push 到 `origin/main`。任何抓取、驗證或推送失敗都會停止，不會提交部分資料；錯誤會寫入 `.automation-logs`。

## 先完成一次性的安全設定

1. 立即撤銷任何曾貼出的 GitHub PAT，重新建立最小權限 token，並使用 Git Credential Manager 或 `gh auth login` 儲存，不要把 token 放進腳本、remote URL、排程參數或 log。
2. 確認 `tw-finance-site` 是 Git repository，且 `origin` 指向正確的 GitHub repo：

```powershell
git -C "C:\Users\wang sona\Desktop\claude cowork\tw-finance-site" remote -v
```

3. 手動測試一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\wang sona\Desktop\claude cowork\tw-finance-site\dashboard\refresh_sentiment.ps1"
```

## 建立 Windows 排程

以一般使用者 PowerShell 執行：

```powershell
$project = 'C:\Users\wang sona\Desktop\claude cowork\tw-finance-site'
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$project\dashboard\refresh_sentiment.ps1`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 22:00
Register-ScheduledTask -TaskName 'TW Finance Dashboard - Daily Sentiment' -Action $action -Trigger $trigger -Description 'Refresh TAIFEX institutional futures/options OI and weekly sentiment data' -Force
```

測試排程：

```powershell
Start-ScheduledTask -TaskName 'TW Finance Dashboard - Daily Sentiment'
Get-ScheduledTaskInfo -TaskName 'TW Finance Dashboard - Daily Sentiment'
```

注意：電腦必須在 22:00 開機且網路可用；若需要睡眠喚醒，可在工作排程器介面勾選「喚醒電腦以執行此工作」。
