# -*- coding: utf-8 -*-
"""過去の誤りのうち、通信や GitHub API が要るものを確かめる（運用・ワークフロー・鍵・GAS・外部API）。

オフラインで確かめられる門は tests/gates_history_d.py にある。ここは外へ聞かないと分からないものだけ。

  1. ワークフローが使う鍵が GitHub Secrets に入っているか（2026-09-26 引用実測の鍵が .env にしか無く CI で空振り）
  2. 管制塔（Apps Script）の公開中の版が、リポジトリの .gs と同じか（2026-08-04 / 08-25 / 09-21 直しても配備されず本番が古いまま）
  3. 外部AIのモデル名・入口が生きているか（2026-09-23 gemini-2.5-flash が404、09-26 Perplexity の旧入口が403。
     まとめて「失敗」と出て原因が分からなかった）。課金の無いモデル照会だけを使う
  4. 配信先リポジトリの本体に next/font/google の import が無いか（2026-09-29 CI のビルドが外部取得で落ちた）

使い方:
    python scripts/history_checks_d.py

見つかったら「要対応: …」と HISTD_OK=no を出して 0 で終わる。動けなかったときだけ 1。
鍵の値は出さない（名前と HTTP の状態だけ）。
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

UA = "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"

# 無ければ使わない作りの鍵。無いことを要対応にはしない（入れると執筆が従量課金に切り替わる鍵もある）
OPTIONAL = {"ANTHROPIC_API_KEY", "SLACK_WEBHOOK_URL", "CLAUDE_CITE_API_KEY", "XAI_API_KEY",
            "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GBP_CLIENT_JSON", "GBP_TOKENS_JSON",
            "CODEX_AUTH_JSON", "X_BEARER_TOKEN"}
SNS_PREFIX = ("FB_", "IG_", "LINKEDIN_", "THREADS_", "SOCIAL_TOKENS")


def _env(key):
    import ai_cite_check
    return ai_cite_check._env(key)


def workflow_secrets():
    out = set()
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        out |= set(re.findall(r"secrets\.([A-Z0-9_]+)", p.read_text(encoding="utf-8")))
    return out - {"GITHUB_TOKEN"}


def check_secrets(found):
    if not shutil.which("gh"):
        print("  GitHub Secrets: gh が無いため確かめられません")
        return
    r = subprocess.run(["gh", "secret", "list", "--json", "name"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        print(f"  GitHub Secrets: 一覧を取れません（{(r.stderr or '').strip()[:80]}）")
        return
    have = {d["name"] for d in json.loads(r.stdout or "[]")}
    miss = sorted(workflow_secrets() - have)
    need = [m for m in miss if m not in OPTIONAL]
    print(f"  GitHub Secrets: ワークフローが使う {len(workflow_secrets())}件のうち未登録 {len(miss)}件"
          + (f"（任意: {', '.join(m for m in miss if m in OPTIONAL)}）" if miss else ""))
    # SNS の鍵はつなぐ作業（social_connect.py）でまとめて入る。1件ずつ並べると他の要対応が埋もれる
    sns = [m for m in need if m.startswith(SNS_PREFIX)]
    if sns:
        found.append(f"要対応: SNS の鍵 {len(sns)}件が GitHub Secrets に無く、CI から投稿されません"
                     f"（{', '.join(sns[:4])}…）→ python scripts/social_connect.py")
    for m in (m for m in need if not m.startswith(SNS_PREFIX)):
        found.append(f"要対応: ワークフローが secrets.{m} を使うのに GitHub Secrets にありません"
                     f"（python scripts/set_secrets.py --apply で .env と同時に入れる）")


def same_source(a, b):
    """改行コードと行末の空白だけの違いは同じとみなす（Apps Script が CRLF を LF に変えることがある）"""
    norm = lambda s: "\n".join(l.rstrip() for l in str(s).replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))
    return norm(a) == norm(b)


def check_gas(found):
    import gas_deploy as G
    if not G.CLASPRC.is_file():
        print("  管制塔の版: clasp の認証が無いため確かめられません")
        return
    e = G.env()
    try:
        tok = G.token()
    except Exception as ex:
        print(f"  管制塔の版: 認証を更新できません（{str(ex)[:60]}）")
        return
    for site, cfg in G.TARGETS.items():
        sid = e.get(cfg["env"], "")
        if not sid:
            print(f"  管制塔の版: {cfg['name']} は {cfg['env']} が未設定のため飛ばします")
            continue
        try:
            deps = G.api(tok, f"projects/{sid}/deployments").get("deployments", [])
            vers = sorted({d.get("deploymentConfig", {}).get("versionNumber") for d in deps} - {None})
            if not vers:
                print(f"  管制塔の版: {cfg['name']} は公開中のデプロイがありません")
                continue
            live = G.api(tok, f"projects/{sid}/content?versionNumber={vers[-1]}")
        except Exception as ex:
            print(f"  管制塔の版: {cfg['name']} に接続できません（{str(ex)[:60]}）")
            continue
        files = {f["name"]: f.get("source", "") for f in live.get("files", [])}
        stale = []
        for local, remote in cfg["files"]:
            name = remote.rsplit(".", 1)[0]
            want = G.fill((ROOT / local).read_text(encoding="utf-8"), e)
            if name not in files:
                stale.append(f"{local}（未配備）")
            elif not same_source(files[name], want):
                stale.append(local)
        print(f"  管制塔の版: {cfg['name']} v{vers[-1]} " + ("一致" if not stale else f"食い違い {len(stale)}件"))
        if stale:
            found.append(f"要対応: {cfg['name']} の公開中の版がリポジトリと違います（{', '.join(stale)}）"
                         f"→ python scripts/gas_deploy.py {site}")


def _model(src, pattern, default):
    m = re.search(pattern, src)
    return m.group(1) if m else default


def _call(url, headers=None, body=None, method=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"User-Agent": UA, "Content-Type": "application/json",
                                                         **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, ""
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8", "ignore")[:200].replace("\n", " ")
    except Exception as ex:
        return 0, str(ex)[:120]


def engine_probes():
    """(名前, 鍵の名前, モデル, 呼び出し, 生きているとみなす状態)。課金の無い照会だけ"""
    src = (ROOT / "scripts" / "ai_cite_check.py").read_text(encoding="utf-8")
    oa = _model(src, r'"model":\s*"(gpt-[^"]+)"', "gpt-4.1-mini")
    gm = _env("GEMINI_MODEL") or _model(src, r'GEMINI_MODEL"\)\s*or\s*"([^"]+)"', "")
    an = _env("ANTHROPIC_MODEL") or _model(src, r'ANTHROPIC_MODEL"\)\s*or\s*"([^"]+)"', "")
    xm = _env("XAI_MODEL") or _model(src, r'XAI_MODEL"\)\s*or\s*"([^"]+)"', "")
    return [
        ("ChatGPT", "OPENAI_API_KEY", oa,
         lambda k: _call(f"https://api.openai.com/v1/models/{oa}", {"Authorization": f"Bearer {k}"}), {200}),
        ("Gemini", "GEMINI_API_KEY", gm,
         lambda k: _call(f"https://generativelanguage.googleapis.com/v1beta/models/{gm}?key={k}"), {200}),
        ("Claude", "CLAUDE_CITE_API_KEY", an,
         lambda k: _call(f"https://api.anthropic.com/v1/models/{an}",
                         {"x-api-key": k, "anthropic-version": "2023-06-01"}), {200}),
        ("Grok", "XAI_API_KEY", xm,
         lambda k: _call(f"https://api.x.ai/v1/models/{xm}", {"Authorization": f"Bearer {k}"}), {200}),
        # Perplexity にはモデル照会が無い。入力の無い要求は課金されずに 400 で返る＝入口と鍵は生きている
        ("Perplexity", "PERPLEXITY_API_KEY", "responses",
         lambda k: _call("https://api.perplexity.ai/v1/responses", {"Authorization": f"Bearer {k}"},
                         body={}, method="POST"), {400, 422}),
    ]


def check_engines(found):
    for name, key, model, call, alive in engine_probes():
        k = _env(key)
        if not k:
            print(f"ENGINE_{name}_OK=unset")
            continue
        code, msg = call(k)
        msg = msg.replace(k, "***")
        ok = code in alive
        print(f"ENGINE_{name}_OK={'yes' if ok else 'no'}  （{model} / HTTP {code}）")
        if not ok:
            hint = {404: "モデル名・入口が打ち切られた", 401: "鍵が無効", 403: "鍵の権限か入口の変更",
                    429: "枠切れ", 0: "通信できない"}.get(code, "")
            found.append(f"要対応: {name}（{model}）が HTTP {code} {hint}｜{msg[:140]}")


FONT_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s*\(\s*)["']next/font/google["']""")


