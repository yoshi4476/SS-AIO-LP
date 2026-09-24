# -*- coding: utf-8 -*-
"""配信先3サイトの生存を毎日見る: HTTPS証明書の期限と、sitemap の 404 率。

**なぜ要るか**: 証明書切れも 404 の増加も「何も起きない」形で現れる。
AIクローラーの遮断（ai_crawler_check）と同じ枠で、毎日いちばん先に見る。

  python scripts/cert_check.py            # 3サイト
  python scripts/cert_check.py --sample 30
出す印: CERT_OK=yes/no。問題は「要対応:」で始める（selfheal の日次が findings に載せる）
"""
import argparse
import random
import re
import socket
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
WARN_DAYS = 30
MAX_404_RATE = 0.02
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; +https://ai.7senses.co.jp/)"}


def cert_days(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as ss:
        exp = ss.getpeercert()["notAfter"]
    dt = datetime.strptime(exp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (dt - datetime.now(timezone.utc)).days


def status(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20, help="sitemap から何URL見るか")
    a = ap.parse_args()
    bad = []
    for sid, cfg in S.load_all().items():
        host = cfg["domain"]
        try:
            days = cert_days(host)
            print(f"   [{sid:<9}] 証明書 残り{days}日")
            if days < WARN_DAYS:
                bad.append(f"{host} の証明書が残り{days}日")
        except Exception as e:
            bad.append(f"{host} の証明書を確認できません（{str(e)[:50]}）")
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{host}/sitemap.xml", headers=UA), timeout=30) as r:
                locs = re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8"))
        except Exception as e:
            bad.append(f"{host} の sitemap.xml を読めません（{str(e)[:50]}）")
            continue
        random.seed(datetime.now().strftime("%Y%m%d"))
        pick = random.sample(locs, min(a.sample, len(locs))) if locs else []
        codes = [status(u) for u in pick]
        n404 = sum(1 for c in codes if c in (404, 410, 0))
        rate = n404 / max(len(codes), 1)
        print(f"   [{sid:<9}] sitemap {len(locs)}件のうち{len(pick)}件を確認 → 404/不達 {n404}件（{rate * 100:.0f}%）")
        if pick and rate > MAX_404_RATE:
            miss = [u for u, c in zip(pick, codes) if c in (404, 410, 0)][:3]
            bad.append(f"{host} の sitemap に 404 が{n404}/{len(pick)}件（例: {', '.join(miss)}）")
    for b in bad:
        print(f"要対応: {b}")
    print(f"CERT_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
