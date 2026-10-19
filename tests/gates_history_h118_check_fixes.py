# -*- coding: utf-8 -*-
"""2026-10-20 の点検: 検査・検出器が「見つからない」「動かなかった」を「問題なし」と読んでいた所を直した。

- score_check: 一次情報の目印に年（2026 など）が入り、鮮度の表記がある記事はどれも通っていた
- daily_audit: 読みやすさの検査が score_check の出力（WARN・「長文」）を読めず、1本も拾っていなかった。
  動かなかった検査（台帳・配信先の一覧・GSC・ビルド・本番の確認）を AUDIT_SKIPPED に残していなかった。
  表示ゼロの判定が URL の形を /<カテゴリ>/ と /blog/ に決め打ちしていた
- pace: 1社を測れないと前の判定（0本など）が保存で消え、翌日から黙って2本に戻っていた
- findings: 1日1本→0本・件数の入れ替わり・割合の変化を「先週と同じ」と読んでいた。印 yes の後で落ちた回を
  問題なしと、印の無い故障を要対応と読んでいた
- seo_audit: sitemap を読めないサイトがあっても yes
- outcome_watch: 週刊の配信の回を始まった時刻で見分けていた（遅れた回を取り違える）
- kw_plan・kw_guard: GSC が落ちた日に実績の語を照合なしで積み、他サイトの取得失敗を黙って飛ばしていた
- kw_fit: 英字の他社名を英字の語の途中（dashboard の board）で当てていた
- originality: 「相談を受けるなかで」「ある歯科では」を拾っていなかった
"""
import contextlib
import io
import sys
import types
from datetime import date

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(*items):
    """(物, 名前, 値) を差し替えて、終わったら必ず戻す"""
    old = [(o, n, getattr(o, n, None), hasattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v, had in old:
            if had:
                setattr(o, n, v)
            else:
                delattr(o, n)


def run_quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


class _Done:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_fact_tokens_skip_years():
    import score_check as SC
    print("\n■ 一次情報の目印に年を数えない（鮮度の表記で全記事が通っていた）")
    claim = "当社のAIO運用は2023年5月〜2026年9月に74社を支援し、継続率は3,200店舗で…（2026-06-23〜2026-09-30）"
    toks = SC.fact_tokens(claim)
    check("年（2023・2026）は目印に入らない", [t for t in toks if t in ("2023", "2026")], [])
    check("年でない数字は残す", "3,200" in toks, True)
    check("年の形でも単位が続けば件数として残す", "2034" in SC.fact_tokens("2034件の口コミ"), True)
    check("単独の年も目印にしない", SC.fact_tokens("2020に創業"), [])
    body_bad = "**AIO対策は…です。** 2026年10月時点の情報です。"
    check("鮮度の表記しか無い本文は、どの事実にも当たらない",
          any(t in body_bad for t in SC.fact_tokens(claim)), False)
    check("事実の数字を使った本文は当たる", any(t in "G-ranで3,200店舗を支援" for t in SC.fact_tokens(claim)), True)


def test_daily_audit_reads_score_check_output():
    import daily_audit as D
    print("\n■ 読みやすさの検査が score_check の実際の出力を読む")
    out = ("PASS | 本文5,000字以上 | 5,376字\n"
           "WARN | ［警告］段落が200字以内（規定150字＋余裕） | 2箇所が超過（最長230字）\n"
           "WARN | ［警告］長文が1割強以内・100字超はゼロ（規定50字） | 70字超9/56文（上限6）・100字超1文\n"
           "WARN | 検索上位の見出しに無い節が2つ以上 | 上位の見出しのデータが無いため確かめていません\n"
           "PASS | ［警告］段落が200字以内（規定150字＋余裕） | 最長189字\n")
    check("WARN の段落・長文を拾い、PASS と別の WARN は拾わない", len(D.readability_lines(out)), 2)
    src = (ROOT / "scripts" / "score_check.py").read_text(encoding="utf-8")
    check("score_check の2項目の見出しに「段落」「長文」がある（名前を変えたら気づく）",
          ("［警告］段落が200字以内" in src, "［警告］長文が1割強以内" in src), (True, True))


def test_daily_audit_marks_checks_that_did_not_run():
    import daily_audit as D
    import cannibal_check as CC
    import hub_client as HC
    import gsc_detail as G
    print("\n■ 日次監査: 動かなかった検査を AUDIT_SKIPPED に残し、「なし」「OK」と言わない")

    def skipped(fn, *a):
        D.SKIPPED.clear()
        todo = []
        _, out = run_quiet(fn, todo, *a)
        got = list(D.SKIPPED)
        D.SKIPPED.clear()
        return got, todo, out

    with patched((HC, "enabled", lambda: False)):
        check("台帳に届かない日は KW供給 を残す", skipped(D.check_supply)[0], ["KW供給"])

    def ext_fail():
        ext_fail.failed = True
        return []
    with patched((CC, "external_dup_check", ext_fail)):
        check("配信先の一覧が取れない日は重複の検査を残す", skipped(D.check_external_dup)[0], ["配信先の既存記事との重複"])

    def serp_part():
        serp_part.failed = True
        return []
    with patched((CC, "serp_overlap", serp_part)):
        check("一部のサイトの GSC が取れない日は食い合いを残す", skipped(D.check_serp_overlap)[0], ["食い合い（一部のサイト）"])

    with patched((D.subprocess, "run", lambda *a, **k: _Done(1, "", "Traceback\nValueError: x"))):
        got, todo, out = skipped(D.check_blocked)
    check("build.py が落ちた日は「BLOCKEDなし」と言わず品質ゲートを残す",
          (got, "BLOCKEDなし" in out, todo), (["品質ゲート"], False, []))

    with patched((D.subprocess, "run", lambda *a, **k: _Done(1, "本番のsitemapを取得できません（timeout）\nDEPLOY_OK=no"))):
        got, todo, _ = skipped(D.check_deploy)
    check("本番の sitemap が取れない日は「本番が古い」と書かず、確かめられなかったと残す", (got, todo), (["本番への反映"], []))
    with patched((D.subprocess, "run", lambda *a, **k: _Done(1, "", "SystemExit: site/sitemap.xml がありません"))):
        check("deploy_check が印を出さずに落ちた日も残す", skipped(D.check_deploy)[0], ["本番への反映"])
    with patched((D.subprocess, "run", lambda *a, **k: _Done(1, "  未デプロイ 3件:\nDEPLOY_OK=no（本番が手元より古い状態です）"))):
        got, todo, _ = skipped(D.check_deploy)
    check("本当に古いときは従来どおり TODO", (got, len(todo)), ([], 1))

    def boom(*a, **k):
        raise RuntimeError("403")
    with patched((G, "client", lambda: object()), (G, "q", boom)):
        got, todo, out = skipped(D.check_unseen)
    check("全サイトの GSC が取れない日に「すべて検索に出ています」と言わない",
          (got, "すべて検索に出ています" in out, todo), (["検索に出ていないページ（一部のサイト）"], False, []))


def test_unseen_uses_the_sites_url_shape():
    import daily_audit as D
    print("\n■ 表示ゼロの判定は社の URL の形（url_prefix・WordPress）で照らす")
    journal = {"domain": "zz.example", "url_prefix": "/journal"}
    check("url_prefix の社の記事を「出ている」と読む",
          D.page_seen(journal, "abc", "blog", {"https://zz.example/journal/abc"}), True)
    check("/{カテゴリ}/ の社は従来どおり", D.page_seen({"domain": "zz.example"}, "abc", "aio", {"https://zz.example/aio/abc"}), True)
    check("末尾スラッシュ無しの社（trailing_slash: false）",
          D.page_seen({"domain": "zz.example", "trailing_slash": False}, "abc", "aio", {"https://zz.example/aio/abc"}), True)
    check("WordPress はパスの最後が slug なら出ている（先方へ問い合わせない）",
          D.page_seen({"domain": "zz.example", "type": "wordpress"}, "abc", "aio", {"https://zz.example/2026/10/abc"}), True)
    check("出ていない記事は出ていない", D.page_seen(journal, "abc", "blog", {"https://zz.example/journal/xyz"}), False)


def test_pace_keeps_the_previous_judgement_when_a_site_fails():
    import client_private as CP
    import pace as P
    print("\n■ 量産の兆候: 測れなかった社の前の判定（0本）を残し、PACE_OK=unknown と要対応で知らせる")
    today = date.today().isoformat()
    prev = {"ai-lab": {"quota": 0, "date": today, "signals": ["x"]}}
    saved = {}

    def load(rel, pub=None):
        return dict(prev) if "pace_state" in rel else {}

    def save(rel, d, owner, dump=None, pub=None):
        saved.update(d)

    def measure(sid, cfg, own, end, use_inspect=True):
        if sid == "ai-lab":
            raise RuntimeError("URL検査の枠を超えました")
        return {"quota": 2, "signals": [], "date": today, "how": "URL検査", "new": 1, "judged": 1,
                "not_indexed_rate": 0.1, "duplicates": 0, "pairs": 0, "imp": [10, 10], "states": {}}
    with patched((CP, "load_dict", load), (CP, "save_dict", save), (P, "measure", measure),
                 (sys, "argv", ["pace.py", "--write", "--no-inspect"])):
        _, out = run_quiet(P.main)
    check("測れなかった社は前の判定のまま保存する", (saved.get("ai-lab") or {}).get("quota"), 0)
    check("PACE_OK=unknown を出す（yes と言わない）", ("PACE_OK=unknown" in out, "PACE_OK=yes" in out), (True, False))
    import findings as F
    pat = next(p for _, s, p in F.CHECKS if s == "pace.py")
    check("findings が拾う「要対応:」の行がある", any(pat.search(ln) for ln in out.splitlines() if "測れません" in ln), True)


def test_findings_sees_worse_numbers_and_crashes():
    import findings as F
    print("\n■ findings: 数字が悪いほうへ動いたら要対応・印の後で落ちた回は問題なしにしない")
    w = lambda a, b: F.worse_numbers(F.line_numbers([a], marks=[]), [b])
    check("1日1本→0本は悪化", bool(w("要対応: zz — 1日1本（新しい記事3本）", "要対応: zz — 1日0本（新しい記事3本）")), True)
    check("1日0本→2本は悪化ではない", w("要対応: zz — 1日0本", "要対応: zz — 1日2本"), "")
    check("件数の入れ替わり（5件,2件→1件,6件）は悪化", bool(w("A 5件・B 2件", "A 1件・B 6件")), True)
    check("割合が5ポイント以上動いたら変化", bool(w("未登録28%", "未登録51%")), True)
    check("割合の小さな揺れは変化にしない", w("未登録28%", "未登録30%"), "")
    check("件数が減っただけなら悪化ではない", w("A 5件", "A 3件"), "")
    seen = {}
    rows = [("量産の兆候と本数（Google の大量生成の定義）", "要対応", ["要対応: zz — 1日1本（新しい記事3本）"])]
    _, s1, _, _ = F.compose(rows, [], seen, "2026-10-12")
    rows2 = [(rows[0][0], "要対応", ["要対応: zz — 1日0本（新しい記事3本）"])]
    body, _, n, _ = F.compose(rows2, [], s1, "2026-10-19")
    check("2週目でも本数が減れば要対応のまま", (n, any("1日の本数が減りました" in b for b in body)), (1, True))
    check("1日の本数は件数の合計に数えない", F.counted(["1日2本（新しい記事3本）"]), 3)

    pat = next(p for _, s, p in F.CHECKS if s.startswith("history_checks_a"))
    check("印 yes の後で落ちた回は「動かせず」", F.judge("HISTA_OK=yes\nTraceback (most recent call last):", 1), "動かせず")
    check("印が無く1で終わり、明細も無い回は「動かせず」", F.judge("Traceback (most recent call last):\n  File x", 1, pat), "動かせず")
    check("印が無く1で終わっても、明細が出ていれば要対応", F.judge("要対応: 配信が落ちています", 1, pat), "要対応")
    check("印 no は終了コードに関わらず要対応", F.judge("NAP_OK=no", 1), "要対応")
    src = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("子の Python に UTF-8 で書かせる（手元の Windows）", '"PYTHONIOENCODING": "utf-8"' in src, True)
    da = (ROOT / "scripts" / "daily_audit.py").read_text(encoding="utf-8")
    check("daily_audit も同じ", ('"PYTHONIOENCODING": "utf-8"' in da, 'errors="ignore"' in da), (True, False))


def test_seo_audit_is_not_yes_when_a_sitemap_fails():
    import seo_audit as SA
    import sites as S
    print("\n■ サイト監査: sitemap を読めないサイトがあれば yes と出さない")
    ids = [s for s, c in S.load_all().items() if c.get("domain")]
    bad_sid = ids[0]

    bad_dom = S.load_all()[bad_sid]["domain"]

    def live(dom, limit, cfg):
        if dom == bad_dom:
            raise RuntimeError("sitemap を読めません（503）")
        return [], []
    with patched((SA, "live", live), (SA, "report", lambda name, rows, show=4: 0),
                 (sys, "argv", ["seo_audit.py", "--live", "--all"])):
        rc, out = run_quiet(SA.main)
    check("SEO_AUDIT_OK=unknown（終了コードは0）", ("SEO_AUDIT_OK=unknown" in out, "SEO_AUDIT_OK=yes" in out, rc), (True, False, 0))
    import findings as F
    check("findings は「動かせず」と読む", F.judge(out, rc), "動かせず")


def test_newsletter_is_found_by_the_send_step():
    import outcome_watch as OW
    print("\n■ 結果の見張り: 週刊の配信は始まった時刻ではなく、配信の手順が成功した回で見る")
    runs = [{"databaseId": 1, "event": "schedule", "createdAt": "2026-10-19T02:09:00Z"},
            {"databaseId": 2, "event": "schedule", "createdAt": "2026-10-19T03:36:00Z"}]
    steps = {1: [{"name": OW.SEND_STEP, "conclusion": "skipped"}],
             2: [{"name": OW.SEND_STEP, "conclusion": "success"}]}
    monday = date(2026, 10, 19)
    check("遅れて 03:36Z に始まった週刊の回を数える", OW.newsletter_sent(runs, monday, steps.get), True)
    check("遅れて 02:09Z に始まった毎日の回（配信を飛ばす）を週刊と取り違えない",
          OW.newsletter_sent(runs[:1], monday, steps.get), False)
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "digest.yml").read_text(encoding="utf-8"))
    names = [s.get("name") for j in wf["jobs"].values() for s in j.get("steps") or []]
    check("digest.yml に配信の手順（名前）がある（名前を変えたら気づく）", OW.SEND_STEP in names, True)


