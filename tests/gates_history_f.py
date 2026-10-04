# -*- coding: utf-8 -*-
"""学びの台帳（data/lessons.jsonl）のうち、機械で守れるものを門にしたもの。

台帳の「判断が要る」学びは、記事を書くたびにプロンプトへ渡される。機械で止められるものまで
そこに置くと、量が増えて肝心の学びが読まれなくなる（CLAUDE.md 0.2）。ここで門にした学びは、
台帳の gate にこのファイルの関数名を書き、プロンプトから外す。

どの門も「壊れた例を拾うこと」「正しい例を拾わないこと」を先に確かめてから、いまのファイルに当てる
（CLAUDE.md 0.1: 0件と言う前に、見つかるはずの例で検出器を試す）。
"""
import json
import re
import sys
import types

import yaml

from test_gates import check, ROOT

ARTICLES = ROOT / "articles"


def warn(label, items):
    if items:
        items = sorted(map(str, items))
        print(f"  WARN  {label}: {len(items)}件  " + " / ".join(items[:8]))


_FM = {}


def articles():
    """(slug, frontmatter, body)。フロントマターの壊れた原稿は飛ばす（別の門が止める）

    5つの門が約400本のフロントマターを YAML で読み直していた（約20秒）。
    フロントマターの文字列が同じなら前の読みを使い、渡すのは写し（門どうしで書き換えが漏れない）"""
    import copy
    out = []
    for p in sorted(ARTICLES.glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        if m.group(1) not in _FM:
            try:
                _FM[m.group(1)] = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                _FM[m.group(1)] = None
        fm = _FM[m.group(1)]
        if isinstance(fm, dict):
            out.append((p.stem, copy.deepcopy(fm), m.group(2)))
    return out


def _draw():
    """日本語フォントで測る下地。フォントが無い環境では None（文字幅を測れない）"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_diagram as MD
    from PIL import Image, ImageDraw
    try:
        MD.font(16)
    except SystemExit:
        return None
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


# ── L0014: FAQ はフロントマターと本文で一字一句同じ（2026-08 の修正ループで片側だけ直した）──
def _flat(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace("**", "")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", "", s)


def faq_mismatch(faq, body):
    """本文に同じ文が無い FAQ の問い・答え"""
    flat = _flat(body)
    out = []
    for f in faq or []:
        if not isinstance(f, dict):
            continue
        for k in ("q", "a"):
            if f.get(k) and _flat(f[k]) not in flat:
                out.append(f"{k}: {str(f[k])[:24]}")
    return out


def test_hist_lessons_faq_matches_body():
    print("\n■ 学びL0014: FAQ の問いと答えが、フロントマター（構造化データ）と本文で同じ")
    body = '<details><summary>費用は？</summary><p class="faq-a">月10万円からです。</p></details>'
    check("検出器: 本文だけ直した答えを拾う",
          faq_mismatch([{"q": "費用は？", "a": "月20万円からです。"}], body), ["a: 月20万円からです。"])
    check("検出器: 空白・タグ・強調の違いは同じとみなす",
          faq_mismatch([{"q": "費用は？", "a": "**月10万円**から です。"}], body), [])
    bad = [f"{s}: {x}" for s, fm, b in articles() for x in faq_mismatch(fm.get("faq"), b)]
    check("全記事の FAQ がフロントマターと本文で一致", bad, [])


# ── L0022 / L0028: keyword: が無いと台帳が「公開済み」にならず、同じ語を書き直す ─────────
def missing_keyword(fm):
    return not str(fm.get("keyword") or "").strip()


# この日より前に書かれた記事（取り込んだ旧形式の記事を含む）には eyecatch が無いものがある。
# 画像の実体はあるため配信先の一覧で欠けるだけ。これより後に書く記事で増やさないことをここで止める
EYECATCH_FROM = "2026-09-02"


def test_hist_lessons_frontmatter_keyword_and_eyecatch():
    print("\n■ 学びL0022/L0028/L0030: 全記事に keyword: と eyecatch: がある")
    check("検出器: keyword が空の記事を拾う", (missing_keyword({"keyword": " "}), missing_keyword({})), (True, True))
    check("検出器: keyword がある記事は通す", missing_keyword({"keyword": "経理代行 費用"}), False)
    arts = articles()
    check("全記事に keyword:（無いと kw_guard の重複判定と台帳の公開記録が効かない）",
          [s for s, fm, _ in arts if missing_keyword(fm)], [])
    no_eye = {s: str(fm.get("date") or "") for s, fm, _ in arts if not fm.get("eyecatch")}
    check(f"{EYECATCH_FROM} 以降の記事に eyecatch: がある（無いと配信先の一覧に画像が出ない）",
          sorted(s for s, d in no_eye.items() if d >= EYECATCH_FROM), [])
    warn("eyecatch: が無い古い記事（直すときに eyecatch を足す）", [s for s, d in no_eye.items() if d < EYECATCH_FROM])


# ── L0058: list型の図解に「|」を書くと、そのまま画像に描かれた（2026-09-23）──────────
class _Rec:
    def __init__(self, d):
        self.d, self.texts = d, []

    def text(self, xy, s, *a, **k):
        self.texts.append(s)
        return self.d.text(xy, s, *a, **k)

    def __getattr__(self, n):
        return getattr(self.d, n)


def drawn_pipes(texts):
    return [t for t in texts if "|" in str(t)]


def test_hist_lessons_list_diagram_draws_no_pipe():
    print("\n■ 学びL0058: list型の図解に「|」をそのまま描かない")
    check("検出器: 「|」入りの文字を拾う", drawn_pipes(["ラベル|説明"]), ["ラベル|説明"])
    check("検出器: 「：」区切りは通す", drawn_pipes(["ラベル：説明"]), [])
    if _draw() is None:
        print("  WARN  日本語フォントが無いため、list型の描画は確かめられません")
        return
    import make_diagram as MD
    rec = {}
    real_canvas, real_save = MD.canvas, MD.save_png

    def canvas(h, title):
        img, d = real_canvas(h, title)
        rec["d"] = _Rec(d)
        return img, rec["d"]
    try:
        MD.canvas, MD.save_png = canvas, (lambda *a, **k: None)
        MD.draw_list("zz-gate-test", "x", "題", ["届出|開業から1か月", "帳簿|毎日つける", "申告|3月15日まで"])
    finally:
        MD.canvas, MD.save_png = real_canvas, real_save
    check("list型は「ラベル|説明」を「：」で描く", drawn_pipes(rec["d"].texts), [])


# ── L0026 / L0031: flow型の文字が箱からあふれ、隣の箱と重なった（2026-08-07 / 08-21）──────
def overflow(d, lines, f, width):
    return [ln for ln in lines if d.textlength(ln, font=f) > width]


def test_hist_lessons_flow_text_fits_box():
    print("\n■ 学びL0026/L0031: flow型の文字が箱に収まる（縮小の下限で諦めず折り返す）")
    d = _draw()
    if d is None:
        print("  WARN  日本語フォントが無いため、図解の文字幅は確かめられません")
        return
    import make_diagram as MD
    long = "IT導入支援事業者と契約内容を相談する"
    check("検出器: 最小の文字でも収まらない行を拾う", bool(overflow(d, [long], MD.font(16), 160)), True)
    lines, f = MD.flow_lines(d, long, 160)
    check("flow_lines は折り返して箱に収める", (overflow(d, lines, f, 160), "".join(lines)), ([], long))
    check("短い項目は分けない", MD.flow_lines(d, "申請|書類をそろえる", 160)[0], ["申請", "書類をそろえる"])
    bad = []
    for s, fm, _ in articles():
        for dg in fm.get("diagrams") or []:
            if not isinstance(dg, dict) or dg.get("type", "flow") != "flow":
                continue
            items = [str(x) for x in dg.get("items") or []][:5]
            if not 2 <= len(items) <= 5:
                continue
            w = (MD.W - 120 - 34 * (len(items) - 1)) // len(items) - 28
            for it in items:
                ls, ff = MD.flow_lines(d, it, w)
                if overflow(d, ls, ff, w) or len(ls) > 5:
                    bad.append(f"{s}: {it}")
    check("全記事の flow 図解の項目が箱に収まる（5行以内）", bad, [])


# ── L0061: アイキャッチの題が「AI / Overview」と英語の途中で折り返された（2026-09-23）──────
def split_words(lines):
    return [f"{a}/{b}" for a, b in zip(lines, lines[1:])
            if re.search(r"[A-Za-z0-9.,%]$", a) and re.match(r"[A-Za-z0-9.,%]", b)]


def test_hist_lessons_eyecatch_keeps_english_words():
    print("\n■ 学びL0061: アイキャッチの題を英数字の語の途中で折り返さない")
    check("検出器: 英語の途中の改行を拾う", split_words(["AIOとは？AI", "Overviewの仕組み"]), ["AIOとは？AI/Overviewの仕組み"])
    check("検出器: 語の切れ目の改行は通す", split_words(["AIOとは？", "AI Overviewの仕組み"]), [])
    d = _draw()
    if d is None:
        print("  WARN  日本語フォントが無いため、アイキャッチの折り返しは確かめられません")
        return
    import make_eyecatch as ME
    check("safe_cut: 「AI Overview」の中では割らない",
          ME.safe_cut("AIOとは？AI Overviewの仕組み", 8) in (6, 17), True)
    bad = []
    for s, fm, _ in articles():
        lines, f = ME.wrap_title(d, str(fm.get("title") or ""), ME.W - 160)
        bad += [f"{s}: {x}" for x in split_words(lines)]
    check("全記事のアイキャッチの題が語の途中で割れない", bad, [])


# ── L0071: 補助金サイトの URL を host=ai.7senses.co.jp で送り HTTP 422（2026-09-26）──────
def wrong_hosts(calls):
    """notify(urls, key, site_url) の呼び出しのうち、URL のドメインと host が違うもの"""
    out = []
    for urls, site_url in calls:
        host = site_url.split("//", 1)[-1].strip("/")
        out += [u for u in urls if u.split("//", 1)[-1].split("/", 1)[0] != host]
    return out


def test_hist_lessons_indexnow_host_follows_url():
    print("\n■ 学びL0071: IndexNow の host は URL のドメインから決める")
    lp, ai = "https://lp.7senses.co.jp/blog/x/", "https://ai.7senses.co.jp/aio/y/"
    check("検出器: 別ドメインの host で送る呼び出しを拾う", wrong_hosts([([lp], "https://ai.7senses.co.jp")]), [lp])
    check("検出器: 同じドメインなら通す", wrong_hosts([([ai], "https://ai.7senses.co.jp")]), [])
    sys.path.insert(0, str(ROOT / "scripts"))
    import notify_indexnow as NI
    calls = []
    saved = NI.notify, NI.load_env, NI.find_key
    try:
        NI.notify = lambda urls, key, site_url: (calls.append((list(urls), site_url)), 200)[1]
        NI.load_env = lambda: {"SITE_URL": "https://ai.7senses.co.jp"}
        NI.find_key = lambda env: "0" * 32
        NI.main([lp, ai])
    finally:
        NI.notify, NI.load_env, NI.find_key = saved
    check("URL を渡したときの通知がドメインごとに分かれる", (wrong_hosts(calls), len(calls)), ([], 2))


# ── L0108: 台帳を読めないまま補充し、既にある語を積み直した（2026-08-04）────────────
def test_hist_lessons_kw_append_needs_readable_ledger():
    print("\n■ 学びL0108: 台帳を読めなかった回は補充しない・入った数を出す")
    sys.path.insert(0, str(ROOT / "scripts"))
    import kw_discover as KD
    fake = types.ModuleType("hub_client")
    fake.enabled = lambda: True
    real = sys.modules.get("hub_client")
    try:
        sys.modules["hub_client"] = fake
        got = (KD.hub_client_enabled_but_unreadable(False), KD.hub_client_enabled_but_unreadable(True))
    finally:
        if real is not None:
            sys.modules["hub_client"] = real
        else:
            sys.modules.pop("hub_client", None)
    check("管制塔が設定済みで読めなかった回を拾い、読めた回は通す", got, (True, False))
    src = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("--append は読めなかった回に止まる",
          bool(re.search(r'"--append" in sys\.argv and hub_client_enabled_but_unreadable\(ledger_ok\)', src)), True)
    check("補充の報告は渡した数ではなく実際に入った数（added）", "r.get('added'" in src, True)


# ── L0045: claude -p の書き換えが権限待ちで止まり、24本連続「変更なし」（2026-09-23）──────
def can_edit(perm_json):
    p = (json.loads(perm_json) or {}).get("permissions") or {}
    return p.get("defaultMode") == "acceptEdits" and any(str(a).startswith("Edit") for a in p.get("allow") or [])


def test_hist_lessons_claude_rewrite_can_edit():
    print("\n■ 学びL0045: auto_rewrite の claude が非対話で実際に書き込める設定で動く")
    check("検出器: 道具を許すだけで書き込みの承認が無い設定を拾う",
          can_edit(json.dumps({"permissions": {"allow": ["Read", "Edit"]}})), False)
    check("検出器: acceptEdits と Edit があれば通す",
          can_edit(json.dumps({"permissions": {"allow": ["Edit(articles/**)"], "defaultMode": "acceptEdits"}})), True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import auto_rewrite as AR
    check("auto_rewrite の権限設定で Edit が承認なしに通る", can_edit(AR.PERM), True)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("claude 呼び出しに --settings PERM と claude_bin() を使う",
          '"--settings", PERM' in src and "exe = claude_bin()" in src, True)


# ── L0116: 出典の種類を .or.jp の末尾で「公的機関」にした（2026-10-02 jidv.org は紹介サイト）──
SAMPLES = {"ohnuki-dental.or.jp": "public", "jidv.org": "public", "mhlw.go.jp": "", "jda.or.jp": ""}


def misclassified(rule):
    """SAMPLES の値は「こう分けたら誤り」。空なら「公的機関に分けないと誤り」"""
    out = []
    for d, wrong in SAMPLES.items():
        got = rule(d)
        if (wrong and got == wrong) or (not wrong and got != "public"):
            out.append(f"{d}={got or '未分類'}")
    return out


def test_hist_lessons_source_class_not_by_suffix():
    print("\n■ 学びL0116: 出典の種類をドメインの末尾（.or.jp/.org）だけで公的機関にしない")
    by_suffix = lambda d: "public" if re.search(r"\.(or\.jp|org|go\.jp)$", d) else ""
    check("検出器: 末尾だけで分ける規則を拾う", misclassified(by_suffix), ["ohnuki-dental.or.jp=public", "jidv.org=public"])
    sys.path.insert(0, str(ROOT / "scripts"))
    import industry_ai_sources as IAS
    check("industry_ai_sources の規則は医院・紹介サイトを公的機関にせず、官公庁・学会は公的機関にする",
          misclassified(IAS.rule_class), [])


# ── L0089: 配信先へ続けて push すると1本おきに落ちた（2026-09-28 補助金47本中17本）────────
def batch_problems(calls, sleeps, fails_once, fails_always, after_abort):
    """publish_changed の動き方の誤り。calls は配信を試みた slug の順"""
    out = []
    for s in fails_once:
        if calls.count(s) != 2:
            out.append(f"{s}: 1回落ちた記事をやり直していない")
    if fails_once and 20 not in sleeps:
        out.append("やり直しの前に20秒待っていない")
    for s in fails_always:
        if calls.count(s) > 2:
            out.append(f"{s}: 3回以上やり直した")
    for s in after_abort:
        if s in calls:
            out.append(f"{s}: 3本続けて落ちた後も配信を続けた")
    return out


def test_hist_lessons_publish_changed_retries_and_continues():
    print("\n■ 学びL0089: 配信は1本ずつ、落ちたら20秒待って1回だけやり直し、3本続けて落ちたら止める")
    check("検出器: やり直さない・止まらない動きを拾う",
          len(batch_problems(["a", "b", "c", "d", "e", "f"], [], ["a"], ["c", "d", "e"], ["f"])), 3)
    check("検出器: 正しい動きは通す",
          batch_problems(["a", "a", "b", "c", "c", "d", "d", "e", "e"], [20, 20, 20, 20], ["a"], ["c", "d", "e"], ["f"]), [])
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish_changed as PC
    plan = {"a": [1, 0], "b": [0], "c": [1, 1], "d": [1, 1], "e": [1, 1], "f": [0]}
    calls, sleeps = [], []

    def run(cmd, **k):
        s = cmd[cmd.index("--slug") + 1]
        calls.append(s)
        seq = plan[s]
        rc = seq.pop(0) if len(seq) > 1 else seq[0]
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="x")
    cfg = {"type": "external-md", "name": "X", "repo": "r"}
    fake_sites = types.SimpleNamespace(load_all=lambda: {"x": cfg}, load=lambda sid: cfg)
    saved = PC.sites_mod, PC.site_articles, PC.subprocess, PC.time, sys.argv
    try:
        PC.sites_mod = fake_sites
        PC.site_articles = lambda sid: list(plan)
        PC.subprocess = types.SimpleNamespace(run=run)
        PC.time = types.SimpleNamespace(sleep=sleeps.append)
        sys.argv = ["publish_changed.py", "--site", "x", "--push"]
        PC.main()
    finally:
        PC.sites_mod, PC.site_articles, PC.subprocess, PC.time, sys.argv = saved
    check("publish_changed の配信の順番・やり直し・打ち切り",
          batch_problems(calls, sleeps, ["a"], ["c", "d", "e"], ["f"]), [])


# ── L0076: CI の浅い clone で --since なしに回し、変更3本のつもりが123本を配信（2026-09）──────
def publish_changed_without_since(text):
    return [ln.strip() for ln in text.splitlines()
            if "publish_changed.py" in ln and not ln.strip().startswith("#") and "--since" not in ln]


def test_hist_lessons_ci_publish_changed_uses_since():
    print("\n■ 学びL0076: ワークフローの publish_changed は必ず --since で差分だけを配信する")
    check("検出器: --since の無い呼び出しを拾う",
          publish_changed_without_since("  python scripts/publish_changed.py --all --push || true"),
          ["python scripts/publish_changed.py --all --push || true"])
    check("検出器: --since つきは通す",
          publish_changed_without_since('python scripts/publish_changed.py --all --since "$BASE_SHA" --push'), [])
    bad = [f"{p.name}: {x}" for p in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
           for x in publish_changed_without_since(p.read_text(encoding="utf-8"))]
    check("ワークフローの publish_changed がすべて --since つき", bad, [])


# ── L0057: 保存した自記事を kw_guard が「完全一致」と判定し、正当な記事を捨てかけた（2026-09-06 / 09-23）──
def _fake_articles(KG, arts, fn):
    real = KG.load_articles
    try:
        KG.load_articles = lambda: [dict({"desc": "", "h2": [], "cat": ""}, **a) for a in arts]
        return fn()
    finally:
        KG.load_articles = real


def test_hist_lessons_kw_guard_hints_self_match():
    print("\n■ 学びL0057: 題名まで同じ完全一致には、自記事を外す読み方を kw_guard がその場で示す")
    sys.path.insert(0, str(ROOT / "scripts"))
    import kw_guard as KG
    arts = [{"slug": "seikyusho-x", "title": "請求書の作り方とは？5つの手順", "kw": "請求書 作り方"}]
    same = _fake_articles(KG, arts, lambda: KG.judge("請求書 作り方", "", title="請求書の作り方とは？5つの手順", use_gsc=False))
    other = _fake_articles(KG, arts, lambda: KG.judge("請求書 作り方", "", title="個人事業主の請求書テンプレート", use_gsc=False))
    hint = lambda res: any("--exclude-slug seikyusho-x" in d for _, _, d in res[1])
    check("題名も同じ完全一致には --exclude-slug の読み直しを示す", (same[0], hint(same)), (2, True))
    check("題名が違う完全一致には示さない（本当の重複は止めたまま）", (other[0], hint(other)), (2, False))


# ── L0109: 統合の検算で kw_guard が消す側の実績で必ず止め、21組すべて見送った（2026-09-28）──────
def test_hist_lessons_merge_guard_excludes_both():
    print("\n■ 学びL0109: 統合の食い合い検査は、残す側と消す側の両方を除いて行う")
    sys.path.insert(0, str(ROOT / "scripts"))
    import kw_guard as KG
    arts = [{"slug": "win", "title": "経理代行の費用相場", "kw": "経理代行 費用"},
            {"slug": "lose", "title": "経理代行の費用と内訳", "kw": "経理代行 費用"}]
    one = _fake_articles(KG, arts, lambda: KG.judge("経理代行 費用", "", use_gsc=False, exclude_slug="win")[0])
    both = _fake_articles(KG, arts, lambda: KG.judge("経理代行 費用", "", use_gsc=False, exclude_slug="win,lose")[0])
    check("検出器: 残す側だけを除くと、消す側との一致で止まる", one, 2)
    check("両方を除けば通る（カンマ区切りの除外が効く）", both, 0)
    src = (ROOT / "scripts" / "auto_merge.py").read_text(encoding="utf-8")
    check("auto_merge は kw_guard に残す側と消す側の両方を渡す",
          bool(re.search(r"""["']--exclude-slug["'],\s*f["']\{s\},\{pair\[["']loser["']\]\}["']""", src)), True)


# ── L0091: AI引用の実測を社名入りの質問で行い、自社が出るのは当然だった（2026-09-23）────────
def test_hist_lessons_cite_queries_skip_brand():
    print("\n■ 学びL0091: AI引用の実測に使う語から指名（社名・サービス名）を除く")
    sys.path.insert(0, str(ROOT / "scripts"))
    import tempfile
    from pathlib import Path
    import ai_cite_check as AC
    import brand_search
    brand_in = lambda qs: [q for q in qs if brand_search.BRAND.search(q)]
    check("検出器: 社名入りの語を拾う", brand_in(["セブンセンシズ 評判", "aio対策 費用"]), ["セブンセンシズ 評判"])
    rows = [{"kw": "セブンセンシズ 評判", "pos": 2, "imp": 300}, {"kw": "aio対策 費用", "pos": 5, "imp": 80},
            {"kw": "AIO対策 費用", "pos": 6, "imp": 40}]
    real = AC.RANKS
    with tempfile.TemporaryDirectory() as d:
        try:
            AC.RANKS = Path(d)
            (Path(d) / "zz.json").write_text(json.dumps({"2026-10-01": rows}, ensure_ascii=False), encoding="utf-8")
            got = AC.queries_for("zz", 5)
        finally:
            AC.RANKS = real
    check("queries_for は指名を外し、表記ゆれの重複も落とす", got, ["aio対策 費用"])


# ── L0114: 記事動画を新しい順で選び、打ち出しから外した MEO も動画にした（2026-10-02）──────
def test_hist_lessons_videos_skip_dropped_themes():
    print("\n■ 学びL0114: 打ち出しから外したテーマ（drop_kw・配分0のカテゴリ）は動画にしない")
    sys.path.insert(0, str(ROOT / "scripts"))
    import article_videos as AV
    cfg = {"drop_kw": ["meo"], "category_mix": {"meo": 0, "aio": 50}, "kw_seeds": {"priority": ["歯科"]},
           "main_category": "aio"}
    rows = [{"site": "s", "title": "歯科医院のMEO対策", "category": "aio"},
            {"site": "s", "title": "歯科医院の地図集客", "category": "meo"}]
    made = lambda fn: [r["title"] for r in rows if fn(r) is not None]
    check("検出器: 外したテーマを作る選び方を拾う", made(lambda r: 0), [r["title"] for r in rows])
    saved = dict(AV._CFG)
    try:
        AV._CFG.clear()
        AV._CFG.update({"s": cfg})
        got = (made(AV.focus), AV.focus({"site": "s", "title": "歯科医院のAIO対策", "category": "aio"}))
    finally:
        AV._CFG.clear()
        AV._CFG.update(saved)
    check("focus は外したテーマを None にし、主力の業種・分野を上げる", got, ([], 3))
    src = (ROOT / "scripts" / "article_videos.py").read_text(encoding="utf-8")
    check("候補の選び方が focus の None を除く", src.count("is None") >= 1 and "focus(m) is not None" in src, True)


# ── L0095: 既存のお客様が再診断すると、ステップメール・自動フォローが再開した（2026-09-28）──────
def _gs_func(src, name):
    m = re.search(rf"function {name}\(.*?\n\}}\n", src, re.S)
    return m.group(0) if m else ""


def follow_order_problems(follow_src):
    """followUp の中で、除外の確認より前に送信の関数を呼んでいないか"""
    i = follow_src.find("excluded_(")
    out = [] if i >= 0 else ["配信除外を見ていない"]
    for send in ("stepMail_(", "toolFollow_("):
        j = follow_src.find(send)
        if j >= 0 and (i < 0 or j < i):
            out.append(f"{send} が除外の確認より前")
    return out


def test_hist_lessons_followup_respects_optout():
    print("\n■ 学びL0095: 自動フォローは行の状態ではなく、メールアドレス・ドメイン単位の配信除外で止める")
    check("検出器: 除外を見ずに送る followUp を拾う",
          follow_order_problems("function followUp() {\n  stepMail_(sh, 2, r);\n}\n"), ["配信除外を見ていない", "stepMail_( が除外の確認より前"])
    src = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    check("followUp は送る前に配信除外を見る", follow_order_problems(_gs_func(src, "followUp")), [])
    free = re.search(r"^const FREE_MAIL = .+$", src, re.M)
    code = (free.group(0) if free else "") + "\n" + "\n".join(_gs_func(src, n) for n in ("normHost_", "domainHit_", "excluded_"))
    js = ("var S={emails:{'old@a.co.jp':true},domains:{'client.co.jp':true,'gmail.com':true}};"
          "globalThis.__out=[excluded_(S,'old@a.co.jp',''),excluded_(S,'x@client.co.jp',''),"
          "excluded_(S,'new@gmail.com',''),excluded_(S,'y@new.jp','対象 https://www.client.co.jp/top')];")
    from gates_history_d import node_run
    got = node_run(code, js)
    if got is None:
        print("  WARN  node が無いため、配信除外の判定は確かめられません")
        return
    check("除外: 登録メール・会社ドメイン・診断サイトのドメインは止め、フリーメールのドメインでは止めない",
          got, [True, True, False, True])


# ── L0119: 「権限が承認待ちです」と言い換え、原因を3回誤診。GitHub の500も「無効」と案内（2026-09）──
def names_status(exc, code):
    return str(code) in str(exc)


def test_hist_lessons_token_check_names_status():
    print("\n■ 学びL0119: 失敗の表示に相手の生のステータスと文言を出す（token_check）")
    check("検出器: 状態を捨てた言い換えを拾う", names_status(Exception("権限が承認待ちです"), 403), False)
    import email.message
    import io
    import urllib.error
    sys.path.insert(0, str(ROOT / "scripts"))
    import token_check as TC

    def call(code, body):
        def boom(*a, **k):
            raise urllib.error.HTTPError("https://api.github.com/x", code, "reason", email.message.Message(),
                                         io.BytesIO(body))
        real, back = TC.urllib.request.urlopen, TC.BACKOFF
        try:
            TC.urllib.request.urlopen, TC.BACKOFF = boom, 0
            TC._api("/x", "t")
        except Exception as e:
            return e
        finally:
            TC.urllib.request.urlopen, TC.BACKOFF = real, back
    e500 = call(500, b"")
    e401 = call(401, b'{"message": "Bad credentials"}')
    check("GitHub の500はトークンの問題にせず、状態を出す",
          (type(e500).__name__, names_status(e500, 500)), ("UpstreamError", True))
    check("401は状態と相手の文言をそのまま出す",
          (type(e401).__name__, names_status(e401, 401), "Bad credentials" in str(e401)), ("AuthError", True, True))


# ── L0094: 週次レポートをHTMLのままメールで送り、受け取り側で文字化け（2026-09-14）──────────
REPORT_SENDERS = ("monthly_report.py", "group_report.py", "report_digest.py", "send_reports.py")


def attaches_pdf(src):
    return bool(re.search(r"""["']attachments["']""", src)) and bool(re.search(r"\.pdf\b", src))


def test_hist_lessons_reports_attach_pdf():
    print("\n■ 学びL0094: 人に届けるレポートは PDF を添付して送る")
    check("検出器: 本文HTMLだけで送る形を拾う", attaches_pdf('payload = {"html": body, "subject": s}'), False)
    check("検出器: PDF の添付は通す", attaches_pdf('"attachments": [{"filename": "report.pdf"}]'), True)
    bad = [n for n in REPORT_SENDERS if not attaches_pdf((ROOT / "scripts" / n).read_text(encoding="utf-8"))]
    check("レポートを送るスクリプトが PDF を添付する", bad, [])


# ── L0093: 提案書の記事一覧に補助金の記事が混ざり、業種の同じ数字を全記事に出していた（2026-10-02/03）──
def off_topic(titles, cat_of, allowed):
    return [t for t in titles if cat_of.get(t) not in allowed]


def test_hist_lessons_figures_follow_site_and_topic():
    print("\n■ 学びL0093: 資料・記事へ差し込む集計は、対象サイトと記事の主題で絞る")
    allowed = {"aio", "seo", "ai-marketing"}
    check("検出器: 別サイトの記事を拾う",
          off_topic(["IT導入補助金の申請"], {"IT導入補助金の申請": "hojokin"}, allowed), ["IT導入補助金の申請"])
    sys.path.insert(0, str(ROOT / "scripts"))
    import industry_ai_sources as IAS
    import industry_hub as IH
    import proposal_make as PM
    cat_of = {str(fm.get("title") or "").strip(): fm.get("category") for _, fm, _ in articles()}
    bad = []
    for ind in IH.load()[0]:
        f = PM.industry_facts(ind["name"])
        if f:
            bad += [f"{ind['name']}: {t}" for t in off_topic(f["titles"], cat_of, allowed)]
    check("提案書の業種ページの記事一覧は AI集客ラボの SEO・AIO・AI集客の記事だけ", bad, [])
    a = IAS.research_box("shika", "歯科医院の費用はいくら？相場と内訳")
    b = IAS.research_box("shika", "歯科医院の治療の選び方")
    if not (a and b):
        print("  WARN  歯科の調査の集計が無いため、記事ごとの調査の枠は確かめられません")
        return
    check("記事末の調査の枠は、題名の質問の種類ごとに中身が変わる", a != b, True)


# ── L0101: 同じサイトに書く自動化が2つ並走し、記事が二重に作られた（2026-07-30）──────────
def scheduled_writers(wfs):
    """(名前, 本文, 日程) のうち、日程の回で記事を書くもの。
    multi_site_prompt を使うワークフローは日程で書く。pipeline_prompt.txt は日程の回が救済に回るかを見る"""
    out = []
    for name, text, crons in wfs:
        if not crons:
            continue
        if "multi_site_prompt" in text:
            out.append(name)
        elif "pipeline_prompt.txt" in text:
            rescued = set(re.findall(r'github\.event\.schedule \}\}" = "([^"]+)" \]; then\s*\n\s*echo "mode=rescue"', text))
            if any(c not in rescued for c in crons):
                out.append(name)
    return out


def test_hist_lessons_one_scheduled_writer():
    print("\n■ 学びL0101: 記事を書く定期実行は1本だけ（救済の回は書かない）")
    rescue = ('if [ "${{ github.event.schedule }}" = "30 12 * * *" ]; then\n  echo "mode=rescue"\n'
              'claude -p "$(cat automation/pipeline_prompt.txt)"')
    check("検出器: 2本目の書き手を拾う",
          scheduled_writers([("a.yml", "python scripts/multi_site_prompt.py", ["7 1 * * *"]),
                             ("b.yml", "claude -p \"$(cat automation/pipeline_prompt.txt)\"", ["7 2 * * *"])]),
          ["a.yml", "b.yml"])
    check("検出器: 日程の回が救済だけなら書き手に数えない",
          scheduled_writers([("b.yml", rescue, ["30 12 * * *"])]), [])
    wfs = []
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        t = p.read_text(encoding="utf-8")
        y = yaml.safe_load(t) or {}
        on = y.get("on") or y.get(True) or {}
        crons = [c.get("cron") for c in ((on.get("schedule") if isinstance(on, dict) else None) or [])]
        wfs.append((p.name, t, crons))
    check("日程で記事を書くワークフローは pipeline-multi.yml だけ", scheduled_writers(wfs), ["pipeline-multi.yml"])


# ── L0102: 自動修復がデプロイの正常な取り消しに反応し、各社分が無いのに送信済みと判断（2026-09-25）──
def trigger_problems(cond):
    c = re.sub(r"\s+", " ", cond)
    out = []
    if "conclusion == 'failure'" not in c:
        out.append("失敗で起動しない")
    if "!= 'success'" in c:
        out.append("成功以外すべてで起動する（デプロイの取り消しも拾う）")
    if "'cancelled'" in c and "name != 'Deploy to Cloudflare Pages'" not in c:
        out.append("デプロイの取り消しで起動する")
    return out


def test_hist_lessons_selfheal_trigger_and_done():
    print("\n■ 学びL0102: 自動修復は失敗（とデプロイ以外の取り消し）で起動し、送り終えたかは送信の工程の成否で見る")
    check("検出器: 成功以外すべてで起動する条件を拾う",
          trigger_problems("github.event.workflow_run.conclusion != 'success'"),
          ["失敗で起動しない", "成功以外すべてで起動する（デプロイの取り消しも拾う）"])
    wf = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    y = yaml.safe_load(wf) or {}
    conds = [str(j.get("if") or "") for j in (y.get("jobs") or {}).values() if "workflow_run" in str(j.get("if") or "")]
    check("selfheal の起動条件", [p for c in conds for p in trigger_problems(c)] if conds else ["起動条件が無い"], [])
    check("送り終えたかを、各社のまとめと詳細版の送信工程の成否（2つとも）で見る",
          '"各社のレポートを1通にまとめて送る"' in wf and '.conclusion == "success"' in wf
          and '[ "${sent:-0}" -ge 2 ]' in wf, True)


# ── L0117: YouTube の自動字幕の誤変換（LLMO→LMO）を断片のまま引いた（2026-08-07）──────────
def warns_at_use(src):
    return bool(re.search(r"print\([^\n]*誤変換[^\n]*確認", src))


def test_hist_lessons_subtitle_warning_at_use():
    print("\n■ 学びL0117: 字幕を渡す道具が、使うその場で「数値・固有名詞は確かめる」と知らせる")
    check("検出器: 知らせない出力を拾う", warns_at_use('print("字幕を保存しました")'), False)
    check("検出器: 知らせる出力は通す", warns_at_use('print("※ 自動字幕は誤変換があります。数値は動画で確認してから")'), True)
    bad = [n for n in ("research.py", "yt_quotes.py") if not warns_at_use((ROOT / "scripts" / n).read_text(encoding="utf-8"))]
    check("research.py・yt_quotes.py が字幕を出すときに注意を出す", bad, [])
