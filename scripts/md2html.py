# -*- coding: utf-8 -*-
"""記事Markdown → 本文HTML の変換（全サイト共通）

build.py（静的HTMLサイト）と publish.py（他サイトへの配信）の両方から使う。
装飾ルールを1か所に集約し、サイトごとに見た目がずれないようにするための共通モジュール。
"""
import re

import markdown

import embeds as _embeds


def close_open_divs(body: str) -> str:
    """閉じ忘れた <div> を、その段落の終わりで閉じる。

    Python-Markdown はブロックレベルの生HTMLに出会うと、対応する終了タグが
    現れるまでMarkdownとして扱わない。原稿で <div class="definition-box"> を
    1つ閉じ忘れるだけで、そこから先の見出しも段落も表も変換されないまま
    素通りし、段落の無い1枚の壁のような記事が配信される。

    原稿を直すのが本筋だが、1本の書き損じで記事全体が読めなくなる損失が
    大きいため、変換の手前で閉じておく。タグが揃っている原稿には何も起きない。
    """
    out = body
    for _ in range(20):
        depth, opened_at = 0, None
        for m in re.finditer(r"<(/?)div\b[^>]*>", out):
            if m.group(1):
                depth -= 1
            else:
                if depth == 0:
                    opened_at = m.start()
                depth += 1
        if depth <= 0 or opened_at is None:
            return out
        end = out.find("\n\n", opened_at)
        out = out + "</div>" if end == -1 else out[:end] + "</div>" + out[end:]
    return out


# 変換されずに残ったMarkdownの痕跡。配信前の検査に使う
_RAW_MARKDOWN = [
    (re.compile(r"^#{2,3} \S", re.M), "見出し (## …)"),
    (re.compile(r"\*\*[^*\n]+\*\*"), "強調 (**…**)"),
    (re.compile(r"^\|.+\|$", re.M), "表 (| … |)"),
    (re.compile(r"\[[^\]\n]+\]\(https?:"), "リンク ([…](…))"),
]


def raw_markdown_left(html: str):
    """変換されずに残ったMarkdownの種類を返す。空リストなら正常"""
    return [name for pat, name in _RAW_MARKDOWN if pat.search(html)]


def convert(body: str, toc_depth: str = "2-2", embeds="frame", report=None):
    """本文Markdownを (HTML, TOCトークン) に変換する。

    地図・動画の記号（@[地図](住所)・@[動画](id) の1行）は、変換の後で決まった形の埋め込みにする（scripts/embeds.py）。
    embeds はその出し方（"frame"・配信先の作業コピーの Path・"link"・"wp"・None）。report は embeds.fill へ渡す"""
    body, items, token = _embeds.mark(close_open_divs(body))
    md = markdown.Markdown(extensions=["tables", "extra", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": toc_depth}})
    html = md.convert(body)
    # テーブルは横スクロール用のラッパで包む（スマホで表が崩れないようにする）
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>")
    # 装飾記法: ==テキスト== → <mark>（黄マーカー）
    html = re.sub(r"==([^=<>\n]+?)==", r"<mark>\1</mark>", html)
    return _embeds.fill(html, items, token, embeds, report), getattr(md, "toc_tokens", [])


def markdown_links(body: str) -> str:
    """先方が Markdown を変換する形式（external-md）へ渡す原稿: 地図・動画の記号の行を普通のリンクの行にする"""
    return _embeds.markdown_links(body)


def plain_text(html: str) -> str:
    """タグ・空白を除いた実文字数の判定用"""
    return re.sub(r"\s", "", re.sub(r"<[^>]+>", "", html))


def reading_minutes(html: str, chars_per_minute: int = 600) -> int:
    return max(1, round(len(plain_text(html)) / chars_per_minute))


def extract_faq(body: str):
    """本文のFAQ（<details><summary>…）を抜き出す。FAQPage Schema と本文の一致を保証するため"""
    pairs = re.findall(
        r"<details><summary>(.*?)</summary>\s*<p[^>]*>(.*?)</p>\s*</details>", body, re.S)
    return [{"q": re.sub(r"<[^>]+>", "", q).strip(),
             "a": re.sub(r"<[^>]+>", "", a).strip()} for q, a in pairs]
