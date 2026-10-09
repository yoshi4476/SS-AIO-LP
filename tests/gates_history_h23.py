# -*- coding: utf-8 -*-
"""公開1〜4週に15位以内へ入れるかを、語の選び方と公開直後の直しに効かせる門（2026-10-05）。

3サイトの分析: 記事は公開1〜3週で表示の山、6週で山の約1/4に落ちる。6週以降も残った記事は公開1〜4週に
「ある語で15位以内（3回以上表示）」に入っていた（入った11本中5〜7本が残る／入らなかった28本中3〜5本）。
山の週の平均順位が20位より下の広い語（「aio対策」「士業 seo」）は消え、残った記事の6週目以降の表示の
73%は1〜4週から出ていた細い語だった。開く理由の強さ（kw_intent）は残るかどうかと差が無かった。
固定すること: 語の点（kw_reach）が広い語を下げ細い語を上げる／買い手の語を先に置く決まりを崩さない／
next_kw が届く語を先に拾う。Search Console・台帳・AIには触れない（手元で作った行だけ）。
"""
from test_gates import check, ROOT


def test_kw_reach_prefers_narrow_words_without_breaking_buyer_first():
    import kw_plan as KP
    import kw_reach as R
    print("\n■ kw_reach: 15位以内に届きそうな細い語を上げ、広い語を下げる")
    check("1語の広い語は下の段（aio対策）", R.band(R.reach("aio対策")), -1)
    check("業種×手法の2語は並（士業 seo・工務店 seo）", (R.band(R.reach("士業 seo")), R.band(R.reach("工務店 seo"))), (0, 0))
    check("条件つきの3語は上の段（ai導入 中小企業 費用・経理 代行 個人事業）",
          (R.band(R.reach("ai導入 中小企業 費用")), R.band(R.reach("経理 代行 個人事業"))), (1, 1))
    check("空白の無い自然文も語に割る（請求書の書き方）", R.tokens("請求書の書き方"), ["請求書", "書き方"])
    check("条件の語で割っただけの複合語は加点を重ねない（中小企業補助金）", R.band(R.reach("中小企業補助金")), 0)
    kw = "工務店 meo 費用"
    check("検索数が大きく難易度が高いほど下げる", R.reach(kw, vol=8000, kd=60) < R.reach(kw, vol=100, kd=10) < R.reach(kw) + 0.01, True)
    held = ["工務店 meo 上がらない"]
    check("自サイトが15位以内を持つ近い語（語を2つ共有）がある主題は上げる", R.reach(kw, held=held) > R.reach(kw), True)
    check("同じ語そのものは近い語に数えない（食い合いの検査の受け持ち）", R.near(kw, [kw]), False)
    check("1語しか共有しなければ近い語にしない", R.near("工務店 seo 費用", ["工務店 meo 上がらない"]), False)
    rows = {"2026-10-01": [], "2026-10-05": [{"kw": "a b", "pos": 9.0, "imp": 3}, {"kw": "c d", "pos": 15.1, "imp": 50},
                                              {"kw": "e f", "pos": 4.0, "imp": 2}]}
    import json
    import tempfile
    from pathlib import Path
    old = R.RANKS
    with tempfile.TemporaryDirectory() as td:
        try:
            R.RANKS = Path(td)
            (Path(td) / "x.json").write_text(json.dumps(rows), encoding="utf-8")
            check("15位以内・3回以上表示の語だけ、最新の日の行から拾う", R.held_queries("x"), ["a b"])
            check("記録が無ければ空（Search Console を呼ばない）", R.held_queries("none"), [])
        finally:
            R.RANKS = old
    span = (R.HI - R.LO) * KP.REACH_WEIGHT
    check("振れ幅が買い手の語の加点（+3.0）より小さい", span < 3.0, True)
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("買い手の語の加点は +3.0 のまま", "s += 3.0" in src, True)
    a = {"kw": "経理代行 費用 相場", "vol": 210, "subject": "s"}
    b = {"kw": "請求書 封筒 書き方", "vol": 5400, "subject": "s"}
    check("近い語の加点があっても、外注を考える語が自分でやる大量検索の語より先（本章-1の例）",
          KP.score(a, (), ["請求書 書き方 封筒 宛名"]) > KP.score(b, (), ["請求書 書き方 封筒 宛名"]), True)
    check("choose は届く点を採用した語に残す（計画の表で確かめられる）", 'c["reach"] = kw_reach.reach(' in src, True)


