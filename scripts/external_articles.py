# -*- coding: utf-8 -*-
"""お客様の側で書かれた記事（当社の工程の外の記事）の狙う語と題を、食い合いの検査に渡す。

**なぜ要るか**: 食い合いの検査（kw_guard）は当社の原稿（articles/）だけを相手にしていた。お客様のサイトには
当社が書いていない記事もあり、その記事の狙う語そのものでも「ぶつかる既存記事はありません」と通り、在庫に積まれていた
（2026-11-03: お客様の社の既存の2本と同じ語が在庫にあった。GSC の実績も、公開から日の浅い記事は拾えない）。

配信のたびに取得する配信先のリポジトリ（publish.ensure_clone）の記事の置き場を読み、当社の原稿に無い slug の記事だけを
非公開の置き場（clients/<id>/external_articles.json）に残す。お客様の記事の題・語は public に置かない。

  python scripts/external_articles.py <社の id> <配信先のリポジトリの場所>   # 手で取り直す（件数だけ出す）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
NAME = "external_articles.json"
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def _field(fm, key):
    m = re.search(rf"^{key}:\s*(.+?)\s*$", fm, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def scan(content_dir, ours):
    """記事の置き場の .md / .mdx のうち、当社の原稿に無い slug の記事 [{slug, kw, title}]"""
    out = []
    for p in sorted(Path(content_dir).glob("*.md*")):
        m = FM.match(p.read_text(encoding="utf-8-sig"))
        if not m:
            continue
        slug = _field(m.group(1), "slug") or p.stem.split(".")[0]
        if slug in ours:
            continue
        kw, title = _field(m.group(1), "keyword"), _field(m.group(1), "title")
        if kw or title:
            out.append({"slug": slug, "kw": kw or title, "title": title})
    return out


def refresh(cfg, dest):
    """配信先の取得の後に呼ぶ。お客様の社で記事の置き場があるときだけ。残した件数（記事の置き場が無ければ None）"""
    import private_store
    import sites as S
    if not S.is_client(cfg.get("id", "")) or not cfg.get("content_dir"):
        return None
    d = Path(dest) / cfg["content_dir"]
    if not d.is_dir():
        return None
    from cannibal_check import load_articles
    rows = scan(d, {a["slug"] for a in load_articles()})
    private_store.write_json(cfg["id"], NAME, rows)
    return len(rows)


def load(site_id):
    """食い合いの検査に足す記事（load_articles と同じ形。slug はお客様の記事と分かる印をつける）"""
    import private_store
    import sites as S
    if not site_id or not S.is_client(site_id):
        return []
    rows = private_store.read_json(site_id, NAME, []) or []
    return [{"slug": f"（お客様の既存の記事）{r.get('slug', '')}", "kw": r.get("kw", ""), "title": r.get("title", ""),
             "desc": "", "cat": "", "h2": [], "external": True} for r in rows if r.get("kw")]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    import sites as S
    n = refresh(S.load(sys.argv[1]), sys.argv[2])
    print(f"EXTERNAL_ARTICLES={'unknown' if n is None else n}")
