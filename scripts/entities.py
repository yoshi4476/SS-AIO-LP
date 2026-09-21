# -*- coding: utf-8 -*-
"""記事が扱う「実体」を、公式の場所へ結び付ける（構造化データの about / mentions）。

AI検索は「この記事は何について書いているか」を、文章だけでなく実体の一致で判断する。
「IT導入補助金」と書くだけでなく、事務局の公式URLと結んでおくと、同じ実体を扱う
他の情報と束ねて扱われ、専門性（knowsAbout）の裏付けにもなる。

URLは全て実在を確かめたもの（2026-09-22 に取得）。架空の実体や、存在しないページには結ばない。
3サイト共通（build.py・publish.py・コーポレートの entities.json が同じ表を使う）。
"""
import json
import re

ENTITIES = [
    {"name": "IT導入補助金", "sameAs": "https://it-shien.smrj.go.jp/", "aliases": ["IT導入補助金"]},
    {"name": "ものづくり補助金", "sameAs": "https://portal.monodukuri-hojo.jp/", "aliases": ["ものづくり補助金"]},
    {"name": "小規模事業者持続化補助金", "sameAs": "https://s23.jizokukahojokin.info/", "aliases": ["持続化補助金"]},
    {"name": "事業再構築補助金", "sameAs": "https://jigyou-saikouchiku.go.jp/", "aliases": ["事業再構築補助金"]},
    {"name": "中小企業庁", "sameAs": "https://www.chusho.meti.go.jp/", "aliases": ["中小企業庁"]},
    {"name": "gBizID", "sameAs": "https://gbiz-id.go.jp/", "aliases": ["gBizID", "GビズID"]},
    {"name": "Googleビジネスプロフィール", "sameAs": "https://www.google.com/business/",
     "aliases": ["Googleビジネスプロフィール", "Google Business Profile", "ビジネスプロフィール"]},
    {"name": "Google AI Overview", "sameAs": "https://support.google.com/websearch/answer/14901683",
     "aliases": ["AI Overview", "AIオーバービュー", "AIによる概要"]},
    {"name": "ChatGPT", "sameAs": "https://ja.wikipedia.org/wiki/ChatGPT", "aliases": ["ChatGPT"]},
    {"name": "Perplexity", "sameAs": "https://www.perplexity.ai/", "aliases": ["Perplexity"]},
    {"name": "Gemini", "sameAs": "https://gemini.google.com/", "aliases": ["Gemini"]},
    {"name": "検索エンジン最適化（SEO）",
     "sameAs": "https://ja.wikipedia.org/wiki/%E6%A4%9C%E7%B4%A2%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%B3%E6%9C%80%E9%81%A9%E5%8C%96",
     "aliases": ["SEO", "検索エンジン最適化"]},
    {"name": "ビジネス・プロセス・アウトソーシング（BPO）",
     "sameAs": "https://ja.wikipedia.org/wiki/%E3%83%93%E3%82%B8%E3%83%8D%E3%82%B9%E3%83%97%E3%83%AD%E3%82%BB%E3%82%B9%E3%82%A2%E3%82%A6%E3%83%88%E3%82%BD%E3%83%BC%E3%82%B7%E3%83%B3%E3%82%B0",
     "aliases": ["BPO", "経理代行", "経理アウトソーシング"]},
    {"name": "インボイス制度", "sameAs": "https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice.htm",
     "aliases": ["インボイス制度", "適格請求書"]},
    {"name": "電子帳簿保存法", "sameAs": "https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/",
     "aliases": ["電子帳簿保存法", "電帳法"]},
    {"name": "freee", "sameAs": "https://www.freee.co.jp/", "aliases": ["freee"]},
]

# 会社の専門領域（Organization / Person の knowsAbout）。実際に事業として提供しているものだけ
KNOWS_ABOUT = ["MEO（マップ検索最適化）", "AIO（AI検索最適化）", "LLMO（大規模言語モデル最適化）", "SEO",
               "Googleビジネスプロフィール運用", "店舗集客", "AI導入支援", "IT導入補助金", "ものづくり補助金",
               "小規模事業者持続化補助金", "経理BPO"]

MAX_ABOUT, MAX_MENTIONS = 3, 6


def _hit(alias, text):
    # 英字は語の途中に当てない（"SEO" が "SEOUL" に当たる等）。日本語はそのまま
    if re.fullmatch(r"[A-Za-z ]+", alias):
        return re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", text, re.I) is not None
    return alias in text


def find(text):
    """文中に出てくる実体（表の順）"""
    text = text or ""
    return [e for e in ENTITIES if any(_hit(a, text) for a in e["aliases"])]


def thing(e):
    return {"@type": "Thing", "name": e["name"], "sameAs": e["sameAs"]}


def about_and_mentions(head_text, body_text):
    """題名・狙う語に出る実体は about、本文だけに出る実体は mentions"""
    about = [thing(e) for e in find(head_text)][:MAX_ABOUT]
    names = {a["name"] for a in about}
    mentions = [thing(e) for e in find(body_text) if e["name"] not in names][:MAX_MENTIONS]
    return about, mentions


def export_json():
    """コーポレート（Next.js）が同じ表を使うための書き出し"""
    return json.dumps({"entities": ENTITIES, "knowsAbout": KNOWS_ABOUT}, ensure_ascii=False, indent=2) + "\n"
