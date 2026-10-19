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
  python scripts/private_store.py --migrate <id>        # 古い場所の材料と sites/<id>.json の設定を private/ へ移す
  python scripts/private_store.py --resolve <公開の id>  # 公開の id → 社の id（記事の枠のジョブの間の受け渡し）
  python scripts/private_store.py --overlay             # お客様の社の記事・画像・台本を作業場所へ重ね、commit の見張りを入れる
  python scripts/private_store.py --pre-commit          # commit の直前（hook）: お客様の社のファイルを公開側から外して残す
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
    """お客様の社のサイト設定（名前・ドメイン・配信先・カテゴリ・戦略の部分の全部と、公開の id）。無ければ空"""
    d = read_json(sid, "site_private.json", {}, root=root)
    return d if isinstance(d, dict) else {}


def new_public_id(sites_dir=None):
    """社名から推測できない公開の id（c と16進8桁）。お客様の社の id にも使う（2026-10-10 運用者の指示）"""
    import secrets
    d = Path(sites_dir) if sites_dir else _sites().SITES_DIR
    while True:
        pid = "c" + secrets.token_hex(4)
        if not (d / f"{pid}.json").exists() and not client_dir(pid).exists():
            return pid


def write_site(cfg, sites_dir, root=None):
    """お客様の社のサイト設定を書く。公開側の sites/<公開の id>.json には社が特定できない印（公開の id・client・
    1日の本数）だけ、設定の全部（名前・ドメイン・配信先・カテゴリ・戦略の部分）は非公開の置き場の
    clients/<社の id>/site_private.json へ。書いたファイルを返す"""
    cfg = {k: v for k, v in cfg.items() if k not in ("_path", "kw_plan", "client")}
    cur = site_private(cfg["id"], root=root)
    pid = cfg.get("public_id") or cur.get("public_id") or cfg["id"]
    stub = {"id": pid, "client": True}
    if cfg.get("daily_articles") is not None:
        stub["daily_articles"] = cfg["daily_articles"]
    sp = Path(sites_dir) / f"{pid}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(stub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [sp, write_json(cfg["id"], "site_private.json", dict(cfg, public_id=pid), root=root)]


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
    """お客様の社で非公開のデータが読めなければ False（理由を出す）。自社の社と、読める社は True。
    sid は社の id でも公開の id でもよい。知らせる文には公開の id だけを出す（社名を CI のログに出さない）"""
    rid = _sites().resolve(sid) if sid else sid
    if not is_client(rid) or available(rid):
        return True
    print(f"要対応: お客様の社 {_sites().public_id(rid) if rid else sid} の{what}を止めました。非公開のデータ（{REPO}）が読めません"
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
        _after_fetch()
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
    _after_fetch()
    return _set_output(True)


def _after_fetch():
    """取得の後: お客様の社の記事・画像・台本を作業場所へ重ねて置き、commit の見張り（hook）を入れる"""
    n = overlay_in()
    install_hook()
    print(f"PRIVATE_OVERLAY={n}", flush=True)


def push(message, tries=3):
    """private/ の変更を commit して push する。何も変わっていなければ何もしない。PRIVATE_PUSH=... を出す"""
    if not (base() / ".git").is_dir():
        print("PRIVATE_PUSH=none（private/ がありません）", flush=True)
        return False
    # AI の手順の前に git の資格を外す（agent_guard --lock）。鍵を受け取っていれば、書く直前に設定し直す
    tok = _token()
    if tok:
        _git("config", "--local", "http.https://github.com/.extraheader", _header(tok))
    overlay_out(unstage=False)         # 作業場所で書いた・直したお客様の社の記事・画像・台本も残す
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        # 書くものが無い回も、書けるかだけは確かめる。書けないまま原稿を書いた回は、その原稿がランナーと一緒に消える。
        # 下見は存在しない枝を作る形にする。main へ下見すると、手元が古いだけ（同時に動いた別の工程が先に送った）で
        # 「先に進んだ変更がある」と断られ、書けないと誤って知らせていた（2026-10-10）。枝は下見なので作られない
        r = _git("push", "--dry-run", "-q", "origin", "HEAD:refs/heads/write-check")
        if r.returncode:
            return _push_failed((r.stderr or r.stdout).strip()[-200:])
        print("PRIVATE_PUSH=nochange", flush=True)
        return True
    _git("commit", "-q", "-m", message)
    for i in range(tries):
        r = _git("push", "-q", "origin", "HEAD")
        if r.returncode == 0:
            print("PRIVATE_PUSH=ok", flush=True)
            return True
        _git("pull", "-q", "--rebase")
        time.sleep(3 * (i + 1))
    return _push_failed((r.stderr or r.stdout).strip()[-200:])


def _push_failed(why):
    """書けないことを、ログの1行ではなく実行の画面の赤い注釈で出す（呼ぶ側の工程も失敗にして、異常の知らせに載せる）"""
    print(f"PRIVATE_PUSH=failed（非公開のリポジトリへ push できませんでした）{why}", flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=非公開のリポジトリへ書けません::{REPO} へ push できません。SITE_PUSH_TOKEN の対象に {REPO} を足して"
              " Contents を Read and write にするか、Secret PRIVATE_DATA_TOKEN を作ってください", flush=True)
    return False


# ── お客様の社の記事と付属物（公開側の作業場所に重ねて置き、公開側の git には入れない） ─────────────
# 記事の原稿（公開前・90点未満で止めたものも）・画像・動画の台本は、公開側に置かない（2026-10-10 運用者の指示）。
# 工程は公開側の articles/ などを読むので、非公開の置き場の同じ場所（private/articles/… など）から作業場所へ重ねて
# 置き（overlay_in）、.git/info/exclude で公開側の git から外す。書いた・直した分は commit の前
# （.git/hooks/pre-commit → --pre-commit）とジョブの終わり（private-data の save → --push）に非公開の置き場へ戻す
OVERLAY_ROOTS = ("articles", "site/images", "data/duo_scripts", "data/duo_shorts")
SLUG_PATHS = ("site/images/{}", "data/duo_scripts/{}.json", "data/duo_shorts/{}.json")
EXCLUDE_HEAD = "# >>> private_store（お客様の社のファイル。公開側の git に入れない。手で書き換えない）"
EXCLUDE_TAIL = "# <<< private_store"
HOOK = """#!/bin/sh
# private_store: お客様の社のファイル（記事・画像・動画の台本）を公開側の commit に入れない（2026-10-10）
[ -f scripts/private_store.py ] || exit 0
for py in python3 python; do
  if "$py" -c "import sys" >/dev/null 2>&1; then exec "$py" scripts/private_store.py --pre-commit; fi
done
exit 0
"""


def _public_git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _git_path(rel):
    r = _public_git("rev-parse", "--git-path", rel)
    if r.returncode or not r.stdout.strip():
        return None
    p = Path(r.stdout.strip())
    return p if p.is_absolute() else ROOT / p


def _record_path():
    """この作業場所で重ねて置いたファイルの記録（作業場所ごと。git の作業場所どうしで共有する info/exclude とは別に持つ）"""
    r = _public_git("rev-parse", "--git-dir")
    if r.returncode or not r.stdout.strip():
        return None
    d = Path(r.stdout.strip())
    return (d if d.is_absolute() else ROOT / d) / "private_overlay.json"


def _record():
    p = _record_path()
    try:
        return set(json.loads(p.read_text(encoding="utf-8"))) if p and p.is_file() else set()
    except ValueError:
        return set()


def _write_record(rels):
    p = _record_path()
    if p:
        p.write_text(json.dumps(sorted(set(rels)), ensure_ascii=False), encoding="utf-8")


def _exclude_entries():
    p = _git_path("info/exclude")
    t = p.read_text(encoding="utf-8", errors="ignore") if p and p.is_file() else ""
    if EXCLUDE_HEAD not in t:
        return []
    block = t.split(EXCLUDE_HEAD, 1)[1].split(EXCLUDE_TAIL, 1)[0]
    return [ln.strip().lstrip("/") for ln in block.splitlines() if ln.strip() and not ln.startswith("#")]


def _write_exclude(rels):
    p = _git_path("info/exclude")
    if not p:
        return
    t = p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
    if EXCLUDE_HEAD in t:
        pre, rest = t.split(EXCLUDE_HEAD, 1)
        post = rest.split(EXCLUDE_TAIL, 1)[1] if EXCLUDE_TAIL in rest else ""
    else:
        pre, post = (t.rstrip("\n") + "\n" if t.strip() else ""), "\n"
    block = EXCLUDE_HEAD + "\n" + "".join(f"/{r}\n" for r in sorted(set(rels))) + EXCLUDE_TAIL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pre + block + post, encoding="utf-8", newline="\n")


