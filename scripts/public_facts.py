# -*- coding: utf-8 -*-
"""主題に固有の公的資料（法令・公的機関）の数字の台帳 data/public_facts.json を読む。

一次性が届かない記事の多くは「その業種に固有の一次情報が無い」で止まっていた（2026-11-09 クリニックの記帳代行が
一次性73点でしまわれた）。自社の数字が無い業種でも、法令・公的機関の数字は確かめて書ける。
ここに置くのは一次情報（条文・公的機関のページ）で確かめた文だけ。AI に足させない（作った数字が入る）。

  python scripts/public_facts.py "クリニック 記帳代行"   # その題に当たる文
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "public_facts.json"

# 題が特定の業種に絞られているかを見る語。業種に絞った題は、その業種の材料が無いと一次性が届かない
INDUSTRY = re.compile(r"医療|クリニック|医院|歯科|診療所|病院|介護|福祉|保育|薬局|不動産|飲食|美容|サロン|理容|建設|工務店|"
                      r"リフォーム|士業|税理士|社労士|弁護士|ホテル|旅館|物流|運送|製造|小売|EC|通販|学習塾|農業|NPO")


def load(path=None):
    try:
        return json.loads((path or LEDGER).read_text(encoding="utf-8")).get("facts") or []
    except (OSError, ValueError):
        return []


def for_text(text, path=None):
    """題（タイトル・狙う語）に当たる公的資料の文。題に業種の語が無ければ当てない（全記事に同じ文を流さない）"""
    t = str(text or "")
    return [f for f in load(path) if any(w and w in t for w in f.get("words") or [])]


def industry_of(text):
    """題に入っている業種の語（無ければ空）"""
    m = INDUSTRY.search(str(text or ""))
    return m.group(0) if m else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    kw = " ".join(sys.argv[1:])
    for f in for_text(kw):
        print(f"- {f['claim']}（{f['org']} {f['url']}・{f['checked']}確認）")


if __name__ == "__main__":
    main()
