# -*- coding: utf-8 -*-
"""過去の誤りの棚卸し（運用・ワークフロー・鍵・GAS・外部API の領域）から作った門。

どの門も「壊れた例を拾うこと」「正しい例を拾わないこと」を先に確かめてから、いまのファイルに当てる
（CLAUDE.md 0.1: 0件と言う前に、見つかるはずの例で検出器を試す）。
通信や GitHub API が要るもの（Secrets の実在・管制塔の公開版・外部AIのモデル）は scripts/history_checks_d.py。
鍵の値は表示しない（ファイルと行と鍵の名前だけ）。
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from test_gates import check, ROOT, ast_nodes

WF = ROOT / ".github" / "workflows"
SCRIPTS = ROOT / "scripts"
GAS = ROOT / "automation" / "gas"
UA_HINT = "User-Agent"


def warn(label, items):
    if items:
        items = sorted(map(str, items))
        print(f"  WARN  {label}: {len(items)}件  " + " / ".join(items[:8]))


_WF = {}


def workflows():
    """9つの門が同じ12本を YAML で読み直していた（約4秒）。中身が同じなら前の読みを使う。
    読んだ辞書を書き換える門があっても他へ漏れないよう、渡すのは写し"""
    import copy
    out = []
    for p in sorted(WF.glob("*.yml")):
        t = p.read_text(encoding="utf-8")
        if _WF.get(p.name, (None,))[0] != t:
            _WF[p.name] = (t, yaml.safe_load(t) or {})
        out.append((p.name, copy.deepcopy(_WF[p.name][1]), t))
    return out


def jobs(y):
    return (y.get("jobs") or {}).items()


def steps(job):
    return job.get("steps") or []


def scripts():
    out = []
    for p in sorted(SCRIPTS.glob("*.py")):
        try:
            out.append((p, p.read_text(encoding="utf-8-sig")))
        except UnicodeDecodeError:
            pass
    return out


def tracked(*pats):
    r = subprocess.run(["git", "ls-files", "-z", "--", *pats], cwd=ROOT, capture_output=True)
    return [x for x in r.stdout.decode("utf-8", "replace").split("\0") if x]


def str_elems(node):
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def node_run(src, js):
    """Apps Script のコードを node で動かす（サービスは js 側で差し替える）。node が無ければ None"""
    node = shutil.which("node")
    if not node:
        return None
    runner = ("const vm=require('vm'),fs=require('fs');"
              "const ctx={};vm.createContext(ctx);"
              "vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx,{timeout:8000});"
              "process.stdout.write(JSON.stringify(ctx.__out));")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "r.js").write_text(runner, encoding="utf-8")
        (Path(d) / "s.js").write_text(src + "\n;\n" + js, encoding="utf-8")
        r = subprocess.run([node, str(Path(d) / "r.js"), str(Path(d) / "s.js")], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        print("  node: " + (r.stderr or "").strip().splitlines()[-1][:160] if r.stderr else "  node: 失敗")
        return "error"
    return json.loads(r.stdout or "null")


# ══ 3. 検算に外れた戻しが、先に当てた正しい直しまで消す（2026-09-21 / 09-25）══════════
def rollback_offenders(src):
    """HEAD へ戻す git 呼び出し（作業コピーの未コミットの直しを巻き込む）。別の作業コピー（cwd=dest）は除く"""
    out = []
    for n in ast_nodes(src)[1]:
        if not isinstance(n, ast.Call):
            continue
        cwd = next((k.value for k in n.keywords if k.arg == "cwd"), None)
        if cwd is not None and not (isinstance(cwd, ast.Name) and cwd.id == "ROOT"):
            continue
        for a in n.args:
            if not isinstance(a, (ast.List, ast.Tuple)):
                continue
            s = str_elems(a)
            if not s or s[0] != "git":
                continue
            if ("checkout" in s and not {"--ours", "--theirs", "-b", "-B"} & set(s)) \
                    or ("reset" in s and "--hard" in s) or "stash" in s \
                    or ("restore" in s and "--source" not in s):
                out.append(n.lineno)
    return out


def _temp_repo(d):
    g = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "t")
    (Path(d) / "articles").mkdir()
    (Path(d) / "articles" / "a.md").write_text("A 元\n", encoding="utf-8")
    (Path(d) / "articles" / "b.md").write_text("B 元\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return g


def _round_trip(snapshot, restore, d):
    """先の工程の未コミットの直し(a)→回の頭を記録→b を書き換え c を新規→戻す。a が残り b・c が戻れば合格"""
    art = Path(d) / "articles"
    (art / "a.md").write_text("A 先に当てた正しい直し\n", encoding="utf-8")
    tree = snapshot()
    (art / "b.md").write_text("B 検算に外れた書き換え\n", encoding="utf-8")
    (art / "c.md").write_text("C 回の中で増えた\n", encoding="utf-8")
    restore(tree)
    return ((art / "a.md").read_text(encoding="utf-8").startswith("A 先に"),
            (art / "b.md").read_text(encoding="utf-8") == "B 元\n",
            not (art / "c.md").exists())


def test_hist_rollback_keeps_earlier_fixes():
    import auto_rewrite as AR
    import report_actions as RA
    print("\n■ 履歴D: 検算に外れた戻しは、その回の変更だけを捨てる（2026-09-21 / 09-25）")
    check("検出器: git checkout -- articles を拾う",
          rollback_offenders('subprocess.run(["git", "checkout", "--", "articles/"])') != [], True)
    check("検出器: 回の頭の tree へ戻す git restore --source は拾わない",
          rollback_offenders('subprocess.run(["git", "restore", "--source", t, "--worktree", "--", "articles"])'), [])
    check("検出器: 別の作業コピー（cwd=dest）の reset --hard は拾わない",
          rollback_offenders('run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest)'), [])
    bad = [f"{p.name}:{ln}" for p, t in scripts() for ln in rollback_offenders(t)]
    check("scripts/ に HEAD へ戻す git 呼び出しが無い", bad, [])
    wf_bad = [f"{n}" for n, _, t in workflows() if re.search(r"git\s+(checkout|restore)\s+(HEAD\s+)?--\s+articles", t)]
    check("ワークフローが articles/ を HEAD へ戻さない", wf_bad, [])

    # 直前の状態との比較: 先に当てた未コミットの直しを「別の記事まで変わった」と数えない
    with tempfile.TemporaryDirectory() as d:
        old = AR.ROOT
        try:
            AR.ROOT = Path(d)
            (Path(d) / "articles").mkdir()
            (Path(d) / "articles" / "a.md").write_text("A", encoding="utf-8")
            (Path(d) / "articles" / "b.md").write_text("B", encoding="utf-8")
            (Path(d) / "articles" / "a.md").write_text("A 先の直し", encoding="utf-8")
            snap = AR.snapshot()
            (Path(d) / "articles" / "b.md").write_text("B 書き換え", encoding="utf-8")
            check("auto_rewrite: 変わったのは書き換えた1本だけと数える", AR.changed_since(snap), ["b.md"])
        finally:
            AR.ROOT = old

    # 2本目だけ外れたとき、1本目の直しが残るか（HEAD へ戻す書き方なら消える＝検出器の自己確認）
    with tempfile.TemporaryDirectory() as d:
        g = _temp_repo(d)
        got = _round_trip(lambda: None, lambda _t: g("checkout", "--", "articles"), d)
        check("自己確認: HEAD へ戻す書き方では先の直しが消える", got[0], False)
    with tempfile.TemporaryDirectory() as d:
        _temp_repo(d)
        old = (RA.ROOT, RA.SCOPE)
        try:
            RA.ROOT, RA.SCOPE = Path(d), ("articles",)
            got = _round_trip(RA.snapshot, RA.restore, d)
        finally:
            RA.ROOT, RA.SCOPE = old
        check("report_actions: 先の直しは残り、回の変更（書き換え・新規）だけ戻る", got, (True, True, True))


# ══ 9. public リポジトリに秘密を置いた（2026-08-21 / 09-25）══════════════════════
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|WEBHOOK|PRIVATE|CREDENTIAL")
SECRET_FILE = re.compile(r"(^|/)(\.env(?!\.example$)[^/]*|[^/]*service-account[^/]*\.json|[^/]*-token(-[^/]*)?\.json"
                         r"|(gbp|youtube)-client\.json|secrets\.local\.txt|\.clasprc\.json|credentials\.json)$")
# 公開が前提の値（IndexNow の鍵はサイト直下にファイルとして置く決まり）
# 公開する決まりの鍵（IndexNow はサイト直下に置く。Turnstile のサイトキーは部品を出す全ページに載る）
PUBLIC_KEYS = {"INDEXNOW_KEY", "TURNSTILE_SITEKEY"}
GENERIC_LOCAL = {"info", "contact", "support", "hello", "mail", "office", "sales", "inquiry", "otoiawase",
                 "toiawase", "admin", "webmaster", "noreply", "no-reply", "pr", "press", "recruit", "saiyo", "info.ai"}
GS_SECRET = re.compile(r"^\s*(?:const|let|var)\s+(\w*(?:SECRET|TOKEN|PASSWORD|API_KEY|APIKEY)\w*)\s*=\s*(['\"])(.*?)\2", re.M)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _placeholder(v):
    # 「名前_XXXXXXXX」は配るときに gas_deploy.fill が埋める見本（例 FORM_SECRET_XXXXXXXX）
    return not v or re.fullmatch(r"X+|x+|[A-Z_]*_X{8,}|YOUR_.*|<.*>|\*+|change-?me", v, re.I) is not None


def env_secret_values(text):
    """鍵らしい名前の値（8文字以上）。JSON の値は中の秘密の項目だけ。名前→値"""
    out = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if not SECRET_NAME.search(k) or k in PUBLIC_KEYS or re.search(r"_(PATH|FILE|DIR)$", k):
            continue
        if v.startswith("{"):
            try:
                d = json.loads(v)
            except ValueError:
                continue
            for kk in ("private_key_id", "client_secret", "refresh_token", "client_email"):
                if isinstance(d.get(kk), str) and len(d[kk]) >= 8:
                    out[f"{k}.{kk}"] = d[kk]
        elif len(v) >= 8 and not _placeholder(v) and "\n" not in v:
            out[k] = v
    return out


def secret_hits(texts, values):
    """[(path, 行, 鍵の名前)]。値そのものは返さない"""
    hits = []
    for path, t in texts.items():
        for i, line in enumerate(t.splitlines(), 1):
            for name, v in values.items():
                if v in line:
                    hits.append((path, i, name))
    return hits


def gs_secret_offenders(text):
    return [m.group(1) for m in GS_SECRET.finditer(text) if not _placeholder(m.group(3))]


def personal_emails(text):
    return [e for e in EMAIL.findall(text) if e.split("@")[0].lower() not in GENERIC_LOCAL]


def test_hist_no_secrets_in_tracked_files():
    print("\n■ 履歴D: 公開リポジトリに秘密を置かない（2026-08-21 / 09-25）")
    fake = "sk-test-ABCDEFGH12345678"
    vals = env_secret_values(f"OPENAI_API_KEY={fake}\nSITE_DOMAIN=ai.7senses.co.jp\nHUB_SECRET=XXXXXXXXXXXXXXXX\n")
    check("検出器: 鍵らしい名前の値だけを集める（プレースホルダは除く）", sorted(vals), ["OPENAI_API_KEY"])
    check("検出器: 平文の鍵を行つきで拾う",
          secret_hits({"x.gs": "a\nconst K = '" + fake + "';"}, vals), [("x.gs", 2, "OPENAI_API_KEY")])
    check("検出器: 鍵の無い文は拾わない", secret_hits({"y.md": "OPENAI_API_KEY を .env に書く"}, vals), [])
    check("検出器: .gs の合言葉に本番値", gs_secret_offenders("const SHARED_SECRET = 'a8f3kq0z9wq';"), ["SHARED_SECRET"])
    check("検出器: .gs の合言葉がプレースホルダなら通す", gs_secret_offenders("const SHARED_SECRET = 'XXXXXXXXXXXXXXXX';"), [])
    check("検出器: 「名前_XXXXXXXX」の見本は通し、埋めた本番値は拾う",
          (gs_secret_offenders("const FORM_SECRET = 'FORM_SECRET_XXXXXXXX';"),
           gs_secret_offenders("const FORM_SECRET = 'q7Zk2_9fPw0LmN4vR8tYc1dE6hJ3sA5u';")), ([], ["FORM_SECRET"]))
    check("検出器: 担当者の個人メール", personal_emails('{"contact": "taro@client.co.jp"}'), ["taro@client.co.jp"])
    check("検出器: 代表アドレスは通す", personal_emails('{"contact": "info@client.co.jp"}'), [])
    check("検出器: .env の控えを秘密のファイルと見なす", bool(SECRET_FILE.search(".env.backup-20260821")), True)
    check("検出器: .env.example は通す", bool(SECRET_FILE.search(".env.example")), False)

    files = tracked()
    check("秘密のファイル（.env の控え・鍵JSON）が追跡されていない", [f for f in files if SECRET_FILE.search(f)], [])
    gs = [f"{p.name}:{n}" for p in sorted(GAS.glob("*.gs")) for n in gs_secret_offenders(p.read_text(encoding="utf-8"))]
    check(".gs の合言葉・鍵がプレースホルダ", gs, [])
    em = [f"{f}: {e}" for f in files if re.match(r"(sites|data/clients)/.*\.json$", f)
          for e in personal_emails((ROOT / f).read_text(encoding="utf-8", errors="ignore"))]
    check("sites/・data/clients/ に個人のメールアドレスが無い", em, [])

    values = {}
    for p in sorted(ROOT.glob(".env*")):
        if p.name != ".env.example" and p.is_file():
            values.update(env_secret_values(p.read_text(encoding="utf-8-sig", errors="ignore")))
    if not values:
        print("  （.env が無いため、平文の鍵の照合は飛ばします）")
        return
    with tempfile.TemporaryDirectory() as d:
        pat = Path(d) / "p.txt"
        pat.write_text("\n".join(values.values()) + "\n", encoding="utf-8")
        r = subprocess.run(["git", "grep", "-I", "-l", "-F", "-f", str(pat)], cwd=ROOT, capture_output=True)
    hit_files = [x for x in r.stdout.decode("utf-8", "replace").splitlines() if x]
    texts = {f: (ROOT / f).read_text(encoding="utf-8", errors="ignore") for f in hit_files}
    hits = [f"{p}:{i}（{n}）" for p, i, n in secret_hits(texts, values)]
    check(f".env の鍵（{len(values)}件）が追跡中のファイルに平文で出ていない", hits, [])


# ══ 10. ワークフローの工程の順番（2026-09-25）═════════════════════════════════
KEY_FILE = "indexing-service-account.json"
WRITE_STEP = re.compile(r"python3? scripts/(\w+)\.py[^\n|;&]*?(--write|--finish|--fix\b|--apply)")


def key_consumers():
    return {p.stem for p, t in scripts() if KEY_FILE in t}


def order_problems(y, consumers):
    """工程の順番の誤り（ジョブごと）。ラベルの一覧を返す"""
    out = []
    for jn, job in jobs(y):
        st = steps(job)
        runs = [(s.get("name") or s.get("uses") or "?", s.get("run") or "") for s in st]
        idx = lambda pat: [i for i, (_, r) in enumerate(runs) if re.search(pat, r)]
        commits = idx(r"git commit")
        if commits:
            for i, (n, r) in enumerate(runs):
                if i > commits[-1] and WRITE_STEP.search(r):
                    out.append(f"{jn}: 「{n}」がコミットの後で記事・台帳を書き換える（ランナーと一緒に消える）")
        gen, before, after = idx(r"multi_site_prompt"), idx(r"kw_gate\.py --before"), idx(r"kw_gate\.py --after")
        ship = idx(r"git commit|wrangler|publish_changed|publish_gap")
        if gen and (not before or before[0] > gen[0]):
            out.append(f"{jn}: 執筆前の食い合いゲートが執筆より後")
        if gen and ship and (not after or after[0] > ship[0]):
            out.append(f"{jn}: 執筆後の食い合いゲートがコミット・配信より後")
        present = False
        for n, r in runs:
            for line in r.splitlines():
                if re.search(r">\s*" + re.escape(KEY_FILE), line):
                    present = True
                elif re.search(r"\brm\b[^\n]*" + re.escape(KEY_FILE), line):
                    present = False
                else:
                    for s in re.findall(r"python3? scripts/(\w+)\.py", line):
                        if s in consumers and not present:
                            out.append(f"{jn}: 「{n}」の {s} が鍵ファイルを置く前に動く")
    conc = y.get("concurrency") or {}
    on = y.get("on") or y.get(True) or {}
    crons = len((on.get("schedule") if isinstance(on, dict) else None) or [])
    if crons > 2 and conc:
        out.append("枠の多いワークフロー全体に concurrency（空き枠の run が実枠・週次の待機を取り消す）")
    groups = [conc] + [j.get("concurrency") or {} for _, j in jobs(y)]
    for g in groups:
        if isinstance(g, dict) and g.get("group") == "article-pipeline" and g.get("cancel-in-progress"):
            out.append("記事のグループで cancel-in-progress: true")
    return out


def test_hist_workflow_step_order():
    print("\n■ 履歴D: ワークフローの工程の順番（2026-09-25）")
    cons = key_consumers() | {"gsc_check"}
    bad = yaml.safe_load("""