def _category(p):
    import re
    try:
        m = re.search(r"^category:\s*[\"']?([\w-]+)", Path(p).read_text(encoding="utf-8-sig")[:3000], re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def client_categories():
    """お客様の社のカテゴリ {カテゴリ: 社の id}（非公開の置き場の設定から。取れない回は空）"""
    S = _sites()
    return {c: sid for sid, cfg in S.load_all().items() if S.is_client(sid) for c in (cfg.get("categories") or {})}


def client_slugs():
    """お客様の社の記事 {slug: 社の id}（公開側の作業場所と非公開の置き場の articles/ から）"""
    cats = client_categories()
    out = {}
    for d in (ROOT / "articles", base() / "articles"):
        for p in (d.rglob("*.md") if cats and d.is_dir() else ()):
            sid = cats.get(_category(p))
            if sid:
                out[p.stem] = sid
    return out


def client_files():
    """公開側の作業場所にある、お客様の社のファイル（記事・画像・動画の台本）の相対パス"""
    cats = client_categories()
    if not cats:
        return []
    out = [p.relative_to(ROOT).as_posix() for p in (ROOT / "articles").rglob("*.md")
           if cats.get(_category(p))]
    for slug in client_slugs():
        for t in SLUG_PATHS:
            q = ROOT / t.format(slug)
            if q.is_file():
                out.append(q.relative_to(ROOT).as_posix())
            elif q.is_dir():
                out += [x.relative_to(ROOT).as_posix() for x in q.rglob("*") if x.is_file()]
    return sorted(set(out))


def overlay_in(mark=True):
    """非公開の置き場のお客様の社のファイルを、公開側の作業場所へ重ねて置き、公開側の git から外す。
    手元に同じファイルがあれば手元を残す（書きかけを上書きしない）。置いた数を返す。
    mark は「この回の始まり」（.git/ss_base）を今の HEAD に置くか。取得の後だけ置く。範囲を戻すたび（widen）に
    置き直すと、それまでの工程（link_boost・auto_rewrite など）がお客様の記事に入れた直しが client_changes から消え、
    最後の配り直しに入らなかった（2026-10-12 の点検）"""
    import shutil
    b = base()
    if not b.is_dir():
        return 0
    rels = []
    for top in OVERLAY_ROOTS:
        d = b / top
        for p in (d.rglob("*") if d.is_dir() else ()):
            if p.is_file():
                rel = p.relative_to(b).as_posix()
                dst = ROOT / rel
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dst)
                rels.append(rel)
    _write_exclude(rels + [r for r in _exclude_entries() if (ROOT / r).exists()])
    _write_record(rels)
    if mark and (b / ".git").is_dir():
        sha = _git("rev-parse", "HEAD").stdout.strip()
        if sha:
            (b / ".git" / "ss_base").write_text(sha, encoding="utf-8")
    return len(rels)


