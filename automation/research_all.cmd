@echo off
rem 業種調査を、質問の下書きから集計まで最後まで回す（サブスクと無料枠だけ。手元で切り離して動かす）
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
python scripts\research_extra.py --draft > automation\research_all.log 2>&1
python scripts\research_run.py --minutes 1400 >> automation\research_all.log 2>&1
echo RESEARCH_ALL_DONE >> automation\research_all.log
