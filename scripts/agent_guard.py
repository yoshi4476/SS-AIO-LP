# -*- coding: utf-8 -*-
"""AI（claude）を動かす手順から鍵を外し、終わったら戻す。AI が書いた記事の配信は、鍵を持つ機械の手順が行う。

記事を書く AI は外の文章（YouTube の字幕・検索上位の見出し・AI の答え）を読む。そこに仕込まれた指示に従うと、
手順の環境変数・作業場所のファイル（Google の鍵・git に残った push の鍵）を外へ持ち出せた（2026-10-11 運用者の指示で塞ぐ）。
AI の手順には AI 用の鍵（claude の鍵と、台帳の操作だけ通る管制塔の合言葉）だけを渡し、ファイルの鍵はこの道具が外す。

  python scripts/agent_guard.py --lock      # AI の前（鍵のある手順）: 鍵のファイルと git の資格を外し、Google は読むだけの許可証に置き換える
  python scripts/agent_guard.py --verify    # AI の手順の先頭（鍵の無い手順）: 外れていなければ AI を動かさない（終了コード1）
  python scripts/agent_guard.py --protect   # AI の後: AI が触ってはいけない場所（コード・ワークフロー・門・指示）の変更を戻す
  python scripts/agent_guard.py --unlock    # AI の後（鍵のある手順）: 鍵のファイルと git の資格を戻す
  python scripts/agent_guard.py --publish   # AI の後（鍵のある手順）: AI が書いた新しい記事を配信する

--lock / --unlock / --protect / --publish は CI（GITHUB_ACTIONS=true）でだけ動く（手元の鍵と .env を消さないため）。
記録（$RUNNER_TEMP/agent_guard.json）には鍵の値を書かない。
"""
import argparse
import base64
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(os.environ.get("AGENT_GUARD_ROOT") or Path(__file__).resolve().parent.parent)
SA = "indexing-service-account.json"
# 許可証で読める範囲。台帳（Sheets）は入れない（問い合わせのお名前・メール・電話が読めてしまう）
TOKEN_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly",
                "https://www.googleapis.com/auth/analytics.readonly"]
# ワークフローが鍵から書き出すファイル（作業場所の直下・ホーム）。戻すときに使う環境変数
SECRET_FILES = {
    "youtube-token.json": "YOUTUBE_TOKEN_JSON", "youtube-client.json": "YOUTUBE_CLIENT_JSON",
    "youtube-token-*.json": "YOUTUBE_TOKENS_JSON", "gbp-client.json": "GBP_CLIENT_JSON",
    "gbp-token-*.json": "GBP_TOKENS_JSON", "ftp-credentials.json": "FTP_CREDENTIALS_JSON",
    "wp-credentials.json": "WP_CREDENTIALS_JSON", "sheets-token.json": "", "credentials.json": "",
}
HOME_SECRET_FILES = {".codex/auth.json": "CODEX_AUTH_JSON", ".git-credentials": ""}
# AI の手順に置いてよい鍵（claude の鍵と、台帳の操作だけ通る管制塔の合言葉）
AGENT_ENV_OK = {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "HUB_SECRET"}
# あれば AI を動かさない鍵（ワークフローが渡す名前）。ほかの「鍵らしい名前」は知らせるだけにする
# （ランナーが足した見知らぬ変数1つで、その日の記事が止まらないように）
KNOWN_SECRETS = {
    "SITE_PUSH_TOKEN", "PRIVATE_DATA_TOKEN", "FTP_CREDENTIALS_JSON", "WP_CREDENTIALS_JSON", "GCP_SERVICE_ACCOUNT_JSON",
    "SA_JSON", "BING_WEBMASTER_API_KEY", "FB_PAGE_TOKEN", "THREADS_TOKEN", "LINKEDIN_TOKEN", "LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_REFRESH_TOKEN", "SOCIAL_TOKENS_JSON", "X_BEARER_TOKEN", "YOUTUBE_API_KEY", "YOUTUBE_CLIENT_JSON",
    "YOUTUBE_TOKEN_JSON", "YOUTUBE_TOKENS_JSON", "GEMINI_API_KEY", "GEMINI_API_KEY_PAID", "OPENAI_API_KEY",
    "PERPLEXITY_API_KEY", "XAI_API_KEY", "CLAUDE_CITE_API_KEY", "RAKKO_API_KEY", "RESEND_API_KEY",
    "CLOUDFLARE_API_TOKEN", "CODEX_AUTH_JSON", "GH_SECRET_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "TURNSTILE_SECRET",
    "WP_BRIDGE_SIGN_KEY", "GBP_CLIENT_JSON", "GBP_TOKENS_JSON", "PAGESPEED_API_KEY", "SLACK_WEBHOOK_URL",
    "HUB_FORM_SECRET", "HUB_AGENT_SECRET", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_RUNTIME_TOKEN",
}
SECRETISH = re.compile(r"(TOKEN|SECRET|PASSWORD|_KEY|_JSON|CREDENTIALS)$")
# AI が触ってはいけない場所。記事の AI が変えても、配信・コミットの前に元へ戻す
PROTECTED = ["scripts", "tests", ".github", ".claude", "templates", "tools", "automation/gas", "automation/wordpress",
             "CLAUDE.md", "PROJECT.md", "requirements.txt", "package.json", "package-lock.json",
             "automation/*.txt", "automation/agent_settings_*.json"]
