# AIO article pipeline runner (registered in Windows Task Scheduler)
# ASCII-only on purpose: PS 5.1 misreads UTF-8 (no BOM) scripts. Japanese prompt lives in pipeline_prompt.txt.
$ErrorActionPreference = "Continue"
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj

$logDir = Join-Path $proj "automation\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$log = Join-Path $logDir "pipeline_$stamp.log"

$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $proj "automation\pipeline_prompt.txt")

# リモート設定済みなら実行前に最新化（GitHub Actions併用時の二重管理防止）
$hasRemote = $null -ne (git remote)
if ($hasRemote) { git pull --rebase --autostash 2>&1 | Out-Null }

# 30日より古いログを自動削除
Get-ChildItem $logDir -Filter *.log | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

"[$(Get-Date -Format s)] pipeline start" | Out-File $log -Encoding utf8
& "C:\Users\user\AppData\Roaming\npm\claude.ps1" -p $prompt --dangerously-skip-permissions --max-turns 400 2>&1 |
    Out-File $log -Append -Encoding utf8
"[$(Get-Date -Format s)] pipeline end (exit=$LASTEXITCODE)" | Out-File $log -Append -Encoding utf8

# Immediate retry (max 2): if the run left BLOCKED articles (score < 90) or build crashed, fix now
$retryPrompt = Get-Content -Raw -Encoding UTF8 (Join-Path $proj "automation\retry_prompt.txt")
for ($i = 1; $i -le 2; $i++) {
    $buildOut = & python "scripts\build.py" 2>&1 | Out-String
    $buildExit = $LASTEXITCODE
    if ($buildExit -eq 0 -and $buildOut -notmatch "BLOCKED") { break }
    "[$(Get-Date -Format s)] BLOCKED/build failure (exit=$buildExit) -> retry $i/2" | Out-File $log -Append -Encoding utf8
    & "C:\Users\user\AppData\Roaming\npm\claude.ps1" -p $retryPrompt --dangerously-skip-permissions --max-turns 400 2>&1 |
        Out-File $log -Append -Encoding utf8
    "[$(Get-Date -Format s)] retry $i end (exit=$LASTEXITCODE)" | Out-File $log -Append -Encoding utf8
}

# ローカルKPI集計（公開前でも学習ループを回す。GA4/GSC稼働後はDaily KPIが上書き）
& python "scripts\local_kpi.py" 2>&1 | Out-File $log -Append -Encoding utf8

# 1行サマリを summary.log に追記（後から一覧で健康状態を確認できる）
$finalBuild = & python "scripts\build.py" 2>&1 | Out-String
$finalExit = $LASTEXITCODE
$todayStr = Get-Date -Format "yyyy-MM-dd"
$newToday = Select-String -Path "articles\*.md" -Pattern ("^date: " + $todayStr) -List
$status = if ($finalExit -ne 0) { "NG(build失敗 exit=$finalExit)" }
          elseif ($finalBuild -match "BLOCKED") { "NG(BLOCKED残り)" }
          elseif ($newToday) { "OK(本日分あり)" }
          else { "WARN(本日分なし)" }
"$(Get-Date -Format 'yyyy-MM-dd HH:mm') | $status | log=$([System.IO.Path]::GetFileName($log))" |
    Out-File (Join-Path $logDir "summary.log") -Append -Encoding utf8
