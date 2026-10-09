# -*- coding: utf-8 -*-
"""2026-10-10 運用者の指示「管制塔のリポジトリは公開のまま（GitHub Actions を無料で使うため）。お客様の情報が
公開されないように。守秘義務も問題ないようにしてほしい」から作った門。

公開されていたもの（2026-10-10 の点検）:
  - CONFLUX の会社情報・記事の材料・一次情報（data/clients/conflux/{company,brief,facts}.json）とキーワード計画
    （docs/kw-conflux.md。週次の補充が「自動補充」の行を積んでいた）
  - sites/conflux.json の戦略の部分（狙う業種・除外語・配分・優先・読者・売り物・監修・計測の ID）
  - 当社の料金と営業の台本（proposal_make.py・sales_* の台本・docs/sales/ の提案書・PROJECT.md）
  - 月次・週次・グループのレポート（reports/**。自社3サイトの実数と問い合わせの数）と 3倍計画（docs/growth-plan.md）
  - CI のログ: 記事の枠が site_brief をそのまま tee し、お客様の売り物と料金・狙う語・一次情報をログに出していた。
    kw_plan・rank 系・compete・findings・publish 系もお客様の語と順位を1語ずつ出していた。成果物（findings.txt）も
    誰でも落とせた

決めたこと:
  1. お客様の情報・料金と営業の台本・レポートは非公開のリポジトリ yoshi4476/ss-aio-private（private/。workflow は
     置かない）にだけ置き、読むのは scripts/private_store.py を通す
  2. sites/<お客様>.json は公開してよい項目（sites.PUBLIC_KEYS）だけ。残りは private の site_private.json
  3. CI のジョブは checkout の直後に .github/actions/private-data（取得と ::add-mask::）を通す
  4. 非公開のデータが取れなければ、お客様の社の記事・計画・配信は止めて知らせる（自社3サイトは動く）
  5. pull_request / pull_request_target で動く workflow を置かない（キャッシュと鍵を他人の変更提案から守る）
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

TIMING = {"sched_guard.py", "schedule_guard.py", "focus_report.py", "ci_rerun.py", "notify_slack.py"}
CLIENT_FILES = re.compile(r"^data/clients/[^/]+/(company|brief|facts|site_private|private)\.json$")
# 当社の料金の書き方（月額◯万円・初期費用◯万円・◯万円／月・"◯万〜◯万円"）。検索数（660万/月）や記事の例文
# （初期費用は平均755万円）は拾わない
PRICE = re.compile(r"(?:月額|初期費用)\s*[0-9０-９]+(?:\.[0-9]+)?\s*万|[0-9]+万(?:〜[0-9]+万)?円\s*[／/]\s*月"
                   r"|[\"'][0-9]+万〜[0-9]+万円[\"']")


def _ignored(rel):
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", rel]).returncode == 0


def _tracked():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, encoding="utf-8")
    return [x for x in r.stdout.splitlines() if x]


def _clients():
    import sites as S
    ids = {sid for sid in S.load_all() if S.is_client(sid)}
    ids |= {p.name for p in (ROOT / "data" / "clients").glob("*") if p.is_dir() and not p.name.startswith("_")}
    return sorted(ids)


def _workflows():
    import yaml
    out = {}
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        out[p.name] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return out


# ── 1. お客様の社のファイル・レポート・料金の資料を公開側で追跡しない ─────────────

def test_client_files_and_reports_are_not_tracked_in_public():
    print("\n■ 守秘義務: お客様の社のファイル・レポート・提案書を公開側で追跡しない（2026-10-10）")
    files = _tracked()
    clients = _clients()
    check("お客様の会社情報・記事の材料・一次情報・設定の戦略の部分を追跡していない",
          [f for f in files if CLIENT_FILES.match(f)], [])
    check("お客様のキーワード計画（docs/kw-<id>.md）を追跡していない",
          [f for f in files if any(f == f"docs/kw-{c}.md" or f.startswith(f"docs/kw-") and f.endswith(f"-{c}.md")
                                   for c in clients)], [])
    check("月次・週次のレポート（PDF・HTML）と目標値・3倍計画を追跡していない",
          [f for f in files if f.startswith("reports/") or f == "docs/growth-plan.md"], [])
    check("提案書（docs/sales/）を追跡していない", [f for f in files if f.startswith("docs/sales/")], [])
    check("非公開のリポジトリの写し（private/）を追跡していない", [f for f in files if f.startswith("private/")], [])
    # 名前にお客様の社の id が入る追跡ファイルは sites/<id>.json だけ（社ごとの記録の書き手が増えても漏れない）
    named = [f for f in files for c in clients
             if re.search(rf"(^|[/_.-]){re.escape(c)}([/_.-]|$)", f) and f != f"sites/{c}.json"
             and not f.startswith(("articles/", "site/", "tests/"))
             and not re.match(r"^data/clients/[^/]+/(delivered\.json|template\.html|menu_sent\.json)$", f)]
    check("名前にお客様の社の id が入る追跡ファイルは sites/<id>.json だけ", named, [])
    for rel in ("data/clients/client-zz/company.json", "data/clients/client-zz/brief.json",
                "data/clients/client-zz/facts.json", "data/clients/client-zz/site_private.json",
                "docs/kw-client-zz.md", "docs/kw-plan-client-zz.md", "docs/kw-priority-client-zz.md",
                "docs/kw-region-client-zz.md", "docs/kw-strong-client-zz.md", "reports/2026-10/report.pdf",
                "reports/targets.json", "reports/growth_plan.json", "docs/growth-plan.md", "docs/sales/x.pptx",
                "private/clients/x/brief.json"):
        check(f"新しい社・新しい月も既定で公開側から外れる: {rel}", _ignored(rel), True)
    check("自社3サイトのキーワード計画はこれまでどおりコミットできる",
          [r for r in ("docs/kw-corporate.md", "docs/kw-plan-corporate.md", "docs/kw-strong-subsidy.md",
                       "docs/kw-priority-ai-lab.md") if _ignored(r)], [])


# ── 2. sites/<お客様>.json は公開してよい項目だけ ────────────────────────────

def test_client_site_config_has_public_keys_only():
    print("\n■ 守秘義務: sites/<お客様>.json は公開してよい項目（sites.PUBLIC_KEYS）だけ")
    import sites as S
    full = {"id": "x", "domain": "x.example", "type": "external-md", "kw_seeds": {"industries": ["製造業"]},
            "ng_terms": ["aws"], "audience": "社長", "ga4_property_id": "1", "categories": {"a": "A"}}
    pub, priv = S.split_public(full)
    check("検出器: 戦略の部分（狙う業種・除外語・読者・計測の ID）は非公開へ分かれる",
          (sorted(pub), sorted(priv)), (["categories", "domain", "id", "type"],
                                        ["audience", "ga4_property_id", "kw_seeds", "ng_terms"]))
    for p in sorted(S.SITES_DIR.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        if not (raw.get("client") or (ROOT / "data" / "clients" / p.stem).is_dir()):
            continue
        check(f"sites/{p.name}: 許可していない項目が無い", sorted(set(raw) - set(S.PUBLIC_KEYS)), [])
        check(f"sites/{p.name}: お客様の印（client: true）がある（無いと CI で自社と判定される）",
              raw.get("client"), True)
    check("お客様の社は load_all で非公開の置き場の戦略の部分を重ねる",
          "private_store.site_private(cfg[\"id\"])" in (ROOT / "scripts" / "sites.py").read_text(encoding="utf-8"), True)


# ── 3. 公開側のコードに料金の数字が無い ────────────────────────────────

def test_no_prices_in_public_code():
    print("\n■ 守秘義務: 当社の料金と営業の台本を公開側のコードに置かない")
    check("検出器: 料金の書き方を拾う",
          [bool(PRICE.search(s)) for s in ("月額99万円", "初期費用 88万〜99万円", "77万円／月", '"11万〜22万円"')],
          [True] * 4)
    check("検出器: 検索数や記事の例文は拾わない",
          [bool(PRICE.search(s)) for s in ("（660万/月）", "農業の初期費用は平均755万円", "5万5千件の検索")],
          [False] * 3)
    targets = [p for p in (ROOT / "scripts").rglob("*.py")] + list((ROOT / "automation").glob("*.txt")) + \
        [ROOT / "PROJECT.md", ROOT / "CLAUDE.md", ROOT / "site.config.json"] + list((ROOT / "docs").rglob("*.md")) + \
        list((ROOT / ".github").rglob("*.yml"))
    hits = []
    for p in targets:
        if not p.is_file() or "private" in p.relative_to(ROOT).parts:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if PRICE.search(ln):
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    check("公開側のコード・指示・文書に料金の数字が無い", hits, [])
    check("営業の台本と提案資料の生成は公開側に無い（非公開のリポジトリの sales/）",
          [n for n in ("sales_script_doc", "sales_script_demo", "sales_script_pr", "sales_shift", "sales_deck",
                       "sales_pptx") if (ROOT / "scripts" / f"{n}.py").is_file()], [])
    src = (ROOT / "scripts" / "proposal_make.py").read_text(encoding="utf-8")
    check("提案書の料金のページは非公開の sales/proposal_pricing.json から読む",
          ("def pricing_pages()" in src, 'private_store.sales_json("proposal_pricing.json")' in src), (True, True))
    check("営業動画の台本は非公開の置き場から読み込む",
          all("private_store.sales_module(" in (ROOT / "scripts" / n).read_text(encoding="utf-8")
              for n in ("sales_video.py", "slide_check.py", "read_audit.py")), True)
    import proposal_make as PM
    with _env(SS_PRIVATE_DIR=str(ROOT / "no-such-private")):
        PM.build_pages(PM.facts())
        txt = "".join(map(str, PM.PAGES))
    check("非公開のデータが無くても提案書は作れ、料金の数字は出ない", bool(PM.PAGES) and not PRICE.search(txt), True)


# ── 4. 他人の変更提案（pull request）で動く workflow を置かない ─────────────────

def test_no_pull_request_workflows():
    print("\n■ 守秘義務: pull_request / pull_request_target で動く workflow が無い（キャッシュと鍵を守る）")
    bad = []
    for name, y in _workflows().items():
        on = y.get("on", y.get(True)) or {}
        keys = set(on) if isinstance(on, dict) else set(on if isinstance(on, list) else [on])
        bad += [f"{name}: {k}" for k in keys if str(k).startswith("pull_request")]
    check("pull_request / pull_request_target の起動が無い", bad, [])


# ── 5. お客様のデータを扱うジョブはログで伏せる ─────────────────────────────

def test_jobs_with_client_data_mask_logs():
    print("\n■ 守秘義務: お客様のデータを扱うジョブは checkout の直後に取得と伏せ（::add-mask::）を通す")
    missing, misplaced, notoken, arts = [], [], [], []
    for name, y in _workflows().items():
        for job, j in (y.get("jobs") or {}).items():
            steps = j.get("steps") or []
            text = json.dumps(steps, ensure_ascii=False)
            scripts = set(re.findall(r"python3? (?:-\S+ )*scripts/([\w/]+\.py)", text))
            co = next((i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout")), None)
            for s in steps:
                if "upload-artifact" in str(s.get("uses", "")):
                    path = str((s.get("with") or {}).get("path", ""))
                    if any(w in path for w in ("findings", "private", "data/clients", "reports", "docs/kw", "brief")):
                        arts.append(f"{name}/{job}: {path}")
            if co is None or not scripts or scripts <= TIMING:
                continue
            pd = next((i for i, s in enumerate(steps) if s.get("uses") == "./.github/actions/private-data"), None)
            if pd is None:
                missing.append(f"{name}/{job}")
                continue
            if pd != co + 1:
                misplaced.append(f"{name}/{job}")
            if "secrets.PRIVATE_DATA_TOKEN" not in str((steps[pd].get("with") or {}).get("token", "")):
                notoken.append(f"{name}/{job}")
    check("お客様のデータを扱う全ジョブに取得と伏せがある", missing, [])
    check("取得と伏せは checkout の直後（それより前の工程はログに何も出さない）", misplaced, [])
    check("鍵（PRIVATE_DATA_TOKEN、無ければ SITE_PUSH_TOKEN）を渡している", notoken, [])
    check("お客様の語が載りうるファイルを成果物（誰でも落とせる）にしない", arts, [])
    act = (ROOT / ".github" / "actions" / "private-data" / "action.yml").read_text(encoding="utf-8")
    cp = (ROOT / ".github" / "actions" / "client-private" / "action.yml").read_text(encoding="utf-8")
    check("private-data は取得してから伏せる",
          ("private_store.py --fetch" in act, "ci_mask.py" in act, act.index("--fetch") < act.index("ci_mask.py")),
          (True, True, True))
    check("client-private の restore は、戻した記録の語も伏せる", "ci_mask.py" in cp, True)
    import ci_mask as M
    corpus = ("aio対策の始め方\n補助金の申請", "事務局へ提出する書類と要件定義の進め方", "aio対策の始め方\n補助金の申請")
    pub = {"conflux", "conflux-partners.jp", "conflux partners の記事"}
    got = {w: M.usable(w, corpus, pub) for w in ("RAG 導入の費用", "ab", "export", "AIO 対策", "事務局",
                                                 "conflux-partners.jp", "https://conflux-partners.jp/package",
                                                 "顧問プラン（月額 99万円・年間契約）", "2026-10")}
    check("伏せる語の選び方: 守秘の語は伏せ、短い語・英数の短い語・自社の記事名の語・一般語・公開済みの名前は伏せない",
          got, {"RAG 導入の費用": True, "ab": False, "export": False, "AIO 対策": False, "事務局": False,
                "conflux-partners.jp": False, "https://conflux-partners.jp/package": False,
                "顧問プラン（月額 99万円・年間契約）": True, "2026-10": False})
    with _env(GITHUB_ACTIONS="", SS_PRIVATE_DIR=str(ROOT / "no-such-private")), contextlib.redirect_stdout(io.StringIO()) as o:
        M.main(["--count"])
    check("手元・件数だけの実行では語を出さない（::add-mask:: も出さない）", "::add-mask::" in o.getvalue(), False)


# ── 6. 導入の書き込み先は非公開の置き場 ─────────────────────────────────

def test_intake_writes_to_private_store():
    print("\n■ 守秘義務: ヒアリングシートの登録は、預かった内容を非公開の置き場にだけ書く")
    import client_intake as C
    import sites as S
    from gates_history_h38 import sample
    old = (C.ROOT, C.SITES)
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "sites").mkdir()
        C.ROOT, C.SITES = r, r / "sites"
        try:
            got = sample(C, "h76-git", "external-md")
            cfg = C.to_config(got)
            C.apply(got, cfg)
            raw = json.loads((r / "sites" / "h76-git.json").read_text(encoding="utf-8"))
            priv = r / "private" / "clients" / "h76-git"
            check("公開側の sites/<id>.json は公開してよい項目だけ（client: true 付き）",
                  (sorted(set(raw) - set(S.PUBLIC_KEYS)), raw.get("client")), ([], True))
            check("会社情報・記事の材料・一次情報・キーワード計画・設定の戦略の部分は非公開の置き場",
                  sorted(p.name for p in priv.iterdir()),
                  ["brief.json", "company.json", "facts.json", "kw.md", "private.json", "site_private.json"])
            check("公開側の data/clients/<id>/ と docs/kw-<id>.md には書かない",
                  ((r / "data" / "clients" / "h76-git").exists(), (r / "docs" / "kw-h76-git.md").exists()),
                  (False, False))
            sp = json.loads((priv / "site_private.json").read_text(encoding="utf-8"))
            check("設定の戦略の部分（狙う業種・読者）は site_private.json にある",
                  ("kw_seeds" in sp, "audience" in sp, "kw_seeds" in raw), (True, True, False))
        finally:
            C.ROOT, C.SITES = old
    iw = (ROOT / "scripts" / "intake_watch.py").read_text(encoding="utf-8")
    ci = (ROOT / "scripts" / "client_intake.py").read_text(encoding="utf-8")
    de = (ROOT / "scripts" / "intake_desktop.py").read_text(encoding="utf-8")
    check("登録の後に非公開のリポジトリへ commit・push する（intake_watch・client_intake）",
          ("C.save_private(" in iw, "save_private(cfg[\"id\"])" in ci), (True, True))
    check("手元に private/ が無ければ登録しない（公開側に落とさない）",
          ('(PS.base() / ".git").is_dir()' in iw, '(PS.base() / ".git").is_dir()' in ci), (True, True))
    check("デスクトップからの取り込みは公開側に sites/ だけを足す",
          ('["git", "add", "sites"]' in de, '"data/clients"' in de), (True, False))


# ── 7. 非公開のデータが無いとき、お客様の記事を書かずに止まる ─────────────────────

@contextlib.contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_client_work_stops_without_private_data():
    print("\n■ 守秘義務: 非公開のデータが取れない回は、お客様の社の記事・計画・配信を止めて知らせる（自社は動く）")
    import sites as S
    import private_store as PS
    clients = [s for s in S.load_all() if S.is_client(s)]
    if not clients:
        print("  WARN  お客様の社が無いため飛ばします")
        return
    sid = clients[0]
    old_root = S.ROOT
    with tempfile.TemporaryDirectory() as d, _env(SS_PRIVATE_DIR=str(Path(d) / "private")):
        S.ROOT = Path(d)                     # 移行前の場所（data/clients/）も無い状態
        try:
            with contextlib.redirect_stdout(io.StringIO()) as o:
                ok = PS.require(sid)
            check("お客様の社は止まり、要対応と PRIVATE_OK=no を出す",
                  (ok, "要対応:" in o.getvalue(), o.getvalue().strip().endswith("PRIVATE_OK=no")), (False, True, True))
            with contextlib.redirect_stdout(io.StringIO()):
                own_ok = PS.require("ai-lab") if "ai-lab" in S.load_all() else True
            check("自社の社は止めない", own_ok, True)
            check("お客様の社は公開側の印だけでお客様と判定され、自社の一覧に入らない",
                  (S.is_client(sid), sid in S.own_ids()), (True, False))
            import site_brief
            argv, sys.argv = sys.argv, ["site_brief.py", sid]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as o:
                    try:
                        site_brief.main()
                        code = 0
                    except SystemExit as e:
                        code = e.code
            finally:
                sys.argv = argv
            check("執筆の案内（site_brief）は書かずに止まる（終了コード3・材料を出さない）",
                  (code, "■ 狙う語" in o.getvalue()), (3, False))
            import kw_plan
            with contextlib.redirect_stdout(io.StringIO()) as o:
                kw_plan.run(sid, False, False)
            check("キーワードの計画は組まずに戻る（ラッコを呼ばない）", "PRIVATE_OK=no" in o.getvalue(), True)
        finally:
            S.ROOT = old_root
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("配信の入口（publish.py）も止める", 'private_store.require(cfg["id"], "配信")' in pub, True)
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("記事の枠は材料が読めない社を書かずに知らせる（skip と blocked・運用通知は送る）",
          ("--check-site" in wf, 'echo "blocked=yes"' in wf, "steps.site.outputs.blocked == 'yes'" in wf), (True, True, True))
    check("記事の枠はお客様の社の案内・語をログに出さない",
          ('python scripts/site_brief.py "${{ steps.site.outputs.id }}" | tee' in wf,
           "steps.site.outputs.quiet" in wf), (False, True))
    prompt = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("執筆の指示: 材料が読めないと出たら書かずに終える", "記事を書かずにそこで終える" in prompt, True)


# ── 8. 移した後も CONFLUX の材料が読める（非公開のデータがある手元・CI） ─────────────

def test_moved_client_data_still_reads():
    print("\n■ 守秘義務: 移した後も、お客様の材料・キーワード・配信の設定が今までどおり読める")
    import sites as S
    import private_store as PS
    clients = [s for s in S.load_all() if S.is_client(s)]
    ready = [s for s in clients if (PS.client_dir(s) / "site_private.json").is_file()]
    if not ready:
        print("  WARN  非公開のデータ（private/）が無いため飛ばします（CI では鍵の権限を確認）")
        return
    for sid in ready:
        cfg = S.load(sid)
        check(f"{sid}: サイト設定に戦略の部分が重なる（狙う業種・読者・カテゴリ）",
              all(cfg.get(k) for k in ("kw_seeds", "audience", "categories", "domain")), True)
        check(f"{sid}: 記事の材料・会社情報・一次情報を非公開の置き場から読む",
              all(PS.client_path(sid, n).is_file() and PS.client_dir(sid) in PS.client_path(sid, n).parents
                  for n in ("brief.json", "company.json", "facts.json")), True)
    import kw_plan
    main, ng = kw_plan.sheet_terms(ready[0])
    check("キーワードの計画がシートの狙う語を読む（brief.json の keyword）", bool(main), True)


def _sensitive_words(sid):
    """お客様の社の強い守秘の語（狙う語・狙わない語・売り物と料金・競合・事例・声・一次情報・まだ公開していない
    会社情報・除外語・読者・テーマ・計測の ID）。非公開の置き場から読む"""
    import ci_mask as M
    import private_store as PS
    b = PS.read_json(sid, "brief.json", {}) or {}
    c = PS.read_json(sid, "company.json", {}) or {}
    sp = PS.site_private(sid)
    kw = b.get("keyword") or {}
    out = list(kw.get("main") or []) + list(kw.get("sub") or []) + list(kw.get("exclude") or [])
    for part in (b.get("service"), b.get("compete"), b.get("cases"), b.get("voices")):
        out += list(M._leaves(part or {}))
    out += [f.get("claim", "") for f in (PS.read_json(sid, "facts.json", {}) or {}).get("facts", [])]
    out += [str(c.get(k) or "") for k in ("address", "tel", "email", "ceo", "capital", "postal", "corporate_number")]
    out += list(M._leaves({k: sp.get(k) for k in ("ng_terms", "kw_off", "kw_needs", "audience", "theme",
                                                    "main_offer", "cta_desc", "ga4_property_id")}))
    return [w.strip() for w in dict.fromkeys(out) if isinstance(w, str) and len(w.strip()) >= 4]


def test_public_code_has_no_client_secrets():
    print("\n■ 守秘義務: 公開側のコード・門・指示・文書に、お客様の狙う語・料金・一次情報・会社情報が無い")
    import sites as S
    import private_store as PS
    ready = [s for s in S.load_all() if S.is_client(s) and (PS.client_dir(s) / "brief.json").is_file()]
    if not ready:
        print("  WARN  非公開のデータ（private/）が無いため飛ばします")
        return
    files = _tracked()
    # 先方のサイトに公開済みの記事（articles/）に出ている語と、英数1語・一般の語は数えない
    pub = "\n".join((ROOT / f).read_text(encoding="utf-8", errors="ignore") for f in files
                    if f.startswith("articles/") and f.endswith(".md"))
    pub_ns = re.sub(r"[ 　]+", "", pub).lower()
    hits = []
    for sid in ready:
        ws = [w for w in _sensitive_words(sid)
              if not (w.isascii() and " " not in w and "@" not in w)
              and re.sub(r"[ 　]+", "", w).lower() not in pub_ns]
        for f in files:
            if not (f.startswith(("scripts/", "tests/", "automation/", "docs/", ".github/"))
                    or f in ("CLAUDE.md", "PROJECT.md", "site.config.json")):
                continue
            try:
                t = (ROOT / f).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hits += [f"{f}: {sid} の守秘の語（{len(w)}字）" for w in ws if w in t]
    check("公開側のコード・門・指示・文書にお客様の守秘の語が無い（非公開の門は private/tests/）", hits, [])
