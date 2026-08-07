# -*- coding: utf-8 -*-
"""3サイトの会社表記（NAP）と法人番号が揃っているかを見る

使い方: python scripts/nap_check.py

AI検索は「同じ事実が複数の外部サイトで一致しているか」で確信度を上げる。
表記がぶれた言及を増やすほど確信度は下がるため、公開中の実物を突き合わせる。
同名の別法人（東京都目黒区）があるので、法人番号の掲載を必須にしている。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"}
P = json.loads((ROOT / "data" / "company_profile.json").read_text(encoding="utf-8"))


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def main():
    ng = []
    num = P["corporate_number"]
    for sid, url in P["sites"].items():
        h = get(url)
        about = get(url.rstrip("/") + ("/company" if sid == "corporate" else "/about/"))
        both = h + about
        print(f"■ {sid}（{url}）")
        checks = [
            ("法人番号", num in both),
            ("正しい商号", P["name"] in both),
            ("電話番号", P["tel"].replace("-", "") in both.replace("-", "")),
            ("所在地", "東成区" in both),
            ("法人番号ページへのsameAs", "houjin-bangou.nta.go.jp" in both),
            ("旧サイト(www)への言及なし", "www.7senses.co.jp" not in both),
            ("逆順の商号なし", "株式会社セブンセンシズ" not in both),
        ]
        for name, ok in checks:
            print(f"   {'OK ' if ok else '要修正'} {name}")
            if not ok:
                ng.append(f"{sid}: {name}")
        print()

    if ng:
        print("NAP_OK=no")
        for x in ng:
            print(f"  - {x}")
        sys.exit(1)
    print("NAP_OK=yes（3サイトとも表記が揃っています）")


if __name__ == "__main__":
    main()