on: {schedule: [{cron: '0 1 * * *'}, {cron: '0 2 * * *'}, {cron: '0 3 * * *'}]}
concurrency: {group: article-pipeline, cancel-in-progress: true}
jobs:
  w:
    steps:
      - {name: 執筆, run: 'claude -p "$(cat automation/multi_site_prompt.txt)"'}
      - {name: 前ゲート, run: python scripts/kw_gate.py --before}
      - {name: コミット, run: 'git commit -m x'}
      - {name: 後ゲート, run: python scripts/kw_gate.py --after}
      - {name: 公開の後, run: python scripts/link_boost.py ai-lab --write}
      - {name: 実測, run: python scripts/gsc_check.py}
""")
    good = yaml.safe_load("""
on: {schedule: [{cron: '0 1 * * *'}, {cron: '0 2 * * *'}, {cron: '0 3 * * *'}]}
jobs:
  w:
    concurrency: {group: article-pipeline, cancel-in-progress: false}
    steps:
      - {name: 鍵, run: "printf '%s' \\"$X\\" > indexing-service-account.json"}
      - {name: 前ゲート, run: python scripts/kw_gate.py --before}
      - {name: 執筆, run: 'claude -p "$(cat automation/multi_site_prompt.txt)"'}
      - {name: 後ゲート, run: python scripts/kw_gate.py --after}
      - {name: リンク, run: python scripts/link_boost.py ai-lab --write}
      - {name: 実測, run: python scripts/gsc_check.py}
      - {name: コミット, run: 'git commit -m x'}
