# -*- coding: utf-8 -*-
"""2026-10-09 運用者の決定「書く記事（台帳の未着手）が1か月分を切ったら、その社だけラッコで調べる。月の途中でもよい。
一番成果（上位表示・問い合わせ）に直結する流れで組むこと」から。

それまで:
- 起動は月次（毎月1日）の「在庫の組み直し」だけで、月の途中で1か月分を切っても次の1日まで動かなかった
- ラッコの枠は「見出し・共起語 70／実際の質問 30」が一番大きいのに、headline・co-occurrence・question-search を
  どの工程も呼んでおらず、課金は効きの弱い関連語の大量取得（予備の枠 20）に寄っていた
- 検索の実績で4〜30位にいる（需要と届く見込みが実証済みの）語が、候補の先頭に来る作りではなかった

固定すること（どれも偽の管制塔・偽のラッコで確かめる。本物は1回も呼ばない）:
- 月の途中でも、1か月分を切った社だけ動く。同じ月に2回は動かない（組んだ月は社のIDと年月だけで残す）
- 課金は目的ごとの枠で使われ、見積もりを超えない。新しく使う3経路（見出し・共起語・質問）が実際に呼ばれる
- 取った見出し・共起語・質問が、執筆の指示（multi_site_prompt の 5c）と書き直しの指示（auto_rewrite の stuck・compete）に入る。
  相手の URL・題・説明文・本文は残さない（見出しは40字まで）
- お客様の社の分（調べ・計画・積んだ語の出どころ）は public の場所に出ない
- 並べ方: 実証済みの語に加点・主力の割合を保つ・ピラーは個別の記事の後・検索数だけの語は積まない・
  既存記事が順位を持つ実証済みの語は新しく書かず書き直しへ回す
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(obj, **kw):
    saved = {k: getattr(obj, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(obj, k, v)
        yield obj
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


PRICE = {"/v1/headline": 3.0, "/v1/co-occurrence": 3.0, "/v1/question-search": 1.5,
         "/v1/suggest-keywords": 1.5, "/v1/related-keywords": 1.5}
LONG_HEAD = "上位ページの見出しはとても長いことがあるのでここで四十字を超える文を入れておきますね、確かめるために"


class FakeRakko:
    """ラッコの代わり。公式の資料（v1.21.0）の形と単価で返す。相手の URL・題・説明文も返す（残さないことを確かめる）"""

    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=0):
        url = req.full_url
        if not url.startswith("https://api.rakkokeyword.com"):
            raise AssertionError("ラッコ以外への通信: " + url)
        path = urllib.parse.urlparse(url).path
        body = json.loads(req.data.decode()) if req.data else {}
        self.calls.append(path)
        kw = body.get("keyword", "")
        if path == "/v1/headline":
            items = [{"page": {"url": f"https://rival{i}.example.com/p", "title": f"競合の題{i}", "description": "競合の説明文"},
                      "metrics": {"position": i + 1, "headlineCount": 12, "wordCount": 8000},
                      "headlines": [{"level": "h1", "text": f"{kw}の題"}, {"level": "h2", "text": f"{kw}とは"},
                                    {"level": "h2", "text": f"{kw}の費用相場"}, {"level": "h2", "text": LONG_HEAD}]}
                     for i in range(3)]
            data = {"query": {"keyword": kw}, "summary": {"totalCount": 3, "returnedCount": 3, "averageHeadlineCount": 12,
                                                          "averageWordCount": 8000, "minWordCount": 1, "maxWordCount": 9},
                    "items": items}
        elif path == "/v1/co-occurrence":
            data = {"query": {"keyword": kw}, "summary": {"totalCount": 2, "returnedCount": 2},
                    "items": [{"word": "相場", "metrics": {"siteCountTotal": 9, "siteCountHeading": 7},
                               "keywordMetrics": {}},
                              {"word": "外注", "metrics": {"siteCountTotal": 8, "siteCountHeading": 2}, "keywordMetrics": {}}]}
        elif path == "/v1/question-search":
            data = {"query": {"keyword": kw}, "summary": {"totalCount": 1, "returnedCount": 1},
                    "items": [{"question": f"{kw}の相場はいくらですか?", "metrics": {"relativeDemand": 100}}]}
        else:
            data = {"keywords": [], "items": []}
        out = {"result": True, "meta": {"consumedCredit": PRICE.get(path, 99.0)}, "data": data, "errors": []}
        return io.BytesIO(json.dumps(out, ensure_ascii=False).encode())


@contextlib.contextmanager
def sandbox():
    """本物の台帳・控え・管制塔・ラッコ・計画ファイル・調べの置き場に触らずに動かす"""
    import hub_client
    import kw_plan as KP
    import kw_serp
    import rakko
    td = Path(tempfile.mkdtemp())
    net = FakeRakko()
    old_ci = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        with patched(rakko, SPEND_LOG=td / "spend.jsonl", CACHE_DIR=td / "cache", api_key=lambda: "k",
                     RETRY_WAIT=(0, 0, 0), _GRANT=None, CONSUMED=0.0, BUDGET=None, _OUT_OF_CREDIT=False), \
                patched(rakko.urllib.request, urlopen=net), \
                patched(hub_client, enabled=lambda: False, _post=lambda b: None), \
                patched(kw_serp, DIR=td / "kw_serp"), \
                patched(KP, RUNS=td / "runs.json", VOL_CACHE=td / "vol.json", DRY=False, DEEP=False):
            rakko._SAID.clear()
            yield td, net
    finally:
        if old_ci is not None:
            os.environ["GITHUB_ACTIONS"] = old_ci


def _site():
    return {"id": "x", "cfg": {"id": "x", "name": "門の社", "domain": "x.example.com"}, "gsc": "",
            "industries": ["zq"], "intents": [], "own_terms": ("zq",), "ng_terms": ()}


BUY = ("外注", "代行", "委託", "依頼", "比較", "料金", "見積", "業者")
PLACE = ("東京", "大阪", "福岡", "札幌", "仙台", "広島")


def _cands(n=12):
    """買い手の語×地名の候補（どの2つも同じ検索とみなされない形）。サブジェクトは地名（1つの束の枠で落ちないように）"""
    import kw_plan as KP
    c = {}
    for i, (b, p) in enumerate([(b, p) for p in PLACE for b in BUY][:n]):
        KP._put(c, f"zq {b} {p}", p, "suggest", vol=500 - i)
    return c


@contextlib.contextmanager
def _flow(todo, added, n=12):
    """run() を偽の材料で最後まで動かす（台帳・GSC・計画ファイルには触らない）"""
    import kw_discover as KD
    import kw_plan as KP
    import pace
    with sandbox() as (td, net), \
            patched(KD, site_config=lambda s: _site()), \
            patched(pace, quota=lambda s: 2), \
            patched(KP, todo_count=lambda s: len(todo), sheet_terms=lambda s: ([], []),
                    stock=lambda s: {"ok": True, "todo": list(todo), "a": [], "keys": set()},
                    collect_free=lambda s, S, cands=None: _cands(n), gsc_owned=lambda s: [],
                    write_plan=lambda *a, **k: ROOT / "docs" / "kw-plan-x.md",
                    add_ledger=lambda s, picked: added.append([c["kw"] for c in picked]) or True):
        yield td, net


def test_runs_mid_month_only_below_one_month_once_a_month():
    import kw_plan as KP
    import rakko
    print("\n■ 在庫の見張り: 1か月分を切った社だけ、月の途中でもその日に組む。同じ月に2回は組まない")
    month = rakko.this_month()
    added = []
    with _flow(["既存 %d" % i for i in range(10)], added) as (td, net):
        _quiet(KP.run, "x", False, False, if_needed=True)
        check("未着手10本（1か月分60を切る）なら、その日に組んで台帳に積む", len(added), 1)
        check("組んだ月を社のIDと年月だけで残す", json.loads((td / "runs.json").read_text(encoding="utf-8")), {"x": month})
        _, out = _quiet(KP.run, "x", False, False, if_needed=True)
        check("同じ月の2回目は組まない（1社1か月1回）", (len(added), "もう組みました" in out), (1, True))
        (td / "runs.json").write_text(json.dumps({"x": "2000-01"}), encoding="utf-8")
        _quiet(KP.run, "x", False, False, if_needed=True)
        check("前の月に組んだ社は、今月また1か月分を切れば組む", len(added), 2)
    added.clear()
    with _flow(["既存 %d" % i for i in range(60)], added) as (td, net):
        _quiet(KP.run, "x", False, False, if_needed=True)
        check("未着手60本（1か月分ちょうど）なら組まない", (added, (td / "runs.json").exists()), ([], False))
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    run_src = src[src.index("def run("):src.index("def main(")]
    check("組んだ月を残すのは台帳に積めた後だけ（積めなければ翌日やり直す）",
          0 < run_src.find("add_ledger(site_id, picked)") < run_src.find("mark_done(site_id, month)"), True)

    import yaml
    daily = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-kpi.yml").read_text(encoding="utf-8"))
    job = (daily.get("jobs") or {}).get("kw-stock") or {}
    runs = "\n".join(str(s.get("run") or "") for s in job.get("steps") or [])
    check("毎日の workflow（daily-kpi.yml）に在庫の見張りのジョブがある", bool(job), True)
    check("見張りは --if-needed で、一新（--replace）しない", ("kw_plan.py --all --if-needed" in runs, "--replace" in runs),
          (True, False))
    check("課金の前に dry-run の構成と見積もりを記録する", 0 <= runs.find("--if-needed --dry-run") < runs.find("--if-needed 2>&1) ||"),
          True)
    check("上限で止めた回を要対応にする（社・全体・1回・目的の枠）",
          all(w in runs for w in ("site_cap", "total_cap", "run_cap", "bucket")), True)
    check("見張りのジョブは KPI の集計と別（落ちても集計を止めない）", "daily_kpi.py" in runs, False)
    check("見張りのジョブは書き込みの権限を自分だけ持つ", (job.get("permissions") or {}).get("contents"), "write")
    monthly = yaml.safe_load((ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8"))
    mruns = " ".join(str(s.get("run") or "") for j in monthly["jobs"].values() for s in j.get("steps") or [])
    check("月次（1日）は在庫を組まない（毎日の見張りと二重に組まない）", "kw_plan.py" in mruns, False)


def test_rakko_budget_is_spent_by_purpose():
    import kw_plan as KP
    import kw_serp
    import rakko
    print("\n■ ラッコ: 見出し・共起語（70）と実際の質問（30）の枠で、新しい3経路を呼ぶ。見積もりと目的ごとの枠を超えない")
    def spent_and_est(out):
        used = {p: rakko.month_spent(None, "x", p) for p in rakko.BUDGET_SPLIT}
        est = dict(item.split(":") for item in out.split("RAKKO_EST_PARTS=")[1].splitlines()[0].split(","))
        return used, {p: float(v) for p, v in est.items()}

    split = rakko.budget_split("x")
    # 無料の候補で足りる回（積む17本に対して候補48本）: 予備は使わない
    added = []
    with _flow(["既存 %d" % i for i in range(55)], added, n=48) as (td, net):
        _, out = _quiet(KP.run, "x", False, False, if_needed=True)
        used, est = spent_and_est(out)
        check("新しい3経路（見出し・共起語・実際の質問）を呼ぶ",
              {"/v1/headline", "/v1/co-occurrence", "/v1/question-search"} <= set(net.calls), True)
        check("見出し・共起語は headline の枠、質問は qa の枠で数える", (used["headline"] > 0, used["qa"] > 0), (True, True))
        check("無料の候補で足りる回は、予備（サジェスト・関連語）を見積もらず使わない",
              (est.get("reserve", 0.0), used["reserve"], "/v1/suggest-keywords" in net.calls), (0.0, 0.0, False))
        check("どの目的も見積もりを超えない", [p for p in used if used[p] > est.get(p, 0) + 1e-9], [])
        check("どの目的も月の枠を超えない", [p for p in used if used[p] > split[p] + 1e-9], [])
        check("積むのは1か月分×1.2 まで（未着手55本 → 72−55＝17本）", len(added[0]), 17)
    # 無料の候補で足りない回（積む62本に対して候補12本）: 予備の枠だけで、ラッコのサジェスト・関連語を使う
    added = []
    with _flow(["既存 %d" % i for i in range(10)], added, n=12) as (td, net):
        _, out = _quiet(KP.run, "x", False, False, if_needed=True)
        used, est = spent_and_est(out)
        check("足りない回は予備を使う（予備の見積もりの中で）", (used["reserve"] > 0, used["reserve"] <= est.get("reserve", 0)),
              (True, True))
        check("どの目的も見積もり・月の枠を超えない",
              [p for p in used if used[p] > min(est.get(p, 0), split[p]) + 1e-9], [])
    # 枠の残りより大きくは見積もらない（今月すでに見出しの枠を66使った社は、残りの4まで）
    with sandbox() as (td, net):
        rakko.SPEND_LOG.write_text(json.dumps({"at": rakko.this_month() + "-02T00:00:00+09:00", "path": "/v1/headline",
                                               "credit": 66.0, "site": "x", "purpose": "headline"}) + "\n", encoding="utf-8")
        S = _site()
        need = KP.plan_need(S, {}, [("write", "zq 費用", "門"), ("write", "zq 相場", "門")], [], False)
        check("見積もりは目的ごとの今月の残りまで（見出し 70−66＝4）", need.get("headline"), 4.0)
        S["need"] = need
        check("計画の見積もり（S['need']）がそのまま許可の見積もりになる", KP.estimate_parts(S), {"headline": 4.0})
        ok, _ = _quiet(rakko.allow, "x", {"headline": 4.0})
        r1, _ = _quiet(rakko.call, rakko.SUGGEST, rakko.suggest_body("zq"))
        check("許可に無い目的（予備）では呼ばない", (ok, r1, "/v1/suggest-keywords" in net.calls), (True, None, False))


def test_saved_headlines_and_questions_reach_writing_and_rewriting():
    import auto_rewrite as AR
    import kw_plan as KP
    import kw_serp
    import rakko
    print("\n■ 取った見出し・共起語・質問を残し、執筆と書き直しの指示に入れる（相手の URL・題・本文は残さない）")
    arts = [p for p in sorted((ROOT / "articles").glob("*.md"))]
    slug, site, kw = None, None, None
    for p in arts:
        s, k = kw_serp.article_meta(p.stem)
        if s and k:
            slug, site, kw = p.stem, s, k
            break
    check("門で使う記事がある（社と狙う語が読める）", bool(slug), True)
    with sandbox() as (td, net):
        _quiet(rakko.allow, site, {"headline": 6.0, "qa": 1.5})
        got, _ = _quiet(KP.fetch_serp, site, [("rewrite", kw, "門")], [kw], {"headline": 6.0, "qa": 1.5})
        rec = kw_serp.get(site, kw)
        raw = (kw_serp.DIR / f"{site}.json").read_text(encoding="utf-8")
        heads = [h[1] for p in (rec or {}).get("headline", {}).get("pages", []) for h in p["heads"]]
        check("見出し・共起語・質問を語ごとに残す", (bool(got), bool(rec and rec.get("headline")),
                                           bool(rec and rec.get("cooccur")), bool(rec and rec.get("questions"))),
              (True, True, True, True))
        check("見出しは40字まで", max(len(h) for h in heads) <= kw_serp.HEAD_MAX, True)
        check("相手の URL・題・説明文は残さない", [w for w in ("http", "競合の題", "競合の説明文") if w in raw], [])
        text = "\n".join(kw_serp.brief(site, kw))
        check("執筆の指示に見出し・共起語・質問が入る",
              (f"{kw}の費用相場" in text, "相場" in text, f"{kw}の相場はいくらですか?" in text), (True, True, True))
        check("執筆の指示は、FAQ の答えを記事の事実だけで書かせる", "答えは記事の事実" in text and "数字" in text, True)
        for kind, extra in (("stuck", {}), ("compete", {"gap": {"kw": kw, "diffs": [], "facts": []}})):
            item = dict({"kind": kind, "slug": slug, "site": site, "why": "門の検査"}, **extra)
            prompt, _allowed = AR.build_prompt(item)
            check(f"書き直し（{kind}）の指示に上位の見出しと質問が入る",
                  (f"{kw}の費用相場" in prompt, f"{kw}の相場はいくらですか?" in prompt), (True, True))
    tmpl = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("記事の枠の指示が kw_serp.py --brief を読む（5c）", 'kw_serp.py --brief "$SITE_ID"' in tmpl, True)
    import client_private as CP
    check("お客様の社の調べは CI のキャッシュで執筆・書き直しへ渡る（client_private の種類）",
          any("data/kw_serp/{}.json" in ts for ts in CP.PER_SITE.values()), True)


def test_client_plan_and_research_stay_private():
    import client_private as CP
    import kw_plan as KP
    print("\n■ お客様の社の調べ・計画・積んだ語の出どころは public の場所に出ない")
    # ラッコで取った見出し・共起語・質問は、規約（社内利用）に合わせて自社の分も Git に入れない（2026-10-09）
    for rel, want in (("data/kw_serp/client-zz.json", 0), ("docs/kw-plan-client-zz.md", 0), ("data/kw_serp/corporate.json", 0),
                      ("data/clients/_own/private/corporate/data/kw_serp/corporate.json", 0), ("docs/kw-plan-corporate.md", 1)):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel])
        check(f"{'Git に入らない' if want == 0 else 'Git に入る（自社）'}: {rel}", r.returncode, want)
    check("ラッコの調べは自社の社も置き場で持ち越す", "kw_serp" in CP.ALL_SITES, True)
    own = CP.private_path("corporate", "data/kw_serp/corporate.json").relative_to(CP.ROOT).as_posix()
    check("自社の社の置き場は data/clients/<社>/ を作らない（作るとお客様と判定される）",
          (own.startswith("data/clients/corporate/"), own.startswith("data/clients/_own/private/")), (False, True))
    import sites as SS
    check("置き場の区画の名前は社の id に無い", CP.OWN in SS.load_all(), False)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data" / "kw_serp").mkdir(parents=True)
        (base / "data" / "kw_serp" / "corporate.json").write_text("{}", encoding="utf-8")
        with patched(CP, ROOT=base, clients=lambda: [], is_private=lambda s: False), \
                patched(CP.S, load_all=lambda: {"corporate": {}}):
            n = CP.pack(["kw_serp"])
            (base / "data" / "kw_serp" / "corporate.json").unlink()
            back = CP.unpack(["kw_serp"])
        check("自社の社の調べも置き場へ写り、次のジョブで戻る",
              (n, (base / "data" / "clients" / "_own" / "private" / "corporate" / "data" / "kw_serp" / "corporate.json").is_file(),
               back, (base / "data" / "kw_serp" / "corporate.json").is_file()), (1, True, 1, True))
        check("自社の社のフォルダ（data/clients/corporate）は作られない",
              (base / "data" / "clients" / "corporate").exists(), False)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data").mkdir()
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"), \
                patched(KP, ORIGIN=base / "data" / "kw_origin.json"):
            KP.remember_origin("cx", [{"kw": "お客様の語", "src": {"gsc"}, "priority": "A", "proven": True}])
            KP.remember_origin("ai-lab", [{"kw": "自社の語", "src": {"seed"}, "priority": "B"}])
            pub = (base / "data" / "kw_origin.json").read_text(encoding="utf-8")
            priv = CP.private_path("cx", "data/kw_origin.json").read_text(encoding="utf-8")
    check("積んだ語の出どころ: お客様の社の語は置き場へ、自社は public へ",
          ("お客様の語" in pub, "自社の語" in pub, "お客様の語" in priv, '"src": "gsc"' in priv), (False, True, True, True))
    for rel in ("data/kw_origin.json", "data/kw_plan_runs.json"):
        p = ROOT / rel
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        check(f"{rel} にお客様の社の語が無い（組んだ月は社のIDと年月だけ）",
              [k for k, v in d.items() if CP.is_private(k) and not (rel.endswith("runs.json") and isinstance(v, str)
                                                                  and len(v) == 7)], [])
    import yaml
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-kpi.yml").read_text(encoding="utf-8"))["jobs"]["kw-stock"]
    steps = job["steps"]
    uses = [str(s.get("uses") or "") + str(s.get("with") or "") for s in steps]
    runs = "\n".join(str(s.get("run") or "") for s in steps)
    check("見張りのジョブはお客様の置き場を戻して残す（client_private の restore と save）",
          (any("client-private" in u and "restore" in u for u in uses), any("client-private" in u and "save" in u for u in uses)),
          (True, True))
    check("見張りのジョブはまとめて足さない（git add -A を使わない。お客様のファイルは .gitignore で外れる）",
          "git add -A" in runs, False)


def test_ranking_puts_proven_and_main_first():
    import kw_plan as KP
    print("\n■ 並べ方: 実証済みの語に加点・主力の割合を保つ・ピラーは後・検索数だけの語は積まない・食い合う実証済みの語は書き直しへ")
    base = {"kw": "zq 外注 東京", "vol": 100, "kd": 30, "subject": "s"}
    check("実証済み（4〜30位・表示10回以上）の語に加点", round(KP.score(dict(base, proven=True)) - KP.score(base), 2), KP.GSC_PROVEN)
    S = _site()
    cands = _cands(12)
    KP._put(cands, "zq 外注 費用 相場", "札幌", "suggest", vol=50)
    KP._put(cands, "zq 外注", "札幌", "seed", vol=9000)           # 「zq 外注 費用 相場」「zq 外注 東京」のピラー（広い語）
    KP._put(cands, "zq 書類 一覧", "仙台", "suggest", vol=5000)    # 検索数だけの語（買い手・開く理由・主力・実績なし）
    rule = lambda k: "委託" in k or "依頼" in k
    with patched(KP, written_corpus=lambda: [], load_articles=lambda: []):
        picked, dropped = KP.choose(cands, S, "x", limit=4, main=(rule, 2), owned=[], floor=True)
    kws = [c["kw"] for c in picked]
    check("主力の語で決めた本数を先に満たす（点の高い語より先に、主力2本）", sum(1 for k in kws if rule(k)), 2)
    with patched(KP, written_corpus=lambda: [], load_articles=lambda: []):
        picked, dropped = KP.choose(cands, S, "x", limit=20, owned=[], floor=True)
    kws = [c["kw"] for c in picked]
    check("検索数だけの語は積まない（買い手・開く理由・主力・実績のどれも無い）",
          ("zq 書類 一覧" in kws, dropped.get("買い手の根拠が無い（検索数だけ）")), (False, 1))
    check("優先度は並びの順に A/B/C", [c["priority"] for c in picked][:1] + [c["priority"] for c in picked][-1:], ["A", "C"])
    # ピラー: 「zq 外注」は「zq 外注 費用 相場」の言葉を全部含まれる広い語。点が高くても個別の記事の後に置く
    c3 = {}
    KP._put(c3, "zq 外注 費用 相場", "札幌", "suggest", vol=50)
    KP._put(c3, "zq 代行 料金 比較", "仙台", "suggest", vol=40)
    KP._put(c3, "zq 外注", "GSC実証", "gsc", vol=900, imp=40, pos=12.0, proven=True)
    with patched(KP, written_corpus=lambda: [], load_articles=lambda: []):
        picked, _ = KP.choose(c3, S, "x", limit=5, owned=[], floor=True)
    kws = [c["kw"] for c in picked]
    by = {c["kw"]: c for c in picked}
    check("ピラー（広い語）は点が高くても、その束の個別の記事より後",
          (by["zq 外注"]["score"] > by["zq 外注 費用 相場"]["score"],
           kws.index("zq 外注") == kws.index("zq 外注 費用 相場") + 1, by["zq 外注"].get("pillar")), (True, True, True))
    proven = {KP.norm("zq 費用"): {"kw": "zq 費用", "proven": True, "pos": 12.0, "imp": 40, "src": {"gsc"}},
              KP.norm("zq 相場"): {"kw": "zq 相場", "proven": True, "pos": 8.0, "imp": 30, "src": {"gsc"}},
              KP.norm("zq 比較"): {"kw": "zq 比較", "proven": True, "pos": 9.0, "imp": 30, "src": {"gsc"}}}
    owned = [{"q": "zq 費用", "page": "https://x.example.com/blog/zq-cost/", "pos": 12.0, "imp": 40, "site": "x", "own": True},
             {"q": "zq 相場", "page": "https://x.example.com/", "pos": 8.0, "imp": 30, "site": "x", "own": True}]
    to_rw, blocked = KP.route_proven("x", proven, owned, {"zq-cost": "zq 費用 相場"})
    check("既存記事が順位を持つ実証済みの語は、新しく書かず書き直しへ（新記事は食い合う）",
          [(r["kw"], r["slug"]) for r in to_rw], [("zq 費用", "zq-cost")])
    check("記事以外のページが順位を持つ実証済みの語は積めない語として残す（kw_guard が着手禁止にする）",
          [r["kw"] for r in blocked], ["zq 相場"])
    rw = KP.rewrite_targets("x", {"zq-cost": "zq 費用 相場"}, to_rw)
    check("書き直しへ回した記事は、見出し・共起語を取る対象に入る（狙う語は記事の keyword）",
          [(r["slug"], r["kw"]) for r in rw], [("zq-cost", "zq 費用 相場")])
    # 実証済みの語のうち、どのページも順位を持たない（kw_guard が止めない）語は、新しく書く候補の先頭に来る
    c2 = _cands(12)
    KP._put(c2, "zq 比較", "GSC実証", "gsc", imp=30, pos=9.0, proven=True)
    with patched(KP, written_corpus=lambda: [], load_articles=lambda: []):
        picked, _ = KP.choose(c2, S, "x", limit=5, owned=[], floor=True)
    check("実証済み（4〜30位）で順位を持つページの無い語は、新しく書く候補の先頭", picked[0]["kw"], "zq 比較")
    plan = KP.serp_plan("x", ["a1", "a2", "a3"], [{"slug": "s1", "kw": "r1", "why": "w"}, {"slug": "s2", "kw": "r2", "why": "w"}])
    check("見出し・共起語は、これから書くAと書き直しを交互に（片方だけで枠を使い切らない）",
          [k for _t, k, _w in plan], ["a1", "r1", "a2", "r2", "a3"])
    check("出どころは成果に近い順で1つ（4〜30位の実績 > シート > 主力×業種 > …）",
          KP.primary_src({"src": {"suggest", "rising", "cache"}}), "gsc")
    # 書く順（next_kw）でも、実証済みの語を台帳の並び・語の形の規則より先に拾う
    import hub_client as HC
    import kw_reach as R
    led = [{"site": "s", "status": "未着手", "keyword": k, "priority": "B"}
           for k in ("aio 費用 相場 中小企業", "aio 外注 東京")]
    with patched(HC, enabled=lambda: True, all_kw=lambda strict=False: led, _ai_targets=lambda s: set(),
                 _get=lambda p: {"ok": True, "keyword": "aio 費用 相場 中小企業", "category": "aio", "aim": ""},
                 _main_offer_pattern=lambda s: r"aio", _drop_pattern=lambda s: "", _unfit=lambda s: (lambda k: False),
                 _proven_targets=lambda s: {HC._norm("aio 外注 東京")}), patched(R, held_queries=lambda s: []):
        got = HC.next_kw("s")
    check("次に書く語は、実証済みの語（4〜30位）を先に拾う", (got["keyword"], got.get("picked_by")),
          ("aio 外注 東京", "実証済みの語（4〜30位）"))


def test_main_first_adds_only_main_words_as_a_without_retiring():
    """2026-10-09 補助金: 未着手106本中の主力が2本。一新は主力の候補が11本しか無く在庫を28本に減らすだけなので、
    主力の語だけを優先度Aで積み足す（今の未着手は消さない・月1回の組みとは数えない）"""
    import kw_plan as KP
    print("\n■ 主力の語だけを優先度Aで積み足す（--main-first）")
    got, retired = [], []
    with _flow(["既存 %d" % i for i in range(100)], []) as (td, net), \
            patched(KP, main_rule=lambda s: ((lambda kw: "代行" in kw), 55, "主力"),
                    add_ledger=lambda s, picked: got.append([(c["kw"], c["priority"]) for c in picked]) or True,
                    replace_ledger=lambda *a, **k: retired.append(1)):
        _quiet(KP.run, "x", False, False, main_first=5)
        check("在庫が足りていても、主力の語だけを積む（優先度はすべてA）",
              (len(got), bool(got and got[0]), all("代行" in k and p == "A" for k, p in (got[0] if got else []))),
              (1, True, True))
        check("今の未着手は取り下げない・月1回の組みとは数えない", (retired, (td / "runs.json").exists()), ([], False))
