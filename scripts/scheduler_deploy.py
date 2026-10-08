# -*- coding: utf-8 -*-
"""定時の起動役（Cloudflare Worker・automation/scheduler）を配る・鍵を入れる（運用者が手元で使う）

  python scripts/scheduler_deploy.py                      予定の表を作り直し、npx wrangler deploy で配る
  python scripts/scheduler_deploy.py --dry-run            配らずに、束ねられるかだけ確かめる（wrangler deploy --dry-run）
  python scripts/scheduler_deploy.py --set-token          GitHub の鍵を Worker の secret（GITHUB_TOKEN）に入れる
  python scripts/scheduler_deploy.py --expiry 2027-10-08  鍵の期限を手で記録する（GitHub の応答に期限のヘッダーが無いとき）

--set-token の鍵は .env の SCHEDULER_GITHUB_TOKEN から読み、無いときだけ伏せ字の入力画面で受け取る。
入れる前に、その鍵で Actions を読めるか（ワークフローの一覧）と起動できるか（存在しないブランチへの起動に 422 が
返るか。実行は作られない）を GitHub で確かめる。鍵は画面にもログにも出さず、wrangler へは標準入力で渡す
（コマンドラインに載せると、プロセスの一覧から読める）。
配った時刻・鍵を入れた日・期限は data/scheduler.json に残る（公開してよい値だけ。コミットする）。

鍵の作り方（GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens）:
  Resource owner: yoshi4476 / Repository access: Only select repositories → SS-AIO-LP /
  Repository permissions: Actions = Read and write（ほかは付けない。Metadata: Read は自動で付く）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sched_guard as SGD  # noqa: E402
import scheduler_build as SB  # noqa: E402

SCHED_DIR = ROOT / "automation" / "scheduler"
WRANGLER = "wrangler@4.121.0"   # Pages の配信（pipeline.yml ほか）と同じ版
ENV_KEY = "SCHEDULER_GITHUB_TOKEN"
# 存在しないブランチへの起動。起動の権限があれば 422（No ref found）が返り、実行は作られない
PROBE_WF = "daily-kpi.yml"
PROBE_REF = "refs/heads/__scheduler_probe__"


def npx():
    exe = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not exe:
        raise SystemExit("npx が見つかりません（Node.js を入れる: winget install OpenJS.NodeJS.LTS）")
    return exe


def wrangler(args, secret=None):
    """automation/scheduler で wrangler を動かす。secret は標準入力で渡す（そのときだけ出力を受け取って伏せる）"""
    return subprocess.run([npx(), "--yes", WRANGLER] + args, cwd=str(SCHED_DIR), input=secret,
                          capture_output=secret is not None, text=True, encoding="utf-8", errors="replace")


def save_state(st):
    SGD.STATE.parent.mkdir(parents=True, exist_ok=True)
    SGD.STATE.write_text(SGD.dump_state(st), encoding="utf-8", newline="\n")


def env_token(path=None):
    """.env の SCHEDULER_GITHUB_TOKEN（無ければ空）。os.environ には入れない（子のプロセスへ渡さない）"""
    p = Path(path or ROOT / ".env")
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.strip() == ENV_KEY:
            return v.strip().strip("'\"")
    return ""


def ask_token():
    """伏せ字の入力画面（.env に鍵が無いときだけ）"""
    import tkinter as tk
    root = tk.Tk()
    root.title("定時の起動役の鍵（GitHub）")
    tk.Label(root, justify="left", text="SS-AIO-LP の Actions: Read and write だけを持つ fine-grained の鍵を貼り付けてください。\n"
             "画面には伏せ字で出ます。入れる前に GitHub で使えるかを確かめます。").pack(padx=16, pady=(14, 6))
    v = tk.StringVar()
    e = tk.Entry(root, textvariable=v, show="*", width=64)
    e.pack(padx=16, pady=4)
    e.focus_set()
    got = {"t": ""}

    def ok(_=None):
        got["t"] = v.get().strip()
        root.destroy()

    tk.Button(root, text="入れる", command=ok).pack(pady=(6, 14))
    root.bind("<Return>", ok)
    root.mainloop()
    return got["t"]


def _req(method, url, token, body=None):
    head = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ss-aio-scheduler-deploy"}
    if body is not None:
        head["Content-Type"] = "application/json"
    return urllib.request.Request(url, method=method, headers=head,
                                  data=json.dumps(body).encode("utf-8") if body is not None else None)


def _call(opener, req):
    """(状態コード, 応答ヘッダー)。例外の文言は出さない（要求に鍵が入っている）"""
    try:
        with opener(req, timeout=20) as r:
            return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers
    except Exception:
        return 0, {}


def check_token(token, opener=urllib.request.urlopen):
    """鍵で Actions を読めて起動できるか。(使えるか, 期限 ISO か空, 説明)"""
    base = f"https://api.github.com/repos/{SB.REPO}/actions"
    st, hdr = _call(opener, _req("GET", f"{base}/workflows?per_page=1", token))
    if st == 401:
        return False, "", "鍵が通りません（失効・貼り間違い）"
    if st in (403, 404):
        return False, "", "Actions を読む権限がありません（Repository access に SS-AIO-LP、Actions を Read and write に）"
    if st != 200:
        return False, "", f"GitHub で確かめられませんでした（HTTP {st}）。時間をおいてやり直す"
    exp = SGD.norm_expiry((hdr or {}).get("github-authentication-token-expiration", ""))
    st, _ = _call(opener, _req("POST", f"{base}/workflows/{PROBE_WF}/dispatches", token, {"ref": PROBE_REF}))
    if st == 422:
        return True, exp, "Actions を読めて、起動もできます"
    if st in (403, 404):
        return False, exp, "起動する権限がありません（Actions を Read and write に）"
    return False, exp, f"起動の権限を確かめられませんでした（HTTP {st}）"


def set_token(ask=ask_token, check=check_token, run=wrangler):
    token, src = env_token(), f".env の {ENV_KEY}"
    if not token:
        token, src = ask(), "入力画面"
    if not token:
        print("鍵がありません。何もしません")
        return 1
    kind = "fine-grained" if token.startswith("github_pat_") else "fine-grained ではない形（権限を Actions だけに絞れる fine-grained を勧めます）"
    print(f"鍵: {src}（{kind}・{len(token)}文字。中身は出しません）")
    ok, exp, why = check(token)
    print(f"GitHub での確認: {why}")
    if not ok:
        return 1
    r = run(["secret", "put", "GITHUB_TOKEN"], secret=token)
    for s in (r.stdout, r.stderr):
        if s and s.strip():
            print(s.replace(token, "<伏せ字>").rstrip())
    if r.returncode:
        print("secret を入れられませんでした（npx wrangler login 済みか・先に python scripts/scheduler_deploy.py で配ったかを確かめる）")
        return 1
    st = SGD.load_state()
    st.update({"token_set_at": date.today().isoformat(), "token_expiry": exp})
    save_state(st)
    print(f"鍵の期限: {exp[:10] if exp else 'GitHub の応答に期限のヘッダーが無い（期限なしの鍵）'}")
    print("data/scheduler.json をコミットしてください")
    return 0


def set_expiry(day):
    try:
        d = date.fromisoformat(day)
    except (TypeError, ValueError):
        print("期限は YYYY-MM-DD で入れてください")
        return 1
    st = SGD.load_state()
    st["token_expiry_manual"] = f"{d.isoformat()}T00:00:00+09:00"
    save_state(st)
    print(f"鍵の期限（手で記録）: {d}。GitHub の応答に期限があればそちらを使います。data/scheduler.json をコミットしてください")
    return 0


def deploy(dry=False):
    if SB.write():
        print("予定の表を作り直しました（automation/scheduler/schedule.json）。コミットして push してください"
              "（Worker は5分ごとに master の表を読みます）")
    if dry:
        with tempfile.TemporaryDirectory() as d:
            r = wrangler(["deploy", "--dry-run", "--outdir", d])
        print("束ねられました（配っていません）" if r.returncode == 0 else "束ねられませんでした")
        return r.returncode
    r = wrangler(["deploy"])
    if r.returncode:
        print("配れませんでした（npx wrangler login 済みか、定時の数がアカウントの上限（無料は5個）に収まっているかを確かめる）")
        return r.returncode
    st = SGD.load_state()
    st["deployed_at"] = datetime.now(SGD.JST).isoformat(timespec="minutes")
    save_state(st)
    print("配りました。鍵がまだなら python scripts/scheduler_deploy.py --set-token。"
          "10分ほどたったら python scripts/sched_guard.py --watch で最初の起動を確かめる")
    print("data/scheduler.json（配った時刻）をコミットしてください")
    return 0


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if "--set-token" in a:
        return set_token()
    if "--expiry" in a:
        i = a.index("--expiry")
        return set_expiry(a[i + 1] if i + 1 < len(a) else "")
    return deploy(dry="--dry-run" in a)


if __name__ == "__main__":
    sys.exit(main())