""")
    check("検出器: 悪い並び（6種）を全部拾う", len(order_problems(bad, cons)), 6)
    check("検出器: 正しい並びは拾わない", order_problems(good, cons), [])
    cur = [f"{n}: {x}" for n, y, _ in workflows() for x in order_problems(y, cons)]
    check("いまのワークフローの工程の順番", cur, [])


# ══ 13. 自動返信の文面が約束と違う（2026-07-28 / 09-28 / 10-02）═════════════════
REPLY_CASES = {
    "download": {"type": "download", "email": "a@example.com", "name": "山田", "checklist": "dental"},
    "site_audit": {"type": "site_audit", "email": "a@example.com", "name": "山田",
                   "audit": {"url": "https://example.com/", "total": 62, "grade": "C", "fixes": "1. タイトルに地域名を入れる"}},
    "diagnosis": {"type": "diagnosis", "email": "a@example.com", "name": "山田",
                  "diagnosis": {"kind": "ai", "total": 55, "grade": "B", "scores": {"構造": 40}}},
    "ai_check": {"type": "contact", "email": "a@example.com", "name": "山田", "form_type": "AI紹介チェック",
                 "message": "AI紹介チェック: 3問中1問で出典に入っています"},
    "contact": {"type": "contact", "email": "a@example.com", "name": "山田", "message": "相談です"},
}


def replies(src):
    js = ("var __m=[];MailApp={sendEmail:function(o){__m.push(o);}};"
          "UrlFetchApp={fetch:function(){throw new Error('offline');}};"
          # 結果メールの返信先は Script Properties で差し替えられる（未設定なら NOTIFY_TO）
          "PropertiesService={getScriptProperties:function(){return {getProperty:function(){return null;}};}};"
          f"var __c={json.dumps(REPLY_CASES)};var __o={{}};"
          "Object.keys(__c).forEach(function(k){__m=[];var d=__c[k];leadReply_('AI集客ラボ',d.type,d);"
          "__o[k]=__m.length?(__m[0].subject+'\\n'+__m[0].body):'';});globalThis.__out=__o;")
    return node_run(src, js)


def promise_problems(r):
    """種別ごとの約束（LP・ツールの画面で言っていること）が本文にあるか"""
    out = []
    if "checklist-dental.pdf" not in r.get("download", ""):
        out.append("資料DLの返信に PDF のリンクが無い")
    sa = r.get("site_audit", "")
    if not all(x in sa for x in ("https://example.com/", "62", "タイトルに地域名を入れる")):
        out.append("サイト診断の返信に 診断URL・点数・直し方 が無い")
    if "55" not in r.get("diagnosis", ""):
        out.append("診断の返信に点数が無い")
    ac = r.get("ai_check", "")
    if "3問中1問" not in ac or "担当よりご連絡" in ac:
        out.append("AI紹介チェックの返信に結果が無い／問い合わせ用の汎用文")
    if "営業日以内" not in r.get("contact", ""):
        out.append("問い合わせの返信に連絡の目安が無い")
    return out


def test_hist_auto_reply_keeps_promise():
    print("\n■ 履歴D: 自動返信が画面の約束どおりの中身を送る（2026-07-28 / 09-28 / 10-02）")
    src = "\n".join((GAS / f).read_text(encoding="utf-8") for f in ("hub.gs", "contact.hub.gs"))
    r = replies(src)
    if r is None:
        print("  WARN  node が無いため、自動返信の文面は確かめられません")
    else:
        check("自己確認: 資料DLの分岐を外すと検出器が拾う",
              "資料DLの返信に PDF のリンクが無い" in promise_problems(
                  replies(src.replace("type === 'download'", "type === 'download__x'")) or {}), True)
        check("自動返信の中身が種別ごとの約束と合う", promise_problems(r) if isinstance(r, dict) else ["実行失敗"], [])
    # 購読のあとのサンクスは購読用の文面に切り替わる（お問い合わせ用の文面が出ていた 2026-07-28）
    thanks = (ROOT / "site" / "thanks" / "index.html").read_text(encoding="utf-8")
    kinds = sorted({t for p in sorted((ROOT / "functions" / "api").glob("*.js"))
                    for t in re.findall(r"/thanks/\?type=(\w+)", p.read_text(encoding="utf-8"))})
    check("サンクスページが送り元の種別（?type=）ごとに文面を切り替える",
          [k for k in kinds if f"'{k}'" not in thanks and f'"{k}"' not in thanks], [])


# ══ 19. 版を固定しない npx・外部取得するビルド（2026-08-12 / 09-29）═════════════════
NPX = re.compile(r"\bnpx\s+(?:--yes\s+|-y\s+)*(@?[\w./-]+(?:@[\w.^~-]+)?)")
NPM_G = re.compile(r"\bnpm\s+(?:i|install)\s+(?:-g|--global)\s+(?:--?\S+\s+)*(@?[\w./-]+(?:@[\w.^~-]+)?)")
FONT_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s*\(\s*)["']next/font/google["']""")


