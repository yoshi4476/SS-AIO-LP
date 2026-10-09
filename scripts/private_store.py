# -*- coding: utf-8 -*-
"""お客様の情報・料金と営業の台本・月次レポートを読む・書く入口（ここを通らずに読まない）。

管制塔（yoshi4476/SS-AIO-LP）は GitHub Actions を無料で使うため public のまま運用する（2026-10-10 運用者の指示）。
お客様から預かったもの・お客様について調べたもの（ヒアリングシートの内容・まだ公開していない会社情報・記事の材料・
一次情報・キーワード計画・サイト設定の戦略の部分・順位や問い合わせの数字）と、当社の料金・営業の台本・月次レポートは、
非公開のリポジトリ yoshi4476/ss-aio-private に置く（workflow は置かない＝Actions の料金はかからない）。

  手元: 管制塔の直下 private/ に取得する（.gitignore 済み）
        git clone https://github.com/yoshi4476/ss-aio-private.git private
  CI  : 各ジョブの最初に .github/actions/private-data が private/ へ取得し、守秘の語を ::add-mask:: で伏せる
        （鍵は Secret PRIVATE_DATA_TOKEN、無ければ SITE_PUSH_TOKEN）

置き場（private/ の中）:
  clients/<id>/company.json       会社の正規表記（著者・発行元・レポートの宛名）。住所・電話・代表者・監修者の資格など
  clients/<id>/brief.json         記事の材料（売り物・読者の困りごと・FAQ・狙う語・狙わない語・競合・事例・声）
  clients/<id>/facts.json         一次情報
  clients/<id>/kw.md              キーワード計画の雛形（以前の docs/kw-<id>.md）
  clients/<id>/site_private.json  サイト設定の戦略の部分（sites/<id>.json から外した項目。sites.load_all が重ねて読む）
  clients/<id>/private.json       担当者の連絡先・接続先（パスワードは入れない）
  sales/                          料金と営業の台本（proposal.json・prices.json・台本のモジュール）
  reports/                        月次・週次・グループのレポートと目標値（targets*.json・growth_plan.json）

移行の間は、手元の古い場所（data/clients/<id>/・docs/kw-<id>.md・reports/）も読む（private/ を先に見る）。
**CI で非公開のデータが取れないときは、お客様の社の記事を書かずに止めて知らせる**（require）。書かれていないことは
書かせない（材料なしで書かせない）。自社3サイトはこれまでどおり動く。

  python scripts/private_store.py --status              # 置き場があるか・社ごとの材料の有無（件数だけ）
  python scripts/private_store.py --check-site <id>     # お客様の社の材料が読めるか（最後の行が PRIVATE_OK=yes/no/own）
  python scripts/private_store.py --is-client <id>      # お客様の社か（yes/no。CI でログに出す量を決める）
  python scripts/private_store.py --fetch               # CI: private/ へ取得する（鍵は環境変数）
  python scripts/private_store.py --push "<理由>"        # private/ の変更を commit・push する
  python scripts/private_store.py --migrate <id>        # 古い場所の材料と sites/<id>.json の戦略の部分を private/ へ移す
"""
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REPO = "yoshi4476/ss-aio-private"
TOKEN_ENVS = ("PRIVATE_DATA_TOKEN", "SITE_PUSH_TOKEN")
# お客様の社の材料のファイル。どれも公開側では追跡しない（.gitignore と門 gates_history_h76）
CLIENT_FILES = ("company.json", "brief.json", "facts.json", "kw.md", "site_private.json", "private.json")


def _sites():
    import sites as S
    return S


def base(root=None):
    """非公開の置き場。root（管制塔の基点）を渡すとその下の private/（門と導入の一時の場所）。
    門は SS_PRIVATE_DIR で一時の場所（空にすると「取れなかった」CI と同じ）へ差し替える"""
    if root is not None and Path(root).resolve() != ROOT.resolve():
        return Path(root) / "private"
    return Path(os.environ.get("SS_PRIVATE_DIR") or ROOT / "private")


def legacy_root(root=None):
    """移行前の置き場の基点。門が sites.ROOT を一時の場所へ差し替えたときは、そちらを見る"""
    return Path(root) if root is not None else Path(_sites().ROOT)


def client_dir(sid, root=None):
    return base(root) / "clients" / str(sid)


def _legacy(sid, name, root=None):
    if name == "kw.md":
        return legacy_root(root) / "docs" / f"kw-{sid}.md"
    return legacy_root(root) / "data" / "clients" / str(sid) / name


def client_path(sid, name, write=False, root=None):
    """お客様の社の材料のファイル。private/ を先に見て、無ければ移行前の場所（あれば）。書くときは必ず private/"""
    p = client_dir(sid, root) / name
    if write or p.exists():
        return p
    old = _legacy(sid, name, root)
    return old if old.exists() else p


