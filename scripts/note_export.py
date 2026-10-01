# -*- coding: utf-8 -*-
"""note に転載する下書きを、公開済みの記事からまとめて書き出す（投稿は人が手で行う）。

    python scripts/note_export.py                    # AIO・SEO・LLMO の記事（既定）
    python scripts/note_export.py --all              # 全カテゴリ

本文は social_post.compose の note 版（各見出しの1文結論＋元記事のURLと社名）。
記事に書かれていることしか書かない。数字を作らない。
並びは直近28日の検索表示の多い順（読まれている記事から転載する）。
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "automation" / "note"
TOPIC = re.compile(r"AIO|SEO|LLMO|GEO|AI検索|AI Overview", re.I)


def impressions():
    """記事URLの末尾ごとの28日の表示回数（取れなければ空）"""
    try:
        import gsc_detail as G
        import sites as S
        sc = G.client()
        end = date.today() - timedelta(days=3)
        out = {}
        for cfg in S.load_all().values():
            for r in G.q(sc, cfg["domain"], str(end - timedelta(days=27)), str(end), ["page"], 25000):
                k = r["keys"][0].rstrip("/").split("/")[-1]
                out[k] = out.get(k, 0) + int(r["impressions"])
        return out
    except Exception:
        return {}


def main():
    import social_post as SP
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    imp = impressions()
    rows = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        art = SP.article(p.stem)
        if not art:
            continue
        if not a.all and not TOPIC.search(art["title"]):
            continue
        sid, _ = SP.site_of(art["category"])
        if sid != "ai-lab" and not a.all:
            continue
        rows.append((imp.get(p.stem, 0), art))
    rows.sort(key=lambda x: (-x[0], x[1]["slug"]))
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.txt"):
        f.unlink()
    index = ["順番\t28日の表示\tタイトル\tファイル"]
    for i, (n, art) in enumerate(rows, 1):
        name = f"{i:03d}_{art['slug']}.txt"
        (OUT / name).write_text(SP.compose(art)["posts"]["note"] + "\n", encoding="utf-8")
        index.append(f"{i}\t{n}\t{art['title']}\t{name}")
    (OUT / "一覧.tsv").write_text("\n".join(index) + "\n", encoding="utf-8-sig")
    print(f"note の下書き {len(rows)}本 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
