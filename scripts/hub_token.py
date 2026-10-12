# -*- coding: utf-8 -*-
"""記事を書く AI に渡す、管制塔（automation/gas/hub.gs）の使い捨ての通行証。

AI 用の合言葉（HUB_AGENT_SECRET）をそのまま渡すと、全社（お客様の社を含む）の狙う語の台帳に書けて、語の一覧も読めた。
AI は外の文章を読むので、仕込まれた指示に従えば別のお客様の語を読み出せる。お客様どうしの守秘のため、その回の社だけに
効き、数時間で切れる通行証に置き換える（2026-10-12）。合言葉は署名の鍵としてだけ使い、AI には渡さない。

形: v1~<書ける社,…>~<読める社,…>~<期限の epoch 秒>~<署名>
  署名 = HMAC-SHA256（鍵 = HUB_AGENT_SECRET、本文 = 署名の前までの "v1~…~期限"）の16進小文字
  社は管制塔の台帳の「サイト」列と同じ社の id（sites.py の id）。hub.gs の agentPass_ と verify は同じ結果を返す

  python scripts/hub_token.py --scope own --out <ファイル>
      自社の回: 書ける社＝読める社＝自社の社
  python scripts/hub_token.py --scope <公開の id か社の id> --out <ファイル> [--hours 8]
      お客様の回: 書ける社＝その社（同じ組の社があればそれも）、読める社＝書ける社＋自社の社

鍵は環境変数 HUB_AGENT_SECRET だけから読む（無ければ何も書かずに HUB_TOKEN=none・終了コード0）。
社が見つからなければ書かずに HUB_TOKEN=none・終了コード1。標準出力に通行証も社の id も出さない
（印 HUB_TOKEN=ok（書ける社 N・読める社 M）だけ。CI では通行証を ::add-mask:: で伏せる）。ファイルは 0600 で書く。
"""
import argparse
import hashlib
import hmac
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

VERSION = "v1"
HOURS = 8
# 鍵が空・短いまま配られると誰でも署名を作れる。hub.gs の AGENT_KEY_MIN と同じ値
KEY_MIN = 16
MAX_LEN = 4000
# 区切りの ~ と , を社の id に入れさせない。数字は JS の \d と同じ半角だけ（Python の \d は全角も通す）
SITE = re.compile(r"[A-Za-z0-9_-]{1,64}")
EXP = re.compile(r"[0-9]{1,12}")
SIG = re.compile(r"[0-9a-f]{64}")


def _ids(sites):
    out = []
    for s in sites or []:
        s = str(s)
        if not SITE.fullmatch(s):
            raise ValueError("社の id に使えない文字があります")
        if s not in out:
            out.append(s)
    return out


def _sign(body, secret):
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def mint(write_sites, read_sites, hours=HOURS, secret=None, now=None):
    """通行証を作る。読める社には書ける社を必ず含める"""
    secret = os.environ.get("HUB_AGENT_SECRET", "") if secret is None else secret
    if len(secret) < KEY_MIN:
        raise ValueError(f"鍵が短すぎます（{KEY_MIN}文字以上）")
    if not hours > 0:
        raise ValueError("期限は0より後にしてください")
    w = _ids(write_sites)
    r = _ids(list(w) + list(read_sites or []))
    exp = int((time.time() if now is None else now) + hours * 3600)
    body = "~".join((VERSION, ",".join(w), ",".join(r), str(exp)))
    tok = body + "~" + _sign(body, secret)
    if len(tok) > MAX_LEN:
        raise ValueError("社が多すぎて通行証が長くなりすぎます")
    return tok


def verify(token, secret, now=None):
    """hub.gs の agentPass_ と同じ照合。(通るか, 書ける社, 読める社＝書ける社を含む)"""
    no = (False, [], [])
    if not isinstance(token, str) or len(token) > MAX_LEN or not isinstance(secret, str) or len(secret) < KEY_MIN:
        return no
    f = token.split("~")
    if len(f) != 5 or f[0] != VERSION or not EXP.fullmatch(f[3]) or not SIG.fullmatch(f[4]):
        return no
    if int(f[3]) <= (time.time() if now is None else now):
        return no
    w = f[1].split(",") if f[1] else []
    r = f[2].split(",") if f[2] else []
    if not all(SITE.fullmatch(s) for s in w + r):
        return no
    if not hmac.compare_digest(_sign("~".join(f[:4]), secret), f[4]):
        return no
    return True, w, r + [s for s in w if s not in r]


def scope_sites(scope):
    """(書ける社, 読める社)。社が見つからなければ None"""
    import sites as S
    all_ = S.load_all()
    own = S.own_ids()
    if scope == "own":
        return list(own), list(own)
    sid = S.resolve(scope)
    if sid not in all_:
        return None
    client = S.is_client(sid)

    def grp(s):
        # 範囲（private_store.scope・agent_guard._scope_sites・agent_work）と同じ組の決め方にそろえる（設定の group は見ない）
        return S.group_key(s)
    # お客様の組に自社の社を入れない（設定の group を誤って書いても、自社の台帳に書ける通行証にしない）
    w = [s for s in all_ if S.is_client(s) == client and grp(s) == grp(sid)]
    return w, w + [s for s in own if s not in w]


def _write(path, tok):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(tok)
    # 既にあったファイルは os.open の mode が効かない
    os.chmod(path, 0o600)


def main(argv=None):
    ap = argparse.ArgumentParser(description="記事を書く AI に渡す、管制塔の使い捨ての通行証を作る")
    ap.add_argument("--scope", required=True, help="own・公開の id・社の id")
    ap.add_argument("--out", required=True, help="通行証を書くファイル（0600）")
    ap.add_argument("--hours", type=float, default=HOURS)
    a = ap.parse_args(argv)
    secret = os.environ.get("HUB_AGENT_SECRET", "").replace("﻿", "").strip().strip("'\"")
    if not secret:
        print("HUB_AGENT_SECRET が無いため通行証を作りません（AI は管制塔の台帳に触れません）")
        print("HUB_TOKEN=none")
        return 0
    if len(secret) < KEY_MIN:
        print(f"HUB_AGENT_SECRET が短すぎるため通行証を作りません（{KEY_MIN}文字以上。管制塔も短い鍵の署名は通しません）")
        print("HUB_TOKEN=none")
        return 0
    got = scope_sites(a.scope)
    if not got or not got[0]:
        print("通行証を作れません（社が見つかりません。非公開のデータが取れているかを確かめてください）")
        print("HUB_TOKEN=none")
        return 1
    w, r = got
    tok = mint(w, r, hours=a.hours, secret=secret)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{tok}", flush=True)
    _write(Path(a.out), tok)
    print(f"HUB_TOKEN=ok（書ける社 {len(w)}・読める社 {len(r)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