def rehome_rewrite_before(slugs):
    """公開側の data/rewrite_before/ にあるお客様の記事の直す前の原稿を、その社の非公開の置き場
    （client_private.rewrite_before_dir）へ移し、移したものの相対パスを返す。auto_rewrite が公開側へ書いていた
    （2026-10-20 の点検。追跡している場所なので、次の commit で公開されていた）。読む側は両方を見るので移しても読める"""
    import shutil
    d = ROOT / "data" / "rewrite_before"
    moved = []
    for f in (sorted(d.glob("*@*.md")) if d.is_dir() and slugs else ()):
        sid = slugs.get(f.name.split("@", 1)[0])
        if not sid:
            continue
        dst = client_dir(sid) / "data" / "rewrite_before" / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.is_file():
            shutil.copy2(f, dst)
        f.unlink()
        moved.append(f.relative_to(ROOT).as_posix())
    return moved


def overlay_out(unstage=True):
    """公開側の作業場所のお客様の社のファイルを非公開の置き場へ戻し、公開側の git から外す（追跡されていれば
    git rm --cached）。重ねて置いた後に消えた・移ったファイルは非公開の置き場からも消す。戻したファイルを返す"""
    import shutil
    b = base()
    if not (b / ".git").is_dir():
        return []
    files = client_files()
    rehomed = rehome_rewrite_before(client_slugs())
    if unstage and rehomed:
        tracked = [x for x in _public_git("ls-files", "--", *rehomed).stdout.splitlines() if x]
        if tracked:
            _public_git("rm", "--cached", "-q", "--", *tracked)
    for rel in files:
        src, dst = ROOT / rel, b / rel
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    prev = _exclude_entries()
    # 消すのは「この作業場所で重ねて置いた」のに作業場所から消えたものだけ。見張りの一覧（info/exclude）は git の
    # 作業場所どうしで共有されるので、別の作業場所が置いた分まで「消えた」と読み、置き場から消していた（2026-10-12、
    # 試しの作業場所で重ね置きした後の commit で、お客様の記事2本・画像・台本を消した。置き場の履歴から戻した）
    mine = _record()
    for rel in prev:
        if rel in mine and not (ROOT / rel).exists() and (b / rel).is_file() \
                and rel.split("/")[0] in ("articles", "site", "data"):
            (b / rel).unlink()
    _write_record([r for r in mine if (ROOT / r).exists()] + files)
    _write_exclude(sorted(set(files) | {r for r in prev if (ROOT / r).exists()}))
    if unstage and files:
        for i in range(0, len(files), 200):
            part = files[i:i + 200]
            tracked = [x for x in _public_git("ls-files", "--", *part).stdout.splitlines() if x]
            if tracked:
                _public_git("rm", "--cached", "-q", "--", *tracked)
    return files


