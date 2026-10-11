# -*- coding: utf-8 -*-
"""原稿の1行の記号から、機械が決まった形の地図・動画の埋め込みを作る（AI に埋め込みの HTML を書かせない）

  @[地図](大阪市中央区本町1丁目2-3)   … Google マップ
  @[動画](abcdEFGhijk)                 … YouTube（youtube-nocookie）

記事を書く AI は外の文章を読むので、iframe を書かせると、仕込まれた指示どおりの行き先を記事に埋め込める。
そのため html_safety が iframe を止めており、お客様の「記事に地図を入れたい」に応えられなかった（2026-10-12 運用者の決定）。
AI が書くのは場所の名前と動画の id だけにし、行き先と属性はここで決める。

差し込み方: 記号の行を実行ごとの乱数の印に置き換えて変換し、印が段落として独立して出た所（<p>印</p>）にだけ
埋め込みを置く（md2html.convert）。HTML の塊・コードの中に入った記号は埋め込まず、門で止める（problems）。
印は推測できないので、AI が印や埋め込みの HTML を書いても埋め込みにはならない。
検査（html_safety）は埋め込みを置いた後の HTML を見て、ここで作った iframe と1文字も違わず、記号の数までのものだけを通す。

出し方（md2html.convert の embeds）:
  "frame"  … iframe（loading=lazy）の figure。当社が HTML を作る形式（自社サイト・external-html・FTP・ZIP・nextjs-json）
  Path     … 配信先の作業コピー。その CSP（_headers の frame-src）が許す行き先だけ iframe、ほかはリンク
  "link"   … 普通のリンクの段落
  "wp"     … WordPress。地図はリンク、動画は URL だけの段落（WordPress が埋め込みに変える。iframe は投稿者の権限で消される）
  None     … 何も出さない
先方が Markdown を変換する形式（external-md）は、原稿の段階で Markdown のリンクにする（markdown_links。先方の変換が
iframe を通すか分からない）
"""
import html as H
import re
import secrets
import unicodedata
from pathlib import Path
from urllib.parse import quote

KINDS = ("地図", "動画")
LIMIT = 3            # 1記事に地図・動画それぞれ
ADDR_MAX = 80
HOSTS = {"地図": "www.google.com", "動画": "www.youtube-nocookie.com"}

_LINE = re.compile(r"@\[(地図|動画)\]\((.*)\)[ \t]*")
_ANY = re.compile(r"@\[(?:地図|動画)\]")
_FENCE = re.compile(r"(`{3,}|~{3,})")
# 住所・場所の名前に使ってよい文字。< > " ' ` と / : （URL）・半角の括弧（記号の閉じと入れ子）・制御文字は入らない
_ADDR_CHAR = re.compile(r"[^\W_]|[ 　\-－‐−―ー・、，,.．（）〒]")
_DOMAIN = re.compile(r"[a-z0-9-]+\.[a-z]{2,}", re.I)
_VID = re.compile(r"[A-Za-z0-9_-]{11}")


def present(body):
    return "@[" in (body or "")


def _value(kind, raw):
    """(値, 誤り)。誤りがあれば値は空"""
    v = raw.strip(" 　")
    if kind == "動画":
        return (v, "") if _VID.fullmatch(v) else ("", "動画の id は YouTube の11文字（英数字と - _）だけ")
    if not v:
        return "", "住所・場所の名前が空"
    if len(v) > ADDR_MAX:
        return "", f"住所・場所の名前は{ADDR_MAX}字まで（{len(v)}字）"
    bad = sorted({c for c in v if not _ADDR_CHAR.fullmatch(c)})
    if bad:
        return "", "住所に使えない文字（" + " ".join(repr(c) for c in bad[:5]) + "）"
    if _DOMAIN.search(unicodedata.normalize("NFKC", v)):
        return "", "住所に URL・ドメインは書けない"
    return v, ""


def _scan(lines):
    """コードの囲みの外の記号の行 [(行の位置, 種類, 値, 誤り)]。文の途中の記号も誤りとして返す"""
    fence = ""
    for i, ln in enumerate(lines):
        f = _FENCE.match(ln)
        if f:
            if not fence:
                fence = f.group(1)
            elif f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not ln[f.end():].strip():
                fence = ""
            continue
        if fence:
            continue
        if ln.startswith("@["):
            m = _LINE.fullmatch(ln.rstrip("\r"))
            if not m:
                yield i, "", "", "記号の行は @[地図](住所) か @[動画](id) だけにする（行頭から行末まで1つ）"
                continue
            v, err = _value(m.group(1), m.group(2))
            yield i, m.group(1), v, err
        elif _ANY.search(ln):
            yield i, "", "", "地図・動画の記号は文の途中に書けない（行頭から1行で書く）"


def _usable(lines):
    """埋め込む記号 [(行の位置, 種類, 値)]（誤りが無く、種類ごとに LIMIT まで）"""
    n = dict.fromkeys(KINDS, 0)
    out = []
    for i, kind, v, err in _scan(lines):
        if not err and n[kind] < LIMIT:
            n[kind] += 1
            out.append((i, kind, v))
    return out


def mark(body):
    """記号の行を、前後を空行にした印の段落に置き換える。(本文, [(種類, 値, 行番号)], 印)"""
    if not present(body):
        return body, [], ""
    token = "ssembed" + secrets.token_hex(8)
    lines = body.split("\n")
    items = []
    for i, kind, v in _usable(lines):
        lines[i] = f"\n{token}n{len(items)}\n"
        items.append((kind, v, i + 1))
    return "\n".join(lines), items, token


