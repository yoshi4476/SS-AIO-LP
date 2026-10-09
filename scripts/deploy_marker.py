# -*- coding: utf-8 -*-
"""Cloudflare Pages へ送る中身（site/ と functions/）の指紋。本番と同じ中身なら送り出しを省く（deploy.yml）。

送り出しは1回あたり約30秒（wrangler の起動・鍵の設定・アップロード）。原稿にもサイトにも効かない push
（ページを作らない道具だけの変更など）でも毎回送っていた（2026-10-03〜09 の147回のうち68回は新しいファイルが0本）。
本番に置いた指紋（/deploy-hash.txt）と、いま作った中身の指紋が同じときだけ省く。
指紋が違う・本番の指紋を読めない・本番に指紋が無い（指紋を置かない工程が送った版）ときは必ず送る。
間違えるなら「送る」向きにだけ間違える（省いて古い版を残すことはしない）。

指紋は送るファイルの全部（相対パスと中身の sha256）と、送り出しに使う wrangler の版から作る。
指紋のファイル自身は数えない。ほかのワークフローの送り出し（記事の枠など）が指紋を置かなくても、
本番の指紋が無くなるだけで、次の deploy.yml は送る（省かない）。

    python scripts/deploy_marker.py --hash --salt wrangler@4.121.0
    python scripts/deploy_marker.py --same https://ss-aio-lp.pages.dev --salt wrangler@4.121.0   SAME=yes|no
    python scripts/deploy_marker.py --write --salt wrangler@4.121.0                              site/ に指紋を置く
"""
import argparse
import hashlib
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "deploy-hash.txt"
DIRS = ("site", "functions")


def fingerprint(root=ROOT, salt=""):
    h = hashlib.sha256()
    h.update(f"salt\0{salt}\0".encode("utf-8"))
    for d in DIRS:
        base = root / d
        if not base.is_dir():
            h.update(f"missing\0{d}\0".encode("utf-8"))
            continue
        files = sorted(p for p in base.rglob("*") if p.is_file())
        for p in files:
            rel = p.relative_to(root).as_posix()
            if rel == f"site/{NAME}":
                continue
            fh = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    fh.update(chunk)
            h.update(f"{rel}\0{fh.hexdigest()}\n".encode("utf-8"))
    return h.hexdigest()


def live(base, timeout=15):
    """本番に置いた指紋。読めなければ空（＝送る）"""
    url = f"{base.rstrip('/')}/{NAME}?r={uuid.uuid4().hex}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (deploy_marker)",
                                                   "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(200).decode("utf-8", "replace").strip()
    except Exception as e:
        if getattr(e, "code", None) == 404:
            return "", "本番に指紋がありません（指紋を置かない工程が送った版）"
        return "", f"本番の指紋を読めません（{type(e).__name__}）"
    if len(body) != 64 or any(c not in "0123456789abcdef" for c in body):
        return "", "本番に指紋がありません（指紋を置かない工程が送った版）"
    return body, ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash", action="store_true")
    ap.add_argument("--same", metavar="BASE_URL")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--salt", default="")
    a = ap.parse_args(argv)
    if a.hash:
        print(fingerprint(salt=a.salt))
        return 0
    if a.same:
        mine = fingerprint(salt=a.salt)
        got, why = live(a.same)
        if got and got == mine:
            print(f"本番と同じ中身です（指紋 {mine[:12]}）")
            print("SAME=yes")
        else:
            print(why or f"中身が変わりました（本番 {got[:12]} → 今回 {mine[:12]}）")
            print("SAME=no")
        return 0
    if a.write:
        mine = fingerprint(salt=a.salt)
        (ROOT / "site" / NAME).write_text(mine, encoding="utf-8")
        print(f"指紋を置きました: site/{NAME}（{mine[:12]}）")
        return 0
    ap.error("--hash / --same / --write のどれかを指定してください")


if __name__ == "__main__":
    sys.exit(main())
