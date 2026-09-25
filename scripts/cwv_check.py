# -*- coding: utf-8 -*-
"""Core Web Vitals を毎週実測し、閾値を割ったページを知らせる。

**なぜ要るか**: 8.4節に「LCP≤2.5s / INP≤200ms / CLS≤0.1」と書いてあるが、
実測する工程が無かった。速度は順位の前提で、崩れても「何も起きない」形で
現れる（実際、Webフォントで LCP 7〜13秒だった期間があった）。

PageSpeed Insights API（鍵なしで使える。1日の上限は低いので、1サイト2URL・週1回）。
フィールドデータ（実利用者・28日）があればそれを、無ければラボ値を使う。

  python scripts/cwv_check.py            # 3サイト × トップ＋記事1本
  python scripts/cwv_check.py --site ai-lab --url https://ai.7senses.co.jp/lp/
出す印: CWV_OK=yes/no。割った項目は「要対応:」で始める。記録: data/cwv.jsonl
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "data" / "cwv.jsonl"
API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
LIMITS = {"LCP": 2500, "INP": 200, "CLS": 0.1}


def _key():
    """鍵なしは 1分あたりの上限が低く 429 になる。Google Cloud の APIキーで上限が上がる
    （PAGESPEED_API_KEY。無ければ同じプロジェクトの YOUTUBE_API_KEY を試す）"""
    import os
    for k in ("PAGESPEED_API_KEY", "YOUTUBE_API_KEY"):
        v = os.environ.get(k, "")
        if not v:
            env = ROOT / ".env"
            if env.is_file():
                for ln in env.read_text(encoding="utf-8-sig").splitlines():
                    if ln.startswith(k + "="):
                        v = ln.split("=", 1)[1].strip().strip('"')
        if v:
            return v
    return ""


_SA_TOKEN = None


def _sa_token():
    """サービスアカウントの鍵があれば、それで呼ぶ（キーのある別プロジェクトでは API が無効で 403 だった。
    鍵のプロジェクト ss-aio-media では有効にしてある）。PageSpeed の OAuth の範囲は openid"""
    global _SA_TOKEN
    if _SA_TOKEN is None:
        _SA_TOKEN = ""
        sa = ROOT / "indexing-service-account.json"
        if sa.is_file():
            try:
                from google.oauth2 import service_account
                import google.auth.transport.requests as gr
                c = service_account.Credentials.from_service_account_file(str(sa), scopes=["openid"])
                c.refresh(gr.Request())
                _SA_TOKEN = c.token
            except Exception:
                _SA_TOKEN = ""
    return _SA_TOKEN


def measure(url, strategy="mobile"):
    params = {"url": url, "strategy": strategy, "category": "performance"}
    headers = {}
    if _sa_token():
        headers["Authorization"] = f"Bearer {_sa_token()}"
    elif _key():
        params["key"] = _key()
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=headers), timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    out = {"url": url, "strategy": strategy, "source": "lab"}
    field = (d.get("loadingExperience") or {}).get("metrics") or {}
    if field:
        out["source"] = "field"
        out["LCP"] = (field.get("LARGEST_CONTENTFUL_PAINT_MS") or {}).get("percentile")
        out["INP"] = (field.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile")
        cls = (field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") or {}).get("percentile")
        out["CLS"] = cls / 100 if cls is not None else None
    audits = ((d.get("lighthouseResult") or {}).get("audits") or {})
    if out.get("LCP") is None:
        out["LCP"] = (audits.get("largest-contentful-paint") or {}).get("numericValue")
    if out.get("CLS") is None:
        out["CLS"] = (audits.get("cumulative-layout-shift") or {}).get("numericValue")
    if out.get("INP") is None:
        out["INP"] = (audits.get("interaction-to-next-paint") or {}).get("numericValue")  # ラボでは出ないことが多い
    out["score"] = round(((d.get("lighthouseResult") or {}).get("categories") or {})
                         .get("performance", {}).get("score", 0) * 100)
    return out


def sample_urls(cfg):
    """トップと、sitemap の先頭の記事1本"""
    import re
    urls = [f"https://{cfg['domain']}/"]
    try:
        with urllib.request.urlopen(f"https://{cfg['domain']}/sitemap.xml", timeout=30) as r:
            locs = re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8"))
        pre = (cfg.get("url_prefix") or "").strip("/")
        art = [u for u in locs if u.count("/") >= 4 and (not pre or f"/{pre}/" in u)]
        if art:
            urls.append(art[-1])          # 新しめの記事（末尾）
    except Exception:
        pass
    return urls


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    bad, rows = [], []
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        for url in ([a.url] if a.url else sample_urls(cfg)):
            try:
                m = measure(url)
            except Exception as e:
                print(f"   {sid}: 計測できません {url[:50]} ({str(e)[:60]})")
                continue
            rows.append({"date": date.today().isoformat(), "site": sid, **m})
            over = [k for k, lim in LIMITS.items() if m.get(k) is not None and m[k] > lim]
            print(f"   {'×' if over else '○'} [{sid:<9}] {url[:52]:<52} 総合{m['score']:>3} "
                  f"LCP {m.get('LCP') and round(m['LCP'])}ms INP {m.get('INP') and round(m['INP'])}ms "
                  f"CLS {m.get('CLS') and round(m['CLS'], 3)}（{m['source']}）")
            if over:
                bad.append(f"{sid} {url} … " + "・".join(over))
            time.sleep(2)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for b in bad:
        print(f"要対応: 表示速度が基準を割っています: {b}")
    if not rows:
        print("CWV_OK=unknown（計測できませんでした。429=鍵なしの上限、403=Google Cloud で "
              "「PageSpeed Insights API」が未有効。有効にするか PAGESPEED_API_KEY を設定）")
        return 0
    print(f"CWV_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
