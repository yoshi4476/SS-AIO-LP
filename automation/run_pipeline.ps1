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

"[$(Get-Date -Format s)] pipeline start" | Out-File $log -Encoding utf8
& "C:\Users\user\AppData\Roaming\npm\claude.ps1" -p $prompt --dangerously-skip-permissions --max-turns 400 *>> $log
"[$(Get-Date -Format s)] pipeline end (exit=$LASTEXITCODE)" | Out-File $log -Append -Encoding utf8

# Immediate retry (max 2): if the run left BLOCKED articles (score < 90), fix and publish them now
$retryPrompt = Get-Content -Raw -Encoding UTF8 (Join-Path $proj "automation\retry_prompt.txt")
for ($i = 1; $i -le 2; $i++) {
    $buildOut = & python "scripts\build.py" 2>&1 | Out-String
    if ($buildOut -notmatch "BLOCKED") { break }
    "[$(Get-Date -Format s)] BLOCKED articles found -> retry $i/2" | Out-File $log -Append -Encoding utf8
    & "C:\Users\user\AppData\Roaming\npm\claude.ps1" -p $retryPrompt --dangerously-skip-permissions --max-turns 400 *>> $log
    "[$(Get-Date -Format s)] retry $i end (exit=$LASTEXITCODE)" | Out-File $log -Append -Encoding utf8
}
