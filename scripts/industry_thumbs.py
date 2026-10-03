# -*- coding: utf-8 -*-
"""業種別のサムネイル（「◯◯のAIO対策」の画像）を、ファイル名で引いて記事に当てる。

    site/images/thumbs/aio-<鍵>.jpg   … 鍵は業種ページの slug（shika / clinic / fudosan …）＋細かい区分

記事の frontmatter は書き換えない。build.py が読み込むたびに、次の条件の記事だけ差し替える。
  - アイキャッチが自動生成のもの（/images/<slug>/eyecatch.png）か未設定。手で選んだ画像は触らない
  - 記事の主題が AI検索の対策（カテゴリ aio、または題・狙う語に AIO／AI検索／LLMO など）。
    画像に「◯◯のAIO対策」と書いてあるため、インスタ集客など別の主題の記事に付けると内容と食い違う
  - 業種が分かり、その業種の画像がある
画像を差し替えたいときは、同じ名前で上書きするだけでよい。業種が増えたら、ファイルを置いて KEYS に足す。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "site" / "images" / "thumbs"

# 鍵 → 画像の題（デスクトップのファイル名・一覧にも使う）
KEYS = {
    "shika": "歯科医院のAIO対策",
    "clinic": "クリニック・医療機関のAIO対策",
    "clinic-biyou": "美容外科・美容クリニックのAIO対策",
    "seikotsuin": "整骨院・接骨院のAIO対策",
    "fudosan": "不動産のAIO対策",
    "koumuten": "工務店・注文住宅のAIO対策",
    "shigyou": "士業の集客・顧客獲得のAIO対策",
    "btob": "BtoBのAIO対策",
    "btob-system": "システム開発のAIO対策",
    "btob-consulting": "経営戦略・コンサルティングのAIO対策",
    "inshoku": "飲食店のAIO対策",
    "salon": "美容室・サロンのAIO対策",
    "reform": "リフォーム・外壁塗装のAIO対策",
    "hotel": "ホテル・旅館のAIO対策",
    "fitness": "フィットネス・ジムのAIO対策",
    "school": "スクール・教育サービスのAIO対策",
    "ec": "EC・ネットショップのAIO対策",
}
# 業種ページ（industry_hub）の無い業種は、題・狙う語の言葉で決める（上から順に見る）
WORDS = [
    ("reform", r"リフォーム|外壁|塗装"),
    ("salon", r"美容室|美容院|ヘアサロン|サロン"),
    ("hotel", r"ホテル|旅館|宿泊"),
    ("fitness", r"フィットネス|ジム|パーソナルトレーニング"),
    ("school", r"学習塾|塾|スクール|教室|予備校"),
    ("ec", r"EC|ネットショップ|通販"),
]
AIO_THEME = re.compile(r"AIO|AI検索|LLMO|AI ?Overview|AIに(選|引用|紹介|出)", re.I)
_DEFS = None


def _hub(title, keyword):
    global _DEFS
    try:
        import industry_hub as IH
        if _DEFS is None:
            _DEFS = IH.load()[0]
        return IH.detect(title, keyword, _DEFS) or ""
    except Exception:
        return ""


def key_for(meta):
    """その記事に当てる鍵（当てないときは空）"""
    title, kw = str(meta.get("title", "")), str(meta.get("keyword", ""))
    if meta.get("category") != "aio" and not AIO_THEME.search(title + " " + kw):
        return ""
    if "飲食" in title or "飲食" in kw:
        return "inshoku"
    for k, rx in WORDS:
        if re.search(rx, title + " " + kw) and variants(k):
            return k
    hub = _hub(title, kw)
    if hub == "clinic" and "美容" in title:
        return "clinic-biyou"
    if hub == "btob":
        if re.search(r"システム開発|SaaS|IT企業|ソフトウェア", title):
            return "btob-system"
        if "コンサル" in title:
            return "btob-consulting"
    return hub if hub in KEYS else ""


def apply(meta):
    """自動生成のアイキャッチの記事だけ、業種の画像に差し替えた eyecatch を返す"""
    cur = meta.get("eyecatch") or ""
    if cur and cur != f"/images/{meta.get('slug')}/eyecatch.png":
        return cur                                   # 手で選んだ画像はそのまま
    k = key_for(meta)
    files = variants(k) if k else []
    if files:
        # 同じ業種に複数枚あれば、記事ごとに決まった1枚（slug から決める。ビルドのたびに変わらない）。
        # 一覧で同じ画像ばかり並ぶのを減らす
        import hashlib
        i = int(hashlib.md5(str(meta.get("slug", "")).encode("utf-8")).hexdigest(), 16) % len(files)
        return f"/images/thumbs/{files[i]}"
    t = theme_for(meta)
    if t and (DIR / f"theme-{t}.jpg").is_file():
        return f"/images/thumbs/theme-{t}.jpg"
    # 業種・テーマの画像が無い記事は、文字だけのアイキャッチをやめて「写真の棚」から内容に合う写真を当てる
    try:
        import photo_shelf
        _, url = photo_shelf.pick(meta.get("title", ""), meta.get("keyword", ""), meta.get("slug", ""))
        if url and photo_shelf.path_of(url).is_file():
            return url
    except Exception:
        pass
    return cur


# 業種の決まらない AI検索の対策の記事は、テーマの画像（費用・注意点・違い…）を題の言葉で当てる。上から順に見る
THEMES = [
    ("cost", r"費用|相場|いくら|料金"),
    ("caution", r"失敗|注意|NG|落とし穴|表示されない|出ない|原因"),
    ("choose", r"選び方|会社|外注|コンサル|ライター"),
    ("diff", r"違い|使い分け|比較"),
    ("llmo", r"LLMO|ChatGPT"),
    ("seo", r"SEO"),
    ("howto", r""),
]


def theme_for(meta):
    title, kw = str(meta.get("title", "")), str(meta.get("keyword", ""))
    if meta.get("category") != "aio" and not AIO_THEME.search(title + " " + kw):
        return ""
    if re.search(r"AIO|AI検索|LLMO", title):
        title = title.replace("SEO", "")               # AIOとSEOの両方を扱う記事は SEO のテーマにしない
    return next(k for k, rx in THEMES if re.search(rx, title))


def shown(url):
    """ページに表示する画像。業種・テーマの画像は同じ名前の WebP があればそちら（約4割軽い）。共有画像は JPEG のまま"""
    if url and url.startswith(("/images/thumbs/", "/images/shelf/")) and url.endswith(".jpg"):
        w = url[:-4] + ".webp"
        if (ROOT / "site" / w.lstrip("/")).is_file():
            return w
    return url


def variants(k):
    """aio-<鍵>.jpg と aio-<鍵>-2.jpg, -3.jpg …（数字だけ。aio-clinic-biyou は clinic の別枚に数えない）"""
    rx = re.compile(rf"^aio-{re.escape(k)}(-\d+)?\.jpg$")
    return sorted(p.name for p in DIR.glob(f"aio-{k}*.jpg") if rx.match(p.name))


# 現場の写真（site/images/scenes/<鍵>.webp）。業種ページ・業種LP・調査・ツール・よくある質問の冒頭の下に、
# その業種や話題の場面を1枚置く。文字だけの面が続くと、どの業種の話かが一目で分からない。
SCENE_ALT = {
    "shika": "歯科医院の診療室で、歯科医師が患者を診る様子",
    "clinic": "明るい診察室で、医師が患者と話す様子",
    "seikotsuin": "整骨院で、施術者が患者の肩を施術する様子",
    "fudosan": "不動産会社の担当者が、マンションの前でお客様に説明する様子",
    "koumuten": "完成した木の家の前に立つ工務店の担当者と施主",
    "shigyou": "書棚のある事務所で、士業の専門家が相談に応じる様子",
    "btob": "ガラス張りの会議室で、商談がまとまり握手する様子",
    "tools": "ノートパソコンでサイトの分析を確かめる経営者",
    "faq": "オンラインで相談に答える担当者",
    "research": "複数の画面でデータを読み解く分析担当",
}
SCENE_OF = {"medical": "clinic", "reform": "koumuten"}   # 業種LP の名前・業種ページの slug → 写真の鍵


def scene_band(key, caption=""):
    """冒頭の下に置く横長の写真。写真が無ければ空"""
    import html as _h
    k = SCENE_OF.get(key, key)
    if not (ROOT / "site" / "images" / "scenes" / f"{k}.webp").is_file():
        return ""
    cap = f'<figcaption>{_h.escape(caption)}</figcaption>' if caption else ""
    return (f'<figure class="scene-band"><img src="/images/scenes/{k}.webp" alt="{_h.escape(SCENE_ALT.get(k, ""))}" '
            f'width="1600" height="900" loading="lazy" decoding="async">{cap}</figure>')


# 業種LP（site/lp/<名前>/）と業種ページ（site/industry/<slug>/）の共有画像を、その業種の画像にする。
# 共通の画像のままだと、LINE や X で「不動産のAIO対策」のページを共有しても、どの業種の話か伝わらない
LP_KEY = {"medical": "clinic", "fudosan": "fudosan", "koumuten": "koumuten", "shigyou": "shigyou"}


def apply_scene_bands(site: Path):
    """業種ページ・業種LP・調査・質問集・ツール・よくある質問の、最初の区画の直後に写真を1枚置く（何度呼んでも同じ）"""
    import re as _re
    R2K = {"dental": "shika", "clinic": "clinic", "fudosan": "fudosan", "koumuten": "koumuten", "shigyou": "shigyou"}
    jobs = [(p, p.parent.name) for p in (site / "industry").glob("*/index.html")]
    jobs += [(p, p.parent.parent.name) for p in (site / "industry").glob("*/faq/index.html")]   # 業種の質問集にも同じ業種の写真
    jobs += [(site / "lp" / k / "index.html", k) for k in LP_KEY]
    for r, k in R2K.items():
        jobs += [(site / "research" / f"{r}-ai-sources" / "index.html", k),
                 (site / "research" / f"{r}-ai-sources" / "questions" / "index.html", "research")]
    jobs += [(site / "research" / "ranking" / "index.html", "research"),
             (site / "tools" / "index.html", "tools"), (site / "faq" / "index.html", "faq")]
    n = 0
    for p, key in jobs:
        band = scene_band(key)
        if not p.is_file() or not band:
            continue
        s = p.read_text(encoding="utf-8")
        s0 = s
        s = _re.sub(r"\n?<!-- scene -->.*?<!-- /scene -->\n?", "", s, flags=_re.S)   # 前後の改行ごと外す（作り直しで空行が増えない）
        m = _re.search(r'<section class="(?:lx-hero|hero|tools-head)[^"]*"', s)
        if not m:
            continue
        end = s.find("</section>", m.end())
        if end < 0:
            continue
        end += len("</section>")
        s = s[:end] + f"\n<!-- scene -->{band}<!-- /scene -->\n" + s[end:]
        if s != s0:
            p.write_text(s, encoding="utf-8", newline="")
            n += 1
    return n


def apply_share_images(site: Path, site_url: str):
    import re as _re
    jobs = [(site / "lp" / k / "index.html", v) for k, v in LP_KEY.items()]
    jobs += [(p, p.parent.name) for p in (site / "industry").glob("*/index.html")]
    n = 0
    for p, key in jobs:
        files = variants(key)
        if not p.is_file() or not files:
            continue
        url = f"{site_url}/images/thumbs/{files[0]}"
        s = p.read_text(encoding="utf-8")
        new = _re.sub(r'(<meta property="og:image" content=")[^"]*(")', lambda m: m.group(1) + url + m.group(2), s, count=1)
        # すでに twitter:image があるページも、同じ画像に差し替える（X だけ古い画像が残らないように。Codex の点検で指摘）
        new = _re.sub(r'(<meta name="twitter:image" content=")[^"]*(")', lambda m: m.group(1) + url + m.group(2), new, count=1)
        if 'name="twitter:image"' not in new:
            new = new.replace("</head>", f'<meta name="twitter:image" content="{url}">\n</head>', 1)
        if new != s:
            p.write_text(new, encoding="utf-8", newline="")
            n += 1
    return n


def apply_shelf_bands(site: Path):
    """用語集の各語・テーマ・比較表のページに、写真の棚から内容に合う1枚を見出しの下に置く（何度呼んでも同じ）。
    文字だけのページが続き、定義の下が大きく空いていたため"""
    import html as _h
    import re as _re
    try:
        import photo_shelf
    except Exception:
        return 0
    n = 0
    pages = list((site / "glossary").glob("*/index.html")) + list((site / "topics").glob("*/index.html"))         + list((site / "compare").glob("*/index.html"))
    for p in pages:
        s = p.read_text(encoding="utf-8")
        m = _re.search(r"<h1>(.*?)</h1>", s, _re.S)
        if not m:
            continue
        title = _re.sub(r"<[^>]+>", "", m.group(1))
        k, url = photo_shelf.pick(title, "", p.parent.name)
        if not url or not photo_shelf.path_of(url).is_file():
            continue
        src = shown(url)
        band = (f'<figure class="scene-band"><img src="{src}" alt="{_h.escape(title)}のイメージ" width="1600" height="900" '
                f'loading="lazy" decoding="async"><figcaption>※ 写真はイメージです</figcaption></figure>')
        s0 = s
        s = _re.sub(r"\n?<!-- shelf -->.*?<!-- /shelf -->\n?", "", s, flags=_re.S)
        h = _re.search(r'<section class="hero"[^>]*>', s)
        if not h:
            continue
        end = s.find("</section>", h.end())
        if end < 0:
            continue
        end += len("</section>")
        s = s[:end] + f"\n<!-- shelf -->{band}<!-- /shelf -->\n" + s[end:]
        if s != s0:
            p.write_text(s, encoding="utf-8", newline="")
            n += 1
    return n
