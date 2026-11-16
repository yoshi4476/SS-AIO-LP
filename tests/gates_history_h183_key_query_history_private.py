# -*- coding: utf-8 -*-
"""主要クエリの順位の履歴（data/key_query_history.jsonl）は、お客様の社の行を非公開の置き場へ分けて書く
（2026-11-16 の週次が、お客様の社の id と狙う語・順位の100行を public に書き、守秘義務の門が落ちた）。
台帳（key_queries.json）は分けていたが、履歴だけは HIST へ直接追記していた"""
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def test_history_rows_of_clients_go_private():
    import client_private as CP
    print("\n■ 主要クエリの履歴: お客様の行は非公開の置き場へ")
    rel = "data/key_query_history.jsonl"
    check("分け書きの記録で、非公開のリポジトリに残す記録", (rel in CP.SPLIT_JSONL, rel in CP.REPO_BACKED), (True, True))
    src = (ROOT / "scripts" / "key_queries.py").read_text(encoding="utf-8")
    check("履歴を HIST へ直接書かない・読まない（client_private の read_lines・save_jsonl を通す）",
          ("HIST.open(" in src, "HIST.write_text(" in src, "HIST.read_text(" in src,
           "CP.save_jsonl(HIST" in src, src.count("CP.read_lines(HIST)") >= 2), (False, False, False, True, True))
