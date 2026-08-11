# -*- coding: utf-8 -*-
"""本番サイトが手元のビルドと一致しているかを見る（デプロイの取りこぼし検知）

使い方: python scripts/deploy_check.py

ワークフローが成功していても、デプロイだけ落ちていることがある。
実際、wrangler の依存パッケージの公開遅れでデプロイが3回とも失敗し、
記事はコミットされているのに本番が数日古いままだった。
手元の sitemap と本番の sitemap を突き合わせて、その状態を見つける。
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"}
SITE = "https://ai.7senses.co.jp"


def urls(text):
    return {u.strip() for u in re.findall(r"<loc>(.*?)</loc>", text)}


def main():
    local = ROOT / "site" / "sitemap.xml"
    if not local.is_file():
        raise SystemExit("site/sitemap.xml がありません。先に build.py を実行してください")
    mine = urls(local.read_text(encoding="utf-8"))

    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"{SITE}/sitemap.xml", headers=UA), timeout=25) as r:
            live = urls(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"本番のsitemapを取得できません（{e}）")
        print("DEPLOY_OK=no")
        sys.exit(1)

    missing = sorted(mine - live)      # 手元にあるのに本番に無い＝未デプロイ
    extra = sorted(live - mine)        # 本番だけにある＝取り下げが未反映

    print(f"  手元 {len(mine)}件 / 本番 {len(live)}件")
    if missing:
        print(f"  未デプロイ {len(missing)}件:")
        for u in missing[:10]:
            print(f"      {u.replace(SITE, '')}")
    if extra:
        print(f"  本番にだけ残っている {len(extra)}件:")
        for u in extra[:10]:
            print(f"      {u.replace(SITE, '')}")

    # URL数が同じでも中身が古いことがある。実際 /lab/ は件数一致のまま
    # 数日前の内容が出ていた。主要ページの本文量で照合する。
    stale = []
    for rel in ("", "lab/", "blog/"):
        f = ROOT / "site" / rel / "index.html"
        if not f.is_file():
            continue
        mine_html = f.read_text(encoding="utf-8")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(f"{SITE}/{rel}", headers=UA), timeout=25) as r:
                live_html = r.read().decode("utf-8", "ignore")
        except Exception:
            continue
        # 差が5%を超えるなら、別バージョンが出ていると見なす
        if abs(len(live_html) - len(mine_html)) > max(400, len(mine_html) * 0.05):
            stale.append((rel or "/", len(mine_html), len(live_html)))
    if stale:
        print("  中身が古いページ:")
        for rel, a, b in stale:
            print(f"      /{rel}  手元 {a:,}バイト / 本番 {b:,}バイト")

    if missing or stale:
        print("\nDEPLOY_OK=no（本番が手元より古い状態です）")
        print("  対処: Deploy ワークフローを手動実行するか、次のpushを待つ")
        sys.exit(1)
    print("\nDEPLOY_OK=yes（本番と手元が一致しています）")


if __name__ == "__main__":
    main()
