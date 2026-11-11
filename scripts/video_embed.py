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
    try:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import client_private as CP       # お客様の社の記事の行は非公開のリポジトリ
        rec = CP.load_videos(LEDGER).get(slug)
    except Exception:
        return None
    return rec if rec and rec.get("youtube") else None


def _iso_duration(sec):
    sec = int(sec or 0)
    return f"PT{sec // 60}M{sec % 60}S"


def upload_date(rec):
    """uploadDate は時差つきの日時で出す。日付だけだと Search Console が「タイムゾーンがありません」
    「日時値が無効です」と出す（2026-10-08 コーポレートで実際に出た）。台帳は日本時間の日付だけを持つ"""
    d = str((rec or {}).get("date") or "")
    return d + "T00:00:00+09:00" if len(d) == 10 else d


def facade(vid, title):
    """押すまで YouTube を読み込まない埋め込み。枠の中に先にサムネイルと再生の印だけを出し（srcdoc）、押したら枠の中で動画へ移る。
    スクリプトは要らない。読み込み前から YouTube の Cookie の指摘が出ていた（Lighthouse のベストプラクティス 96 点。2026-11-12）"""
    import html as H
    url = f"https://www.youtube-nocookie.com/embed/{vid}"
    doc = ("<style>*{margin:0;padding:0}html,body{height:100%;overflow:hidden;background:#0b1830}"
           "a{display:block;height:100%;position:relative}img{width:100%;height:100%;object-fit:cover}"
           "span{position:absolute;left:50%;top:50%;width:72px;height:72px;margin:-36px 0 0 -36px;border-radius:50%;background:rgba(11,24,48,.82)}"
           "span::after{content:'';position:absolute;left:28px;top:20px;border-style:solid;border-width:16px 0 16px 26px;border-color:transparent transparent transparent #fff}"
           f"</style><a href='{url}?autoplay=1' aria-label='動画を再生する'>"
           f"<img src='https://i.ytimg.com/vi/{vid}/hqdefault.jpg' alt=''><span></span></a>")
    return (f'<iframe src="{url}" srcdoc="{H.escape(doc, quote=True)}" title="{H.escape(str(title)[:80], quote=True)}" '
            'loading="lazy" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowfullscreen '
            'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>')


def block(meta, click_to_load=False):
    """埋め込みの HTML（figure + VideoObject の JSON-LD）。無ければ空文字。
    click_to_load は AI集客ラボのビルドだけが使う（配信先のサイトは、枠の中の画像の許可（CSP）が社ごとに違うのでこれまでどおり）"""
    rec = info(meta.get("slug", ""))
    if not rec:
        return ""
    vid = rec["youtube"]
    ld = {"@context": "https://schema.org", "@type": "VideoObject",
          "name": str(meta.get("title", ""))[:100],
          "description": str(meta.get("description", ""))[:300],
          "thumbnailUrl": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
          "uploadDate": upload_date(rec),
          "duration": _iso_duration(rec.get("sec")),
          "embedUrl": f"https://www.youtube.com/embed/{vid}",
          "contentUrl": f"https://www.youtube.com/watch?v={vid}"}
    return (
        '<figure class="article-video" style="margin:24px 0">'
        '<div style="position:relative;padding-top:56.25%;background:#0b1830;border-radius:12px;overflow:hidden">'
        + (facade(vid, meta.get("title", "")) if click_to_load else
           f'<iframe src="https://www.youtube-nocookie.com/embed/{vid}" title="{str(meta.get("title", ""))[:80]}" '
           'loading="lazy" allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen '
           'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>') + '</div>'
        '<figcaption style="font-size:.85em;color:#5b6980;margin-top:6px">この記事の要点を約'
        f'{max(1, int(rec.get("sec") or 0) // 60)}分の動画にまとめています（本文と同じ内容です）</figcaption>'
        '</figure>\n<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n")


def prepend(html, meta, click_to_load=False):
    b = block(meta, click_to_load)
    return (b + html) if b else html
