# -*- coding: utf-8 -*-
"""先方のURLを入れるだけで、ヒアリングシートの下書きを作る（先方は確かめて足すだけ）。

**なぜ要るか**: ヒアリングシートは100項目近くあり、先方が白紙から埋めると時間がかかり、
空欄のまま戻ってくる。会社名・住所・電話・サービス・既存ページの題名などは、先方のサイトに
すでに書いてある。それを拾って下書きにする。

**拾うのはサイトに書いてあることだけ**（推測で埋めない）。拾った欄には「サイトから転記」と
注記を付け、先方に確かめてもらう。一次情報・著者・狙わない語など、サイトに無い欄は空のまま残す。

  python scripts/intake_from_url.py https://example.co.jp/
  python scripts/intake_from_url.py https://example.co.jp/ --industry restaurant
出力: intake/下書き/<ドメイン>_ヒアリング下書き.xlsx（intake/ 直下ではないので、自動登録には回らない）
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "intake" / "下書き"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-intake/1.0; +https://ai.7senses.co.jp/)"}
SUB = ("company", "about", "corporate", "profile", "gaiyou", "outline", "service", "services", "menu", "access")


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.read(600_000).decode(r.headers.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return ""


def text(html):
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def jsonld(html):
    out = []
    for s in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            d = json.loads(s)
        except ValueError:
            continue
        for x in (d.get("@graph", [d]) if isinstance(d, dict) else d):
            if isinstance(x, dict):
                out.append(x)
    return out


def gather(base):
    base = base.rstrip("/") + "/"
    pages = {base: fetch(base)}
    for s in SUB:
        u = urllib.parse.urljoin(base, s + "/")
        h = fetch(u)
        if h and len(h) > 2000:
            pages[u] = h
    got, src = {}, {}

    def put(k, v, where):
        v = re.sub(r"\s+", " ", str(v or "")).strip()
        if v and k not in got:
            got[k], src[k] = v, where

    for u, h in pages.items():
        for x in jsonld(h):
            t = str(x.get("@type", ""))
            if any(k in t for k in ("Organization", "LocalBusiness", "Restaurant", "Store", "Clinic", "Dentist")):
                put("company.name", x.get("name"), u)
                put("company.tel", x.get("telephone"), u)
                a = x.get("address") or {}
                if isinstance(a, dict):
                    put("company.postal", a.get("postalCode"), u)
                    put("company.address", " ".join(str(a.get(k, "")) for k in ("addressRegion", "addressLocality", "streetAddress")), u)
                oh = x.get("openingHours")
                if oh:
                    put("company.hours", " / ".join(oh) if isinstance(oh, list) else oh, u)
        t = text(h)
        m = re.search(r"〒\s?(\d{3}-?\d{4})\s*([^\s　]{2,40}[都道府県][^\s　]{2,60})", t)
        if m:
            put("company.postal", m.group(1), u)
            put("company.address", m.group(2), u)
        m = re.search(r"(?:TEL|Tel|電話|℡)[:：\s]*((?:0\d{1,4})[-‐－ ]?\d{1,4}[-‐－ ]?\d{3,4})", t)
        if m:
            put("company.tel", m.group(1), u)
        # 代表者名: 役職の直後の人名だけ。地名（「代表取締役 … 大阪」）を拾った実例があるので、
        # 地名・組織の語で終わるものは捨てる
        for m in re.finditer(r"(?:代表取締役(?:社長)?|代表者|院長|店長|オーナー)[:：\s　]*([一-龥]{1,4}[\s　]?[一-龥ぁ-ん]{1,4})", t):
            nm = m.group(1).strip()
            if re.search(r"(都|道|府|県|市|区|町|村|大阪|東京|京都|株式|会社|法人|医院|店|代表|取締|社長|役員|院長)", nm) or len(nm.replace(" ", "").replace("　", "")) < 3:
                continue
            put("company.ceo", nm, u)
            break
        m = re.search(r"(?:営業時間|診療時間)[:：\s]*([^。]{4,60})", t)
        if m:
            # 会社概要の表は「営業時間 … 取引銀行 …」と続くので、次の見出し語で切る
            hrs = re.split(r"\s(?:取引|事業|設立|所在地|資本金|代表|電話|TEL|定休|アクセス|住所)", m.group(1))[0]
            put("company.hours", hrs, u)
        m = re.search(r"(?:設立|創業)[:：\s]*(\d{4}年(?:\d{1,2}月)?)", t)
        if m:
            put("company.founded", m.group(1), u)
    home = pages[base]
    og = re.search(r'<meta[^>]+property="og:site_name"[^>]+content="([^"]+)"', home)
    title = re.search(r"<title>(.*?)</title>", home, re.S)
    desc = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', home)
    put("name", (og.group(1) if og else (title.group(1).split("|")[0].split("｜")[0] if title else "")), base)
    put("company.name", og.group(1) if og else "", base)
    put("domain", urllib.parse.urlparse(base).netloc, base)
    put("theme", desc.group(1) if desc else "", base)
    heads = []
    for u, h in pages.items():
        heads += [re.sub(r"<[^>]+>|\s+", " ", x).strip() for x in re.findall(r"<h[12][^>]*>(.*?)</h[12]>", h, re.S)]
    heads = [x for x in dict.fromkeys(heads) if 2 <= len(x) <= 40][:12]
    put("service.list", "\n".join(heads), "見出し（h1/h2）")
    # 既にある記事・ページの題名（食い合いを避ける材料）
    sm = fetch(urllib.parse.urljoin(base, "sitemap.xml"))
    locs = re.findall(r"<loc>(.*?)</loc>", sm)[:40]
    if locs:
        put("asset.articles", f"sitemap に {len(re.findall(r'<loc>', sm))} ページ（例: " + "、".join(l.replace(base, "/") for l in locs[1:9]) + "）", "sitemap.xml")
    put("asset.site", base, base)
    return got, src


def main():
    import client_intake as C
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--industry", default="")
    a = ap.parse_args()
    got, src = gather(a.url)
    OUT.mkdir(parents=True, exist_ok=True)
    dom = urllib.parse.urlparse(a.url).netloc or "site"
    path = OUT / f"{dom}_ヒアリング下書き.xlsx"
    C.make_sheet(path, a.industry)
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill
    wb = load_workbook(path)
    ws = wb.active
    n = 0
    for row in range(C.SAMPLE_ROW, ws.max_row + 1):
        key = ws.cell(row=row, column=6).value
        if key in got:
            ws.cell(row=row, column=2, value=got[key])
            ws.cell(row=row, column=2).fill = PatternFill("solid", start_color="FFF4CC")
            note = ws.cell(row=row, column=4).value or ""
            ws.cell(row=row, column=4, value=f"【サイトから転記・要確認】{src[key]}\n{note}")
            n += 1
    wb.save(path)
    print(f"■ {a.url}: {n}欄を下書きしました（黄色の欄は先方に確かめてもらう）")
    for k, v in got.items():
        print(f"   {k:<18} {v[:60]}")
    print(f"   → {path}")
    print("INTAKE_DRAFT_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