def read_json(sid, name, default=None, root=None):
    try:
        return json.loads(client_path(sid, name, root=root).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def read_text(sid, name, default="", root=None):
    try:
        return client_path(sid, name, root=root).read_text(encoding="utf-8")
    except OSError:
        return default


def write_json(sid, name, obj, root=None):
    p = client_path(sid, name, write=True, root=root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return p


def write_text(sid, name, text, root=None):
    p = client_path(sid, name, write=True, root=root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def site_private(sid, root=None):
    """サイト設定の戦略の部分（sites/<id>.json から外した項目）。無ければ空"""
    d = read_json(sid, "site_private.json", {}, root=root)
    return d if isinstance(d, dict) else {}


def write_site(cfg, sites_dir, root=None):
    """お客様の社のサイト設定を書く。公開してよい項目（sites.PUBLIC_KEYS）だけを sites/<id>.json へ、
    残り（戦略の部分）を非公開の置き場の clients/<id>/site_private.json へ。書いたファイルを返す"""
    S = _sites()
    pub, priv = S.split_public(cfg)
    pub["client"] = True
    priv.pop("kw_plan", None)         # キーワード計画は clients/<id>/kw.md（場所は private_store が決める）
    sp = Path(sites_dir) / f"{cfg['id']}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(pub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [sp, write_json(cfg["id"], "site_private.json", priv, root=root)]


def known_clients():
    """private/clients/ にある社（社の設定が無くても数える。--status 用）"""
    d = base() / "clients"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def available(sid=None):
    """非公開のデータがあるか。sid を渡すと、その社の材料（設定の戦略の部分か執筆の材料）があるか"""
    if sid is None:
        return (base() / "clients").is_dir() or (base() / ".git").is_dir()
    return any(client_path(sid, n).is_file() for n in ("site_private.json", "brief.json", "company.json", "facts.json"))


def is_client(sid):
    return bool(sid) and _sites().is_client(sid)


def require(sid, what="記事"):
    """お客様の社で非公開のデータが読めなければ False（理由を出す）。自社の社と、読める社は True"""
    if not is_client(sid) or available(sid):
        return True
    print(f"要対応: {sid} の{what}を止めました。非公開のデータ（{REPO} の clients/{sid}/）が読めません"
          "（CI は鍵 PRIVATE_DATA_TOKEN／SITE_PUSH_TOKEN にこのリポジトリの読み書きの権限が要ります。"
          "手元は python scripts/private_store.py --fetch で private/ に取得）", flush=True)
    print("PRIVATE_OK=no", flush=True)
    return False


def require_or_exit(sid, what="記事"):
    if not require(sid, what):
        raise SystemExit(3)


# ── 料金と営業の台本・レポート ───────────────────────────────

def sales_path(name):
    return base() / "sales" / name


def sales_json(name, default=None):
    """料金・営業の台本の文言（private/sales/<name>）。無ければ default（公開側に数字を置かない）"""
    try:
        return json.loads(sales_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def sales_module(name):
    """営業の台本のモジュール（private/sales/<name>.py）を読み込む。無ければ SystemExit（理由を出す）"""
    import importlib
    d = base() / "sales"
    if not (d / f"{name}.py").is_file():
        raise SystemExit(f"営業の台本 {name} がありません（{REPO} の sales/{name}.py。private/ に取得してください）")
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    return importlib.import_module(name)


def reports_dir():
    """レポートの置き場。非公開のデータがあれば private/reports、無ければ手元の reports/（公開側では追跡しない）"""
    return base() / "reports" if available() else legacy_root() / "reports"


def report_path(rel):
    """レポートの置き場のファイル。読むときは private/ に無ければ手元の reports/ も見る（移行の間）"""
    p = reports_dir() / rel
    if p.exists():
        return p
    old = legacy_root() / "reports" / rel
    return old if old.exists() else p


# ── CI での取得と、変更の commit・push ───────────────────────────

def _token():
    return next((os.environ[k] for k in TOKEN_ENVS if os.environ.get(k)), "")


def _git(*args, check=False, quiet=True):
    r = subprocess.run(["git", "-C", str(base()), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
    return r


def _header(tok):
    b64 = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{b64}", flush=True)      # 鍵は伏せられるが、その base64 は伏せられない
    return f"AUTHORIZATION: basic {b64}"


def _set_output(ok):
    """CI の工程の出力（ok=yes/no）。.github/actions/private-data が受け取る"""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"ok={'yes' if ok else 'no'}\n")
    return ok


def fetch():
    """private/ へ取得する（あれば最新にする）。PRIVATE_DATA=ok/none/denied を出す"""
    b = base()
    if (b / ".git").is_dir():
        # この回で書いた変更が残っていれば取り込まない（後の push が重ね直す）
        dirty = bool(_git("status", "--porcelain").stdout.strip())
        r = _git("pull", "-q", "--rebase") if not dirty else None
        print("PRIVATE_DATA=ok" + ("" if r is not None and r.returncode == 0 else "（最新にせず、手元の写しのまま）"),
              flush=True)
        return _set_output(True)
    tok = _token()
    if not tok and os.environ.get("GITHUB_ACTIONS"):
        print("PRIVATE_DATA=none（鍵がありません。Secret PRIVATE_DATA_TOKEN か SITE_PUSH_TOKEN を渡してください）",
              flush=True)
        return _set_output(False)
    # 手元は運用者の git の資格情報で取る（鍵を環境変数に置かない）。CI は鍵を見出しで渡し、URL に入れない
    pre = ["-c", f"http.https://github.com/.extraheader={_header(tok)}"] if tok else []
    r = subprocess.run(["git", *pre, "clone", "-q", *(["--depth", "30"] if tok else []),
                        f"https://github.com/{REPO}.git", str(b)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        err = r.stderr or ""
        why = ("権限がありません（鍵にこのリポジトリの Contents の読み書きが要ります）"
               if any(w in err for w in ("not found", "403", "Authentication", "could not read")) else
               (err.strip().splitlines() or ["不明"])[-1][:160])
        print(f"PRIVATE_DATA=denied（{why}）", flush=True)
        return _set_output(False)
    if tok:
        _git("config", "--local", "http.https://github.com/.extraheader", _header(tok))
        _git("config", "--local", "user.name", "AIO Pipeline Bot")
        _git("config", "--local", "user.email", "noreply@7senses.co.jp")
    print("PRIVATE_DATA=ok", flush=True)
    return _set_output(True)


def push(message, tries=3):
    """private/ の変更を commit して push する。何も変わっていなければ何もしない。PRIVATE_PUSH=... を出す"""
    if not (base() / ".git").is_dir():
        print("PRIVATE_PUSH=none（private/ がありません）", flush=True)
        return False
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        print("PRIVATE_PUSH=nochange", flush=True)
        return True
    _git("commit", "-q", "-m", message)
    for i in range(tries):
        if _git("push", "-q", "origin", "HEAD").returncode == 0:
            print("PRIVATE_PUSH=ok", flush=True)
            return True
        _git("pull", "-q", "--rebase")
        time.sleep(3 * (i + 1))
    print("PRIVATE_PUSH=failed（非公開のリポジトリへ push できませんでした）", flush=True)
    return False


# ── 移行（古い場所 → private/） ────────────────────────────────

def migrate(sid):
    """古い場所の材料と、sites/<id>.json の戦略の部分を private/ へ移す。公開側の sites/<id>.json は許可した項目だけにする。
    公開側のファイルの git rm --cached は呼び出し側（運用者）が行う。移したファイルの一覧を返す"""
    S = _sites()
    moved = []
    for name in ("company.json", "brief.json", "facts.json", "private.json", "kw.md"):
        old = _legacy(sid, name)
        if old.is_file() and not (client_dir(sid) / name).is_file():
            moved.append(write_text(sid, name, old.read_text(encoding="utf-8")))
    raw = json.loads((S.SITES_DIR / f"{sid}.json").read_text(encoding="utf-8-sig"))
    moved += write_site({**site_private(sid), **raw}, S.SITES_DIR)[1:]
    return moved


def status():
    print(f"PRIVATE_DIR={'yes' if available() else 'no'}")
    S = _sites()
    for sid in [s for s in S.load_all() if S.is_client(s)]:
        have = [n for n in CLIENT_FILES if client_path(sid, n).is_file()]
        print(f"  {sid}: 材料 {len(have)}/{len(CLIENT_FILES)} 件（{', '.join(have) or 'なし'}）")
    sales = base() / "sales"
    print(f"  料金と営業の台本: {len([p for p in sales.rglob('*') if p.is_file()]) if sales.is_dir() else 0} 件")
    rep = base() / "reports"
    print(f"  レポート: {len([p for p in rep.rglob('*') if p.is_file()]) if rep.is_dir() else 0} 件")


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if "--fetch" in a:
        return 0 if fetch() else 0       # 取れなくても止めない（お客様の工程が require で止まる）
    if "--push" in a:
        i = a.index("--push")
        msg = a[i + 1] if i + 1 < len(a) else "管制塔から更新"
        return 0 if push(msg) else 1
    if "--is-client" in a:
        print("yes" if is_client(a[a.index("--is-client") + 1]) else "no")
        return 0
    if "--check-site" in a:
        sid = a[a.index("--check-site") + 1]
        if not is_client(sid):
            print("PRIVATE_OK=own")
            return 0
        if require(sid):
            print("PRIVATE_OK=yes")
        return 0
    if "--migrate" in a:
        for p in migrate(a[a.index("--migrate") + 1]):
            print(f"  移した: {p.relative_to(base()).as_posix()}")
        return 0
    if "--status" in a:
        status()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