def pinned(spec):
    return re.search(r"@\d+\.\d+\.\d+$", spec) is not None


def test_hist_pinned_tool_versions():
    print("\n■ 履歴D: CI の外部ツールは版を固定し、ビルドで外へ取りに行かない（2026-08-12 / 09-29）")
    check("検出器: wrangler@4 は固定でない", pinned(NPX.search("npx --yes wrangler@4 pages deploy").group(1)), False)
    check("検出器: wrangler@4.121.0 は固定", pinned(NPX.search("npx --yes wrangler@4.121.0 pages deploy").group(1)), True)
    check("検出器: next/font/google の import を拾う", bool(FONT_IMPORT.search("import { Noto_Sans_JP } from 'next/font/google'")), True)
    check("検出器: コメントで触れているだけは拾わない", bool(FONT_IMPORT.search("// next/font/google はビルドのたびに取りに行く")), False)
    npx = sorted({f"{n}: {s}" for n, _, t in workflows() for s in NPX.findall(t) if not pinned(s)})
    check("ワークフローの npx は版を x.y.z で固定", npx, [])
    warn("npm install -g の版が固定されていない（claude-code・codex は版の更新を追うため保留）",
         {f"{n}: {s}" for n, _, t in workflows() for s in NPM_G.findall(t) if not pinned(s)})
    src = [f for f in tracked("*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs")
           if FONT_IMPORT.search((ROOT / f).read_text(encoding="utf-8", errors="ignore"))]
    check("このリポジトリのソースに next/font/google の import が無い", src, [])
    pw = ROOT / ".publish-work"
    if pw.is_dir():
        hits = [str(p.relative_to(pw)) for ext in ("*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs") for p in pw.rglob(ext)
                if not {"node_modules", ".next", "out", "dist"} & set(p.relative_to(pw).parts)
                and FONT_IMPORT.search(p.read_text(encoding="utf-8", errors="ignore"))]
        warn("配信先の作業コピーに next/font/google の import（本体は history_checks_d が GitHub で確かめる）", hits)


# ══ 32. GAS の関数の二重定義・列のずれ（2026-08-21 / 08-24 / 09-21）══════════════════
TOP_DECL = re.compile(r"^(?:function\s+([^\s(]+)\s*\(|(?:const|let|var)\s+([\w$]+)\s*=)", re.M)


def gas_projects():
    import gas_deploy as G
    groups, seen = [], set()
    for cfg in G.TARGETS.values():
        fs = tuple(sorted({l for l, _ in cfg["files"]}))
        if fs not in seen:
            seen.add(fs)
            groups.append(fs)
    for p in sorted(GAS.glob("*.gs")):
        rel = p.relative_to(ROOT).as_posix()
        if not any(rel in g for g in groups):
            groups.append((rel,))
    return groups


def duplicate_decls(texts):
    seen, dup = {}, []
    for name, t in texts.items():
        for m in TOP_DECL.finditer(t):
            d = m.group(1) or m.group(2)
            if d in seen and seen[d] != name:
                dup.append(f"{d}（{seen[d]} と {name}）")
            seen.setdefault(d, name)
    return dup