def _scope_dir():
    import tempfile
    return Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())


def _ws():
    """作業場所の印。手元では一時の場所（%TEMP%）を作業場所どうしで共有するので、記録を作業場所ごとに分ける
    （別の作業場所で絞ったままの記録で、本体の置き場の99件を「迷子」としてよけ、push が削除を送りえた。2026-10-12）"""
    import hashlib
    return hashlib.sha1(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:10]


def _scope_state():
    return _scope_dir() / f"private_scope_{_ws()}.json"


def _scope_hidden():
    # 作業場所の外（AI の許可の一覧で読ませない場所。CI では $RUNNER_TEMP）
    return _scope_dir() / f"private_scope_hidden_{_ws()}"


def scope(target):
    """AI が動く間だけ、作業場所に置くお客様の社を target（公開の id・社の id・own）に絞る。all で戻す。

    記事を書く AI は作業場所のファイルを読めるので、全社の原稿・材料・順位を置いたままだと、A社の回の AI が
    B社のまだ公開していない原稿や狙う語を読めた（2026-10-11 運用者「ほかの社の原稿も見られないように」）。
    非公開の置き場は git なので、書きかけを手元で commit してから sparse-checkout で外す（外した分は commit に
    残るので、戻し損ねても消えない。save の push も外した分を消さない）。CI のキャッシュで持ち越した派生データ
    （順位・語・上位の見出し）は、作業場所の外へよけて all で戻す。範囲を絞るのは CI だけ（手元の写しは触らない）
    """
    if target in ("all", ""):
        return widen()
    if not (os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("PRIVATE_SCOPE_FORCE") == "1"):
        print("SCOPE=skip（CI の外では範囲を絞りません。試すときは PRIVATE_SCOPE_FORCE=1）", flush=True)
        return True
    if _scope_state().is_file():
        widen()
    import shutil
    S = _sites()
    keep = set()
    if target != "own":
        sid = S.resolve(target)
        if S.is_client(sid):
            g = S.group_key(sid)
            keep = {c for c in S.load_all() if S.is_client(c) and S.group_key(c) == g} | {sid}
    others = sorted((set(c for c in S.load_all() if S.is_client(c)) | set(known_clients())) - keep)
    by_slug = client_slugs()
    b = base()
    git_ok = (b / ".git").is_dir()
    state = {"target": target, "others": len(others), "hidden": [], "skipped": []}
    try:
        n = _narrow(b, git_ok, others, by_slug, state)
    except Exception as e:
        # 途中で落ちたら全部へ戻す（外した記事を戻し、置き場の sparse を外す）。呼び出し側は AI を起こさない
        _scope_state().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(f"SCOPE=failed（範囲を絞れませんでした: {type(e).__name__}: {str(e)[:120]}。全部へ戻します）", flush=True)
        widen()
        return False
    print(f"SCOPE=narrowed（外した社 {len(others)}・記事などのファイル {n}・派生データ {len(state['hidden'])}）", flush=True)
    return True