def _modes(mode):
    if isinstance(mode, Path):
        return {k: ("frame" if frame_allowed(mode, HOSTS[k]) else "link") for k in KINDS}
    if mode == "wp":
        return {"地図": "link", "動画": "url"}
    if mode in ("frame", "link"):
        return dict.fromkeys(KINDS, mode)
    return {}


def fill(html, items, token, mode="frame", report=None):
    """印の段落を埋め込みに置き換える。report（dict）を渡すと、置いた iframe の開始タグ（frames）と、
    段落として独立していなかったため置けなかった記号の行番号（lost）を入れる"""
    frames, lost = [], []
    if token:
        modes = _modes(mode)
        for n, (kind, v, line) in enumerate(items):
            para = f"<p>{token}n{n}</p>"
            if html.count(para) != 1:
                lost.append(line)
                continue
            how = modes.get(kind)
            block = html_for(kind, v, how) if how else ""
            if how == "frame":
                frames.append(re.search(r"<iframe [^>]*>", block).group(0))
            html = html.replace(para, block)
        html = re.sub(re.escape(token) + r"n\d+", "", html)
    if report is not None:
        report.update(frames=frames, lost=lost)
    return html


def _links(kind, v):
    if kind == "地図":
        return "https://www.google.com/maps/search/?api=1&query=" + quote(v, safe=""), f"Google マップで「{v}」を開く"
    return f"https://www.youtube.com/watch?v={v}", "YouTube で動画を見る"


def html_for(kind, v, how="frame"):
    """1つの記号の HTML。AI の書いた文字は、URL に入れるときは符号化し、title・文字にはエスケープして入れるだけ"""
    e = H.escape
    href, label = _links(kind, v)
    if how == "url":
        return f"<p>{e(href)}</p>"
    link = f'<a href="{e(href)}" target="_blank" rel="noopener">{e(label)}</a>'
    if how == "link":
        return f'<p class="ss-embed-link">{link}</p>'
    if kind == "地図":
        src, title, cls = f"https://www.google.com/maps?q={quote(v, safe='')}&output=embed", f"「{v}」の地図（Google マップ）", "ss-map"
        extra, size = "", "height:360px"
    else:
        src, title, cls = f"https://www.youtube-nocookie.com/embed/{v}", "YouTube の動画", "ss-video"
        # 動画は横幅に合わせた16:9（高さを固定すると、スマホで上下に黒い帯が出る）
        extra, size = ' allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen', "aspect-ratio:16/9;height:auto"
    return (f'<figure class="ss-embed {cls}" style="margin:24px 0">'
            f'<iframe src="{e(src)}" title="{e(title)}" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"{extra} '
            f'style="display:block;width:100%;max-width:100%;{size};border:0;border-radius:12px"></iframe>'
            f'<figcaption style="font-size:.85em;color:#5b6980;margin-top:6px">{link}</figcaption></figure>')


def markdown_links(body):
    """先方が Markdown を変換する形式へ渡す原稿: 記号の行を、前後を空行にした普通のリンクの行にする"""
    if not present(body):
        return body
    lines = body.split("\n")
    for i, kind, v in _usable(lines):
        href, label = _links(kind, v)
        lines[i] = f"\n[{label}]({href})\n"
    return "\n".join(lines)


def problems(body, lost=()):
    """記号の書き違い [("embed", 例)]。例は行番号と理由だけ（住所はお客様の情報になりうる。CI のログは public）。
    lost は段落として独立していなかった記号の行番号（fill の report）"""
    if not present(body):
        return []
    out, n = [], dict.fromkeys(KINDS, 0)
    for i, kind, _v, err in _scan(body.split("\n")):
        if err:
            out.append(("embed", f"本文の{i + 1}行目: {err}"))
        else:
            n[kind] += 1
    out += [("embed", f"{k}が{c}つ（1記事{LIMIT}つまで）") for k, c in n.items() if c > LIMIT]
    out += [("embed", f"本文の{x}行目: 記号が HTML の塊・コードなどの中にある（前後を空行にした単独の行にする）") for x in lost]
    return out


def frame_allowed(dest, host):
    """配信先の CSP（Cloudflare Pages の _headers）が host の iframe を許すか。CSP・枠の読み込み先の項目が無ければ許す。
    許さない行き先に iframe を置くと空の枠が出るので、リンクにする（publish.youtube_blocked と同じ読み方）"""
    for rel in ("_headers", "public/_headers", "static/_headers"):
        f = Path(dest) / rel
        if not f.is_file():
            continue
        m = re.search(r"^[ \t]*Content-Security-Policy:[ \t]*(.+)$", f.read_text(encoding="utf-8", errors="ignore"),
                      re.I | re.M)
        if not m:
            continue
        pol = {p.split()[0].lower(): p.split()[1:] for p in m.group(1).split(";") if p.strip()}
        rule = pol.get("frame-src", pol.get("child-src", pol.get("default-src")))
        if rule is None:
            return True
        for s in rule:
            s = re.sub(r"^https://", "", s.lower()).rstrip("/")
            if s in ("*", "https:", host) or (s.startswith("*.") and host.endswith(s[1:])):
                return True
        return False
    return True
