# -*- coding: utf-8 -*-
"""管制塔から、どの方式の社でもサイトの構成（ナビ・トップ・固定ページ・CSS・メニュー・配色）を変える入口。

配信方式ごとに道具が違うと、「Git の社は直せるが、レンタルサーバーと WordPress の社は記事しか
届かない」状態になる（2026-10-04 まで）。先方に作業をさせないため、全方式を同じ4つの操作にそろえる。

  python scripts/site_change.py --site <id> --pull       # 先方のサイトを手元の作業場所へ取る（変える前の控えを残す）
  （作業場所のファイルを直す: パスは --pull が表示する）
  python scripts/site_change.py --site <id> --diff       # 何が変わるかを見る
  python scripts/site_change.py --site <id> --push       # 変えた分だけ先方へ反映する
  python scripts/site_change.py --site <id> --rollback   # 直前の反映の前へ戻す（--rollback <コミット> で任意の時点）

作業場所は .publish-work/<id>-site/。中に Git の履歴を持ち、取った時点（remote）と反映の履歴が残る。

| 方式 | 取る | 反映 |
|:--|:--|:--|
| Git の社（external-*・nextjs-json） | 配信先リポジトリを取る | commit + push（先方のビルドが動く） |
| ftp | サーバーのファイルを全部取る（大きいファイル・WordPress 本体は除く） | 変えたファイルだけ上げる・消したファイルは消す |
| wordpress | 固定ページ・メニュー・ナビ・テンプレート・配色・サイト設定を JSON で取る（FTP の接続情報がある社は有効なテーマの PHP も theme/ に取る） | 変えた項目だけ REST API で更新する（theme/ は FTP で戻す） |
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
# WordPress で取るもの: (資源名, 一覧の取り方, 書き戻す項目)。公式の REST API リファレンスで確かめた資源だけ
WP_RES = [
    ("pages", "pages?context=edit&per_page=100&status=publish,draft,private",
     ("title", "content", "slug", "status", "parent", "menu_order", "excerpt")),
    ("menus", "menus?context=edit&per_page=100", ("name", "description", "locations", "auto_add")),
    ("menu-items", "menu-items?context=edit&per_page=100",
     ("title", "url", "menus", "parent", "menu_order", "type", "object", "object_id", "status", "target", "classes")),
    ("navigation", "navigation?context=edit&per_page=100", ("title", "content", "status")),
    ("templates", "templates?context=edit&per_page=100", ("content", "title", "description")),
    ("template-parts", "template-parts?context=edit&per_page=100", ("content", "title", "description", "area")),
]
WP_SETTINGS = ("title", "description", "show_on_front", "page_on_front", "page_for_posts", "posts_per_page")


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


def ensure_repo(m: Path):
    if (m / ".git" / "HEAD").is_file():
        return
    import shutil
    import stat
    # 壊れた .git は消して作り直す（Windows の読み取り専用のオブジェクトも消せるように）
    if (m / ".git").exists():
        shutil.rmtree(m / ".git", onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
    git("init", "-q", str(m), cwd=m)
    for k, v in (("user.name", "AIO Pipeline Bot"), ("user.email", "noreply@7senses.co.jp"), ("core.autocrlf", "false")):
        mgit(m, "config", k, v)


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
        if p.is_file() and not rel.startswith(".git/") and rel not in keep:
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


# ---------------------------------------------------------------- WordPress

def _wp(cfg, path, data=None, method=None):
    import publish
    return publish._wp_call(cfg, path, data, method)


def _wp_val(v):
    # title・content は {"raw": ..., "rendered": ...}。書き戻せるのは raw だけ
    return v.get("raw", v.get("rendered")) if isinstance(v, dict) and ("raw" in v or "rendered" in v) else v


def _wp_routes(cfg):
    """先方の WordPress が持つ資源の一覧（古い版・クラシックテーマには navigation・templates が無い）"""
    import publish
    import urllib.request
    base = publish._wp_api(cfg).rsplit("/wp/v2", 1)[0]
    try:
        req = urllib.request.Request(base + "/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return set(json.loads(r.read().decode("utf-8")).get("routes", {}))
    except Exception:
        return set()


def wp_pull(cfg):
    m = mirror(cfg)
    m.mkdir(parents=True, exist_ok=True)
    routes = _wp_routes(cfg)
    got = {}
    for name, q, fields in WP_RES:
        if routes and f"/wp/v2/{name}" not in routes:
            continue
        d = m / name
        if d.is_dir():
            for p in d.glob("*.json"):
                p.unlink()
        d.mkdir(exist_ok=True)
        items = _wp(cfg, q)
        items = items if isinstance(items, list) else []
        for it in items:
            rec = {k: _wp_val(it.get(k)) for k in fields if k in it}
            key = str(it["id"]).replace("/", "__")     # テンプレートの id は「テーマ//名前」
            (d / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        got[name] = len(items)
    s = _wp(cfg, "settings")
    (m / "settings.json").write_text(json.dumps({k: s.get(k) for k in WP_SETTINGS if k in s},
                                                ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    # 配色・書体（ブロックテーマだけ）。有効なテーマの利用者側の global styles を取る
    try:
        th = _wp(cfg, "themes?status=active")
        href = ((th[0].get("_links") or {}).get("wp:user-global-styles") or [{}])[0].get("href", "") if th else ""
        gid = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
        if gid:
            g = _wp(cfg, f"global-styles/{gid}?context=edit")
            (m / "global-styles.json").write_text(
                json.dumps({"id": gid, "styles": g.get("styles"), "settings": g.get("settings")},
                           ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            got["global-styles"] = 1
    except SystemExit:
        pass
    got.update(wp_theme_pull(cfg, m))
    snapshot(m, f"取得 {datetime.now():%Y-%m-%d %H:%M}（{got}）")
    return f"取りました: {got}（新しい固定ページ・メニュー項目は <資源>/new-<名前>.json で作れます）"


# テーマの PHP は REST では触れない。FTP の接続情報（FTP_CREDENTIALS_JSON の同じ社のID）がある社だけ、
# 有効なテーマ（子テーマなら親も）を theme/ に取り、変えたファイルを FTP で戻す
THEME_DIR = "theme"


def wp_theme_pull(cfg, m: Path):
    import deliver_files as DF
    import speed_fix
    if not speed_fix.has_ftp(cfg):
        return {}
    files = speed_fix._wp_theme_files(cfg)
    d = m / THEME_DIR
    if d.is_dir():
        import shutil
        shutil.rmtree(d)
    with DF.Remote(DF.credentials(cfg)) as r:
        for f in files:
            data = r.get(f)
            if data is not None:
                p = d / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
    return {"theme": len(files)}


def wp_theme_push(cfg, ch):
    """theme/ の変更を FTP で戻す。取った後に先方で変わったファイルがあれば上書きしない"""
    import deliver_files as DF
    m = mirror(cfg)
    ch = [(st, f[len(THEME_DIR) + 1:], f) for st, f in ch]
    with DF.Remote(DF.credentials(cfg)) as r:
        moved = [rel for st, rel, f in ch if st != "A" and r.get(rel) != at_remote(m, f)]
        if moved:
            raise SystemExit("先方のサーバーで、取った後に変わったテーマのファイルがあります（上書きしません）:\n  "
                             + "\n  ".join(moved[:10]) + "\n--pull で取り直してから、もう一度直してください")
        for st, rel, f in ch:
            if st == "D":
                r.delete(rel)
            else:
                r.put(m / f, rel)
    return len(ch)


def wp_push(cfg, ch):
    m = mirror(cfg)
    fields_of = {n: f for n, _, f in WP_RES}
    theme = [(st, f) for st, f in ch if f.startswith(THEME_DIR + "/")]
    ch = [(st, f) for st, f in ch if not f.startswith(THEME_DIR + "/")]
    done = wp_theme_push(cfg, theme) if theme else 0
    for st, f in ch:
        p = m / f
        if f == "settings.json":
            _wp(cfg, "settings", json.loads(p.read_text(encoding="utf-8")))
            done += 1
            continue
        if f == "global-styles.json":
            g = json.loads(p.read_text(encoding="utf-8"))
            _wp(cfg, f"global-styles/{g['id']}", {"styles": g.get("styles"), "settings": g.get("settings")})
            done += 1
            continue
        name, _, file = f.partition("/")
        if name not in fields_of or not file.endswith(".json"):
            continue
        key = file[:-5].replace("__", "/")
        if st == "D":
            # 固定ページはゴミ箱へ（管理画面から戻せる）。それ以外は完全に消す
            _wp(cfg, f"{name}/{key}" + ("" if name == "pages" else "?force=true"), method="DELETE")
            done += 1
            continue
        data = {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if k in fields_of[name]}
        if st == "A" or key.startswith("new-"):
            created = _wp(cfg, name, data)
            # 作られた id の名前に付け替え、次の反映で二重に作らない
            p.rename(p.with_name(f"{str(created['id']).replace('/', '__')}.json"))
        else:
            now = _wp(cfg, f"{name}/{key}?context=edit")
            was = json.loads(at_remote(m, f) or b"{}")
            if any(_wp_val(now.get(k)) != was.get(k) for k in was):
                raise SystemExit(f"先方の管理画面で、取った後に変わっています（上書きしません）: {f}\n--pull で取り直してください")
            _wp(cfg, f"{name}/{key}", data)
        done += 1
    return f"{done} 件を反映しました"


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
    try:
        c = json.loads((ROOT / "data" / "clients" / cfg["id"] / "company.json").read_text(encoding="utf-8"))
        to = c.get("contact_email") or c.get("email")
    except (OSError, ValueError):
        to = None
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
    a = ap.parse_args()
    cfg = S.load(a.site)
    t = cfg["type"]
    m = mirror(cfg)
    if t == "self-static":
        raise SystemExit("このリポジトリのサイトです。site/ と templates/ を直して build.py で公開してください")
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
        print((ftp_pull if t == "ftp" else wp_pull)(cfg))
        print(f"作業場所: {m}")
        return 0
    if not (m / ".git" / "HEAD").is_file():
        raise SystemExit(f"先に --pull してください（{m} がありません）")
    if a.rollback:
        # 指定の時点の中身に作業場所を戻し、その差分を反映する（履歴は消さない）
        mgit(m, "checkout", a.rollback, "--", ".")
        # checkout だけでは、その時点より後に足したファイルが残る（試しで about.html が消えなかった）
        for f in mgit(m, "diff", "--name-only", "--diff-filter=A", a.rollback, "HEAD").splitlines():
            (m / f).unlink(missing_ok=True)
        print(f"作業場所を {a.rollback} の状態に戻しました")
        a.push = True
    ch = changes(m)
    for st, f in ch:
        print(f"  {st} {f}")
    print(f"変更 {len(ch)} 件")
    if not a.push or not ch:
        return 0
    msg = {"ftp": ftp_push, "wordpress": wp_push, "zip": zip_push}[t](cfg, ch)
    snapshot(m, f"反映 {datetime.now():%Y-%m-%d %H:%M}: {len(ch)}件")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