def _narrow(b, git_ok, others, by_slug, state):
    """scope の本体。外した記事などのファイルの数を返す。途中で落ちたときに戻せるよう、記録を先に書いて足していく"""
    import shutil
    moved_files = 0
    cats = client_categories()
    if git_ok:
        # 1. 書きかけを非公開の置き場へ写し、手元で commit する（push は最後の save）。絞っても消えないように
        overlay_out(unstage=False)
        _git("add", "-A")
        if _git("diff", "--cached", "--quiet").returncode:
            r = _git("-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                     "commit", "-q", "-m", "CI: 範囲を絞る前の控え")
            if r.returncode:
                raise RuntimeError("控えを commit できません")
        # 途中で落ちたときに widen で戻せるよう、外す前に記録を置く
        _scope_state().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        # 2. 公開側の作業場所から、ほかの社の記事・画像・台本を外す（置き場と同じ中身のものだけ）。記事は category で
        #    見分ける（slug から articles/<slug>.md を組むと、_merged・_conflicted の下のお客様の原稿が残った）
        drop = []

        def _drop(f):
            r = f.relative_to(ROOT).as_posix()
            src = b / r
            if src.is_file() and src.read_bytes() == f.read_bytes():
                f.unlink()
                drop.append(r)

        for q in sorted((ROOT / "articles").rglob("*.md")):
            if cats.get(_category(q)) in others:
                _drop(q)
        for slug, sid in by_slug.items():
            if sid not in others:
                continue
            for t in SLUG_PATHS:
                q = ROOT / t.format(slug)
                for f in ([q] if q.is_file() else ([x for x in q.rglob("*") if x.is_file()] if q.is_dir() else [])):
                    _drop(f)
                if q.is_dir() and not any(q.rglob("*")):
                    shutil.rmtree(q, ignore_errors=True)
        moved_files = len(drop)
        # 外したファイルは commit の見張りの一覧からも外す（残すと、戻す前に保存したとき「消えた」と読まれうる）
        _write_exclude([r for r in _exclude_entries() if r not in set(drop)])
        _write_record([r for r in _record() if r not in set(drop)])
        # 3. 非公開の置き場を絞る。当社の料金・営業の台本・レポートと、お客様の門も AI の間は置かない
        pats = ["/*", "!/sales/", "!/reports/", "!/tests/", "!/security/"]
        pats += [f"!/clients/{c}/" for c in others]
        pats += [f"!/{q.relative_to(b).as_posix()}" for q in sorted((b / "articles").rglob("*.md"))
                 if cats.get(_category(q)) in others]
        for slug, sid in by_slug.items():
            if sid in others:
                pats += [f"!/{t.format(slug)}" + ("/" if not t.endswith(".json") else "") for t in SLUG_PATHS]
        r = subprocess.run(["git", "-C", str(b), "sparse-checkout", "set", "--no-cone", "--stdin"],
                           input="\n".join(pats) + "\n", capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            raise RuntimeError(f"非公開の置き場を絞れません: {(r.stderr or '').strip()[-120:]}")
        # 無視されたファイル（門の __pycache__ に社の内部名と中身が残る）は sparse-checkout では消えない
        for d in list(b.rglob("__pycache__")):
            shutil.rmtree(d, ignore_errors=True)
        # 外したファイルの一覧を控える（戻すとき、外した場所へ書かれたものを見つけるため。git は作業場所に現れた
        # ファイルの「外した」印を自分で消すので、戻す時点の印では見つけられない）。日本語の名前を引用の形にしない
        state["skipped"] = [ln[2:] for ln in _git("-c", "core.quotePath=false", "ls-files", "-t").stdout.splitlines()
                            if ln.startswith("S ")]
    # 4. キャッシュで持ち越した派生データ（data/clients/<社>/ と社ごとの記録）を作業場所の外へよける
    import client_private as CP
    hidden = state["hidden"]
    hid = _scope_hidden()
    for c in others:
        rels = [f"data/clients/{c}"] + [p.format(c) for ps in CP.PER_SITE.values() for p in ps]
        for rel in rels:
            q = ROOT / rel
            if q.exists():
                dst = hid / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
                shutil.move(str(q), str(dst))
                hidden.append(rel)
    _scope_state().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return moved_files


def widen():
    """scope で絞った範囲を戻す（非公開の置き場を全部に戻して重ね直し、よけた派生データを戻す）"""
    import shutil
    st = _scope_state()
    if not st.is_file():
        print("SCOPE=all", flush=True)
        return True
    try:
        state = json.loads(st.read_text(encoding="utf-8"))
    except ValueError:
        state = {}
    b = base()
    if (b / ".git").is_dir():
        # 絞っている間に、外した場所へ書かれたファイルがあれば、戻す前に作業場所の外へよける（戻すと commit 済みの
        # その社の中身を上書きし、次の保存でその社の分を書き換えてしまう）
        stray = [r for r in state.get("skipped") or [] if (b / r).is_file()]
        for r in stray:
            dst = _scope_dir() / f"private_scope_stray_{_ws()}" / r
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(b / r), str(dst))
        if stray:
            print(f"要対応: 範囲を絞っている間に、外した社の場所へ書かれたファイルが {len(stray)}件ありました"
                  "（上書きせずに作業場所の外へよけました）", flush=True)
        _git("sparse-checkout", "disable")
        overlay_in(mark=False)
    back, kept = 0, 0
    hid = _scope_hidden()
    for rel in state.get("hidden") or []:
        src, dst = hid / rel, ROOT / rel
        if not src.exists():
            continue
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        elif src.is_dir():
            # 絞っている間に同じ場所へ書かれたものは残し、無いものだけ戻す
            for f in src.rglob("*"):
                t = dst / f.relative_to(src)
                if f.is_file() and not t.exists():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(t))
            kept += 1
        else:
            kept += 1
        back += 1
    shutil.rmtree(hid, ignore_errors=True)
    st.unlink()
    print(f"SCOPE=all（戻した派生データ {back}" + (f"・同じ場所に新しいものがあり残したもの {kept}" if kept else "") + "）",
          flush=True)
    return True