def test_kw_plan_and_guard_honor_gsc_failures():
    import kw_guard as KG
    import kw_plan as KP
    print("\n■ GSC が取れない日: 計画は実績の語を積まず、食い合い審査は他サイトの失敗も判定不能にする")

    def down(site_id):
        down.failed = "GSC に接続できません（試験）"
        return []

    def up(site_id):
        up.failed = ""
        return [{"keys": ["語", "https://zz.example/a/"], "position": 3.0, "impressions": 50}]
    with patched((KG, "gsc_rows", down)):
        _, out = run_quiet(KP.gsc_owned, "ai-lab")
        cands = {"a": {"kw": "a", "proven": True}, "b": {"kw": "b"}}
        run_quiet(KP.drop_proven_if_gsc_down, cands)
    check("取れない日は所有語を空にし、理由を残す", (bool(KP.GSC_DOWN), "積みません" in out), (True, True))
    check("取れない日は実績の語（proven）を候補から外す", sorted(cands), ["b"])
    with patched((KG, "gsc_rows", up)):
        owned, _ = run_quiet(KP.gsc_owned, "ai-lab")
    check("取れた日は所有語を返し、前の失敗を持ち越さない", (len(owned), KP.GSC_DOWN), (1, []))

    import sites as S
    group = S.group_of("ai-lab")
    other = next(s for s in group if s != "ai-lab")
    other_dom = S.load_all()[other]["domain"]

    class _Q:
        def __init__(self, site):
            self.site = site

        def execute(self):
            if other_dom in self.site:
                raise PermissionError("403")
            return {"rows": []}

    class _SA:
        def query(self, siteUrl, body):
            return _Q(siteUrl)

    class _SC:
        def searchanalytics(self):
            return _SA()
    disc = types.ModuleType("googleapiclient.discovery")
    disc.build = lambda *a, **k: _SC()
    pkg = types.ModuleType("googleapiclient")
    pkg.discovery = disc
    gc = types.ModuleType("gcreds")
    gc.load = lambda *a, **k: object()
    saved = {k: sys.modules.get(k) for k in ("googleapiclient", "googleapiclient.discovery", "gcreds")}
    sys.modules.update({"googleapiclient": pkg, "googleapiclient.discovery": disc, "gcreds": gc})
    try:
        with patched((KG, "CRED", ROOT / "tests" / "gates_history_h118_check_fixes.py")):
            lv, _ = run_quiet(KG.judge, "門の試験用の存在しない語 zqx", "ai-lab")
            failed = KG.gsc_rows.failed
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    check("同じ組の他サイトが取れない日は判定不能（3）", (lv[0], bool(failed)), (KG.UNKNOWN, True))
    src = (ROOT / "scripts" / "kw_guard.py").read_text(encoding="utf-8")
    check("上限の行数に達したら知らせる", "GSC_ROW_LIMIT" in src and "上限" in src, True)