def _array_len(s, i):
    """s[i] が '[' の配列リテラルの要素数（入れ子・文字列・コメント・末尾のカンマを除いた最上位の要素）"""
    depth, n, q, j, item = 0, 0, "", i, False
    while j < len(s):
        c = s[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == q:
                q = ""
        elif s.startswith("//", j):
            j = s.find("\n", j)
            if j < 0:
                return -1
            continue
        elif s.startswith("/*", j):
            j = s.find("*/", j) + 2
            continue
        elif c in "'\"`":
            q = c
            item = item or depth == 1
        elif c in "([{":
            depth += 1
            if depth > 1:
                item = True
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return n + (1 if item else 0)
        elif c == "," and depth == 1:
            n, item = n + (1 if item else 0), False
        elif not c.isspace() and depth >= 1:
            item = True
        j += 1
    return -1


def append_mismatch(text, tabs):
    """appendRow の要素数とタブの見出しの列数の食い違い"""
    out = []
    # フォームから来る行は数式の注入よけ（cells_）で包んで書く（2026-10-10・gates_history_h78_security）
    for m in re.finditer(r"([\w$]+(?:\('([^']+)'\))?)\.appendRow\(\s*(?:cells_\(\s*)?\[", text):
        tab = m.group(2)
        if not tab:
            # 変数は同じ関数の中で sheet_('タブ') を代入したものだけ見る（別の関数の sh と取り違えない）
            v = m.group(1)
            start = max(text.rfind("\nfunction ", 0, m.start()), 0)
            a = list(re.finditer(r"\b" + re.escape(v) + r"\s*=\s*sheet_\('([^']+)'\)", text[start:m.start()]))
            tab = a[-1].group(1) if a else None
        if tab not in tabs:
            continue
        n = _array_len(text, m.end() - 1)
        if n != len(tabs[tab]):
            out.append(f"{tab}: {n}列で書く（見出しは{len(tabs[tab])}列） @{text[:m.start()].count(chr(10)) + 1}行")
    return out


def tabs_of(hub_text):
    m = re.search(r"const TABS = \{(.*?)\n\};", hub_text, re.S)
    out = {}
    for name, body in re.findall(r"'([^']+)':\s*\[(.*?)\]", m.group(1) if m else "", re.S):
        out[name] = re.findall(r"'([^']*)'", body)
    return out


def test_hist_gas_project_integrity():
    print("\n■ 履歴D: GAS の関数の二重定義と、台帳の列のずれ（2026-08-21 / 08-24 / 09-21）")
    check("検出器: 2ファイルに function doPost",
          bool(duplicate_decls({"a.gs": "function doPost(e) {}", "b.gs": "function doPost(e) {}"})), True)
    check("検出器: 別の名前なら通す", duplicate_decls({"a.gs": "function doPost(e) {}", "b.gs": "function doGet(e) {}"}), [])
    tabs = {"問い合わせ": list("abcdefghijklmn")}
    check("検出器: 14列の台帳へ11列で書く",
          bool(append_mismatch("const sh = sheet_('問い合わせ');\nsh.appendRow([1,2,3,4,5,6,7,8,9,10,11]);", tabs)), True)
    check("検出器: 列数が合えば通す（入れ子・文字列のカンマは数えない）",
          append_mismatch("const sh = sheet_('問い合わせ');\nsh.appendRow([f(a, b), 'x,y', [1, 2], 4,5,6,7,8,9,10,11,12,13,\n  // 注記, カンマ入り\n  14,\n]);", tabs), [])
    dups = []
    for g in gas_projects():
        dups += duplicate_decls({f: (ROOT / f).read_text(encoding="utf-8") for f in g})
    check("同じ Apps Script プロジェクトに同名の関数・定数が無い", dups, [])
    hub_files = next((g for g in gas_projects() if "automation/gas/hub.gs" in g), ())
    tabs = tabs_of((GAS / "hub.gs").read_text(encoding="utf-8"))
    check("管制塔の見出し定義（TABS）を読めた", len(tabs) >= 10, True)
    ch = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    check("自己確認: 本物の問い合わせの記録から1列落とすと拾う",
          bool(append_mismatch(ch.replace("temp, '未対応',", "temp,", 1), tabs)) and "temp, '未対応'," in ch, True)
    mis = [f"{Path(f).name} {x}" for f in hub_files for x in append_mismatch((ROOT / f).read_text(encoding="utf-8"), tabs)]
    check("管制塔の appendRow が見出しの列数と同じ", mis, [])


# ══ 33. GAS を直しても配備されない（2026-08-04 / 08-25 / 09-21）══════════════════
def test_hist_gas_deploy_drift_is_watched():
    import gas_deploy as G
    import history_checks_d as H
    print("\n■ 履歴D: GAS の公開版とリポジトリの食い違いを見張る（2026-08-04 / 08-25 / 09-21）")
    check("比較: 改行コード・行末の空白だけの違いは同じ", H.same_source("a\r\nb  \r\n", "a\nb\n"), True)
    check("比較: 中身が違えば食い違い", H.same_source("function a(){return 1}", "function a(){return 2}"), False)
    deployed = {l for cfg in G.TARGETS.values() for l, _ in cfg["files"]}
    warn("gas_deploy の配布対象に無い .gs（直しても自動では配備されない）",
         [p.name for p in sorted(GAS.glob("*.gs")) if p.relative_to(ROOT).as_posix() not in deployed])
    check("管制塔の配布対象のファイルが全部ある",
          [l for l, _ in G.TARGETS["hub"]["files"] if not (ROOT / l).is_file()], [])


# ══ 34. 使う鍵が CI に渡っていない（2026-09-17 / 09-26 / 10-01）═══════════════════
ENV_READ = re.compile(r"""(?:environ\.get|getenv|_env|\benv)\(\s*["']([A-Z][A-Z0-9_]+)["']|environ\[\s*["']([A-Z][A-Z0-9_]+)["']""")
ALT = {"LEAD_TO_EMAIL": "NOTIFY_TO_EMAIL"}      # notify_slack は NOTIFY_TO_EMAIL があればそちらを使う


def distributed():
    import set_key
    import set_push_token
    import set_secrets
    out = set(set_secrets.TO_GITHUB) | set(set_key.KEYS) | {set_push_token.KEY}
    for _, t in scripts():
        out |= set(re.findall(r"""\[\s*["']gh["'],\s*["']secret["'],\s*["']set["'],\s*["']([A-Z0-9_]+)["']""", t))
    return out


def missing_keys(y, reads):
    """ステップが呼ぶスクリプトが読む鍵のうち、そのステップに渡っていないもの"""
    out = []
    top = set(y.get("env") or {})
    for jn, job in jobs(y):
        je = top | set(job.get("env") or {})
        for st in steps(job):
            have = je | set(st.get("env") or {})
            for s in sorted(set(re.findall(r"python3? scripts/(\w+)\.py", st.get("run") or ""))):
                miss = {k for k in reads.get(s, ()) if k not in have and ALT.get(k) not in have}
                if miss:
                    out.append(f"{jn}「{st.get('name')}」{s}: {', '.join(sorted(miss))}")
    return out


def test_hist_ci_gets_the_keys_scripts_read():
    print("\n■ 履歴D: スクリプトが読む鍵がワークフローで渡され、配る一覧にもある（2026-09-17 / 09-26 / 10-01）")
    wf_secrets = set()
    for _, _, t in workflows():
        wf_secrets |= set(re.findall(r"secrets\.([A-Z0-9_]+)", t))
    wf_secrets.discard("GITHUB_TOKEN")
    universe = wf_secrets | distributed()
    reads = {p.stem: {a or b for a, b in ENV_READ.findall(t)} & universe for p, t in scripts()}
    bad = yaml.safe_load("jobs: {m: {steps: [{name: 引用, env: {GEMINI_API_KEY: x}, run: python scripts/ai_cite_check.py}]}}")
    good = yaml.safe_load("jobs: {m: {steps: [{name: 引用, env: {GEMINI_API_KEY: x, OPENAI_API_KEY: x}, run: python scripts/ai_cite_check.py}]}}")
    fake = {"ai_cite_check": {"GEMINI_API_KEY", "OPENAI_API_KEY"}}
    check("検出器: OPENAI_API_KEY が渡っていない工程を拾う", missing_keys(bad, fake) != [], True)
    check("検出器: 渡っていれば通す", missing_keys(good, fake), [])
    check("検出器: ai_cite_check が読む鍵を集められる", {"OPENAI_API_KEY", "GEMINI_API_KEY"} <= reads.get("ai_cite_check", set()), True)
    cur = [f"{n} {x}" for n, y, _ in workflows() for x in missing_keys(y, reads)]
    check("ワークフローの各工程に、呼ぶスクリプトが読む鍵が渡っている", cur, [])
    check("ワークフローが使う鍵は全部 set_secrets 等の配る一覧にある", sorted(wf_secrets - distributed()), [])


# ══ 35. 外部APIのモデル・版の打ち切りで黙って失敗（2026-09-23 / 09-26 / 10-01）══════════
def names_cause(fn):
    """HTTP 404 を受けたとき、例外の文に状態と理由が出るか"""
    import io
    import urllib.error
    import urllib.request
    real = urllib.request.urlopen

    def boom(*a, **k):
        raise urllib.error.HTTPError("https://x/", 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}'))
    urllib.request.urlopen = boom
    try:
        fn()
    except Exception as ex:
        return "404" in str(ex) and "model not found" in str(ex)
    finally:
        urllib.request.urlopen = real
    return False


def test_hist_external_api_errors_are_named():
    import ai_cite_check as A
    print("\n■ 履歴D: 外部APIの打ち切りを「失敗」で済ませない（2026-09-23 / 09-26 / 10-01）")

    def bad_post():
        try:
            A._post("https://x/", {}, {})
        except Exception:
            raise RuntimeError("失敗")
    check("自己確認: 状態を捨てる呼び方は拾う", names_cause(bad_post), False)
    check("ai_cite_check._post は HTTP の状態と本文を例外に載せる", names_cause(lambda: A._post("https://x/", {}, {})), True)
    check("引用の印が状態ごとに分かれる（404→モデル名）", A._mark({"error": "HTTP 404: x"}), "モデル名")
    lit = re.compile(r"""LinkedIn-Version["']\s*,\s*["']\d{6}""")
    check("検出器: LinkedIn-Version の直書きを拾う", bool(lit.search('req.add_header("LinkedIn-Version", "202405")')), True)
    check("LinkedIn-Version を直書きしない（1年で打ち切られる）", [p.name for p, t in scripts() if lit.search(t)], [])
    gm = re.compile(r"""GEMINI_MODEL["']\s*(?:\)\s*or|,)\s*["'](gemini-[^"']+)["']""")
    check("検出器: Gemini の既定モデルを拾う", gm.findall('os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")'), ["gemini-2.5-flash"])
    models = {f"{p.name}={m}" for p, t in scripts() for m in gm.findall(t)}
    check("Gemini の既定モデルが全スクリプトで同じ（片方だけ古いと404）", len({m.split("=")[1] for m in models}) <= 1, True)


# ══ 36. BOM なしの .ps1 を PowerShell 5.1 が誤読（2026-07-28）═══════════════════
def test_hist_ps1_has_bom():
    print("\n■ 履歴D: .ps1 は BOM 付き UTF-8（2026-07-28）")
    has = lambda b: b[:3] == b"\xef\xbb\xbf"
    check("検出器: BOM なしを拾う", has("Set-Location 'C:\\Users\\システム開発'".encode("utf-8")), False)
    check("検出器: BOM 付きは通す", has(b"\xef\xbb\xbf" + "Write-Host 'あ'".encode("utf-8")), True)
    ps = tracked("*.ps1")
    check(".ps1 を見つけられた", len(ps) > 0, True)
    check("全 .ps1 が BOM 付き", [f for f in ps if not has((ROOT / f).read_bytes())], [])


# ══ 37. 鍵JSONの BOM で Google API の認証が全滅（2026-07-27 / 08-01）════════════════
def bom_unsafe_loads(src):
    return [n.lineno for n in ast_nodes(src)[1] if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "from_service_account_file"]


def test_hist_credentials_read_bom_safe():
    print("\n■ 履歴D: 鍵JSONは BOM を許す読み方で読む（2026-07-27 / 08-01）")
    check("検出器: from_service_account_file を拾う",
          bom_unsafe_loads("c = service_account.Credentials.from_service_account_file('indexing-service-account.json')") != [], True)
    check("検出器: gcreds.load は通す", bom_unsafe_loads("c = gcreds.load(SA, scopes)"), [])
    check("scripts/ のサービスアカウント鍵は gcreds.load を通す",
          [f"{p.name}:{ln}" for p, t in scripts() if p.name != "gcreds.py" for ln in bom_unsafe_loads(t)], [])
    import gcreds
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sa.json"
        p.write_text(json.dumps({"type": "x"}), encoding="utf-8-sig")
        try:
            gcreds.load(p, [])
            parsed = True
        except ValueError as ex:
            parsed = "BOM" not in str(ex) and "Expecting value" not in str(ex)
        except Exception:
            parsed = True        # BOM は読めた（鍵として不完全なだけ）
        check("gcreds.load は BOM 付きの鍵を読める", parsed, True)
    warn("OAuth の鍵を *_file で読む（BOM で落ちる。youtube_upload は担当外のため保留）",
         [f"{p.name}:{n.lineno}" for p, t in scripts() for n in ast_nodes(t)[1]
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and n.func.attr in ("from_authorized_user_file", "from_client_secrets_file")])


# ══ 38. サイトIDの直書きが移植先で空振り（2026-08-24）═══════════════════════════
def site_enumerations(src, ids):
    """2つ以上のサイトIDを並べた tuple/list/set（全サイトを回すつもりの直書き）"""
    out = []
    for n in ast_nodes(src)[1]:
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)) and len(set(str_elems(n)) & ids) >= 2:
            out.append(n.lineno)
    return out


