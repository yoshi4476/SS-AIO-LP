# -*- coding: utf-8 -*-
"""記事に入れてはいけない HTML と、本番の転送先を見る（判定はこの1か所だけに置く）

記事を書く AI は外の文章（YouTube の字幕・検索上位の見出し）を読む。そこに仕込まれた指示に従うと、
本文に外部のスクリプト・onerror・iframe・外部への form・javascript: の URL・自動の転送を入れたり、
site/_redirects で相談先を外の場所へ転送したりできる。Markdown の変換（md2html）は生の HTML をそのまま通し、
題・説明・FAQ も雛形へそのまま入るので、どれも読者の画面で動く。
build.py（公開できなくなる側）・publish.py（全方式）・score_check（書く段）・seo_audit（転送）が同じ関数を呼ぶ。
方式ごとに書くと、1つの方式だけを見る検査になる（publish.py の script の検査は先方の変換の社だけだった）

  python scripts/html_safety.py      # 原稿（articles/*.md）と site/_redirects を数える（HTML_SAFETY_OK=yes|no）
"""
import html as H
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWN_SUFFIX = "7senses.co.jp"

KINDS = {
    "script": "スクリプト（ld+json 以外の script）",
    "on": "on で始まる属性（onerror・onclick など）",
    "frame": "埋め込み（iframe・object・embed）",
    "base": "base（ページのリンクの行き先をまとめて変える）",
    "form": "外部へ送る form",
    "url": "javascript: などの URL",
    "refresh": "meta の http-equiv（自動の転送など）",
}
_FRAMES = {"iframe", "frame", "frameset", "object", "embed", "applet", "portal"}
_BAD_SCHEMES = {"javascript", "vbscript", "livescript"}
_NAV = {"href", "xlink:href", "action", "formaction"}
# HTMLParser とブラウザで読み方が分かれる形（noscript の中の属性値・--!> で閉じる注釈など）のための、字面での二重の確かめ。
# on 属性は、< を含まない引用符の中（URL の /online= など）を外してから見る
_RX = (
    ("script", re.compile(r"<\s*script\b(?![^>]*application/ld\+json)", re.I)),
    ("frame", re.compile(r"<\s*(?:iframe|frame|frameset|object|embed|applet|portal)\b", re.I)),
    ("base", re.compile(r"<\s*base\b", re.I)),
    ("refresh", re.compile(r"<\s*meta\b[^>]*http-equiv", re.I)),
)
_RX_ON = re.compile(r"<[a-z][^>]*?[\s\"'/]on[a-z]+\s*=", re.I)
_QUOTED = re.compile(r"\"[^\"<]*\"|'[^'<]*'")
_ON_TEXT = re.compile(r"(?:^|[\s\"'/;])on[a-z]+\s*=", re.I)
# 本文に無ければ当てはまりようのない字面。全記事の変換を毎回し直すとビルドが数秒延びるので、これが無い記事は変換しない。
# ブラウザは URL の途中のタブ・改行を消して読むので、語の文字の間の空白・制御文字も許す
_SEP = r"[\x00-\x20]*"
_PRE = re.compile("|".join([r"<\s*/?\s*(?:script|iframe|frame|object|embed|applet|portal|base|meta|form)",
                            r"on[a-z]+\s*=", "formaction", "&#", r"&[a-z][a-z0-9]*;"]
                           + [_SEP.join(map(re.escape, w)) for w in ("javascript", "vbscript", "livescript", "data:")]),
                  re.I)
# Markdown のリンク・画像・参照の行き先（[文字](行き先)・[id]: 行き先）
_MD_URL = re.compile(r"\]\(\s*<?([^)\s>]+)|^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*<?(\S+?)>?[ \t]*$", re.M)
_ABS = re.compile(r"https?://([a-z0-9.-]+)(?::\d{1,5})?(?=[/?#]|$)", re.I)
_ODD = re.compile(r"[\\\x00-\x20\x7f]")

_OWN = None


def own_hosts():
    """自社のサイトのドメイン（sites/*.json のうちお客様の印が無いもの）。お客様のドメインは自社に数えない"""
    global _OWN
    if _OWN is None:
        hosts = set()
        for p in sorted((ROOT / "sites").glob("*.json")):
            try:
                c = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            sid = str(c.get("id") or p.stem)
            if c.get("domain") and not c.get("client") and not (ROOT / "data" / "clients" / sid).is_dir():
                hosts.add(str(c["domain"]).lower())
        _OWN = hosts
    return _OWN


def own_host(host, extra=()):
    h = (host or "").lower().rstrip(".")
    return (h == OWN_SUFFIX or h.endswith("." + OWN_SUFFIX) or h in own_hosts()
            or h in {str(x).lower() for x in extra if x})


def internal_path(u):
    """/ で始まるサイトの中の場所か。// と /\\ はブラウザが別のドメインとして読むので外す"""
    return bool(re.match(r"/(?![/\\])", u or "")) and not _ODD.search(u)


def own_url(u, extra=()):
    """サイトの中の場所か、自社のドメインの URL か（user@host・\\ の混ざった形は別のドメインへ行けるので通さない）"""
    u = u or ""
    if internal_path(u):
        return True
    m = _ABS.match(u)
    return bool(m) and not _ODD.search(u) and own_host(m.group(1), extra)


def _scheme(v):
    # ブラウザは URL の前後の空白・制御文字を捨て、途中のタブ・改行を消してから読む
    s = re.sub(r"[\x00-\x20\x7f]", "", H.unescape(v or "")).lower()
    m = re.match(r"([a-z][a-z0-9+.-]*):", s)
    return m.group(1) if m else ""


