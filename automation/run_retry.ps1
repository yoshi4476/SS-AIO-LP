# Same-day retry runner: publishes articles that failed earlier today.
# Invoked by Task Scheduler (AIO-Pipeline-Retry, daily 21:30) and skips itself when nothing to do.
$ErrorActionPreference = "Continue"
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj

$logDir = Join-Path $proj "automation\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$log = Join-Path $logDir "retry_$stamp.log"

"[$(Get-Date -Format s)] retry check start" | Out-File $log -Encoding utf8

# Fast pre-check without spending tokens: blocked articles OR no article dated today
$buildOut = & python "scripts\build.py" 2>&1 | Out-String
$buildOut | Out-File $log -Append -Encoding utf8
$today = Get-Date -Format "yyyy-MM-dd"
$todayArticle = Select-String -Path "articles\*.md" -Pattern ("date: " + $today) -Quiet

if (($buildOut -notmatch "BLOCKED") -and $todayArticle) {
    "[$(Get-Date -Format s)] nothing to retry (no BLOCKED, today's article exists)" | Out-File $log -Append -Encoding utf8
    exit 0
}

$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $proj "automation\retry_prompt.txt")
"[$(Get-Date -Format s)] retry run start" | Out-File $log -Append -Encoding utf8
& "C:\Users\user\AppData\Roaming\npm\claude.ps1" -p $prompt --dangerously-skip-permissions --max-turns 400 *>> $log
"[$(Get-Date -Format s)] retry run end (exit=$LASTEXITCODE)" | Out-File $log -Append -Encoding utf8
