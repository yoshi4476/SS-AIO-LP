# -*- coding: utf-8 -*-
"""YouTube に上がった記事動画を、その記事のページに埋め込む（VideoObject つき）。

**なぜ要るか**: article_videos が動画を上げても、記事の側は何も変わらなかった。
埋め込めば、動画リッチリザルトの対象になり、読者の滞在時間も伸びる。
台帳（data/videos.json）に youtube の ID がある記事だけが対象。無ければ何もしない。

build.py（AI集客ラボ）と publish.py（配信先）の両方が同じ関数を呼ぶ。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "videos.json"


def info(slug):
    if not LEDGER.is_file():
        return None
    try:
        rec = json.loads(LEDGER.read_text(encoding="utf-8")).get(slug)
    except Exception:
        return None
    return rec if rec and rec.get("youtube") else None


def _iso_duration(sec):
    sec = int(sec or 0)
    return f"PT{sec // 60}M{sec % 60}S"


def block(meta):
    """埋め込みの HTML（figure + VideoObject の JSON-LD）。無ければ空文字"""
    rec = info(meta.get("slug", ""))
    if not rec:
        return ""
    vid = rec["youtube"]
    ld = {"@context": "https://schema.org", "@type": "VideoObject",
          "name": str(meta.get("title", ""))[:100],
          "description": str(meta.get("description", ""))[:300],
          "thumbnailUrl": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
          "uploadDate": rec.get("date", ""),
          "duration": _iso_duration(rec.get("sec")),
          "embedUrl": f"https://www.youtube.com/embed/{vid}",
          "contentUrl": f"https://www.youtube.com/watch?v={vid}"}
    return (
        '<figure class="article-video" style="margin:24px 0">'
        '<div style="position:relative;padding-top:56.25%;background:#0b1830;border-radius:12px;overflow:hidden">'
        f'<iframe src="https://www.youtube-nocookie.com/embed/{vid}" title="{str(meta.get("title", ""))[:80]}" '
        'loading="lazy" allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen '
        'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
        '<figcaption style="font-size:.85em;color:#5b6980;margin-top:6px">この記事の要点を約'
        f'{max(1, int(rec.get("sec") or 0) // 60)}分の動画にまとめています（本文と同じ内容です）</figcaption>'
        '</figure>\n<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n")


def prepend(html, meta):
    b = block(meta)
    return (b + html) if b else html