def install_hook():
    """公開側の .git/hooks/pre-commit に、お客様の社のファイルを commit に入れない見張りを置く"""
    p = _git_path("hooks/pre-commit")
    if not p:
        return False
    if p.is_file() and "private_store" not in p.read_text(encoding="utf-8", errors="ignore"):
        print("  ! pre-commit の hook が別にあるため入れません（scripts/private_store.py --pre-commit を足してください）")
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HOOK, encoding="utf-8", newline="\n")
    try:
        os.chmod(p, 0o755)
    except OSError:
        pass
    return True


def pre_commit():
    """公開側の commit の直前（hook）。お客様の社のファイルを非公開の置き場へ戻して commit から外し、残っていれば止める"""
    files = []
    if (base() / ".git").is_dir():
        files = overlay_out(unstage=True)
        staged = set(_public_git("diff", "--cached", "--name-only").stdout.splitlines())
        left = sorted(staged & set(files))
        if left:
            print(f"お客様の社のファイル {len(left)}件が公開側の commit に入ろうとしています。止めます", file=sys.stderr)
            return 1
    # お客様の社の記事を外した後に、まだ新しく入る記事のうち自社のカテゴリでないもの（カテゴリを書き違えたお客様の記事・
    # 範囲を絞って社の決まらない記事）を止める。非公開の置き場が無い回も見る
    bad = foreign_new_articles()
    if bad:
        print(f"自社のカテゴリでない新しい記事 {len(bad)}件が公開側の commit に入ろうとしています。止めます"
              "（カテゴリを確かめてください。お客様の記事なら非公開の置き場へ）", file=sys.stderr)
        return 1
    if files:
        push("公開側の commit の前に、お客様の社の記事・画像・台本を残す")
    return 0