# 列挙が意味を持つものだけ通す。足すときは理由を書く
SITE_LIST_ALLOW = {"add_fact.py": "人が書き換える記入例の雛形"}


def test_hist_no_hardcoded_site_list():
    import sites as S
    print("\n■ 履歴D: 全サイトを回すときはサイトIDを直書きしない（2026-08-24）")
    ids = set(S.load_all())
    check("検出器: ('ai-lab', 'corporate', 'subsidy') を拾う",
          site_enumerations("for sid in ('ai-lab', 'corporate', 'subsidy'):\n    pass", {"ai-lab", "corporate", "subsidy"}) != [], True)
    check("検出器: 1つだけの既定値は拾わない", site_enumerations("def f(site='ai-lab'): pass", {"ai-lab", "corporate"}), [])
    check("sites.own_ids は受託のクライアントを除く", set(S.own_ids()) <= ids and len(S.own_ids()) >= 1, True)
    cur = [f"{p.name}:{ln}" for p, t in scripts() if p.name not in SITE_LIST_ALLOW for ln in site_enumerations(t, ids)]
    check("scripts/ にサイトIDの列挙が無い（sites.load_all / own_ids を使う）", cur, [])
    warn("許可リストで通したサイトIDの列挙", [f"{n}（{why}）" for n, why in SITE_LIST_ALLOW.items()
                                   if site_enumerations((SCRIPTS / n).read_text(encoding="utf-8-sig"), ids)])
    wf = [f"{n}: {m}" for n, _, t in workflows() for m in re.findall(r"--site[= ]\"?(" + "|".join(map(re.escape, ids)) + r")\b", t)]
    check("ワークフローにサイトIDの直書きが無い", wf, [])
    single = {p.name for p, t in scripts() if re.search(r"""["'](%s)["']""" % "|".join(map(re.escape, ids)), t)}
    warn("サイトIDの文字列を1つずつ書いているスクリプト（既定値・表示名。移植時に見直す）", single)


