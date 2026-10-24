# -*- coding: utf-8 -*-
"""管制塔から、どの方式の社でもサイトの構成（ナビ・トップ・固定ページ・CSS・メニュー・配色）を変える入口。

配信方式ごとに道具が違うと、「Git の社は直せるが、レンタルサーバーと WordPress の社は記事しか
届かない」状態になる（2026-10-04 まで）。先方に作業をさせないため、全方式を同じ4つの操作にそろえる。

  python scripts/site_change.py --site <id> --pull       # 先方のサイトを手元の作業場所へ取る（変える前の控えを残す）
  （作業場所のファイルを直す: パスは --pull が表示する）
  python scripts/site_change.py --site <id> --diff       # 何が変わるかを見る
  python scripts/site_change.py --site <id> --push       # 変えた分だけ先方へ反映する
  python scripts/site_change.py --site <id> --rollback   # 直前の反映の前へ戻す（--rollback <コミット> で任意の時点）
  python scripts/site_change.py --site <id> --ask "<指示>"   # 取る→Claude が直す→検査→写真で止まる（--yes で反映）
      # 中身は site_renovate.py。反映後にトップと変えたページを確かめ、だめなら自動で戻す

作業場所は .publish-work/<id>-site/。中に Git の履歴を持ち、取った時点（remote）と反映の履歴が残る。

| 方式 | 取る | 反映 |
|:--|:--|:--|
| Git の社（external-*・nextjs-json） | 配信先リポジトリを取る | commit + push（先方のビルドが動く） |
| ftp | サーバーのファイルを全部取る（大きいファイル・WordPress 本体は除く） | 変えたファイルだけ上げる・消したファイルは消す |
| wordpress | FTP の接続情報がある社だけ、ftp と同じく取る（テーマも含む。WordPress 本体・アップロード画像は除く）。無い社は扱わない（預かる鍵は投稿者の権限だけで、固定ページ・メニュー・配色を REST で変えられない） | ftp と同じ |
| zip | 取れない（先方のサーバーに触れない） | 変更を ZIP と手順書にして先方へメールで送る（先方が置く作業が残る。勧めない） |

**反映の前に、先方で誰かが同じものを変えていないかを確かめる。** 取った時点と今のサーバーが
違えば止める（先方の更新を上書きして消さない）。固定ページの削除はゴミ箱へ移すだけにする。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
WORK = ROOT / ".publish-work"
GIT_TYPES = ("external-md", "external-html", "nextjs-json")
# FTP で取らないもの。WordPress 本体・アップロード画像・キャッシュは構成の変更に要らず、取ると時間がかかる
FTP_SKIP = ("wp-admin", "wp-includes", "wp-content/uploads", "wp-content/cache", "cgi-bin", ".well-known")
FTP_MAX = 5 * 1024 * 1024
# 作業場所に置くが先方へ送らないもの（--ask の比較の写真）
LOCAL_ONLY = ("_preview/",)


def git(*a, cwd, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(a)}: {(r.stderr or r.stdout)[-300:]}")
    return r.stdout


def mirror(cfg):
    return WORK / f"{cfg['id']}-site"


def mgit(m: Path, *a, check=True):
    """作業場所の git。必ずその場所の .git を名指しする。
    名指ししないと、.git が壊れているときに git が親の管制塔リポジトリまでさかのぼり、
    本体に無関係なファイルをまとめてコミットした（2026-10-04 の試験で実際に起きた）"""
    return git(f"--git-dir={m / '.git'}", f"--work-tree={m}", *a, cwd=m, check=check)


def _exclude_local(m: Path):
    """写真（_preview/）を作業場所の記録に入れない。入れると FTP の社では先方のサーバーへ上がる"""
    ex = m / ".git" / "info" / "exclude"
    have = ex.read_text(encoding="utf-8") if ex.is_file() else ""
    if any(x not in have.split() for x in LOCAL_ONLY):
        ex.parent.mkdir(parents=True, exist_ok=True)
        ex.write_text(have + "".join(x + "\n" for x in LOCAL_ONLY if x not in have.split()), encoding="utf-8")


def ensure_repo(m: Path):
    if (m / ".git" / "HEAD").is_file():
        _exclude_local(m)
        return
    import shutil
    import stat
    # 壊れた .git は消して作り直す（Windows の読み取り専用のオブジェクトも消せるように）
    if (m / ".git").exists():
        shutil.rmtree(m / ".git", onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
    git("init", "-q", str(m), cwd=m)
    for k, v in (("user.name", "AIO Pipeline Bot"), ("user.email", "noreply@7senses.co.jp"), ("core.autocrlf", "false")):
        mgit(m, "config", k, v)
    _exclude_local(m)


def snapshot(m: Path, msg):
    """作業場所の今の中身を記録し、それを「先方の今の状態」（remote）にする"""
    ensure_repo(m)
    mgit(m, "add", "-A")
    mgit(m, "commit", "-q", "--allow-empty", "-m", msg)
    mgit(m, "tag", "-f", "remote")


def changes(m: Path):
    """remote（取った時点）から今の作業場所までの変化: [(状態 A/M/D, 相対パス)]"""
    mgit(m, "add", "-A")
    out = mgit(m, "diff", "--cached", "--name-status", "--no-renames", "remote")
    return [tuple(l.split("\t", 1)) for l in out.splitlines() if "\t" in l]


def at_remote(m: Path, f):
    return subprocess.run(["git", f"--git-dir={m / '.git'}", "show", f"remote:{f}"], cwd=m, capture_output=True).stdout


# ---------------------------------------------------------------- FTP

def ftp_pull(cfg):
    import deliver_files as DF
    m = mirror(cfg)
    m.mkdir(parents=True, exist_ok=True)
    skip = tuple(cfg.get("ftp_skip") or FTP_SKIP)
    with DF.Remote(DF.credentials(cfg)) as r:
        files = r.walk("", skip)
        big = [f for f, n in files if n > FTP_MAX]
        keep = {f for f, n in files if n <= FTP_MAX}
        for f in keep:
            data = r.get(f)
            if data is not None:
                p = m / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
    # サーバーから消えたものは作業場所からも消す（.git は除く）
    for p in list(m.rglob("*")):
        rel = p.relative_to(m).as_posix()
        if p.is_file() and not rel.startswith((".git/",) + LOCAL_ONLY) and rel not in keep:
            p.unlink()
    snapshot(m, f"取得 {datetime.now():%Y-%m-%d %H:%M}（{len(keep)}ファイル）")
    note = f"／{FTP_MAX // 1024 // 1024}MB超の {len(big)} ファイルは取っていません（触りません）" if big else ""
    return f"{len(keep)} ファイルを取りました{note}"


def ftp_push(cfg, ch):
    import deliver_files as DF
    m = mirror(cfg)
    with DF.Remote(DF.credentials(cfg)) as r:
        # 先方で変わっていないか: 変えるファイルの今の中身が、取った時点と同じか
        moved = [f for st, f in ch if st != "A" and r.get(f) != at_remote(m, f)]
        if moved:
            raise SystemExit("先方のサーバーで、取った後に変わったファイルがあります（上書きしません）:\n  "
                             + "\n  ".join(moved[:10]) + "\n--pull で取り直してから、もう一度直してください")
        for st, f in ch:
            if st == "D":
                r.delete(f)
            else:
                r.put(m / f, f)
    return f"{len(ch)} ファイルを反映しました"


# ---------------------------------------------------------------- Git の社

BOT = ("-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp")


def git_push(cfg, committed=False):
    """committed: 呼び出し側がもうコミットした（戻すとき）。作業ツリーが空でも押す。
    以前は差分の有無だけで判断していたため、--rollback の revert が押されずに「変更はありません」で終わった"""
    import publish
    dest = WORK / cfg["id"]
    git("add", "-A", cwd=dest)
    if git("status", "--porcelain", cwd=dest).strip():
        git(*BOT, "commit", "-q", "-m", f"サイト構成の変更（管制塔 {date.today()}）", cwd=dest)
    elif not committed:
        return "変更はありません"
    token = publish._push_token()
    if not publish.try_run(["git", "push", f"https://x-access-token@github.com/{cfg['repo']}.git", f"HEAD:{cfg['branch']}"],
                           cwd=dest, env=publish.git_auth(token)):
        raise SystemExit("push できませんでした（python scripts/token_check.py で鍵を確かめてください）")
    return "push しました（先方のビルドが動きます）"


# ---------------------------------------------------------------- ZIP の社

def zip_push(cfg, ch):
    """先方のサーバーに触れない社: 変えたファイルと手順書を ZIP にして先方へメールする"""
    import zipfile
    m = mirror(cfg)
    out = ROOT / "deliveries" / cfg["id"] / f"{date.today().isoformat()}-サイト変更.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    gone = [f for st, f in ch if st == "D"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for st, f in ch:
            if st != "D":
                z.write(m / f, f)
        steps = ["1. 同梱のファイルを、サーバーの同じ場所に上書きで置いてください"]
        if gone:
            steps += ["2. 次のファイルを削除してください"] + [f"   /{f}" for f in gone]
        z.writestr("手順.txt", "\n".join(steps) + "\n")
    sent = _mail_zip(cfg, out)
    return f"ZIP を作りました: {out.relative_to(ROOT)}" + ("（先方へメールしました）" if sent else "（送っていません）")


def _mail_zip(cfg, path: Path):
    """data/clients/<id>/company.json の担当者メールへ送る。手元の実行では送らない（本番の宛先に届くため）"""
    import base64
    import urllib.request
    if not os.environ.get("GITHUB_ACTIONS"):
        return False
    # ヒアリングシートは会社の窓口を "email" で書く。"contact_email" だけを見ていたため、
    # シートから登録した社には1通も届かず、ZIP を作っただけで終わっていた
    import private_store
    c = private_store.read_json(cfg["id"], "company.json", {}) or {}
    to = c.get("contact_email") or c.get("email")
    key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("LEAD_FROM_EMAIL")
    if not (to and key and sender):
        return False
    body = {"from": sender, "to": [to], "subject": f"【{cfg.get('name', cfg['id'])}】サイト更新ファイルのお届け",
            "text": "サイトの更新ファイルをお送りします。添付の ZIP の「手順.txt」に沿って、サーバーへ置いてください。",
            "attachments": [{"filename": path.name, "content": base64.b64encode(path.read_bytes()).decode()}]}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "ss-aio-pipeline/1.0"})   # 無いと Cloudflare が 1010 で弾く
    try:
        urllib.request.urlopen(req, timeout=60)
        return True
    except Exception as e:
        print(f"  メールを送れませんでした: {e}")
        return False


# ---------------------------------------------------------------- 入口

def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--rollback", nargs="?", const="remote~1", default=None)
    ap.add_argument("--ask", help="改修の指示（取る→Claude が直す→検査→写真→止まる。site_renovate.py）")
    ap.add_argument("--yes", action="store_true", help="--ask の検査が通れば反映する（反映後に確かめ、だめなら戻す）")
    ap.add_argument("--no-preview", action="store_true", help="--ask で画面の写真を撮らない")
    a = ap.parse_args()
    cfg = S.load(a.site)
    t = cfg["type"]
    m = mirror(cfg)
    if t == "self-static":
        raise SystemExit("このリポジトリのサイトです。site/ と templates/ を直して build.py で公開してください")
    if t == "wordpress":
        import speed_fix
        if not speed_fix.has_ftp(cfg):
            raise SystemExit(f"{cfg['id']} は WordPress で、FTP の接続情報がありません。預かる鍵は記事の投稿者の権限だけなので、"
                             "サイトの構成は変えられません（変えるなら FTP の接続情報を FTP_CREDENTIALS_JSON に登録する）")
    if a.ask:
        import site_renovate
        return site_renovate.run(cfg, a.ask, yes=a.yes, preview=not a.no_preview)
    if t in GIT_TYPES:
        import publish
        dest = WORK / cfg["id"]
        if a.pull:
            publish.ensure_clone(cfg, publish._push_token())
            print(f"配信先リポジトリを取りました: {dest}（ここで直して --push）")
        elif a.rollback:
            git(*BOT, "revert", "--no-edit", "HEAD", cwd=dest)
            print(git_push(cfg, committed=True))
        elif a.push:
            print(git_push(cfg))
        else:
            print(git("status", "--short", cwd=dest))
        return 0
    if a.pull:
        if t == "zip":
            m.mkdir(parents=True, exist_ok=True)
            snapshot(m, "取得できない方式（ZIP）。ここに置いたファイルが送る対象になる")
            print(f"ZIP の社は先方のサーバーを取れません。変えるファイルを {m} に置いて --push してください")
            return 0
        print(ftp_pull(cfg))
        print(f"作業場所: {m}")
        return 0
    if not (m / ".git" / "HEAD").is_file():
        raise SystemExit(f"先に --pull してください（{m} がありません）")
    if a.rollback:
        restore(cfg, a.rollback)
        print(f"作業場所を {a.rollback} の状態に戻しました")
        a.push = True
    ch = changes(m)
    for st, f in ch:
        print(f"  {st} {f}")
    print(f"変更 {len(ch)} 件")
    if not a.push or not ch:
        return 0
    print(push_mirror(cfg, ch))
    return 0


def restore(cfg, rev="remote~1"):
    """作業場所を指定の時点の中身に戻す（履歴は消さない。反映は push_mirror）"""
    m = mirror(cfg)
    mgit(m, "checkout", rev, "--", ".")
    # checkout だけでは、その時点より後に足したファイルが残る（試しで about.html が消えなかった）
    for f in mgit(m, "diff", "--name-only", "--diff-filter=A", rev, "HEAD").splitlines():
        (m / f).unlink(missing_ok=True)


def push_mirror(cfg, ch):
    """FTP・WordPress・ZIP の社: 作業場所の変化を先方へ反映し、反映後の中身を「先方の今」として記録する"""
    msg = {"ftp": ftp_push, "wordpress": ftp_push, "zip": zip_push}[cfg["type"]](cfg, ch)
    snapshot(mirror(cfg), f"反映 {datetime.now():%Y-%m-%d %H:%M}: {len(ch)}件")
    return msg


if __name__ == "__main__":
    sys.exit(main())