def test_rival_names_on_word_boundaries():
    import kw_fit as KF
    print("\n■ 他社名: 英字の名前は英字の語の途中で当てない・日本語の名前は部分一致のまま")
    hits = {kw: KF.rival(kw) for kw in (
        "経理代行 dashboard", "invoice 対応 経理代行", "請求書 board", "請求書freee", "freee会計 使い方",
        "マネー フォワード 経費", "money forward 経費", "epca 経理", "pca 会計 乗り換え", "invoice ログイン")}
    check("dashboard の board は他社名ではない", hits["経理代行 dashboard"], None)
    check("インボイス対応の買い手の語（invoice 対応）は他社名ではない", hits["invoice 対応 経理代行"], None)
    check("当たるべき名前は当たる",
          [bool(hits[k]) for k in ("請求書 board", "請求書freee", "freee会計 使い方", "マネー フォワード 経費",
                                   "money forward 経費", "pca 会計 乗り換え", "invoice ログイン")], [True] * 7)
    check("英字の語の途中の pca は当てない", hits["epca 経理"], None)
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("kw_plan も同じ判定を使う（部分一致を残さない）",
          ("kw_fit.rival(low, RIVALS)" in src, "any(t in low for t in RIVALS)" in src), (True, False))


def test_stock_phrases_catch_variants():
    import originality as O
    print("\n■ 決まり文句: ひらがなの「なか」・「ある歯科では」も拾い、所在の「ある」は拾わない")
    bad = ["私たちが相談を受けるなかで、よく出る誤解です。",
           "ある歯科では、予約が増えました。",
           "とある店舗では売上が伸びました。",
           "例えばある整骨院では、口コミが増えました。",
           "弊社が支援するなかでも同じ声がありました。"]
    good = ["駅前にある医院では夜間診療をしています。",
            "対象である会社では届出が必要です。",
            "書いてある店舗では使えません。",
            "歯科医院では、予約の導線を整えます。",
            "あるいは会社で規程を作ります。"]
    old = O.load_experiences
    try:
        O.load_experiences = lambda site=None: []
        check("悪い例をすべて拾う", [bool(O.stock_phrases(s)) for s in bad], [True] * len(bad))
        check("良い例を拾わない", [bool(O.stock_phrases(s)) for s in good], [False] * len(good))
        O.load_experiences = lambda site=None: [{"key": "2026年9月の大阪の歯科医院の相談", "text": "x"}]
        check("登録した体験の目印を含む文は通す",
              O.stock_phrases("ある歯科では、2026年9月の大阪の歯科医院の相談で導線が無かった。"), [])
    finally:
        O.load_experiences = old