def test_next_kw_takes_reachable_words_first():
    import hub_client as HC
    import kw_reach as R
    print("\n■ next_kw: 同じ規則の中では15位に届く語を先に、台帳の先頭が広い語なら届く語へ替える")
    saved = {k: getattr(HC, k) for k in ("enabled", "_get", "all_kw", "_ai_targets", "_main_offer_pattern", "_drop_pattern")}
    saved_held = R.held_queries
    led = []
    row = lambda k: {"site": "s", "status": "未着手", "keyword": k, "priority": "B"}
    try:
        HC.enabled = lambda: True
        HC._get = lambda p: {"ok": True, "keyword": "aio対策", "category": "aio", "aim": ""}
        HC.all_kw = lambda strict=False: led
        HC._ai_targets = lambda site: set()
        HC._main_offer_pattern = lambda site: r"aio"
        HC._drop_pattern = lambda site: ""
        R.held_queries = lambda site: []
        led[:] = [row(k) for k in ("aio対策", "aio費用", "aio 費用 相場 中小企業")]
        got = HC.next_kw("s")
        check("強い語の中でも、台帳で後ろにある届く語を先に拾う",
              (got["keyword"], got.get("picked_by")), ("aio 費用 相場 中小企業", "強い語×主力"))
        led[:] = [row(k) for k in ("aio対策", "aio施策", "aio 導入 事例 中小企業")]
        got = HC.next_kw("s")
        check("台帳の先頭が広い語（aio対策）なら、主力の中で届く語へ替える",
              (got["keyword"], got.get("picked_by")), ("aio 導入 事例 中小企業", "15位に届く細い語"))
        HC._get = lambda p: {"ok": True, "keyword": "aio 導入 事例 中小企業", "category": "aio", "aim": ""}
        got = HC.next_kw("s")
        check("先頭が並以上の主力の語なら台帳のまま", (got["keyword"], got.get("picked_by")), ("aio 導入 事例 中小企業", None))
    finally:
        for k, v in saved.items():
            setattr(HC, k, v)
        R.held_queries = saved_held


