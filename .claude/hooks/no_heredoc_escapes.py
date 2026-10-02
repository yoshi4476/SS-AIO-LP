# -*- coding: utf-8 -*-
"""Bash の heredoc で Python を渡し、その中に \\n \\t \\d \\s \\b \\1 などを書いたコマンドを止める。

この環境では heredoc 経由のバックスラッシュが制御文字や実際の改行に化け、
ファイルが壊れる（2026-09〜10 に10回以上。2026-10-02 だけで3回）。
「気をつける」では止まらなかったので、実行前に機械で止める。
コードは Write / Edit で書き、`python <ファイル>` で実行する。
"""
import json
import re
import sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")
except Exception:
    sys.exit(0)

if re.search(r"<<-?\s*['\"]?\w+", cmd) and re.search(r"\bpython[0-9.]*\b", cmd) \
        and re.search(r"\\[ntrdsbwDSWB0-9]", cmd):
    print("heredoc で渡す Python に \\n・\\t・\\d などのバックスラッシュがあります。"
          "この環境では化けてファイルが壊れます。Write でファイルに書いてから python で実行してください。",
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