def foreign_new_articles():
    """公開側に新しく入る（staged の追加）articles/**/*.md のうち、自社のカテゴリでないもの"""
    S = _sites()
    own = {c for sid, cfg in S.load_all().items() if not S.is_client(sid) for c in (cfg.get("categories") or {})}
    added = _public_git("-c", "core.quotePath=false", "diff", "--cached", "--name-only", "--diff-filter=A").stdout
    return [x for x in added.splitlines()
            if x.startswith("articles/") and x.endswith(".md") and (ROOT / x).is_file() and _category(ROOT / x) not in own]


_CLIENT_SLUGS = None


def client_slug(slug):
    """お客様の社の記事か（1回の実行の中では覚えておく。記事の頭を全部読むため）"""
    global _CLIENT_SLUGS
    if _CLIENT_SLUGS is None:
        try:
            _CLIENT_SLUGS = set(client_slugs())
        except Exception:
            _CLIENT_SLUGS = set()
    return str(slug) in _CLIENT_SLUGS


def shown(slug):
    """CI のログに出す記事の名前。お客様の社の記事は slug を出さない（CI のログは public。件数で数える）"""
    return "（お客様の記事）" if client_slug(slug) else slug


def private_git(*args):
    """非公開の置き場で同じ git を動かした出力（記事の記録を公開側と合わせて読む。無ければ空）"""
    if not (base() / ".git").is_dir():
        return ""
    return _git(*args).stdout or ""


def tracked(rel):
    """公開側か非公開の置き場のどちらかの git で追跡されているか"""
    if _public_git("ls-files", "--error-unmatch", "--", rel).returncode == 0:
        return True
    return bool((base() / ".git").is_dir() and _git("ls-files", "--error-unmatch", "--", rel).returncode == 0)


def _base_sha():
    try:
        return (base() / ".git" / "ss_base").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def client_changes(added_only=False):
    """この回（重ねて置いた後）に書いた・直したお客様の社のファイルの相対パス。added_only なら新しく足したものだけ"""
    sha = _base_sha()
    out = set()
    if sha:
        flt = ["--diff-filter=A"] if added_only else []
        out |= {x for x in private_git("diff", "--name-only", *flt, sha, "HEAD").splitlines() if x}
    for rel in client_files():
        dst = base() / rel
        if added_only:
            known = (_git("cat-file", "-e", f"{sha}:{rel}").returncode == 0) if sha else dst.is_file()
            if not known:
                out.add(rel)
        elif not dst.is_file() or dst.read_bytes() != (ROOT / rel).read_bytes():
            out.add(rel)
    return sorted(out)


