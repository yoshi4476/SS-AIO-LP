# -*- coding: utf-8 -*-
"""記事Markdown → 本文HTML の変換（全サイト共通）

build.py（静的HTMLサイト）と publish.py（他サイトへの配信）の両方から使う。
装飾ルールを1か所に集約し、サイトごとに見た目がずれないようにするための共通モジュール。
"""
import re

import markdown


def convert(body: str, toc_depth: str = "2-2"):
    """本文Markdownを (HTML, TOCトークン) に変換する"""
    md = markdown.Markdown(extensions=["tables", "extra", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": toc_depth}})
    html = md.convert(body)
    # テーブルは横スクロール用のラッパで包む（スマホで表が崩れないようにする）
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>")
    # 装飾記法: ==テキスト== → <mark>（黄マーカー）
    html = re.sub(r"==([^=<>\n]+?)==", r"<mark>\1</mark>", html)
    return html, getattr(md, "toc_tokens", [])


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