def test_early_rewrite_targets_narrow_words_in_weeks_2_to_5():
    import datetime as dt
    import inspect
    import re
    import tempfile
    from pathlib import Path
    import auto_rewrite as A
    import sites as S
    print("\n■ auto_rewrite --kind early: 公開14〜35日の記事に、15位以内に出ている細い語を題・H2・FAQへ入れる")
    check("細い語: 狙う語の語を含み、無い語を足した語だけ",
          (A.narrower_terms("工務店 meo 上がらない", "工務店 meo対策"), A.narrower_terms("aio 事例", "aio 導入事例"),
           A.narrower_terms("三点照合 自動化", "請求書 照合 自動化"), A.narrower_terms("税理士 顧問", "工務店 meo対策")),
          (["上がらない"], [], ["三点照合"], []))
    # 本物の原稿を1本選び、公開から20日目として、その記事のURLに出る語の行を手で作る
    art = None
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        sc = re.search(r"^score:\s*(\d+)", t, re.M)
        kw = re.search(r"^keyword:\s*(.+)$", t, re.M)
        d = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", t, re.M)
        cat = re.search(r"^category:\s*(\S+)", t, re.M)
        if sc and int(sc.group(1)) >= 90 and kw and d and cat and S.find_category_owner(cat.group(1)) \
                and len(kw.group(1).split()) >= 2 and not re.search(r"ぞうさん", t):
            art = (p.stem, kw.group(1).strip(), dt.date.fromisoformat(d.group(1)), S.find_category_owner(cat.group(1)))
            break
    slug, kw, d0, sid = art
    url = f"https://x.example/c/{slug}/"
    q = kw + " ぞうさん"
    rows = [{"kw": q, "url": url, "pos": 9.0, "imp": 6}, {"kw": kw, "url": url, "pos": 7.0, "imp": 40}]
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "log.jsonl"
        log.write_text("", encoding="utf-8")
        got = A.early_items(5, today=d0 + dt.timedelta(days=20), rows_of=lambda s: rows if s == sid else [], log=log)
        check("公開20日・細い語で9位・6回 → 対象（狙う語そのものは対象にしない）",
              [(x["slug"], x["query"], x["terms"]) for x in got], [(slug, q, ["ぞうさん"])])
        check("公開10日・40日は対象外", [A.early_items(5, today=d0 + dt.timedelta(days=n), log=log,
                                                  rows_of=lambda s: rows if s == sid else []) for n in (10, 40)], [[], []])
        far = [dict(rows[0], pos=16.0)]
        check("16位は対象外（15位以内の線）", A.early_items(5, today=d0 + dt.timedelta(days=20), log=log,
                                                    rows_of=lambda s: far if s == sid else []), [])
        thin = [dict(rows[0], imp=2)]
        check("表示2回は対象外（3回以上の線）", A.early_items(5, today=d0 + dt.timedelta(days=20), log=log,
                                                     rows_of=lambda s: thin if s == sid else []), [])
        other = rows + [{"kw": q, "url": "https://x.example/c/other-page/", "pos": 3.0, "imp": 9}]
        check("同じ語で別の自社ページが上にいれば入れない（食い合う）",
              A.early_items(5, today=d0 + dt.timedelta(days=20), log=log, rows_of=lambda s: other if s == sid else []), [])
        log.write_text('{"kind": "early", "slug": "%s", "ok": true}\n' % slug, encoding="utf-8")
        check("一度直した記事は二度目を直さない（1記事1回）",
              A.early_items(5, today=d0 + dt.timedelta(days=20), log=log, rows_of=lambda s: rows if s == sid else []), [])
    b = "---\nfaq:\n  - q: 工務店のMEOとは？\n---\n## 始め方\n本文\n"
    good = ("---\nfaq:\n  - q: 工務店のMEOとは？\n  - q: 工務店のMEOが上がらないときは？\n---\n"
            "## 始め方\n本文\n## 順位が上がらないときは？\n本文\n")
    t0 = "工務店のMEO対策｜始め方と5つのコツ"
    it = {"terms": ["上がらない"]}
    check("題の小さな言い換え・H2を1本・FAQ を1問足す直しは通す",
          A.early_guard(b, good, t0, "工務店のMEO対策｜上がらない時の5つのコツ", it), "")
    check("題を別物に書き換えたら止める", A.early_guard(b, good, t0, "上がらない地図順位を直す方法とは", it).startswith("題を変えすぎ"), True)
    check("FAQ に細い語の問いが無ければ止める",
          A.early_guard(b, good.replace("  - q: 工務店のMEOが上がらないときは？\n", ""), t0, t0, it).startswith("FAQ に細い語"), True)
    two = good + "## 別の節\n本文\n"
    check("H2を2本以上足したら止める", A.early_guard(b, two, t0, t0, it).startswith("H2の本数"), True)
    check("出典のURLを増やしたら止める",
          A.early_guard(b, good + '<a href="https://example.com/x">x</a>\n', t0, t0, it).startswith("出典のURL"), True)
    check("selftest の誤検出の点検に early が入っている", "（early）" in inspect.getsource(A.false_alarms), True)
    rsrc = inspect.getsource(A.run_one)
    check("run_one が early_guard を通し、直す前の原稿を残す（28日後に戻せる）",
          # 残すかは keep_original が決める（2026-10-09 に serp・浮いた枠の直しも残すようにした）
          ("early_guard(" in rsrc, "keep_original(kind)" in rsrc and A.keep_original("early")), (True, True))
    check("--kind early で early_items を使う（台帳の種類は early・effect_ab が種類別に判定）",
          'elif a.kind == "early":' in inspect.getsource(A.main), True)
    check("見出しに細い語が入ったかを共通の検算（terms）でも見る", "\"terms\": terms" in inspect.getsource(A.early_items), True)