# ══ 42. ラッコの控えが CI で毎回消え、毎週課金（2026-09-27）════════════════════════
RAKKO_USERS = re.compile(r"python3? scripts/(kw_plan|kw_discover|rakko|findings)\.py")
RAKKO_WRITERS = {"kw_plan", "kw_discover"}


def rakko_paths():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    return sorted({l.strip().rstrip("/") for l in gi.splitlines() if "rakko" in l and not l.strip().startswith("#")})


def rakko_cache_problems(y, paths):
    out = []
    for jn, job in jobs(y):
        restored, saved_after = False, set()
        st = steps(job)
        for i, s in enumerate(st):
            uses = s.get("uses") or ""
            p = str((s.get("with") or {}).get("path") or "")
            if uses.startswith("actions/cache") and "/save" not in uses and all(x in p for x in paths):
                restored = True
            m = set(RAKKO_USERS.findall(s.get("run") or ""))
            if not m:
                continue
            if not restored:
                out.append(f"{jn}「{s.get('name')}」: ラッコの控えを戻す前に {','.join(sorted(m))}")
            if m & RAKKO_WRITERS:
                later = [t for t in st[i + 1:] if (t.get("uses") or "").startswith("actions/cache/save")
                         and all(x in str((t.get("with") or {}).get("path") or "") for x in paths)]
                if not later and not (s.get("uses") or "").startswith("actions/cache@"):
                    if not any((t.get("uses") or "").startswith("actions/cache@") for t in st[:i]):
                        out.append(f"{jn}「{s.get('name')}」: 使った後にラッコの控えを残していない")
    return out


def test_hist_rakko_cache_persists():
    print("\n■ 履歴D: ラッコの控えを CI の実行をまたいで持ち越す（2026-09-27）")
    paths = rakko_paths()
    check("Git 対象外のラッコの控えを見つけられた", "data/rakko_cache" in paths, True)
    pstr = "\n".join(paths)
    bad = {"jobs": {"w": {"steps": [{"name": "補充", "run": "python scripts/kw_discover.py --append"}]}}}
    good = {"jobs": {"w": {"steps": [
        {"name": "戻す", "uses": "actions/cache/restore@v4", "with": {"path": pstr}},
        {"name": "補充", "run": "python scripts/kw_discover.py --append"},
        {"name": "残す", "uses": "actions/cache/save@v4", "with": {"path": pstr}}]}}}
    check("検出器: 控えを戻さず残さない工程を拾う", len(rakko_cache_problems(bad, paths)), 2)
    check("検出器: 戻して残していれば通す", rakko_cache_problems(good, paths), [])
    cur = [f"{n} {x}" for n, y, _ in workflows() for x in rakko_cache_problems(y, paths)]
    check("ラッコを使うワークフローが控えを戻して残す", cur, [])


# ══ 43. KW計画の一新で新旧両方にある語が消えた（2026-09-21）════════════════════════
def _replace_with_fake_hub(KP, rows, picked):
    """kw_plan.replace_ledger を偽の管制塔で動かし、取り下げた語と積んだ語を返す"""
    import types
    calls = {"retire": [], "add": []}
    fake = types.ModuleType("hub_client")
    fake.enabled = lambda: True
    fake.all_kw = lambda strict=False: rows
    fake.retire_kw = lambda site, kws, reason, force=False: calls["retire"].extend(kws)
    fake.add_kw = lambda site, items: (calls["add"].extend(i["keyword"] for i in items), {"added": len(items)})[1]
    real, added, origin = sys.modules.get("hub_client"), KP.ADDED, getattr(KP, "ORIGIN", None)
    with tempfile.TemporaryDirectory() as d:
        try:
            sys.modules["hub_client"] = fake
            KP.ADDED = Path(d) / "added.json"
            if origin is not None:
                KP.ORIGIN = Path(d) / "origin.json"     # 積んだ語の出どころ（2026-10-09〜）も本物に書かない
            KP.replace_ledger("x", picked)
        finally:
            KP.ADDED = added
            if origin is not None:
                KP.ORIGIN = origin
            if real is not None:
                sys.modules["hub_client"] = real
            else:
                sys.modules.pop("hub_client", None)
    return calls


def gas_ledger_after(rows, retire, add):
    """hub.gs の retireKw_ → addKw_ を偽の台帳で動かし、行を返す"""
    src = (GAS / "hub.gs").read_text(encoding="utf-8")
    js = ("function FS(r){this.r=r;}FS.prototype.getLastRow=function(){return this.r.length+1;};"
          "FS.prototype.getRange=function(r,c,nr,nc){var s=this;return{getValues:function(){return s.r.slice(r-2,r-2+(nr||1))"
          ".map(function(x){return x.slice(c-1,c-1+(nc||1));});},getValue:function(){return s.r[r-2][c-1];},"
          "setValue:function(v){s.r[r-2][c-1]=v;}};};FS.prototype.appendRow=function(a){this.r.push(a.slice());};"
          f"var __sh=new FS({json.dumps(rows)});sheet_=function(){{return __sh;}};"
          f"retireKw_('x',{json.dumps(retire)},'計画を一新');addKw_('x',{json.dumps([{'keyword': k} for k in add])});"
          "globalThis.__out=__sh.r.map(function(x){return [x[1],x[2]];});")
    return node_run(src, js)