# ── 移行（古い場所 → private/） ────────────────────────────────

def migrate(sid):
    """古い場所の材料と、sites/<社の id>.json の設定を private/ へ移す。公開側には社が特定できない印
    （sites/<公開の id>.json）だけを置き、古い sites/<社の id>.json は消す（git rm は呼び出し側）。移したファイルの一覧を返す"""
    S = _sites()
    moved = []
    for name in ("company.json", "brief.json", "facts.json", "private.json", "kw.md"):
        old = _legacy(sid, name)
        if old.is_file() and not (client_dir(sid) / name).is_file():
            moved.append(write_text(sid, name, old.read_text(encoding="utf-8")))
    old = S.SITES_DIR / f"{sid}.json"
    raw = json.loads(old.read_text(encoding="utf-8-sig")) if old.is_file() else {}
    full = {**site_private(sid), **{k: v for k, v in raw.items() if k != "client"}, "id": sid}
    full["public_id"] = full.get("public_id") if full.get("public_id") not in (None, sid) else new_public_id()
    moved += write_site(full, S.SITES_DIR)
    if old.is_file() and full["public_id"] != sid:
        old.unlink()
    return moved


def status():
    print(f"PRIVATE_DIR={'yes' if available() else 'no'}")
    S = _sites()
    for sid in [s for s in S.load_all() if S.is_client(s)]:
        have = [n for n in CLIENT_FILES if client_path(sid, n).is_file()]
        print(f"  {S.public_id(sid)}: 材料 {len(have)}/{len(CLIENT_FILES)} 件（{', '.join(have) or 'なし'}）")
    sales = base() / "sales"
    print(f"  料金と営業の台本: {len([p for p in sales.rglob('*') if p.is_file()]) if sales.is_dir() else 0} 件")
    rep = base() / "reports"
    print(f"  レポート: {len([p for p in rep.rglob('*') if p.is_file()]) if rep.is_dir() else 0} 件")


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if "--fetch" in a:
        return 0 if fetch() else 0       # 取れなくても止めない（お客様の工程が require で止まる）
    if "--scopes" in a:               # 範囲ごとに AI を回す回の範囲の一覧（own と、お客様の社の公開の id。1行に1つ）
        S = _sites()
        for x in ["own"] + sorted(S.public_id(c) for c in S.load_all() if S.is_client(c)):
            print(x)
        return 0
    if "--scope" in a:                # AI の間だけお客様の社を絞る（all で戻す）。止まらない（印で知らせる）
        i = a.index("--scope")
        return 0 if scope(a[i + 1] if i + 1 < len(a) else "all") else 1
    if "--push" in a:
        i = a.index("--push")
        msg = a[i + 1] if i + 1 < len(a) else "管制塔から更新"
        widen()                       # 絞ったまま保存しない（外した社の分を見張りの一覧から落とさない）
        return 0 if push(msg) else 1
    if "--pre-commit" in a:
        return pre_commit()
    if "--overlay" in a:              # 手元: 取得し直さずに重ねて置くだけ・hook を入れるだけ
        _after_fetch()
        return 0
    if "--is-client" in a:
        print("yes" if is_client(a[a.index("--is-client") + 1]) else "no")
        return 0
    if "--shown" in a:                # ワークフローがログに出す記事の名前（お客様の記事は slug を出さない）
        print(shown(a[a.index("--shown") + 1]))
        return 0
    if "--resolve" in a:              # 公開の id → 社の id（記事の枠が select から受け取った id を戻す）
        print(_sites().resolve(a[a.index("--resolve") + 1]))
        return 0
    if "--public-id" in a:
        print(_sites().public_id(a[a.index("--public-id") + 1]))
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
            print(f"  書いた: {p.name}（{'非公開' if base() in p.parents else '公開側の印'}）")
        return 0
    if "--status" in a:
        status()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
