# -*- coding: utf-8 -*-
"""ChatGPT（Codex のサブスク）が利用上限で答えなかった業種だけを聞き直す。
Claude・Gemini の答えは30日キャッシュされるので、聞き直しは ChatGPT の分だけになる。
    python automation/research_refill_chatgpt.py [--after HH:MM]
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "automation" / "research_refill.log"
if "--after" in sys.argv:
    hh, mm = map(int, sys.argv[sys.argv.index("--after") + 1].split(":"))
    while datetime.now() < datetime.now().replace(hour=hh, minute=mm, second=0):
        time.sleep(300)
todo = []
for f in sorted((ROOT / "data" / "research").glob("*-summary.json")):
    a = json.loads(f.read_text(encoding="utf-8")).get("answered") or {}
    if a.get("ChatGPT", 0) < 25:          # 50問中の半分未満しか答えが無い業種
        todo.append(f.name[:-len("-summary.json")])
with LOG.open("a", encoding="utf-8") as out:
    out.write(f"{datetime.now():%m-%d %H:%M} 聞き直す業種: {todo}\n")
    for ind in todo:
        out.write(f"■ {ind}\n")
        out.flush()
        subprocess.run([sys.executable, "scripts/industry_ai_sources.py", "--industry", ind, "--sub"], cwd=ROOT,
                       stdout=out, stderr=subprocess.STDOUT, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out.write("REFILL_DONE\n")