def test_top_hero_video_does_not_become_late_lcp():
    import re
    print("\n■ AI集客ラボのトップ: ヒーロー動画は最初の操作の後に読み、モバイルは背景の大きな写真を敷かない")
    for f in ("index.html", "lp/index.html"):
        h = (ROOT / "site" / f).read_text(encoding="utf-8")
        js = "".join(re.findall(r"<script>(.*?)</script>", h, re.S))
        hero = [s for s in re.findall(r"<script>(.*?)</script>", h, re.S) if "video.lx-hero-video" in s]
        check(f"{f}: 動画を差し込む処理は1つ", len(hero), 1)
        s = hero[0] if hero else ""
        check(f"{f}: 読み込みの後に時間で流さない（後から LCP に数えられる）",
              bool(re.search(r'addEventListener\("load"', s)) or "setTimeout" in s, False)
        check(f"{f}: 最初の操作（タップ・キー・スクロール）で読む", all(e in s for e in ('"pointerdown"', '"keydown"', '"scroll"')), True)
        check(f"{f}: データ節約・2G では読まない", "saveData" in s and "2g" in s, True)
        check(f"{f}: 動きを減らす設定では読まない", "prefers-reduced-motion" in s, True)
        check(f"{f}: 計測タグの遅延読み込みはそのまま", "googletagmanager.com/gtag/js" in js, True)
    h = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    pre = re.search(r'<link rel="preload" as="image" href="/images/home/mv\.webp"[^>]*>', h)
    check("トップ: 背景写真の先読みは広い画面だけ", bool(pre and 'media="(min-width: 921px)"' in pre.group(0)), True)
    mob = re.search(r"@media \(max-width:920px\)\{\.home \.lx-hero\{background:([^}]*)\}\}", h)
    check("トップ: 狭い画面の背景に大きな写真（--mv-photo）を敷かない", bool(mob) and "mv-photo" not in mob.group(1), True)
    still = re.search(r'<img[^>]*lx-hero-still[^>]*>', h)
    check("トップ: 最初の描画は優先の静止画（fetchpriority=high・遅延読み込みしない）",
          bool(still and 'fetchpriority="high"' in still.group(0) and 'loading="lazy"' not in still.group(0)), True)


def test_glossary_sends_readers_to_the_article_that_targets_the_term():
    import re
    import glossary as GL
    import sites as S
    print("\n■ 用語集: 各語の定義の直下に、その語を狙う記事への「詳しくは」を必ず置く（301 の転送先でも見える）")
    pubs = [{"slug": "def-src", "keyword": "店舗 集客 方法", "title": "定義を書いた記事", "category": "aio", "date": "2026-09-01"},
            {"slug": "aim", "keyword": "llmo 店舗集客", "title": "LLMOの店舗集客", "category": "aio", "date": "2026-09-02"}]
    rec = {"term": "LLMO店舗集客", "id": "x1", "definition": "d" * 30, "slug": "def-src", "category": "aio",
           "title": "定義を書いた記事", "date": "2026-09-01"}
    check("狙う語が用語と一致する記事へ向ける（定義を書いた記事ではなく）", GL.target_of(rec, pubs)["slug"], "aim")
    check("括弧の言い換えを外しても照合する（Googleビジネスプロフィール（GBP））",
          GL.target_of(dict(rec, term="Googleビジネスプロフィール（GBP）"),
                       [dict(pubs[1], keyword="googleビジネスプロフィール")])["slug"], "aim")
    check("狙う記事が無ければ定義の出典の記事", GL.target_of(dict(rec, term="ぜんぜん別の語"), pubs)["slug"], "def-src")
    r = dict(rec, target="aim", target_title="LLMOの店舗集客", target_category="aio")
    sec = re.search(r'<section class="gl-term" id="x1">.*?</section>', GL.index_html([r]), re.S).group(0)
    check("節の中で、定義の直後に「詳しくは」（狙う記事へ）・その後に定義の出典",
          (sec.index("definition-box") < sec.index('class="gl-more">詳しくは <a href="/aio/aim/">')
           < sec.index('定義の出典の記事: <a href="/aio/def-src/">')), True)
    same = dict(rec, target="def-src", target_title="定義を書いた記事", target_category="aio")
    s2 = GL.index_html([same])
    check("出典と狙う記事が同じならリンクは1本（同じURLを2回並べない）", s2.count('href="/aio/def-src/"'), 1)
    check("用語集に noindex・正規URLの変更を入れない", ("noindex" in s2, "canonical" in s2), (False, False))
    sid = S.primary()
    terms = GL.collect(sid)
    html = GL.index_html(terms)
    secs = re.findall(r'<section class="gl-term" id="([0-9a-f]+)">(.*?)</section>', html, re.S)
    check("実データ: すべての語の節に「詳しくは」がある", [i for i, s in secs if 'class="gl-more">詳しくは <a href="/' not in s], [])
    slugs = {p.stem for p in (ROOT / "articles").glob("*.md")}
    check("実データ: 詳しくはの行き先は公開記事（存在する原稿）", [t["term"] for t in terms if t["target"] not in slugs], [])
    ids = {i for i, _ in secs}
    check("旧URL /glossary/<id>/ の転送先（#id）が用語集の節にある",
          [ln for ln in GL.redirects(terms) if ln.split()[1].split("#")[1] not in ids], [])
