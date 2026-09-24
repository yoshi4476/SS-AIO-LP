# -*- coding: utf-8 -*-
"""著者ページと sameAs を、あちこちにある実在の証拠から機械で束ねる。

**なぜ要るか**: E-E-A-T の「著者の実在」は、Person の sameAs と著者ページの実績で
機械に示す。ところが sameAs は build.py の固定リストで、YouTube・note・登壇・掲載が
増えても更新されなかった。実在の証拠は台帳にたまる（動画の台帳・言及の台帳・一次データ・
法人番号）。ここで束ねて、記事の Person と著者ページの両方へ流す。

材料（全部、既にあるもの）:
  data/author.json         … 手で足す分（YouTubeチャンネル・X・登壇実績など）
  data/videos.json         … 上げた動画（YouTube の URL）
  data/mentions.json       … 第三者の掲載（third=true・alive=true のもの）
  data/datasets/*.json     … 公開した一次データ
  build.py の ORG/AUTHOR   … 法人番号ページ・既定の sameAs

  python scripts/author_profile.py            # 束ねた結果を見る
  python scripts/author_profile.py --write    # data/author_profile.json と著者ページを更新
出す印: AUTHOR_OK=yes / SAMEAS=<件>
"""
import argparse
import html as _h
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONF = ROOT / "data" / "author.json"
OUT = ROOT / "data" / "author_profile.json"
PAGE = ROOT / "site" / "author" / "haraguchi" / "index.html"


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except Exception:
        return default


def gather():
    import build as B
    conf = _load(CONF, {})
    same = list(B.AUTHOR_SAME_AS)
    for k in ("youtube_channel", "x", "note", "linkedin", "facebook", "instagram", "wikidata"):
        if conf.get(k):
            same.append(conf[k])
    same.append(f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHouzinNo={B.ORG_NUMBER}")
    # 第三者の掲載（生きているものだけ）。リンクの有無は問わない（言及として数える）
    mentions = [m for m in (_load(ROOT / "data" / "mentions.json", {}).get("items") or [])
                if str(m.get("third")).lower() == "true" and str(m.get("alive")).lower() == "true" and m.get("url")]
    videos = _load(ROOT / "data" / "videos.json", {})
    works = [{"kind": "動画", "title": slug, "url": f"https://www.youtube.com/watch?v={v['youtube']}", "date": v.get("date", "")}
             for slug, v in videos.items() if v.get("youtube")]
    datasets = sorted((ROOT / "data" / "datasets").glob("*.json"))
    creds = list(conf.get("credentials") or [])          # {title, url, date, kind}（登壇・寄稿・資格）
    seen, uniq = set(), []
    for u in same:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    n_articles = sum(1 for p in (ROOT / "articles").glob("*.md")
                     if re.search(r"^score:\s*(9\d|100)", p.read_text(encoding="utf-8-sig")[:600], re.M))
    return {"date": date.today().isoformat(), "same_as": uniq, "mentions": mentions[:30], "works": works[-20:],
            "credentials": creds, "counts": {"articles": n_articles, "datasets": len(datasets), "videos": len(works)}}


def render_block(prof):
    lis = []
    c = prof["counts"]
    lis.append(f"<li>監修記事 {c['articles']}本（品質90点以上で公開したもの）／公開した一次データ {c['datasets']}件／解説動画 {c['videos']}本</li>")
    for m in prof["mentions"][:10]:
        lis.append(f'<li>掲載: <a href="{_h.escape(m["url"])}" target="_blank" rel="noopener">{_h.escape(m.get("where") or m["url"])}</a>'
                   f'（{_h.escape(str(m.get("added", ""))[:7])}）</li>')
    for cr in prof["credentials"][:10]:
        u = cr.get("url")
        t = _h.escape(cr.get("title", ""))
        lis.append(f'<li>{_h.escape(cr.get("kind", "実績"))}: ' + (f'<a href="{_h.escape(u)}" target="_blank" rel="noopener">{t}</a>' if u else t)
                   + (f'（{_h.escape(str(cr.get("date", ""))[:7])}）' if cr.get("date") else "") + "</li>")
    for w in prof["works"][-5:]:
        lis.append(f'<li>動画: <a href="{_h.escape(w["url"])}" target="_blank" rel="noopener">{_h.escape(w["title"])}</a></li>')
    return ("<!-- auto:works -->\n  <h2>実績（台帳から自動集計・" + prof["date"] + "更新）</h2>\n  <ul>\n    "
            + "\n    ".join(lis) + "\n  </ul>\n  <!-- /auto:works -->")


def write_page(prof):
    if not PAGE.is_file():
        return False
    t = PAGE.read_text(encoding="utf-8")
    same_json = json.dumps(prof["same_as"], ensure_ascii=False)
    t2 = re.sub(r'"sameAs":\s*\[[^\]]*\]', '"sameAs": ' + same_json, t, count=1)
    t2 = re.sub(r'"dateModified":\s*"\d{4}-\d{2}-\d{2}"', f'"dateModified": "{prof["date"]}"', t2, count=1)
    block = render_block(prof)
    if "<!-- auto:works -->" in t2:
        t2 = re.sub(r"<!-- auto:works -->.*?<!-- /auto:works -->", block, t2, count=1, flags=re.S)
    else:
        t2 = t2.replace("<h2>外部プロフィール</h2>", block + "\n\n  <h2>外部プロフィール</h2>", 1)
    # 外部プロフィールの一覧に、無いリンクを足す（既にある行は触らない）
    m = re.search(r"<h2>外部プロフィール</h2>\s*<ul>(.*?)</ul>", t2, re.S)
    if m:
        ul = m.group(1)
        add = [u for u in prof["same_as"] if u not in ul and "houjin-bangou" not in u and "7senses.co.jp" not in u]
        if add:
            extra = "".join(f'\n    <li><a href="{_h.escape(u)}" target="_blank" rel="noopener me">{_h.escape(u)}</a></li>' for u in add)
            t2 = t2[:m.end(1)] + extra + t2[m.end(1):]
    if t2 != t:
        PAGE.write_text(t2, encoding="utf-8", newline="\n")
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    prof = gather()
    print(f"■ sameAs {len(prof['same_as'])}件 / 掲載 {len(prof['mentions'])}件 / 実績 {len(prof['credentials'])}件 / 動画 {len(prof['works'])}本")
    for u in prof["same_as"]:
        print(f"   - {u}")
    if a.write:
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"   {'著者ページを更新しました' if write_page(prof) else '著者ページは変更なし'}")
    print(f"AUTHOR_OK=yes\nSAMEAS={len(prof['same_as'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