def form_ok(u, extra=()):
    """form の送り先がサイトの中か自社か（空・#・? は同じページ。相対の場所は同じサイト）"""
    u = re.sub(r"^[\x00-\x20]+|[\x00-\x20]+$", "", u or "")
    if not u or u.startswith(("#", "?")):
        return True
    if _scheme(u) or u.startswith(("//", "/\\", "\\")):
        return own_url(u, extra)
    return "\\" not in u


class _Scan(HTMLParser):
    def __init__(self, extra):
        super().__init__(convert_charrefs=True)
        self.extra, self.hits = extra, []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text() or f"<{tag}>"
        a = {}
        for k, v in attrs:
            a.setdefault(k.lower(), v or "")
        if tag == "script" and (a.get("type", "").strip().lower() != "application/ld+json" or "src" in a):
            self.hits.append(("script", raw))
        if tag in _FRAMES:
            self.hits.append(("frame", raw))
        if tag == "base":
            self.hits.append(("base", raw))
        if tag == "meta" and "http-equiv" in a:
            self.hits.append(("refresh", raw))
        if tag == "form" and not form_ok(a.get("action", ""), self.extra):
            self.hits.append(("form", raw))
        for k, v in attrs:
            k = k.lower()
            if k.startswith("on") and v is not None:
                self.hits.append(("on", raw))
            if k == "formaction" and not form_ok(v, self.extra):
                self.hits.append(("form", raw))
            sch = _scheme(v)
            if sch in _BAD_SCHEMES or (sch == "data" and k in _NAV):
                self.hits.append(("url", raw))


def find(html, extra=()):
    """HTML（の断片）にある入れてはいけないもの [(種類, 例)]。extra は自社に加えて送ってよいドメイン（その社のドメイン）"""
    if not html:
        return []
    s = _Scan(extra)
    s.feed(html)
    s.close()
    hits = s.hits + [(k, m.group(0)) for k, rx in _RX for m in rx.finditer(html)]
    hits += [("on", m.group(0)) for m in _RX_ON.finditer(_QUOTED.sub('""', html))]
    return _uniq(hits)


def md_links(text):
    """Markdown のリンク・画像の行き先が javascript: などのもの"""
    return _uniq([("url", m.group(0)) for m in _MD_URL.finditer(text or "")
                  if _scheme(m.group(1) or m.group(2)) in _BAD_SCHEMES])


def _uniq(hits):
    out, seen = [], set()
    for k, ex in hits:
        key = (k, ex[:80])
        if key not in seen:
            seen.add(key)
            out.append((k, ex))
    return out


def meta_fields(meta):
    """雛形・構造化データへそのまま入るフロントマターの文字（題・説明・FAQ）"""
    vals = [meta.get("title"), meta.get("description")]
    for f in meta.get("faq") or []:
        if isinstance(f, dict):
            vals += [f.get("q"), f.get("a")]
    return [str(v) for v in vals if v]


def article_problems(meta, body, extra=(), raw=False):
    """記事（フロントマターと本文）にある入れてはいけない HTML [(種類, 例)]。

    本文は当社の変換（md2html）の後の HTML を見る（コードの中の <script> は文字になるので止めない）。
    raw=True は原稿の Markdown のまま先方が変換する社（external-md）。先方の変換（marked など）は
    「<div> の直後のコードの囲み」を HTML のまま通すが当社の変換は文字にするので、原稿の字面も見る"""
    hits = []
    if _PRE.search(body or ""):
        import md2html
        hits += find(md2html.convert(body)[0], extra) + md_links(body)
        if raw:
            hits += find(body, extra)
    for v in meta_fields(meta or {}):
        # 題・説明は属性の値（content="…"）にも、構造化データの JSON にもそのまま入る。
        # 引用符で属性から抜けた on 属性・閉じの </script> だけでも動くので、タグの形でなくても止める
        hits += find(v, extra) + [("script", m.group(0)) for m in re.finditer(r"<\s*/?\s*script\b", v, re.I)]
        hits += [("on", m.group(0).strip()) for m in _ON_TEXT.finditer(v)]
    return _uniq(hits)


def describe(hits, n=3, sample=True):
    """種類の並びと最初の1例。お客様の記事は sample=False（例の URL に住所・社名が入りうる。CI のログは public）"""
    kinds = list(dict.fromkeys(k for k, _ in hits))
    ex = hits[0][1].replace("\n", " ")[:60] if hits and sample else ""
    return "・".join(KINDS[k] for k in kinds[:n]) + (f"（例: {ex}）" if ex else "")


def redirect_problems(text, extra=()):
    """_redirects の行のうち、転送先がサイトの中（/ で始まる）でも自社のドメインでもないもの [(行番号, 元, 先)]"""
    out = []
    for i, line in enumerate((text or "").splitlines(), 1):
        parts = line.split()
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        if not own_url(parts[1], extra):
            out.append((i, parts[0], parts[1]))
    return out


def main():
    sys.path.insert(0, str(ROOT / "scripts"))
    import private_store
    bad = 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig", errors="replace")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        import yaml
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        hits = article_problems(meta if isinstance(meta, dict) else {}, m.group(2), raw=True)
        if hits:
            bad += 1
            print(f"  {private_store.shown(p.stem)}: {describe(hits, sample=not private_store.client_slug(p.stem))}")
    rd = ROOT / "site" / "_redirects"
    red = redirect_problems(rd.read_text(encoding="utf-8")) if rd.is_file() else []
    for n, src, dst in red:
        print(f"  site/_redirects {n}行目: {src} → {dst[:80]}（自社の外）")
    print(f"記事 {bad}本・転送 {len(red)}行")
    print(f"HTML_SAFETY_OK={'no' if bad or red else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
