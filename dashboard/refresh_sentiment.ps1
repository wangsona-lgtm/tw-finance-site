$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$DashboardDir = $PSScriptRoot
$RepoDir = Split-Path -Parent $DashboardDir
$JsonPath = Join-Path $DashboardDir 'sentiment-data.json'
$HistoryPath = Join-Path $DashboardDir 'sentiment-history.json'
$LogDir = Join-Path $RepoDir '.automation-logs'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $LogDir "refresh-$stamp.log"

function Invoke-Logged([string]$FilePath, [string[]]$Arguments) {
  & $FilePath @Arguments *>&1 | Tee-Object -FilePath $log -Append
  if ($LASTEXITCODE -ne 0) { throw "$FilePath failed with exit code $LASTEXITCODE" }
}

$python = $null
foreach ($candidate in @(
  (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
  'C:\Users\wang sona\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
)) {
  if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
}
if (-not $python) {
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) { $python = $pyCmd.Source }
}
if (-not $python) {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) { $python = $pythonCmd.Source }
}
if (-not $python) { throw 'Python 3 was not found. Install Python or update the $python candidates in this script.' }

Push-Location $RepoDir
try {
  Add-Content -Path $log -Value "[$(Get-Date -Format o)] Starting TAIFEX sentiment refresh"
  Invoke-Logged $python @((Join-Path $DashboardDir 'fetch_sentiment_data.py'))

  $data = Get-Content -Raw -LiteralPath $JsonPath | ConvertFrom-Json
  if ($null -eq $data.institutional_oi.items -or @($data.institutional_oi.items).Count -ne 3) {
    throw 'sentiment-data.json does not contain exactly three institutional OI rows'
  }
  if ($data.error -ne $null) { throw "sentiment-data.json reports an error: $($data.error)" }
  if (-not $data.pc_ratio.pc_vol_ratio -or -not $data.pc_ratio.pc_oi_ratio) { throw 'P/C ratios are missing' }
  if (-not $data.futures.foreign_tx_net) { throw 'Foreign futures net OI is missing' }
  Get-Content -Raw -LiteralPath $HistoryPath | ConvertFrom-Json | Out-Null

  $html = Get-Content -Raw -LiteralPath (Join-Path $DashboardDir 'index.html')
  foreach ($required in @('sentiment-data.json','sentiment-history.json','本週每日籌碼比較','institutionalOiSummary')) {
    if ($html -notlike "*$required*") { throw "Dashboard validation failed: missing $required" }
  }

  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($null -eq $git) { throw 'git is not installed or not on PATH' }
  $inside = (& git -C $RepoDir rev-parse --is-inside-work-tree 2>$null)
  if ($inside -ne 'true') { throw 'No Git repository found. Initialize/clone tw-finance-site before enabling push.' }
  $remote = (& git -C $RepoDir remote get-url origin 2>$null)
  if (-not $remote) { throw 'Git remote origin is not configured' }

  & git -C $RepoDir add -- dashboard/sentiment-data.json dashboard/sentiment-history.json
  if ($LASTEXITCODE -ne 0) { throw 'git add failed' }
  $changes = (& git -C $RepoDir diff --cached --name-only)
  if ($changes) {
    & git -C $RepoDir commit -m "chore: refresh sentiment data $(Get-Date -Format yyyy-MM-dd)" *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { throw 'git commit failed' }
  }
  & git -C $RepoDir push origin main *>&1 | Tee-Object -FilePath $log -Append
  if ($LASTEXITCODE -ne 0) { throw 'git push failed' }
  Add-Content -Path $log -Value "[$(Get-Date -Format o)] SUCCESS"
}
catch {
  Add-Content -Path $log -Value "[$(Get-Date -Format o)] ERROR: $($_.Exception.Message)"
  throw
}
finally { Pop-Location }
