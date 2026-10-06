# -*- coding: utf-8 -*-
"""お客様の社を検索エンジンへつなぐ（最初の接続の点検と、配信と一緒に置くファイル）

運用者の方針（2026-10-06）: どの納品方式でも、最初の接続が済んだ後は人の手なしで全機能が動く。
公開直後の通知（IndexNow・Bing・Indexing API）は、以前は自社の AI集客ラボの枠だけで動いていた。
お客様の社で通知が届くには、次の3つが要る。

  IndexNow     鍵ファイル（<鍵>.txt）がドメインの直下にあること
               → 配信のたびに置く（place。Git の社は配信先リポジトリ・FTP の社はサーバーの直下。
                 WordPress は橋渡しの mu-plugin が返す: wp_bridge.push_settings）
  Bing         当社の Bing アカウントにドメインを足し、所有権を確かめること
               → ヒアリングシートで同意（bing_consent）を取った社だけ。確認ファイル BingSiteAuth.xml を
                 配信のたびに置き、本番に出たら bing_webmaster.connect が VerifySite で確かめる
  Indexing API 当社のサービスアカウントが Search Console のオーナーであること
               → 先方にお願いするしかない（ここでは送らずに「要対応」を出す: notify_indexing.gsc_owner_ok）

  python scripts/search_connect.py --check     # お客様の社の接続の点検（週次 findings・ヒアリングの後）

印: SEARCH_CONNECT_OK=yes / no（要対応あり）/ unset（お客様の社が無い）。終了コードは常に0（8.7節）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 配信先リポジトリで公開されるフォルダの候補（publish._public_file と同じ並び）
ROOTS = ("", "public", "static", "site")
MARKERS = ("index.html", "robots.txt", "sitemap.xml", "llms.txt", "favicon.ico")
# 直下に置くファイルを publish.py が扱う方式（自前ビルドは site/ に、WordPress は橋渡しが返す）
PLACE_TYPES = ("external-md", "external-html", "nextjs-json", "ftp", "zip")


def public_root(cfg, dest: Path):
    """配信先の作業場所の中で、ドメインの直下として公開されるフォルダ"""
    if cfg.get("public_dir") is not None:
        return dest / cfg["public_dir"]
    for rel in ROOTS:
        if any((dest / rel / m).is_file() for m in MARKERS):
            return dest / rel
    return dest / "public" if (dest / "public").is_dir() else dest


def files_for(cfg, current_auth=None):
    """直下に置くファイル {名前: 中身}。お客様の社だけ（自社の各サイトは各自の仕組みで置いてある）。
    current_auth は今ある BingSiteAuth.xml の中身（先方が自分の Bing アカウントで置いた分を消さないため）。
    None なら本番から読む"""
    import sites as S
    if cfg.get("type") not in PLACE_TYPES or not S.is_client(cfg["id"]):
        return {}
    import notify_indexnow as NI
    import bing_webmaster as BW
    out = {}
    key = NI.find_key(NI.load_env())
    if key:
        out[f"{key}.txt"] = key
    code = BW.auth_code(cfg)
    if code:
        cur = BW.live_auth(cfg["domain"]) if current_auth is None else current_auth
        out[BW.SITE_AUTH] = BW.site_auth_xml([code], cur)
    return out


def place(cfg, dest):
    """publish.py が配信のたびに呼ぶ。中身が変わるファイルだけ書き、書いたものを返す（配信の一覧へ足す）"""
    import bing_webmaster as BW
    root = public_root(cfg, Path(dest))
    auth = root / BW.SITE_AUTH
    files = files_for(cfg, auth.read_text(encoding="utf-8") if auth.is_file() else None)
    written = []
    for name, text in files.items():
        p = root / name
        if p.is_file() and p.read_text(encoding="utf-8") == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        written.append(p)
    return written


def check(cfgs=None):
    """お客様の社の最初の接続のうち、先方にお願いすることが残っているか"""
    import sites as S
    import notify_indexing as NX
    cfgs = S.load_all() if cfgs is None else cfgs
    clients = {sid: c for sid, c in cfgs.items() if S.is_client(sid)}
    if not clients:
        print("SEARCH_CONNECT_OK=unset（お客様の社がありません）")
        return []
    owners = NX.owner_domains() if NX.SA_PATH.is_file() else None
    bad = []
    for sid, c in clients.items():
        g = NX.gsc_owner_ok(c, owners)
        b = c.get("bing_consent") is True
        print(f"  {sid}: Search Console のオーナー {'済' if g else '未'} / Bing の同意 {'可' if b else '無し（対象外）'}"
              f" / 方式 {c.get('type')}")
        if not g:
            bad.append(NX.gsc_owner_todo(c))
        if c.get("type") == "zip":
            bad.append(f"要対応: {c.get('name', sid)} は zip（新規受付なし）です。FTP の接続情報か Git の配信先をいただき、"
                       "ftp か Git の方式へ切り替えてください（先方が毎回上げる作業が残っています）")
    for line in dict.fromkeys(bad):
        print(line)
    print("SEARCH_CONNECT_OK=" + ("no" if bad else "yes"))
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        check()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