def test_hist_kw_replace_keeps_overlap():
    import kw_plan as KP
    print("\n■ 履歴D: KW計画の一新で、新旧両方にある語は未着手のまま残る（2026-09-21）")
    rows = [{"site": "x", "keyword": "経理代行 費用 相場", "status": "未着手"},
            {"site": "x", "keyword": "古い在庫の語", "status": "未着手"},
            {"site": "x", "keyword": "公開済みの語", "status": "公開済み"}]
    picked = [{"kw": "経理代行 費用相場", "priority": "A", "subject": "s", "intent": 1},
              {"kw": "新しい語", "priority": "B", "subject": "s", "intent": 1}]
    calls = _replace_with_fake_hub(KP, rows, picked)
    check("取り下げるのは旧計画だけにある語", calls["retire"], ["古い在庫の語"])
    real = KP.split_retire
    try:
        KP.split_retire = lambda todo, plan, own=(): (list(todo), [])
        bad = _replace_with_fake_hub(KP, rows, picked)
    finally:
        KP.split_retire = real
    check("自己確認: 未着手を全部取り下げる書き方では両方にある語が消える", "経理代行 費用 相場" in bad["retire"], True)
    sheet = [[r["site"], r["keyword"], r["status"]] + [""] * 8 for r in rows]
    after = gas_ledger_after(sheet, calls["retire"], calls["add"])
    if after is None:
        print("  WARN  node が無いため、管制塔側（hub.gs）の取り下げ・追加は確かめられません")
        return
    st = {k: s for k, s in after} if isinstance(after, list) else {}
    check("管制塔: 両方にある語は未着手のまま", st.get("経理代行 費用 相場"), "未着手")
    check("管制塔: 旧計画だけの語は対象外", st.get("古い在庫の語"), "対象外")
    check("管制塔: 公開済みは触らない", st.get("公開済みの語"), "公開済み")
    check("管制塔: 表記ゆれの重複を積まず、新しい語だけ増える",
          sorted(k for k, _ in after) == sorted(["経理代行 費用 相場", "古い在庫の語", "公開済みの語", "新しい語"]), True)


# ══ 59. Cloudflare 配下のAPIが既定の UA を弾く（2026-07-28）═════════════════════════
CF_HOSTS = ("api.resend.com", "api.openai.com", "api.perplexity.ai", "api.x.ai", "api.anthropic.com", "api.cloudflare.com")


def requests_without_ua(src):
    out = []
    for n in ast_nodes(src)[1]:
        if not (isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "Request" and n.args):
            continue
        seg = ast.get_source_segment(src, n) or ""
        if UA_HINT in seg:
            continue
        h = next((k.value for k in n.keywords if k.arg == "headers"), None)
        spread = isinstance(h, ast.Dict) and None in h.keys       # {**UA, ...}
        if h is not None and (spread or not isinstance(h, ast.Dict)) and UA_HINT in src:
            continue
        out.append(n.lineno)
    return out


def test_hist_api_requests_send_user_agent():
    print("\n■ 履歴D: Cloudflare 配下のAPIへは User-Agent を付ける（2026-07-28 Resend で error 1010）")
    check("検出器: UA の無い Request を拾う",
          requests_without_ua("urllib.request.Request('https://api.resend.com/emails', data=b)") != [], True)
    check("検出器: UA があれば通す",
          requests_without_ua("urllib.request.Request(u, data=b, headers={'User-Agent': 'x'})"), [])
    check("検出器: google の Request()（引数なし）は拾わない", requests_without_ua("c.refresh(Request())"), [])
    bad, other = [], []
    for p, t in scripts():
        lines = requests_without_ua(t)
        (bad if any(h in t for h in CF_HOSTS) else other).extend(f"{p.name}:{ln}" for ln in lines)
    check("Cloudflare 配下のAPIを呼ぶスクリプトの Request に UA がある", bad, [])
    warn("UA の無い Request（Cloudflare 配下以外。弾かれたら UA を足す）", other)


# ══ 61. Windows で claude/codex が見つからない・改行で指示が切れる（2026-09-22 / 10-01 / 10-03）═══
AGENT_NAMES = {"claude", "codex", "claude.cmd", "codex.cmd"}


def agent_call_problems(src):
    out = []
    for n in ast_nodes(src)[1]:
        if not isinstance(n, ast.Call) or not n.args or not isinstance(n.args[0], ast.List) or not n.args[0].elts:
            continue
        elts = n.args[0].elts
        s = str_elems(n.args[0])
        head = elts[0]
        is_agent = (isinstance(head, ast.Constant) and head.value in AGENT_NAMES) \
            or (isinstance(head, ast.Call) and getattr(head.func, "attr", getattr(head.func, "id", "")) == "claude_bin") \
            or (isinstance(head, ast.Name) and head.id in ("exe", "claude", "codex") and ("-p" in s or "exec" in s))
        if not is_agent or not ("-p" in s or "exec" in s):
            continue
        if isinstance(head, ast.Constant):
            out.append(f"{n.lineno}: 名前のまま起動（shutil.which で解決していない）")
        if not any(k.arg in ("input", "stdin_text") for k in n.keywords):
            out.append(f"{n.lineno}: 指示を引数で渡している（stdin で渡す）")
    return out


def test_hist_cli_agents_resolved_and_stdin():
    print("\n■ 履歴D: claude/codex は実体を解決し、指示は標準入力で渡す（2026-09-22 / 10-01 / 10-03）")
    check("検出器: subprocess.run(['claude','-p',prompt]) を拾う",
          len(agent_call_problems("subprocess.run(['claude', '-p', prompt])")), 2)
    check("検出器: claude_bin() と input= なら通す",
          agent_call_problems("subprocess.run([AR.claude_bin(), '-p'], input=prompt)"), [])
    check("検出器: git log -p は対象外", agent_call_problems("sh(['git', 'log', '-p', '--', f])"), [])
    cur = [f"{p.name}:{x}" for p, t in scripts() for x in agent_call_problems(t)]
    check("scripts/ の claude/codex 呼び出し", cur, [])


# ══ 追加. 複数パスの git add を 2>/dev/null || true で黙らせない（2026-10-03）══════════
GIT_ADD_QUIET = re.compile(r"git add\s+([^|;&\n]*?)\s*2>\s*/dev/null")


def quiet_multi_add(text):
    """1つでも無いパスがあると git add は何も入れずに失敗し、黙らせると台帳が消える"""
    out = []
    for m in GIT_ADD_QUIET.finditer(text):
        args = [a for a in m.group(1).split() if not a.startswith("-")]
        if len(args) >= 2:
            out.append(m.group(0))
    return out


def test_hist_git_add_paths_are_checked():
    print("\n■ 履歴D: 複数パスの git add を黙らせない（2026-10-03 台帳が消えて動画を二重投稿）")
    check("検出器: git add a b 2>/dev/null || true を拾う",
          quiet_multi_add("git add articles data/videos.json 2>/dev/null || true") != [], True)
    check("検出器: 1パスずつ確かめる書き方は通す",
          quiet_multi_add('for p in articles data/videos.json; do if [ -e "$p" ]; then git add "$p"; fi; done'), [])
    cur = [f"{n}: {x}" for n, _, t in workflows() for x in quiet_multi_add(t)]
    check("ワークフローに複数パスの git add 2>/dev/null が無い", cur, [])