def check_delivery_fonts(found):
    import sites as S
    if not shutil.which("gh"):
        print("  配信先のフォント: gh が無いため確かめられません")
        return
    for sid, cfg in S.load_all().items():
        repo = cfg.get("repo") or ""
        if cfg.get("type") == "self-static" or "/" not in repo:
            continue
        r = subprocess.run(["gh", "api", "-X", "GET", "search/code", "-f", f'q="next/font/google" repo:{repo}'],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if r.returncode != 0:
            print(f"  配信先のフォント: {repo} を検索できません（{(r.stderr or '').strip()[:60]}）")
            continue
        hits = []
        for it in json.loads(r.stdout or "{}").get("items", []):
            path = it.get("path", "")
            if not re.search(r"\.(t|j)sx?$|\.mjs$", path):
                continue
            c = subprocess.run(["gh", "api", f"repos/{repo}/contents/{path}", "-H", "Accept: application/vnd.github.raw"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            if c.returncode == 0 and FONT_IMPORT.search(c.stdout or ""):
                hits.append(path)
        print(f"  配信先のフォント: {repo} " + ("import なし" if not hits else f"import {len(hits)}件"))
        for h in hits:
            found.append(f"要対応: {repo}/{h} が next/font/google を import しています（CI のビルドが外部取得で落ちる。next/font/local へ）")


def main():
    found = []
    for fn in (check_secrets, check_gas, check_engines, check_delivery_fonts):
        try:
            fn(found)
        except Exception as ex:
            print(f"  {fn.__name__}: 確かめられませんでした（{type(ex).__name__}: {str(ex)[:80]}）")
    for f in found:
        print(f)
    print(f"HISTD_OK={'no' if found else 'yes'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"history_checks_d が動けませんでした: {type(ex).__name__}: {str(ex)[:120]}")
        sys.exit(1)