# 自動修復の AI はコードを直すのが仕事なので、守るのは鍵の外し方そのものだけ
PROTECTED_JAIL = ["scripts/agent_guard.py", "scripts/gcreds.py", "automation/agent_settings_*.json", ".claude",
                  "tests/gates_history_h91_agent_jail.py", ".github"]


def child_env(env=None):
    """道具の中から呼ぶ AI（claude -p）に渡す環境変数。呼ばれた AI は手順の環境変数をそのまま受け継ぎ、
    読み取りのコマンド（echo・cat）は許可なしで動くので、鍵の名前の変数を外して渡す（claude の鍵だけ残す）"""
    env = dict(os.environ if env is None else env)
    keep = {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"}
    return {k: v for k, v in env.items()
            if k in keep or not (k.upper() in KNOWN_SECRETS or k.upper() == "HUB_SECRET" or SECRETISH.search(k.upper()))}


def _ci():
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("AGENT_GUARD_FORCE") == "1"


def _state_path():
    return Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "agent_guard.json"


def _load_state():
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def repos(root=None):
    """鍵が残りうる git の作業場所（管制塔・非公開の置き場・配信先の作業コピー）"""
    root = Path(root or ROOT)
    out = [root] if (root / ".git").exists() else []
    if (root / "private" / ".git").exists():
        out.append(root / "private")
    work = root / ".publish-work"
    if work.is_dir():
        out += sorted(p for p in work.iterdir() if (p / ".git").exists())
    return out


def _headers(repo):
    """[(設定ファイル, 名前)] — 認証の見出し（AUTHORIZATION）を持つ extraheader"""
    r = _git(repo, "config", "--show-origin", "--null", "--get-regexp", r"^http\..*\.extraheader$")
    out = []
    parts = r.stdout.split("\0")
    for i in range(0, len(parts) - 1, 2):
        origin, kv = parts[i], parts[i + 1]
        key, _, val = kv.partition("\n")
        if "authorization" in val.lower() and origin.startswith("file:"):
            out.append((origin[5:], key))
    return out


def _cred_remotes(repo):
    """[(名前, URL)] — 資格が URL に入った remote"""
    out = []
    for ln in _git(repo, "remote", "-v").stdout.splitlines():
        m = re.match(r"(\S+)\s+(https://[^/@\s]+@\S+)\s+\(fetch\)", ln)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _token_env(repo, root):
    repo, root = Path(repo), Path(root)
    if repo == root:
        return "GITHUB_TOKEN"
    if repo == root / "private":
        return "PRIVATE_DATA_TOKEN"
    return "SITE_PUSH_TOKEN"


def _secret_files(root=None):
    root = Path(root or ROOT)
    out = []
    for pat, env in SECRET_FILES.items():
        out += [(p, env) for p in root.glob(pat) if p.is_file()]
    home = Path(os.environ.get("AGENT_GUARD_HOME") or Path.home())
    for rel, env in HOME_SECRET_FILES.items():
        p = home / rel
        if p.is_file():
            out.append((p, env))
    return out


def _sa_is_key(root=None):
    p = Path(root or ROOT) / SA
    try:
        return p.is_file() and "private_key" in p.read_text(encoding="utf-8-sig")
    except Exception:
        return False


def _articles(root=None):
    root = Path(root or ROOT)
    return {p.stem: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted((root / "articles").glob("*.md"))}


def _mint_token(info):
    """鍵から、読むだけ・1時間で切れる許可証を作る（鍵そのものは AI の作業場に残さない）"""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    import gcreds
    c = service_account.Credentials.from_service_account_info(info, scopes=TOKEN_SCOPES)
    c.refresh(Request())
    exp = c.expiry.replace(tzinfo=timezone.utc).isoformat() if c.expiry else ""
    return {"type": gcreds.TOKEN_TYPE, "token": c.token, "scopes": TOKEN_SCOPES, "expiry": exp}


def _write_token(path, tok):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tok), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def refresher(root=None, every=2400, life=8 * 3600):
    """許可証を40分ごとに作り直す（許可証は1時間で切れ、救済・週次の AI は1時間を超えることがある）。
    鍵は標準入力で受け取り、環境変数にもファイルにも置かない（このプロセスの環境変数は AI から読めるため、
    呼ぶ側は env -i で空にして起こす）。--unlock が置く止めの印か、life 秒で終わる"""
    import time
    root = Path(root or ROOT)
    info = json.loads(sys.stdin.read().lstrip("﻿"))
    stop = _state_path().with_suffix(".stop")
    start = time.time()
    while time.time() - start < life and not stop.exists():
        for _ in range(every // 10):
            time.sleep(10)
            if stop.exists():
                return
        try:
            _write_token(root / SA, _mint_token(info))
        except Exception:
            pass


def lock(root=None, mint=True):
    root = Path(root or ROOT)
    _state_path().with_suffix(".stop").unlink(missing_ok=True)
    st = {"articles": _articles(root), "headers": [], "remotes": [], "files": [], "sa": "none"}
    # Google の鍵 → 読むだけの許可証（鍵の元: 作業場所のファイルか、この手順の環境変数）
    sa_path = root / SA
    info = None
    if _sa_is_key(root):
        info = json.loads(sa_path.read_text(encoding="utf-8-sig"))
        st["sa"] = "file"
    elif os.environ.get("GCP_SERVICE_ACCOUNT_JSON"):
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT_JSON"].lstrip("﻿"))
    if info and mint:
        try:
            tok = _mint_token(info)
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::add-mask::{tok['token']}", flush=True)
            _write_token(sa_path, tok)
            st["token"] = True
        except Exception as e:
            print(f"  Google の許可証を作れませんでした（{type(e).__name__}）。AI の手順では検索の実績を読みません", flush=True)
            if sa_path.exists():
                sa_path.unlink()
    elif sa_path.exists() and _sa_is_key(root):
        sa_path.unlink()
    # ファイルの鍵
    for p, env in _secret_files(root):
        p.unlink()
        st["files"].append({"path": str(p), "env": env})
    # git に残った資格（checkout と非公開の置き場の取得が設定に書く）
    for repo in repos(root):
        for cfg, key in _headers(repo):
            # 設定ファイルの場所は作業場所からの相対で返ることがある
            _git(repo, "config", "--file", cfg, "--unset-all", key)
            st["headers"].append({"repo": str(repo), "key": key, "env": _token_env(repo, root)})
        for name, url in _cred_remotes(repo):
            clean = re.sub(r"^https://[^/@]+@", "https://", url)
            _git(repo, "remote", "set-url", name, clean)
            st["remotes"].append({"repo": str(repo), "name": name, "url": clean, "env": _token_env(repo, root)})
    _save_state(st)
    print(f"AGENT_LOCK=ok（記事 {len(st['articles'])}本を控え・Google: {'許可証' if st.get('token') else 'なし'}・"
          f"鍵のファイル {len(st['files'])}・git の資格 {len(st['headers']) + len(st['remotes'])} を外しました）", flush=True)
    return st


def problems(root=None, env=None):
    """AI を動かしてよいか。外れていない鍵の名前（値は出さない）"""
    root = Path(root or ROOT)
    env = os.environ if env is None else env
    out = [f"環境変数 {k}" for k, v in sorted(env.items()) if v and k in KNOWN_SECRETS]
    if _sa_is_key(root):
        out.append(f"{SA} が鍵のまま")
    out += [f"鍵のファイル {p.name}" for p, _env in _secret_files(root)]
    for repo in repos(root):
        rel = os.path.relpath(repo, root)
        out += [f"git の資格（{rel}: {key}）" for _cfg, key in _headers(repo)]
        out += [f"git の資格（{rel}: remote {name}）" for name, _url in _cred_remotes(repo)]
    g = subprocess.run(["git", "config", "--global", "--get-regexp", r"^http\..*\.extraheader$"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "authorization" in g.stdout.lower():
        out.append("git の資格（global）")
    return out


def suspects(env=None):
    """鍵らしい名前だが一覧に無い環境変数（止めずに知らせる）"""
    env = os.environ if env is None else env
    return sorted(k for k, v in env.items()
                  if v and SECRETISH.search(k) and k not in AGENT_ENV_OK and k not in KNOWN_SECRETS)


def verify(root=None):
    sus = suspects()
    if sus:
        print("  鍵らしい名前の環境変数（AI は止めません。鍵なら AI の手順から外してください）: " + " / ".join(sus), flush=True)
    bad = problems(root)
    if bad:
        print("AGENT_JAIL=ng（AI の手順に鍵が残っています。AI を動かしません）: " + " / ".join(bad), flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=AI の作業場に鍵が残っています::" + " / ".join(bad), flush=True)
        return False
    print("AGENT_JAIL=ok", flush=True)
    return True


def _header(tok):
    b64 = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{b64}", flush=True)
    return f"AUTHORIZATION: basic {b64}"


def _tok(env):
    if env == "PRIVATE_DATA_TOKEN":
        return os.environ.get("PRIVATE_DATA_TOKEN") or os.environ.get("SITE_PUSH_TOKEN") or ""
    return os.environ.get(env) or ""


def unlock(root=None):
    root = Path(root or ROOT)
    st = _load_state()
    stop = _state_path().with_suffix(".stop")
    stop.write_text("stop", encoding="utf-8")      # 許可証の作り直しを止める
    miss = []
    sa_path = root / SA
    if os.environ.get("GCP_SERVICE_ACCOUNT_JSON") and st.get("sa") == "file":
        sa_path.write_text(os.environ["GCP_SERVICE_ACCOUNT_JSON"], encoding="utf-8")
        os.chmod(sa_path, 0o600)
    elif sa_path.exists():
        # 許可証は1時間で切れる。残すと後の工程が鍵と取り違える（後の工程は自分で鍵を書き出す）
        try:
            if json.loads(sa_path.read_text(encoding="utf-8-sig")).get("type") != "service_account":
                sa_path.unlink()
        except Exception:
            sa_path.unlink()
    for f in st.get("files", []):
        val = os.environ.get(f["env"] or "", "")
        p = Path(f["path"])
        if not val:
            miss.append(p.name)
            continue
        if f["env"] in ("YOUTUBE_TOKENS_JSON", "GBP_TOKENS_JSON"):
            m = re.match(r"(.*-)(.+)\.json$", p.name)
            try:
                p.write_text(json.dumps(json.loads(val)[m.group(2)]), encoding="utf-8")
            except Exception:
                miss.append(p.name)
                continue
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(val, encoding="utf-8")
        os.chmod(p, 0o600)
    for h in st.get("headers", []):
        tok = _tok(h["env"])
        if not tok:
            miss.append(f"git の資格（{os.path.relpath(h['repo'], root)}）")
            continue
        _git(h["repo"], "config", "--local", h["key"], _header(tok))
    for r in st.get("remotes", []):
        tok = _tok(r["env"])
        if not tok:
            miss.append(f"git の資格（{os.path.relpath(r['repo'], root)}: {r['name']}）")
            continue
        _git(r["repo"], "remote", "set-url", r["name"], r["url"].replace("https://", f"https://x-access-token:{tok}@", 1))
    print("AGENT_UNLOCK=" + ("ok" if not miss else "partial（戻せなかったもの: " + " / ".join(miss) + "）"), flush=True)
    return not miss


def _match(rel, pats):
    """段ごとに照合する（fnmatch の * は / もまたぐので、automation/*.txt が automation/logs/ の中まで当たる）"""
    parts = rel.replace("\\", "/").split("/")
    for p in pats:
        pp = p.split("/")
        if len(parts) >= len(pp) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pp)) \
                and (len(parts) == len(pp) or "*" not in pp[-1]):
            return True
    return False


def protect(root=None, scope="article"):
    """AI が触ってはいけない場所の変更を戻す。戻した場所（パス）を返す"""
    root = Path(root or ROOT)
    pats = PROTECTED if scope == "article" else PROTECTED_JAIL
    back = []
    for ln in _git(root, "status", "--porcelain", "-uall").stdout.splitlines():
        code, rel = ln[:2], ln[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        if not _match(rel, pats):
            continue
        if code == "??":
            (root / rel).unlink(missing_ok=True)
        else:
            _git(root, "checkout", "HEAD", "--", rel)
        back.append(rel)
    if back:
        print(f"AGENT_PROTECT=restored（AI が触ってはいけない場所 {len(back)}件を元に戻しました）: " + " / ".join(back[:10]),
              flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning::AI が触ってはいけない場所を変えていたため、元に戻しました（{len(back)}件）", flush=True)
    else:
        print("AGENT_PROTECT=ok", flush=True)
    return back


def changes(root=None):
    """(新しい記事, 中身が変わった記事) — lock の控えと今の articles/ を比べる"""
    st = _load_state()
    before = st.get("articles") or {}
    now = _articles(root)
    new = sorted(s for s in now if s not in before)
    changed = sorted(s for s in now if s in before and now[s] != before[s])
    return new, changed


def _site_of(slug, root=None):
    sys.path.insert(0, str(Path(root or ROOT) / "scripts"))
    import sites as S
    text = (Path(root or ROOT) / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")[:4000]
    m = re.search(r"^category:\s*[\"']?([^\"'\n]+)", text, re.M)
    return S.find_category_owner(m.group(1).strip()) if m else None


def publish(root=None):
    """AI が書いた新しい記事を publish_flow で配信し、中身の変わった別リポジトリの社の記事を配り直す"""
    root = Path(root or ROOT)
    sys.path.insert(0, str(root / "scripts"))
    import private_store as PS
    import sites as S
    new, changed = changes(root)
    res = {"published": 0, "held": 0, "failed": 0}
    py = sys.executable
    for slug in new:
        site = _site_of(slug, root)
        name = PS.shown(slug)
        if not site:
            print(f"   × {name}: カテゴリから配信先のサイトが決まりません", flush=True)
            res["failed"] += 1
            continue
        r = subprocess.run([py, "scripts/publish_flow.py", site, slug], cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        quiet = S.is_client(site)
        if re.search(r"^HELD\(監修待ち\)", out, re.M):
            res["held"] += 1
            print(f"   … {name}: 監修待ち", flush=True)
        elif r.returncode == 0:
            res["published"] += 1
            print(f"   ○ {name}: 公開しました", flush=True)
        else:
            res["failed"] += 1
            print(f"   × {name}: 公開できませんでした（終了コード {r.returncode}）", flush=True)
        if not quiet:
            print("\n".join("     " + x for x in out.strip().splitlines()[-12:]), flush=True)
    ext = sorted({s for s in (_site_of(x, root) for x in changed) if s and S.load(s).get("type") != "self-static"})
    for site in ext:
        r = subprocess.run([py, "scripts/publish_changed.py", "--site", site, "--push"], cwd=root, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        print(f"   配り直し（{S.public_id(site) if hasattr(S, 'public_id') else site}）: 終了コード {r.returncode}", flush=True)
    print(f"AGENT_PUBLISH={'ng' if res['failed'] else 'ok'}（新しい記事 {len(new)}本: 公開 {res['published']}・"
          f"監修待ち {res['held']}・失敗 {res['failed']} / 中身の変わった記事 {len(changed)}本・配り直し {len(ext)}サイト）",
          flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    for f in ("lock", "verify", "unlock", "protect", "publish", "refresh"):
        g.add_argument(f"--{f}", action="store_true")
    ap.add_argument("--scope", default="article", choices=["article", "jail"])
    a = ap.parse_args()
    if a.verify:
        return 0 if verify() else 1
    if a.refresh:
        refresher()
        return 0
    if not _ci():
        print("CI の外では動かしません（手元の鍵と .env を消さないため）。試すときは AGENT_GUARD_FORCE=1", flush=True)
        return 0
    if a.lock:
        lock()
    elif a.unlock:
        unlock()
    elif a.protect:
        protect(scope=a.scope)
    elif a.publish:
        publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
