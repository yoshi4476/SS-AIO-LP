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
    if url and url.startswith("/images/thumbs/") and url.endswith(".jpg"):
        w = url[:-4] + ".webp"
        if (ROOT / "site" / w.lstrip("/")).is_file():
            return w
    return url


def variants(k):
    """aio-<鍵>.jpg と aio-<鍵>-2.jpg, -3.jpg …（数字だけ。aio-clinic-biyou は clinic の別枚に数えない）"""
    rx = re.compile(rf"^aio-{re.escape(k)}(-\d+)?\.jpg$")
    return sorted(p.name for p in DIR.glob(f"aio-{k}*.jpg") if rx.match(p.name))


# 業種LP（site/lp/<名前>/）と業種ページ（site/industry/<slug>/）の共有画像を、その業種の画像にする。
# 共通の画像のままだと、LINE や X で「不動産のAIO対策」のページを共有しても、どの業種の話か伝わらない
LP_KEY = {"medical": "clinic", "fudosan": "fudosan", "koumuten": "koumuten", "shigyou": "shigyou"}


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
        if 'name="twitter:image"' not in new:
            new = new.replace("</head>", f'<meta name="twitter:image" content="{url}">\n</head>', 1)
        if new != s:
            p.write_text(new, encoding="utf-8", newline="")
            n += 1
    return n
