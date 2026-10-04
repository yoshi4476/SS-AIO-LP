# -*- coding: utf-8 -*-
"""落ちたCIが一時的な失敗（ネットワーク・429・タイムアウト）なら、同じ run を1回だけ再実行する

自動修復（selfheal.yml の heal）は記事・週次・月次などを見張って直すが、記事動画・業種調査・
調査の更新・写真の棚・監修の記録は見張っておらず、通信が一瞬切れただけでもその日の分が失われ、
誰にも知らされなかった。

再実行するのは、失敗したジョブ全部が一時的と読めたときだけ。
  - 中身の誤り（門に落ちた・配信先で404になる・鍵が無い・コードの例外）は、再実行しても同じ所で止まる。
    2026-10-04 に別リポジトリの配信が「404になる」の検査で止まり続けた例がこれに当たる
  - 理由が読めない失敗も再実行しない（知らせるだけ）
  - 同じ run は1回まで（run_attempt が2以上なら再実行しない）。再実行の回が落ちても次は無い
  - 後に同じワークフローの run があれば再実行しない（古いデプロイを再実行すると、新しい公開を古い中身で上書きする）

使い方:
    python scripts/ci_rerun.py --run <run_id>           # 判定して、一時的なら再実行する（CI。GH_TOKEN と GITHUB_REPOSITORY が要る）
    python scripts/ci_rerun.py --run <run_id> --dry     # 判定だけ
    python scripts/ci_rerun.py --selftest

出力の印: RERUN=done（再実行した）/ RERUN=skip（しない）。知らせるものは「要対応:」の行。
判定が動かなかったときだけ終了コード1（8.7節の決まり）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELFHEAL = ROOT / ".github" / "workflows" / "selfheal.yml"

# 中身の誤り。先に見る（一時的な語と同じ尾に出ても、再実行しない側に倒す）
PERMANENT = [
    (r"404になる|\b404\b|Not Found", "配信先・相手先で404（中身か設定の誤り）"),
    (r"門が通らない|サイト監査の門|^\s*NG\s{2}", "門（品質・監査の検査）に落ちた"),
    (r"\b(SyntaxError|IndentationError|ModuleNotFoundError|ImportError|NameError|AttributeError|"
     r"TypeError|KeyError|ValueError|AssertionError|IndexError|UnicodeDecodeError)\b", "コードの例外"),
    # 「未設定 — スキップ」は正常な回にも出るので鍵の語に入れない（読めなければ unknown で再実行しない）
    # 2026-09-25 の記事の枠: 管制塔が「unauthorized」を返した（合言葉の不一致）。再実行しても同じ
    (r"Bad credentials|invalid_grant|(?i:unauthorized)|\b401\b|\b403\b|Permission denied", "鍵・権限"),
    (r"CONFLICT|merge conflict|<{7}", "Git の衝突"),
    # 2026-08-11 のデプロイ: 存在しない版の miniflare を求めて3回とも失敗した。再実行しても同じ
    (r"ETARGET|No matching version found", "依存の版が無い"),
]
TRANSIENT = [
    (r"\b429\b|Too Many Requests|rate.?limit|RESOURCE_EXHAUSTED|quota exceeded", "429・利用上限"),
    (r"\b50[0234]\b|\b529\b|Bad Gateway|Service Unavailable|Gateway Time-?out|Internal Server Error|overloaded",
     "相手側の一時障害（5xx）"),
    (r"timed? ?out|Timeout|ETIMEDOUT|exceeded the maximum execution time|deadline exceeded", "タイムアウト"),
    (r"Connection (reset|refused|aborted)|ECONNRESET|ECONNREFUSED|RemoteDisconnected|IncompleteRead|"
     r"Temporary failure in name resolution|Could not resolve host|EAI_AGAIN|getaddrinfo|Network is unreachable|"
     r"UNEXPECTED_EOF|early EOF|remote end hung up|unable to access 'https://", "ネットワーク"),
    (r"lost communication with the server|runner has received a shutdown signal|The operation was canceled",
     "ランナーの中断"),
]
TAIL = 80
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ")


def log_tail(text, n=TAIL):
    """失敗の理由は最後の ##[error] の直前に出る。ログ全体を見ると、途中で出ただけの
    警告（Gemini の 429 で飛ばした等）を失敗の理由と読み違える"""
    lines = [STAMP.sub("", l) for l in (text or "").splitlines()]
    errs = [i for i, l in enumerate(lines) if "##[error]" in l]
    end = errs[-1] + 1 if errs else len(lines)
    return "\n".join(lines[max(0, end - n):end])


def classify(tail):
    """('transient' | 'permanent' | 'unknown', 理由)"""
    for kind, rules in (("permanent", PERMANENT), ("transient", TRANSIENT)):
        for rx, why in rules:
            m = re.search(rx, tail, re.M | re.I if kind == "transient" else re.M)
            if m:
                return kind, f"{why}（{m.group(0)[:40]}）"
    return "unknown", "理由を読み取れない"


def decide(attempt, newer, verdicts):
    """verdicts: [(ジョブ名, 種類, 理由)]。(再実行するか, 理由)"""
    if attempt >= 2:
        return False, f"再実行は1回まで（この run は{attempt}回目）"
    if newer:
        return False, "後に同じワークフローの実行がある（古い中身で上書きしない）"
    if not verdicts:
        return False, "落ちたジョブが見つからない"
    bad = [v for v in verdicts if v[1] != "transient"]
    if bad:
        return False, " / ".join(f"{j}: {why}" for j, _, why in bad)
    return True, " / ".join(f"{j}: {why}" for j, _, why in verdicts)


def watch_lists(text=None):
    """selfheal.yml の各ジョブの起動条件にある fromJSON の一覧 {ジョブ名: [ワークフロー名]}。
    名前の一覧を1か所（selfheal.yml）にだけ置くため、ここでは読むだけにする"""
    import yaml
    y = yaml.safe_load(text if text is not None else SELFHEAL.read_text(encoding="utf-8")) or {}
    out = {}
    for name, job in (y.get("jobs") or {}).items():
        m = re.search(r"fromJSON\('(\[.*?\])'\)", str(job.get("if") or ""), re.S)
        if m:
            out[name] = json.loads(m.group(1))
    return out


def gh(*args):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"gh api {args[0][:60]}: {(r.stderr or '').strip()[:120]}")
    return r.stdout


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if "--selftest" in a:
        return selftest()
    if "--run" not in a:
        print(__doc__)
        return 1
    run_id = a[a.index("--run") + 1]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("GITHUB_REPOSITORY がありません")
        return 1
    try:
        run = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}"))
        latest = json.loads(gh(f"repos/{repo}/actions/workflows/{run['workflow_id']}/runs"
                               f"?branch={run.get('head_branch') or ''}&per_page=1"))
        newer = any(r["id"] > run["id"] for r in latest.get("workflow_runs") or [])
        jobs = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"))["jobs"]
        verdicts = []
        for j in jobs:
            if j.get("conclusion") not in ("failure", "timed_out"):
                continue
            if j.get("conclusion") == "timed_out":
                verdicts.append((j["name"], "transient", "タイムアウト（ジョブの上限）"))
                continue
            try:
                kind, why = classify(log_tail(gh(f"repos/{repo}/actions/jobs/{j['id']}/logs")))
            except RuntimeError as e:
                kind, why = "unknown", f"ログを読めない（{str(e)[:60]}）"
            verdicts.append((j["name"], kind, why))
    except Exception as e:
        print(f"判定が動きませんでした: {type(e).__name__} {str(e)[:160]}")
        return 1

    name, attempt = run.get("name", ""), int(run.get("run_attempt") or 1)
    ok, why = decide(attempt, newer, verdicts)
    for j, kind, w in verdicts:
        print(f"  {j}: {kind} — {w}")
    if ok and "--dry" not in a:
        r = subprocess.run(["gh", "run", "rerun", str(run_id), "--failed", "--repo", repo],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(f"要対応: {name} を再実行できませんでした（{(r.stderr or '').strip()[:100]}）")
            print("RERUN=skip")
            return 0
        print(f"{name}: 一時的な失敗のため1回だけ再実行しました（{why}）")
        print("RERUN=done")
        return 0
    if ok:
        print(f"{name}: 再実行の対象です（--dry のため実行しない）: {why}")
        print("RERUN=skip")
        return 0
    # 自動修復（heal）が見張っているものは、そちらが知らせる。二重に送らない
    healed = name in (watch_lists().get("heal") or [])
    if not healed and not newer:
        print(f"要対応: {name} が失敗しました（再実行しません: {why}）{run.get('html_url', '')}")
    else:
        print(f"{name}: 再実行しません（{why}）")
    print("RERUN=skip")
    return 0


def selftest():
    cases = [
        ("urllib.error.HTTPError: HTTP Error 429: Too Many Requests\n##[error]Process completed with exit code 1.", "transient"),
        ("requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected())\n##[error]x", "transient"),
        ("##[error]The job running on runner X has exceeded the maximum execution time of 100 minutes.", "transient"),
        ("fatal: unable to access 'https://github.com/a/b/': Could not resolve host: github.com\n##[error]x", "transient"),
        ("配信先のビルドが止まりました: /blog/x/ が404になる\n##[error]Process completed with exit code 1.", "permanent"),
        ("::error::門が通らないため公開しません\n##[error]Process completed with exit code 1.", "permanent"),
        ("KeyError: 'domain'\n##[error]Process completed with exit code 1.", "permanent"),
        ("::warning::CODEX_AUTH_JSON 未登録\n##[error]Process completed with exit code 1.", "unknown"),
        ("remote: Invalid username or token.\nfatal: Authentication failed\n##[error]x 403", "permanent"),
        ("何かが起きた\n##[error]Process completed with exit code 2.", "unknown"),
        ("→ 台帳から外せませんでした（unauthorized）\n##[error]Process completed with exit code 1.", "permanent"),
        ("Error: Reached max turns (300)\n##[error]Process completed with exit code 1.", "unknown"),
        ("npm error notarget No matching version found for miniflare@5.20260804.1-alpha.\n"
         "Cloudflare APIが応答せず（3/3）。40秒後に再試行\n##[error]3回ともデプロイ失敗", "permanent"),
        # 途中の警告に 429 があっても、失敗の直前が中身の誤りなら再実行しない
        ("Gemini 429 で飛ばしました\n" + "x\n" * 5 + "AssertionError\n##[error]exit 1", "permanent"),
    ]
    ng = [(t[:50], classify(log_tail(t))[0], want) for t, want in cases if classify(log_tail(t))[0] != want]
    far = "Gemini: HTTP 429\n" + "ok\n" * (TAIL + 5) + "なにか\n##[error]exit 1"
    if classify(log_tail(far))[0] != "unknown":
        ng.append(("尾より前の 429 は見ない", classify(log_tail(far))[0], "unknown"))
    for got, want, label in ((decide(1, False, [("a", "transient", "")])[0], True, "1回目の一時的な失敗は再実行"),
                             (decide(2, False, [("a", "transient", "")])[0], False, "2回目は再実行しない"),
                             (decide(1, True, [("a", "transient", "")])[0], False, "後の run があれば再実行しない"),
                             (decide(1, False, [("a", "transient", ""), ("b", "permanent", "")])[0], False,
                              "1つでも中身の誤りなら再実行しない")):
        if got != want:
            ng.append((label, got, want))
    for x in ng:
        print(f"  NG  {x}")
    print(f"CI_RERUN_SELFTEST={'ok' if not ng else 'ng'}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
