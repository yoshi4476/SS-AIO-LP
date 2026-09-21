# -*- coding: utf-8 -*-
"""品質ゲートの回帰テスト

実行: python tests/test_gates.py

ここにあるのは、実際に起きた不具合をそのまま固定したもの。
どれもコードを読むだけでは見つからず、動かして初めて分かった。

  1. 食い合い検査が、審査対象の語そのものの台帳行を重複と数え、
     どのKWも弾かれてパイプラインがKWを1件も取得できなくなった
  2. 狙う語を文字の類似で比べ、「it導入補助金 学習塾」と
     「it導入補助金 飲食店」を同じものとみなした（88件中ほとんどが誤検出）
  3. タグの開始と終了の数だけを見ていたため、閉じ忘れと余分な閉じが
     相殺し、</content> が公開HTMLに残った
  4. 採点とビルドで文字数の数え方が違い、同じ記事が5,251字と4,922字になった
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FAIL = []


def check(name, got, want):
    ok = got == want
    print(f"  {'OK' if ok else 'NG'}  {name}" + ("" if ok else f"  （得た {got!r} / 期待 {want!r}）"))
    if not ok:
        FAIL.append(name)


# ── 1. 狙う語の判定 ──────────────────────────────
def test_kw_conflicts():
    from cannibal_check import kw_conflicts, norm_kw
    print("\n■ 狙う語の食い合い判定")
    arts = [{"slug": "a", "kw": "aio診断", "title": "AIO診断のやり方", "desc": "", "h2": [], "cat": "aio"},
            {"slug": "b", "kw": "it導入補助金 学習塾", "title": "学習塾のIT導入補助金", "desc": "", "h2": [], "cat": "aio"},
            {"slug": "c", "kw": "整骨院 集客", "title": "整骨院の集客", "desc": "", "h2": [], "cat": "aio"}]
    check("表記ゆれを同じ語とみなす", bool(kw_conflicts("aio 診断", arts)), True)
    check("全角も同じ語とみなす", norm_kw("ＡＩＯ診断") == norm_kw("aio診断"), True)
    # 業種が違うだけのKWを弾かない（実データで88件中ほとんどが誤検出だった）
    check("業種違いは食い合いにしない", bool(kw_conflicts("it導入補助金 飲食店", arts)), False)
    check("狭い語は広い語に含まれる", bool(kw_conflicts("整骨院 集客 口コミ", arts)), True)
    check("無関係な語は通す", bool(kw_conflicts("動物病院 集客", arts)), False)


# ── 2. タグの対応 ────────────────────────────────
def test_tag_balance():
    sys.path.insert(0, str(ROOT / "scripts"))
    from live_check import tag_balance
    print("\n■ タグの対応検査")
    check("正しい入れ子は通る", tag_balance("<div><p>あ</p></div>"), [])
    check("void要素は数えない", tag_balance("<div><img src='x'><br></div>"), [])
    # 数を数えるだけだと、この2つは相殺して見つからない
    both = tag_balance("<div>あ</content>")
    check("閉じ忘れと余分な閉じを両方見つける", len(both), 2)
    check("開始タグの無い閉じを見つける",
          any("対応する開始タグが無い" in x for x in tag_balance("<p>あ</p></content>")), True)
    check("コードブロック内は無視する", tag_balance("<script>if(a</b>){}</script>"), [])


# ── 3. 文字数の数え方 ────────────────────────────
def test_char_count():
    import md2html
    print("\n■ 文字数の数え方")
    body = "## 見出し\n\n本文です。\n\n| 列A | 列B |\n|:--|:--|\n| あ | い |\n"
    plain = re.sub(r"\s|<[^>]+>", "", md2html.convert(body)[0])
    # 見出しの # や表の | を数えない（採点とビルドで食い違う原因だった）
    check("記法の記号を数えない", ("#" in plain) or ("|" in plain), False)
    check("本文は数える", "本文です。" in plain, True)


# ── 4. 管制塔の食い合い判定（GAS） ──────────────────
def test_hub_gas():
    print("\n■ 管制塔（GAS）の食い合い判定")
    src = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")

    def fn(name):
        m = re.search(rf"function {name}\(.*?\n\}}\n", src, re.S)
        return m.group(0) if m else ""

    harness = """
var READS = 0, ROWS = [];
for (var i = 0; i < 60; i++) ROWS.push(['ai-lab','重複語' + (i%3), '公開済み','A','','','','','','','']);
for (var i = 0; i < 40; i++) ROWS.push(['ai-lab', i < 20 ? '重複語' + (i%3) : '新しい語' + i,
                                        '未着手','B','','','','','','','']);
function kwRows_() { READS++; return ROWS; }
"""
    js = harness + fn("normKw_") + fn("kwConflict_") + fn("nextKw_") + """
var r = nextKw_('ai-lab');
console.log(JSON.stringify({reads: READS, kw: r.keyword,
                            skipped: (r.skipped_conflict||[]).length}));
"""
    tmp = ROOT / "tests" / "_hub_tmp.js"
    tmp.write_text(js, encoding="utf-8")
    try:
        out = subprocess.run(["node", str(tmp)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        import json
        d = json.loads(out.stdout.strip() or "{}")
    finally:
        tmp.unlink(missing_ok=True)
    # 自分の台帳行を重複と数えると、どのKWも弾かれてパイプラインが止まる
    check("自分の行を重複と数えない", bool(d.get("kw", "").startswith("新しい語")), True)
    # 候補ごとに台帳を読み直すと、未着手が数百件でGASの実行時間の上限に当たる
    check("台帳の読み取りは1回だけ", d.get("reads"), 1)
    check("本当の重複だけを飛ばす", d.get("skipped"), 20)


# ── 5. 執筆後ゲートの自己照合 ────────────────────
def test_self_exclusion():
    """書いた記事が自分自身と「完全一致」で止まった事故の再現。
    正当な新記事3本が全部この誤検出で止まり、その回の執筆が無駄になった。"""
    from kw_guard import judge
    print("\n■ 執筆後ゲートの自己照合")
    import glob, re
    # 実在の記事を1本選び、自分のKWで審査する。
    # 導入直後は記事が無いので、その場合は飛ばす（雛形でも落ちないように）
    files = sorted(glob.glob(str(ROOT / "articles" / "*.md")))
    if not files:
        print("  --  記事が無いため飛ばします（導入直後の状態）")
        return
    f = files[0]
    slug = Path(f).stem
    fm = Path(f).read_text(encoding="utf-8-sig").split("---", 2)[1]
    kw = (re.search(r"^keyword:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
    lv_with, _ = judge(kw, "", use_gsc=False, exclude_slug=slug)
    lv_without, _ = judge(kw, "", use_gsc=False)
    check("自分を除けば自分とは食い合わない", lv_with < 2, True)
    check("除かなければ完全一致で止まる（検査自体は生きている）", lv_without, 2)


# ── 6. 公開済み記事を新規とみなさない ────────────
def test_published_not_rewritten_as_new():
    """公開中の記事10本が隔離された事故の再現。

    内部リンクの追加などで既存記事が書き換わると、gitの差分では
    「変更」として出る。それを新規として審査すると、別ページが同じ語で
    順位を持っているという理由で、公開中の記事が隔離されてしまう。
    """
    import kw_gate
    print("\n■ 公開済み記事の扱い")
    pairs = kw_gate.written_keyword("ai-lab")
    published = [s for s, _ in pairs
                 if list((ROOT / "site").glob(f"*/{s}/index.html"))]
    check("公開済みの記事を新規として拾わない", published, [])


# ── 7. トークンの権限判定 ──────────────────────
def test_token_check_probes_write():
    """「書き込み可」と出るのに配信が403で落ちた事故の再現。

    GitHub APIの permissions.push は「その利用者の権限」であって
    トークンの権限ではない。細粒度PATが Contents: Read only でも
    true が返るため、これを見ていた検査は通り、配信で落ちた。
    """
    src = (ROOT / "scripts" / "token_check.py").read_text(encoding="utf-8")
    print("\n■ トークンの権限判定")
    check("利用者の権限で判定していない",
          'get("permissions") or {}).get("push")' in src, False)
    check("実際に書き込みを試している", "_probe_write" in src, True)
    check("403を権限不足として扱う", "403" in src, True)


# ── 8. 自動修復の待ち受け名 ──────────────────────
def test_selfheal_watches_real_workflows():
    """待ち受ける名前が1文字でも違うと、落ちても何も起きない。

    最初に書いたときは日本語の名前を並べていたが、実際の name: は
    英語だった。名前は目で合わせず、機械で突き合わせる。
    """
    import yaml
    print("\n■ 自動修復の待ち受け名")
    wf = ROOT / ".github" / "workflows"
    heal = yaml.safe_load((wf / "selfheal.yml").read_text(encoding="utf-8"))
    # PyYAML は on: を True と読む
    trig = heal.get("on") or heal.get(True) or {}
    watched = set((trig.get("workflow_run") or {}).get("workflows") or [])
    actual = {yaml.safe_load(f.read_text(encoding="utf-8")).get("name")
              for f in wf.glob("*.yml") if f.name != "selfheal.yml"}
    missing = sorted(watched - actual)
    check("待ち受け名がすべて実在する", missing, [])
    check("待ち受けが空でない", bool(watched), True)


# ── 9. ラボからコーポレートへの導線 ────────────────
def test_lab_links_to_corporate():
    """カテゴリーの記事を読み切った人の行き先。

    ラボは読む場所、コーポレートは頼む場所。つながっていないと、
    記事を読み終えた人が次にどこへ行けばいいか分からない。
    リンク先を手で書いているので、綴りの間違いを機械で見る。
    """
    import glob
    import json as _json
    print("\n■ ラボからコーポレートへの導線")
    own = [f for f in (ROOT / "sites").glob("*.json")
           if _json.loads(f.read_text(encoding="utf-8")).get("type") == "self-static"]
    if not own:
        print("  --  自前ビルドのサイトが無いため飛ばします")
        return
    conf = _json.loads(own[0].read_text(encoding="utf-8"))
    cats = list((conf.get("categories") or {}).keys())
    # コーポレート側に実在するページ
    src = (ROOT / ".publish-work" / "corporate" / "src" / "lib" / "services.ts")
    known = {"/aio-agent", "/rakushift", "/contact", "/company", "/"}
    if src.exists():
        known |= {"/services/" + s for s in
                  re.findall(r'slug: "([^"]+)"', src.read_text(encoding="utf-8"))}
    missing, nolink = [], []
    for c in cats:
        f = ROOT / "site" / c / "index.html"
        if not f.is_file():
            continue
        html = f.read_text(encoding="utf-8")
        urls = set(re.findall(r'href="https://corp\.7senses\.co\.jp([^"]*)"', html))
        deep = {u for u in urls if u not in ("", "/")}
        if not deep:
            nolink.append(c)
        if src.exists():
            missing += [f"{c}{u}" for u in deep if u.split("#")[0] not in known]
    if not any((ROOT / "site" / c / "index.html").is_file() for c in cats):
        print("  --  カテゴリーページがまだ無いため飛ばします（導入直後の状態）")
        return
    check("全カテゴリーに個別リンクがある", nolink, [])
    check("リンク先が配信先に実在する", missing, [])


# ── 10. 日次監査の本数カウント ────────────────────
def test_daily_audit_ignores_unscored_drafts():
    """score未設定（Phase 5未通過）の記事を「本日公開」に数えた事故の再現。

    publish.pyはscore<90を配信拒否するため、そういう記事はまだサイトに無い。
    それを本数に数えると「本日OK」と誤表示した上で、check_liveが
    「公開したのに404」という偽の不具合をTODOに積む。"""
    import daily_audit
    print("\n■ 日次監査の本数カウント")
    today = daily_audit.today_iso()
    fixture = {"ai-lab": [
        {"slug": "a", "date": today, "score": "95", "title": "t", "category": "c"},
        {"slug": "b", "date": today, "score": "", "title": "t2", "category": "c"},
    ]}
    orig = daily_audit.articles_by_site
    daily_audit.articles_by_site = lambda: fixture
    try:
        by_site = daily_audit.check_volume([])
    finally:
        daily_audit.articles_by_site = orig
    check("scoreのない記事は本数に数えない", len(by_site["ai-lab"]), 1)


def test_every_article_has_a_lead_path():
    """全記事にリード導線があること。

    読んで納得した人の行き先が無いと、記事はそこで終わる。
    実際コーポレートは88本中75本に行き先が無く、記事からの反応がゼロだった。
    新しい記事が増えるたびに漏れるため、機械で見張る。
    """
    lead = re.compile(r"/diagnosis/|/site-audit/|#diagnosis|/contact|/lp/")
    missing = []
    for f in sorted((ROOT / "articles").glob("*.md")):
        body = f.read_text(encoding="utf-8", errors="replace").split("---", 2)[-1]
        if not lead.search(body):
            missing.append(f.stem)
    check("リード導線の無い記事", missing[:5], [])

    # 検査そのものが働いているか。build.py が見張っていないと、
    # 上の判定が通っていても次に増えた記事で崩れる
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.pyがリード導線を見張っている", "リード導線なし" in src, True)

    # 日次パイプラインで新しい記事にも入ること
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("日次で導線を入れている", "tool_links.py --write" in wf, True)


def test_token_never_in_command_line():
    """配信のコマンドラインにトークンを載せないこと。

    URLに埋めると、プロセス一覧を見るだけでPATが読める。特権は要らない。
    実際、稼働中の配信からPATの全体が読み出せた。失敗時のログにも残る。
    """
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("URLにトークンを埋めていない", "x-access-token:{token}" in src, False)
    check("askpass経由で渡している", "GIT_ASKPASS" in src, True)
    check("失敗ログでトークンを伏せている", "def mask(" in src, True)


def test_kw_intent_separates_click_need():
    """検索結果で用が済む語と、開かないと済まない語を見分けられること。

    同じ順位でもCTRは5倍違った。例文・診断系は8〜9位で表示88回・クリック0、
    不採択理由・書き方は5〜7位でクリックが付いていた。
    この判定が壊れると、読まれない語を書き続けることになる。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import kw_intent
    weak = ["口コミ 返信 例文 医療", "aio 診断", "meo対策 とは"]
    strong = ["ai導入補助金 不採択理由", "実績報告 書き方", "持続化補助金 対象 条件"]
    check("弱い語を弱と判定", [kw_intent.verdict(k)[0] for k in weak], ["弱"] * 3)
    check("強い語を強と判定", [kw_intent.verdict(k)[0] for k in strong], ["強"] * 3)

    # 執筆前のゲートが注意を出すこと。判定だけあっても使われなければ意味がない
    guard = (ROOT / "scripts" / "kw_guard.py").read_text(encoding="utf-8")
    check("食い合いゲートが開く理由を見る", "kw_intent" in guard, True)
    disc = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("候補の並びに反映している", "kw_intent" in disc, True)


def test_lead_funnel_is_watched():
    """リード導線の各段階が、週次で測られ続けること。

    導線を入れただけでは伸びない。押されているのか、押した先で
    落ちているのかが分からないと、次に直す場所が決まらない。
    実際、記事のCTAは長らくクリックが記録されず、判断できなかった。
    """
    f = ROOT / "scripts" / "funnel.py"
    check("段階を測る道具がある", f.is_file(), True)
    src = f.read_text(encoding="utf-8") if f.is_file() else ""
    for ev in ("cta_click", "form_start", "form_submit"):
        check(f"{ev} を見ている", ev in src, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で走る", "funnel.py" in wf, True)


def test_cta_wording_is_measured_not_guessed():
    """CTAの文言を推測で決めないこと。

    記事を見た544件に対しクリックは38件。どの文言なら押されるかは
    推測では決まらない。半々で出し分けて実測する仕組みを保つ。
    """
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("記事のCTAをA/Bの対象にしている", 'data-ab="article_cta"' in b, True)
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    # パラメータはGA4の管理画面で登録しないと集計できない。名前に入れる
    check("A/Bを出来事の名前に入れている", "'cta_click_' + abv" in js, True)
    check("表示側も名前に入れている", "'ab_impression_' + v" in js, True)
    check("結果を読む道具がある", (ROOT / "scripts" / "ab_result.py").is_file(), True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で結果を見る", "ab_result.py" in wf, True)


def test_each_site_declares_what_it_sells():
    """サイトごとに、何を売る記事なのかが決まっていること。

    主力が決まっていないと、書きやすい領域に寄る。実際3サイトとも
    主力が最多ではなかった（ラボはAIO 19.8%、コーポレートはBPO 40.8%、
    補助金はAI導入補助金 37.6%）。読まれても売上につながらない。
    """
    import json
    for f in sorted((ROOT / "sites").glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        check(f"{f.stem} に主力がある", bool(c.get("main_offer")), True)
        mix = c.get("category_mix") or c.get("scheme_mix") or {}
        real = {k: v for k, v in mix.items() if not k.startswith("_")}
        check(f"{f.stem} に狙う配分がある", bool(real), True)
        if real:
            check(f"{f.stem} の配分が100%", sum(real.values()), 100)
    brief = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("執筆前に主力を見せている", "このサイトで売るもの" in brief, True)


def test_next_keyword_prefers_main_offer():
    """次に書く語は、そのサイトの主力を先に選ぶこと。

    台帳は優先度順に返すが、いま台帳の語はすべて優先度Bで実質は行の並び順。
    主力から離れた古い語が先に出ていた（ラボで「工務店 sns 集客」など）。
    配信済みの管制塔コードは優先度付きの追加に対応しておらず、
    台帳側では順序を変えられないため、取り出す側で寄せている。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import hub_client
    for site, must in (("ai-lab", "aio"), ("subsidy", "ai導入補助金"),
                       ("corporate", "bpo")):
        pat = hub_client._main_offer_pattern(site)
        check(f"{site} の主力の目印がある", bool(pat), True)
        check(f"{site} の目印が主力を含む", must in pat, True)
    src = (ROOT / "scripts" / "hub_client.py").read_text(encoding="utf-8")
    check("next_kw が主力を優先している", "主力優先" in src, True)


def test_improvements_apply_themselves():
    """効果の出ていない記事が、毎週自動で手当てされること。

    「対策した」と「効果があった」は別物で、測って終わりでは何も変わらない。
    条件で決まる手当て（内部リンク）は機械に任せ、文章の判断が要るものだけ
    人（AI）へ渡す。全部を自動にすると、主張のずれた記事が量産される。
    """
    for f in ("effect.py", "auto_improve.py"):
        check(f"{f} がある", (ROOT / "scripts" / f).is_file(), True)
    src = (ROOT / "scripts" / "auto_improve.py").read_text(encoding="utf-8")
    check("内部リンクは自動で当てる", "add_links" in src, True)
    # タイトルの書き換えを機械に任せると、中身の無い約束が並ぶ
    check("タイトルは自動で書き換えない", "def rewrite_title" in src, False)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で自動改善が走る", "auto_improve.py --write" in wf, True)
    pr = (ROOT / "automation" / "weekly_optimize_prompt.txt").read_text(encoding="utf-8")
    check("人が判断する分はAIへ渡している", "人が判断すること" in pr, True)
    check("一度に触る本数を制限している", "最大5本" in pr, True)


def test_auto_fixes_are_reviewed():
    """自動で当てた修正が、必ず見直されること。

    当てる側は1本ずつしか見ないため、積み上がりを検知できない。実測では
    「関連して、[X]もあわせてご確認ください。」という同じ一文が内部リンク文
    970本中403本（41.5%）を占め、1記事に11本並んだものまであった。
    1本単位では基準内でも、全体で見れば量産の指紋になる。
    """
    check("見直し役がある", (ROOT / "scripts" / "auto_review.py").is_file(), True)
    rv = (ROOT / "scripts" / "auto_review.py").read_text(encoding="utf-8")
    im = (ROOT / "scripts" / "auto_improve.py").read_text(encoding="utf-8")

    # 当てたら自動で見直しへ繋ぐ。人の判断に委ねると忙しい週に飛ばされる
    check("自動修正のあと見直しが走る", "auto_review.py" in im, True)
    # 検算なしで書き込むと、パターンの取りこぼしが本番の記事を壊す
    check("書き込む前に検算する", "def guard" in rv, True)
    for keep in ("cta-button", "diagnosis", "contact"):
        check(f"リード導線「{keep}」は削除対象から外す", keep in rv, True)
    check("HTMLタグの開閉数を見る", "</figure>" in rv, True)
    check("台帳に残す", "auto_fix.jsonl" in rv and "auto_fix.jsonl" in im, True)
    check("ビルドの機械ゲートに通す", "build.py" in rv, True)

    # 言い回しを自前で書くスクリプトがあると、その一文がサイト中に並ぶ
    for f in ("auto_improve.py", "link_boost.py"):
        src = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        check(f"{f} は自前の定型文を書かない",
              "もあわせてご確認ください" in src, False)
        check(f"{f} は link_new の型を使う", "ln.sentence" in src, True)

    # サイト全体の偏りを測れること（記事単位の基準では捕まらない）
    sys.path.insert(0, str(ROOT / "scripts"))
    import auto_review as ar
    check("全体の偏りに上限がある", ar.MAX_SHARE <= 0.2, True)
    check("1記事のリンク段落に上限がある", ar.MAX_LINK_PARA <= 6, True)

    doc = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    check("パイプライン定義に載っている", "自動修正と、その見直し" in doc, True)



def test_client_onboarding_is_one_sheet():
    """ヒアリングシートを1枚埋めれば運用が立ち上がること。

    設定が sites/ と data/ に散っていると、埋め忘れたまま記事を作り始めて
    後から気づく。特に一次情報（その会社にしか出せない数値）が無いまま
    書くと、どのサイトでも書ける記事になりAI検索に引用されない。
    """
    check("ヒアリングシートを作る口がある",
          (ROOT / "scripts" / "client_intake.py").is_file(), True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import client_add as ca
    import client_intake as ci

    # シートは共通＋執筆材料＋被リンクで1枚。fields_for がその全部を返す
    keys = {k for k, *_ in ci.fields_for() if not k.startswith("#")}
    # 主力商材が無いと、表示は増えても相談につながらない記事が量産される
    for k in ("main_offer", "main_category", "categories", "category_mix"):
        check(f"シートで「{k}」を聞いている", k in keys, True)
    # 一次情報はAI検索に引用されるかを決める材料。必須で聞く
    check("一次情報を必須で聞いている",
          any(k == "facts.1.claim" and req for k, _, _, _, req in ci.FIELDS), True)
    check("一次情報の時点も聞いている", "facts.1.as_of" in keys, True)
    for k in ("company.name", "company.address", "cta.label", "cta.url"):
        check(f"シートで「{k}」を聞いている", k in keys, True)

    # シートの回答が、そのまま設定として通ること
    nl = chr(10)
    got = {k: "x" for k in keys}
    got.update({
        "id": "sample-media", "type": "external-html", "repo": "o/r",
        "categories": "sample-a: A" + nl + "sample-b: B",
        "category_mix": "sample-a: 60" + nl + "sample-b: 40",
        "main_category": "sample-a",
        "kw_seeds.industries": nl.join("業種%d" % i for i in range(25)),
        "kw_seeds.intents": nl.join("意図%d" % i for i in range(10)),
        "facts.1.as_of": "2026-09",
    })
    cfg = ci.to_config(got)
    check("シートから設定が組み立つ", bool(cfg["main_offer"] and cfg["categories"]), True)
    check("配分が数値として読める", cfg["category_mix"]["sample-a"], 60)
    check("一次情報が取り出せる", len(ci.to_facts(got, "sample-media")) >= 1, True)
    ng, _ = ci.review(got, cfg)
    check("埋まったシートは不備なしで通る", ng, [])
    # JSONから直接入れる口（client_add）の必須項目も満たせること
    check("JSON側の必須項目もすべて埋まる",
          [k for k in ca.REQUIRED if not cfg.get(k)], [])

    # 受託運用で、クライアントの記事に運用会社の実績が混ざらないこと
    import facts
    check("一次情報をクライアント別に読む", hasattr(facts, "load_for"), True)

    # 記事を書くための材料。空だと「どこにでもある記事」になる
    for k in ("service.list", "customer.faq", "author.name", "tone.style",
              "target.persona", "kw.main", "kw.sub"):
        check(f"シートで「{k}」を聞いている", k in keys, True)
    # 被リンクは買えない。すでにある関係を掘り起こすしかない
    for k in ("link.orgs", "link.partners", "link.press"):
        check(f"外部との接点「{k}」を聞いている", k in keys, True)
    # 業種が変われば必要な材料も変わる
    check("業種別のシートがある", "restaurant" in ci.INDUSTRY, True)
    rkeys = {k for k, *_ in ci.fields_for("restaurant") if not k.startswith("#")}
    for k in ("shop.seats", "menu.signature", "attract.reserve", "flink.gourmet"):
        check(f"飲食店シートで「{k}」を聞いている", k in rkeys, True)

    # メイン×サブから主題が組み立つこと。同じ語の重ねは出さない
    got2 = dict(got)
    got2.update({"kw.main": "梅田 個室 居酒屋", "kw.sub": "梅田 宴会 個室",
                 "kw_seeds.intents": "個室" + nl + "予約",
                 "kw.exclude": "求人"})
    subs = [x["keyword"] for x in ci.subjects(got2)]
    check("サブキーワードが主題になる", "梅田 宴会 個室" in subs, True)
    check("同じ語を重ねない", [s for s in subs if s.count("個室") > 1], [])
    check("狙わない語を除く", [s for s in subs if "求人" in s], [])

    # 執筆エージェントがこれを読めること
    import site_brief
    check("執筆ブリーフが材料を読む", hasattr(site_brief, "show_brief"), True)


def test_quality_gate_holds_on_wordpress():
    """納品方式が変わっても、基準に届かない記事が公開されないこと。

    静的サイトはファイルごと生成しないため物理的に公開できない。
    WordPressはデータベースに入ってしまうので、公開ステータスへの
    遷移を先方側で止める必要がある。配信スクリプトだけで見ていると、
    管理画面から直接投稿された記事を止められない。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import client_add as ca
    import publish
    check("WordPress納品に対応している", "wordpress" in ca.TYPES, True)
    check("WordPressへ配信できる", hasattr(publish, "write_wordpress"), True)

    php = ROOT / "automation" / "wordpress" / "ss-quality-gate.php"
    check("品質ゲートのプラグインがある", php.is_file(), True)
    src = php.read_text(encoding="utf-8")
    # 管理画面から止められる場所に置くと「忙しいので一旦切った」が起きる
    check("mu-plugins に置く指示がある", "mu-plugins" in src, True)
    # 個別の入口をふさぐ形にすると、入口が増えたときに漏れる
    check("すべての保存が通る関所で止める", "wp_insert_post_data" in src, True)
    check("公開を下書きへ戻す", "'draft'" in src or '"draft"' in src, True)
    check("予約投稿も対象にする", "future" in src, True)
    check("未採点は公開させない", "品質スコアがありません" in src, True)
    check("止めた理由を管理画面に出す", "admin_notices" in src, True)
    # 配信側でも見る。二重に見ないと、どちらか一方の抜け道が残る
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("配信側も90点未満を止める", "公開基準未達" in pub, True)
    check("公開されなかったことに気づける", "公開されませんでした" in pub, True)


def test_daily_todo_fits_in_one_run():
    """同日救済が1回で終わる量にとどまること。

    定期実行は数時間ずれる。実際、21:30の救済が翌03:07に走り、
    深夜に「本日0本」を見て6本書こうとしてターン上限で落ちた。
    さらにTODOが13件あり、救済プロンプトが説明しているのは4種類だけだった。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import daily_audit as da
    # 公開の時刻を過ぎていないものを「不足」と言わない
    check("公開時刻を持っている", bool(da.PUBLISH_HOURS), True)
    check("1回で扱う上限がある", da.MAX_TODAY <= 10, True)
    now, later = da.split_todo([
        "TODO: ai-lab の記事を本日あと 2 本作成して公開する",
        "TODO: 「aio診断」で自社ページが競合（ai-lab）。…",
        "TODO: リライト候補が223件ある。…",
        "TODO: x は subsidy の既存記事と重複（類似度0.6・url）。…",
    ])
    check("記事の作成が先頭に来る", "の記事を本日あと" in now[0], True)
    check("カニバリは今日やらない", any("競合" in x for x in later), True)
    check("リライト候補は今日やらない", any("リライト候補" in x for x in later), True)
    check("重複301は今日やる", any("既存記事と重複" in x for x in now), True)

    # 救済プロンプトが、今日やるTODOの全種類を説明していること
    pr = (ROOT / "automation" / "retry_prompt.txt").read_text(encoding="utf-8")
    for key in ("本作成して公開する", "品質基準まで直して", "の領域。",
                "既存記事と重複", "のKWを補充する"):
        check(f"救済プロンプトが「{key}」を説明している", key in pr, True)
    check("NOTE行は触らないと書いてある", "NOTE" in pr, True)

    # 似ているだけの記事を毎日TODOに出さない（実害で判定する）
    import cannibal_check as cc
    check("重複を実績で仕分ける", hasattr(cc, "judge_overlap"), True)
    check("食い合っていないものは出さない",
          "clear" in (cc.judge_overlap.__doc__ or ""), True)


def test_near_page1_is_pushed_every_week():
    """1ページ目に近い記事が、放置されずに毎週底上げされること。

    順位そのものは約束できない。決めるのはGoogleで、反映にも数ヶ月かかる。
    できるのは「こちら側でやれることを漏れなく続ける」ことだけなので、
    そこを仕組みに固定する。
    """
    check("底上げの工程がある", (ROOT / "scripts" / "priority_boost.py").is_file(), True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import priority_boost as pb
    # 主力の語に絞る。関係ない語で上位を取っても相談につながらない
    for sid in ("ai-lab", "corporate", "subsidy"):
        check(f"{sid} の主力の語を持っている", bool(pb.MAIN_PATTERN.get(sid)), True)
    check("あと少しの帯を狙う", pb.NEAR[0] >= 10 and pb.NEAR[1] <= 21, True)
    check("被リンクの下限がある", pb.INBOUND_FLOOR >= 10, True)
    # タイトルの判断は人に残す。機械が当てると主張のずれた記事になる
    src = (ROOT / "scripts" / "priority_boost.py").read_text(encoding="utf-8")
    check("タイトルは自動で書き換えない", "人が判断して直す" in src, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "priority_boost.py --write" in wf, True)


def test_main_category_actually_grows():
    """主力カテゴリが、狙いの配分に向かって増えること。

    site_brief が「次に書くなら◯◯」と出していても、執筆する側が
    それに従わなければ配分は動かない。実測で、AI集客ラボの主力（aio）は
    21%（狙い45%）まで落ち、直近21日の新規記事でも22%のままだった。
    指示が出ているだけでは足りず、従わせる一文が要る。
    """
    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("配分に従う指示がある", "次に書くなら" in pr, True)
    check("主力が不足すると何が起きるか書いてある",
          "相談につながらない" in pr, True)

    # 主力優先の目印が、主力カテゴリの語だけを拾うこと。
    # 広すぎると別カテゴリの語まで主力扱いになり、配分が動かない
    sys.path.insert(0, str(ROOT / "scripts"))
    import re as _re
    import hub_client as hb
    pat = _re.compile(hb._main_offer_pattern("ai-lab"), _re.I)
    check("主力の語を拾う", bool(pat.search("aio 診断")), True)
    check("別カテゴリの語は拾わない", bool(pat.search("chatgpt 集客 方法")), False)
    for sid in ("ai-lab", "corporate", "subsidy"):
        check(f"{sid} に主力の目印がある", bool(hb._main_offer_pattern(sid)), True)


def test_paragraph_split_keeps_text():
    """長い段落を分けても、地の文が変わらないこと。

    読みにくい段落は機械で分けられるが、文の途中で切れば意味が壊れる。
    「。」の直後だけで分け、分けた前後で文字が1字でも増減したら
    その記事は書き換えない。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import split_paragraphs as sp
    check("分ける工程がある", (ROOT / "scripts" / "split_paragraphs.py").is_file(), True)

    # 文の途中では切らない
    nl = chr(10)
    body = nl.join(["---", "title: x", "---", ("あ" * 120 + "です。") * 3])
    after, n = sp.process(body)
    check("長い段落を分ける", n > 0, True)
    check("地の文は変わらない", sp.plain(body) == sp.plain(after), True)
    check("「。」の直後で分かれる",
          all(p.rstrip().endswith(("。", "」", "）")) or "あ" not in p
              for p in after.split(nl + nl)[1:]), True)

    # 表・リスト・HTMLの塊には触らない
    check("表は触らない", sp.splittable("| 列A | 列B |" + "あ" * 300), False)
    check("リストは触らない", sp.splittable("- " + "あ" * 300), False)
    check("HTMLの塊は触らない", sp.splittable("<div>" + "あ" * 300 + "</div>"), False)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "split_paragraphs.py --all --write" in wf, True)


def test_anchor_text_stays_readable():
    """内部リンクのアンカーが、読める長さに収まること。

    自動で入れるリンク文は記事タイトルをそのままアンカーにする。
    タイトルは45字まで許されるため、前後の文と合わせると1文が100字を超える。
    実測で公開317本中49本がこれで警告に引っかかっていた。
    リンク先は絶対に変えず、表示される文字だけを意味の切れ目で詰める。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import link_new as ln
    import shorten_anchors as sa
    check("詰める工程がある", (ROOT / "scripts" / "shorten_anchors.py").is_file(), True)

    long_title = "飲食店のAI導入補助金 対象要件｜資本金・従業員数など5つの基準【2026年】"
    s = sa.shorten(long_title)
    check("長いアンカーを詰める", len(s) < len(long_title), True)
    check("詰めた結果が短すぎない", len(s) >= sa.MIN, True)
    check("元の文字列から作る（作文しない）",
          all(c in long_title for c in s), True)

    # 短いものには触らない
    check("短いアンカーは触らない", sa.shorten("AIO対策の始め方"), "AIO対策の始め方")

    # 今後生成されるリンクも詰まっていること（そうしないと毎週また溜まる）
    for fit in (0.1, 0.9):
        for seed in range(8):
            line = ln.sentence(long_title, "/aio/x/", seed, fit)
            anchor = line[line.index("[") + 1:line.index("](")]
            check(f"生成されるアンカーが{sa.MAX}字以内（seed={seed} fit={fit}）",
                  len(anchor) <= sa.MAX, True)

    # リンク先は変えない
    import re as _re
    body = f"[{long_title}](/subsidy/inshokuten-hojokin/)"
    out = _re.sub(r"\[([^\]]+)\]", lambda m: "[" + sa.shorten(m.group(1)) + "]", body)
    check("リンク先は変わらない", "(/subsidy/inshokuten-hojokin/)" in out, True)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "shorten_anchors.py --write" in wf, True)


def test_block_breaks_render_correctly():
    """段落の切れ目が壊れていないこと。

    リンク挿入と段落分割が、それぞれ別の壊し方をしていた。どちらも記事の点数には
    出ず、画面で初めて分かる。表がパイプ記号のまま本文に出て、** がそのまま表示される。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import fix_block_breaks as fb
    import split_paragraphs as sp
    nl = chr(10)

    # 1. 空行なしで続く表・リストの前に空行を入れる
    for block in ("| 列A | 列B |", "1. 最初の手順", "- 箇条書き"):
        out, n = fb.add_blank_lines("本文です。" + nl + block)
        check(f"「{block[:6]}」の前に空行を入れる", n == 1 and nl + nl in out, True)
    out, n = fb.add_blank_lines("1. 一つ目" + nl + "2. 二つ目")
    check("リストの行同士には入れない", n, 0)

    # 2. 装飾の途中で分かれた段落を戻す
    broken = "**失敗1: 土台を飛ばす。" + nl + nl + "**理由はこうです。"
    out, n = fb.rejoin_marks(broken)
    check("** が分かれた段落を戻す", n == 1 and out.count(nl + nl) == 0, True)
    ok = "普通の段落です。" + nl + nl + "次の段落です。"
    check("閉じている段落は触らない", fb.rejoin_marks(ok)[1], 0)

    # 3. 生HTMLの中の ** を <strong> にする（Markdownが処理しないため）
    out, n = fb.strong_in_html('<div class="caution-box">罰金は**100万円**です。</div>')
    check("生HTMLの ** を <strong> にする", n == 1 and "<strong>100万円</strong>" in out, True)
    check("地の文の ** は触らない", fb.strong_in_html("本文の**強調**です。")[1], 0)

    # 4. 分割側でも、装飾の内側では切らない（同じ壊れ方を作らない）
    body = nl.join(["---", "title: x", "---",
                    "あ" * 100 + "。**" + "い" * 100 + "。" + "う" * 100 + "**。"])
    after, _ = sp.process(body)
    for para in after.split(nl + nl):
        check("分けた各段落で ** が閉じている", para.count("**") % 2, 0)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "fix_block_breaks.py --write" in wf, True)


def test_rendered_html_is_checked():
    """出来上がったHTMLを見る検査が、ビルドの中で動くこと。

    これまでの検査は全部、原稿（Markdown）だけを見ていた。そのため
    「原稿は正しいが変換すると壊れる」崩れを長く見逃した。表がパイプ記号の
    まま出る・** がそのまま表示される・リンクが押せない、の3種。
    どれも記事の点数には出ず、読者の画面にだけ出る。
    """
    import tempfile
    sys.path.insert(0, str(ROOT / "scripts"))
    import md2html
    import render_check as rc

    def md2html_convert(src):
        return md2html.convert(src)[0]

    # ビルドが必ず通ること（単体スクリプトのままだと呼ばれずに終わる）
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("ビルドが描画検査を呼ぶ", "render_check.scan(" in b, True)

    # 実際に捕まえること。素通りする検査は無いのと同じ
    cases = {
        "強調記号がそのまま出ている": "<article><p>罰金は**100万円**です。</p></article>",
        "Markdownリンクが押せない形で出ている":
            "<article><p>詳細は[解説](/seo/x/)です。</p></article>",
        "表の区切り記号が本文に出ている":
            "<article><p>| 列A |" + chr(10) + "|:--|</p></article>",
        "altの無い画像がある": '<article><p><img src="a.png"></p></article>',
        "押せないリンクがある": '<article><p><a href="">文字</a></p></article>',
        "句点が続いている": "<article><p>そうです。。</p></article>",
    }
    d = Path(tempfile.mkdtemp())
    for i, (name, src) in enumerate(cases.items()):
        f = d / str(i) / "index.html"
        f.parent.mkdir(parents=True)
        f.write_text(src, encoding="utf-8")
        check(f"崩れを見つける: {name}", name in rc.scan([f]), True)

    # 正しいページを間違いと言わないこと
    f = d / "ok" / "index.html"
    f.parent.mkdir(parents=True)
    f.write_text('<article><p>罰金は<strong>100万円</strong>、詳細は'
                 '<a href="/seo/x/">解説</a>。</p>'
                 '<img src="a.png" alt="図"></article>', encoding="utf-8")
    check("正しいページを誤検出しない", dict(rc.scan([f])), {})

    # 配信の全方式が同じ検査を通ること。writerごとに書くと方式が増えたとき漏れる。
    # 実際 external-html と wordpress には検査が無く、表がパイプ記号のまま
    # 5本配信されていた
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    body = re.search(r"(?s)def main\(\):.*?if cfg\[.type.\] == .self-static.", src)
    check("配信前の検査が main にある（方式ごとではなく）",
          bool(body and "render_check.problems(" in body.group(0)), True)
    check("writerの中に個別の検査を残していない",
          "raw_markdown_left(" in src, False)

    # 表の列数が合わないと、Markdownは表として扱わず本文にそのまま出す
    n = chr(10)
    broken = md2html_convert("| A | B | C |" + n + "|:--|:--|" + n + "| 1 | 2 | 3 |")
    check("列数の合わない表を崩れとして見つける",
          any("表の区切り記号" in x[0] for x in rc.problems(broken)), True)
    good = md2html_convert("| A | B | C |" + n + "|:--|:--|:--|" + n + "| 1 | 2 | 3 |")
    check("列数の合う表は崩れと数えない", rc.problems(good), [])

    # コード例の中の記法は崩れではない（誤検出すると検査が信用されなくなる）
    f2 = d / "code" / "index.html"
    f2.parent.mkdir(parents=True)
    f2.write_text("<article><pre><code>**太字**の書き方</code></pre></article>",
                  encoding="utf-8")
    check("コード例は崩れと数えない", dict(rc.scan([f2])), {})


def test_import_has_no_side_effects():
    """読み込むだけで外へ出ていくスクリプトが無いこと。

    notify_indexnow.py は処理をモジュール直下に書いていたため、
    `import notify_indexnow` した瞬間にIndexNowへ送信していた。
    実際、検査のために読み込んだだけで136件のURLを送ってしまった。
    副作用は必ず main() の中に置き、__main__ ガードで囲う。
    """
    import ast
    print("\n■ 読み込みの副作用")
    OUT = ("urlopen", "urlretrieve", "post", "put", "get", "request", "run",
           "check_output", "call", "Popen", "write_text", "write_bytes", "unlink")
    ng = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        has_main = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == "main" for n in tree.body)
        if has_main and '__name__ == "__main__"' not in src \
                and "__name__ == '__main__'" not in src:
            ng.append(f"{p.name}: main() があるのに __main__ ガードが無い")
        # モジュール直下で外に出ていく呼び出しをしていないか
        for n in tree.body:
            if not isinstance(n, ast.Expr):
                continue
            for c in ast.walk(n):
                if isinstance(c, ast.Call):
                    f = c.func
                    name = f.attr if isinstance(f, ast.Attribute) else \
                        (f.id if isinstance(f, ast.Name) else "")
                    if name in OUT:
                        ng.append(f"{p.name}: 読み込み時に {name}() を呼んでいる")
    check("読み込むだけで動くスクリプトが無い", ng, [])

    # 実際に読み込んでも何も起きないこと（構文だけ見ても分からない）
    import importlib
    sys.path.insert(0, str(ROOT / "scripts"))
    broke = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        try:
            importlib.import_module(p.stem)
        except SystemExit:
            broke.append(f"{p.name}: 読み込みで終了した")
        except Exception as e:
            broke.append(f"{p.name}: {type(e).__name__}")
    check("全スクリプトが安全に読み込める", broke, [])

    # requirements.txtに無い外部ライブラリをモジュール直下でimportしていないか
    # （実行環境にたまたま入っていただけの依存は、入っていない環境で上のチェックが再現しない）
    import importlib.metadata
    dist_map = importlib.metadata.packages_distributions()
    req_names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            req_names.add(re.split(r"[<>=\[]", line)[0].strip().lower().replace("_", "-"))
    local_modules = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    missing_req = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for n in tree.body:
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module.split(".")[0]]
            for m in mods:
                if m in sys.stdlib_module_names or m in local_modules:
                    continue
                dists = {d.lower().replace("_", "-") for d in dist_map.get(m, [])}
                if dists and not (dists & req_names):
                    missing_req.append(f"{p.name}: {m} ({'/'.join(dists)}) がrequirements.txtに無い")
    check("外部importがrequirements.txtに宣言されている", missing_req, [])


def test_long_sentences_are_split():
    """長すぎる1文が、意味を変えずに分かれること。

    切ってよいのは「左がそれだけで文として成り立つ形」だけ。
    「〜によると、」「〜し、」で切ると主語と述語がねじれる。
    「が」は逆接とは限らず、前置きの「が」に「ただし」を足すと意味がずれる。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import split_sentences as ss
    nl = chr(10)

    long_ok = "あ" * 40 + "を運用しており、" + "い" * 40 + "という結果になりました。"
    out = ss.split_sentence(long_ok)
    check("連用中止法で分ける", out and "しています。" in out, True)

    reason = "あ" * 40 + "が公開されているため、" + "い" * 40 + "を先に確認します。"
    out = ss.split_sentence(reason)
    check("理由の「ため」を「そのため」で受け直す",
          out and "そのため、" in out, True)

    # 左が文にならない形では切らない
    for bad in ("によると、", "を使い、", "が必要なため、"):
        s = "あ" * 40 + bad + "い" * 40 + "です。"
        out = ss.split_sentence(s)
        if bad == "が必要なため、":
            continue          # 「ため」は受け直せるので対象
        check(f"「{bad}」では切らない", out, None)

    # 前置きの「が」には「ただし」を足さない
    preface = "あ" * 40 + "について解説していますが、" + "い" * 20 + "は対象外です。"
    check("前置きの「が」は切らない", ss.split_sentence(preface), None)

    # 装飾の内側では切らない
    deco = "あ" * 30 + "**" + "い" * 20 + "しており、" + "う" * 20 + "**" + "え" * 30 + "です。"
    out = ss.split_sentence(deco)
    check("装飾の内側では切らない", out is None or out.count("**") % 2 == 0, True)

    # 検算: 記録した書き換え以外は動いていない
    body = nl.join(["---", "title: x", "---", long_ok])
    after, n, edits = ss.process(body)
    check("分けた数を記録する", n, len(edits))
    check("検算が通る", ss.verify(body, after, edits), "")
    check("食い違いを見つける",
          bool(ss.verify(body, after + "余計な文字", edits)), True)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "split_sentences.py --write" in wf, True)


def test_rewrite_is_verified_and_reverted():
    """文章の判断を任せた直しが、必ず検算され、外れたら戻ること。

    auto_improve は、タイトルと検索意図の見直しを人へ回していた。
    判断そのものは機械に任せてよいが、**通してよいかを決めるのは機械側**でなければ
    ならない。検算が無い書き換えは、主張のずれた記事を静かに量産する。
    """
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("直しの工程がある", (ROOT / "scripts" / "auto_rewrite.py").is_file(), True)

    # 外れたら必ず元に戻す
    check("検算に外れたら元に戻す", 'git", "checkout", "--"' in src, True)
    check("戻したあとビルドし直す",
          src.count("build.py") >= 2, True)

    # 検算の中身。1つでも欠けると、その穴から壊れた記事が通る
    for name, key in (("数字を作らせない", "numbers("),
                      ("出典を消させない", "sources("),
                      ("狙う語を変えさせない", "狙う語が変わりました"),
                      ("タイトルの字数", "TITLE_MIN"),
                      ("警告を増やさせない", "警告が増えました"),
                      ("食い合いを作らせない", "kw_guard"),
                      ("ビルドを通す", "ビルドが通りません"),
                      ("他の記事に触らせない", "別の記事まで変わっています")):
        check(f"検算: {name}", key in src, True)

    # 台帳に残す（何をいつ直したか追えないと、戻す判断ができない）
    check("台帳に残す", "auto_fix.jsonl" in src, True)

    # 1回に触る本数を絞る（まとめて当てると原因が分からなくなる）
    m = re.search(r'"--limit", type=int, default=(\d+)', src)
    check("1回に触る本数を絞る", bool(m) and int(m.group(1)) <= 5, True)

    # 全権限を飛ばさない。使う道具を読み書きだけに絞る
    check("権限を全部は飛ばさない", "dangerously-skip-permissions" in src, False)
    check("使う道具を絞る", "--allowedTools" in src, True)

    # 対象を取りこぼさない（画面表示は8件で打ち切られる）
    sys.path.insert(0, str(ROOT / "scripts"))
    import auto_improve
    check("全件を返す口がある", hasattr(auto_improve, "human_items"), True)

    # 少ない表示回数の増減はノイズ。ここを根拠に記事を書き換えてはいけない
    import effect
    def act(before_imp, after_imp, pos=30.0):
        return effect.actions([{"slug": "x", "site": "ai-lab",
                                "before": (before_imp, 0, pos),
                                "after": (after_imp, 0, pos)}])
    check("表示1→0では書き換えない", act(1, 0), [])
    check("表示4→0では書き換えない", act(4, 0), [])
    check("表示15→2では書き換えない", act(15, 2), [])
    check("表示94→9なら見直す",
          [x["do"] for x in act(94, 9)], ["review"])
    check("下限は他の分岐と同じ値", effect.MIN_IMP, 20)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "auto_rewrite.py --write" in wf, True)
    # 検算が壊れたままエージェントを動かすと、悪い書き換えがそのまま公開される。
    # 先に自己診断を通し、落ちたら書き換えを飛ばす
    check("先に検算の自己診断を通す",
          wf.index("--selftest") < wf.index("auto_rewrite.py --write"), True)
    check("診断に落ちたら書き換えない",
          "steps.guard.outputs.ok == 'yes'" in wf, True)
    check("自己診断の口がある", "--selftest" in src, True)
    check("自己診断は必ず元に戻す", "finally:" in src, True)
    # 積み上がりの見直しより前に置く。後ろだと、当てた週は見直されないまま公開される
    check("見直しより前に置く",
          wf.index("auto_rewrite.py") < wf.index("auto_review.py --fix"), True)


def test_output_matches_source():
    """原稿に書いたものが、出力に同じ数だけ出ていること。

    症状を並べる検査は「こちらが知っている壊れ方」しか見つけられない。
    実際、表が生で出る・** がそのまま出る・リンクが押せない・段落が繋がる、の
    4種類が長期間だれにも気づかれずに公開されていた。どれも点数には出なかった。
    ここでは中身を見ず、塊の数だけを突き合わせる。知らない壊れ方でも数は合わなくなる。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import md2html
    import render_check as rc
    nl = chr(10)
    print(nl + "■ 原稿と出力の突き合わせ")

    def gap(src):
        return rc.structure_gap(src, "<article>" + md2html.convert(src)[0] + "</article>")

    # 実際に起きた4種類を、症状名を使わずに見つけられること
    check("列数の合わない表を見つける",
          bool(gap("| A | B | C |" + nl + "|:--|:--|" + nl + "| 1 | 2 | 3 |")), True)
    check("空行なしのリストを見つける",
          bool(gap("本文です。" + nl + "- 一つ目" + nl + "- 二つ目")), True)
    check("空行なしの表を見つける",
          bool(gap("本文です。" + nl + "| A | B |" + nl + "|:--|:--|" + nl + "| 1 | 2 |")), True)
    check("生HTML内のリンクを見つける",
          bool(gap('<div class="box">詳細は[解説](/seo/x/)です。</div>')), True)

    # 正しいものを間違いと言わない（誤検出すると検査が信用されなくなる）
    check("正しい表は素通り", gap("| A | B |" + nl + "|:--|:--|" + nl + "| 1 | 2 |"), [])
    check("正しいリストは素通り",
          gap("本文です。" + nl + nl + "- 一つ目" + nl + "- 二つ目"), [])
    check("コード例の中は数えない",
          gap("```" + nl + "| これは表ではない |" + nl + "```"), [])

    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("ビルドが突き合わせる", "structure_gap(" in b, True)


def test_inquiry_body_is_not_truncated():
    """届いた相談の本文が、途中で切れないこと。

    clean_() は件名や会社名のための関数で、改行を空白に潰して80字で切る。
    これを相談内容にも使っていたため、実際に届いた問い合わせが
    「インド人新卒採用支援サービスを…検索され」でちょうど80字で途切れた。
    メールだけでなく台帳にも切れたまま保存されており、続きは復元できない。

    本文には body_() を使う。改行を残し、送信側の上限（2000字）を超える値にする。
    """
    import re as _re
    print(chr(10) + "■ 問い合わせ本文の扱い")
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")

    check("本文用の関数がある", "function body_(" in gs, True)
    # 本文に clean_ を使っていないこと（ここが事故の原因だった）
    for field in ("d.message", "d.body", "d.message || d.body"):
        check(f"clean_({field}) を使っていない",
              f"clean_({field})" in gs, False)
    check("台帳へは body_ で書く", "body_(d.message || d.body)" in gs, True)
    check("メールへは body_ で出す", "body_(d.message)" in gs, True)

    # 上限が、送信側（lead.js）の上限より大きいこと。小さいとそこで切れる
    m = _re.search(r"function body_\(s\)[\s\S]*?slice\(0, *(\d+)\)", gs)
    js = (ROOT / "functions" / "api" / "lead.js").read_text(encoding="utf-8")
    m2 = _re.search(r"String\(v\)\.slice\(0, *(\d+)\)", js)
    gas_max = int(m.group(1)) if m else 0
    web_max = int(m2.group(1)) if m2 else 0
    check(f"上限が送信側（{web_max}字）を上回る", gas_max > web_max, True)

    # 改行を潰していないこと（段落が読めなくなる）
    body_fn = m.group(0) if m else ""
    check("改行を空白に潰していない",
          _re.search(r"replace\(/\[\r\n\]\+/g, *['\"] ['\"]\)", body_fn) is None, True)

    # 件名や会社名は従来どおり clean_（1行に収める必要がある）
    check("件名は clean_ のまま", "clean_(d.company)" in gs, True)


def test_articles_are_not_uniform():
    """記事の長さが1つの帯に固まっていないこと。

    CLAUDE.md は「全記事が同じ長さに揃うと、それ自体が量産の指紋になる」と
    書いているのに、実測では312本（92%）が5,000字台に固まっていた。
    depth も273本（81%）が standard のまま。仕組みはあるのに使われていなかった。
    原因は、執筆プロンプトに長さの指示が1行も無かったこと。

    透かし（SynthID）は関係ない。この仕組みは画像をPillowで描いており、
    AI画像生成を使っていないので透かし自体が存在しない。
    見られているのは「書き方が揃っていること」のほうである。
    """
    print(chr(10) + "■ 記事の均一さ")
    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("執筆プロンプトが長さを指示する", "depth:" in pr, True)
    for d in ("quick", "standard", "deep"):
        check(f"{d} の使いどころが書いてある", d in pr, True)
    check("水増しを禁じている", "水増し" in pr, True)
    check("冒頭の型を固定しないよう書いてある", "とは" in pr and "型を固定" in pr, True)

    ad = (ROOT / "scripts" / "daily_audit.py").read_text(encoding="utf-8")
    check("日次監査が偏りの中身まで出す", "最も多い帯" in ad, True)
    # ばらつきの数字だけでは、どれだけ固まっているか読み取れなかった
    check("1帯への集中を見ている", "share >= 0.5" in ad, True)


def test_facts_are_per_article():
    """一次情報が、記事ごとに違うものになること。

    会社の実績（3,200店舗）はどの記事に書いても同じ一文になる。
    実測では126本（37%）が同じ数字を載せていた。肩書きとしては正しいが、
    「その記事にしかない情報」にはならず、AI検索の引用先にも選ばれにくい。

    自サイトのGSC実測は記事ごとに違う。「この語が何位で、何回表示され、
    何回クリックされたか」は、ほかのどのサイトも書けない。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import facts
    print(chr(10) + "■ 記事ごとの一次情報")

    check("記事ごとの実測を出す口がある", hasattr(facts, "own_query_facts"), True)

    rows = [{"kw": "口コミ 返信 例文 医療", "pos": 8.7, "imp": 96, "clicks": 0, "ctr": 0.0},
            {"kw": "aio対策 自分で", "pos": 26.2, "imp": 28, "clicks": 1, "ctr": 3.6},
            {"kw": "原口優", "pos": 1.3, "imp": 36, "clicks": 4, "ctr": 11.1},
            {"kw": "少ない語", "pos": 5.0, "imp": 3, "clicks": 0, "ctr": 0.0}]
    import json as _j, tempfile
    d = Path(tempfile.mkdtemp())
    (d / "t.json").write_text(_j.dumps({"2026-09-17": rows}), encoding="utf-8")
    old = facts.RANKS
    facts.RANKS = d
    try:
        a = facts.own_query_facts("t", "口コミ 返信 例文 医療")
        b = facts.own_query_facts("t", "aio対策 自分で")
        check("語ごとに違う数字が出る",
              bool(a) and bool(b) and a[0]["claim"] != b[0]["claim"], True)
        # 上位なのにクリックが無い語は、自社の無力さではなく検索の性質として書く
        check("0クリックを自社の弱みとして書かない",
              "クリックは0回" not in a[0]["claim"], True)
        check("0クリックを検索の性質として説明する",
              "答えが済む" in a[0]["claim"], True)
        check("数字はそのまま出す", "96回" in a[0]["claim"] and "8.7位" in a[0]["claim"], True)
        check("出典と時点が付く",
              bool(a[0].get("source")) and bool(a[0].get("as_of")), True)
        # 表示が少ない語は偶然と区別できないので出さない
        check("表示が少ない語は出さない", facts.own_query_facts("t", "少ない語"), [])
        check("語が無ければ何も出さない", facts.own_query_facts("t", ""), [])
    finally:
        facts.RANKS = old

    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("プロンプトが記事ごとの数字を優先させる", "その記事にしかない数字" in pr, True)
    check("丸めを禁じている", "丸めたり" in pr, True)


def test_unindexed_pages_are_chased():
    """公開したのに検索に出ていないページを、放置しないこと。

    書いて配信したところで満足すると、載っていないページが溜まる。
    実測で、公開30日以上たっても28日間まったく表示されないページが19件あった。
    コーポレートは sitemap の40%（53件）が表示ゼロだった。

    拾う仕組み（index_status.py / reindex.py）は作られていたが、
    **どこからも呼ばれていなかった**。作っただけで動いていない道具は無いのと同じ。
    """
    print(chr(10) + "■ 未掲載ページの追跡")
    for f in ("index_status.py", "reindex.py"):
        check(f"{f} がある", (ROOT / "scripts" / f).is_file(), True)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週、登録状況を見て再通知する", "reindex.py" in wf, True)

    ad = (ROOT / "scripts" / "daily_audit.py").read_text(encoding="utf-8")
    check("日次監査が気づく", "def check_unseen" in ad, True)
    check("監査から呼ばれている", "check_unseen(todo)" in ad, True)
    # 30日未満は評価が定まっていないだけ。手を当てても意味がない
    check("30日を境にしている", "days < 30" in ad, True)
    # 記事は所属サイトでだけ数える（全サイトで照合すると1本を3回数える）
    check("所属サイトだけで数える", "find_category_owner" in ad, True)
    check("直し方を示す", "reindex.py" in ad, True)


def test_rate_claims_need_evidence():
    """割合を書くなら、母数と集計期間を必ず添えること。

    「採択率90%」だけでは、何社中何社か、いつからいつまでかが分からない。
    根拠を示さない割合は優良誤認になる（景品表示法）。
    人の注意に任せると、忙しいときに抜ける。登録の時点で機械が止める。
    """
    import json as _j, subprocess as _s, tempfile
    print(chr(10) + "■ 一次情報の登録条件")
    d = Path(tempfile.mkdtemp())

    def judge(obj):
        f = d / "f.json"
        f.write_text(_j.dumps(obj, ensure_ascii=False), encoding="utf-8")
        r = _s.run([sys.executable, str(ROOT / "scripts" / "add_fact.py"),
                    "--check", str(f)], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="ignore")
        return r.returncode == 0

    base = {"sites": ["subsidy"], "topic": ["補助金"],
            "source": "自社実績", "as_of": "2026-09"}
    check("母数も期間も無い割合は止める",
          judge({**base, "id": "x1", "claim": "当社の採択率は90%です"}), False)
    check("母数を本文に書いていなければ止める",
          judge({**base, "id": "x2", "claim": "当社の採択率は90.5%です",
                 "denominator": 42, "period": "2025-04〜2026-03"}), False)
    check("母数が小さすぎれば止める",
          judge({**base, "id": "x3", "denominator": 3, "period": "2026-01〜2026-09",
                 "claim": "2026年に支援した3社のうち3社が採択されました（採択率100%）"}), False)
    check("雛形のままは止める",
          judge({**base, "id": "x4", "claim": "＜例＞◯◯社を支援しました"}), False)
    check("数値が無ければ止める",
          judge({**base, "id": "x5", "claim": "多くの企業を支援してきました"}), False)
    check("母数と期間を本文に書いてあれば通す",
          judge({**base, "id": "x6", "denominator": 42, "period": "2025-04〜2026-03",
                 "claim": "2025年4月〜2026年3月に支援した42社のうち38社が採択されました"
                          "（採択率90.5%）"}), True)
    # 実数（割合でない）は母数を求めない
    check("割合でなければ母数は求めない",
          judge({**base, "id": "x7", "claim": "2026年9月までに42社の申請を支援しました"}), True)


def test_submissions_are_not_double_counted():
    """送信の数を、二重に数えないこと。

    site.js は1回の送信で form_submit と lead_capture の両方を発火させる。
    両方を足していたため「送信10件」と出ていたが、実際は4件だった
    （form_submit 4 + lead_capture 6）。転換率を2倍以上に見せてしまう。

    問い合わせと購読も分ける。同じ箱に入れると、商談につながる数が分からない。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import funnel
    print(chr(10) + "■ 送信数の数え方")
    names = dict(funnel.STEPS)["送信した"]
    check("lead_capture を送信に数えない", "lead_capture" in names, False)
    check("form_submit は数える", "form_submit" in names, True)
    # 同じ送信で飛ぶイベントを2つ以上足していないか
    fired_together = {"form_submit", "lead_capture", "lead_newsletter"}
    check("同時に飛ぶイベントを重ねて数えない",
          len(fired_together & set(names)) <= 1, True)

    routes = dict(funnel.LEAD_ROUTES)
    check("問い合わせと購読を分ける口がある",
          "問い合わせ・相談" in routes and "ニュースレター購読" in routes, True)
    check("購読を問い合わせに含めない",
          "newsletter" in routes["問い合わせ・相談"], False)

    src = (ROOT / "scripts" / "funnel.py").read_text(encoding="utf-8")
    # 内訳が出せないときは、黙らずに何をすればよいかを出す
    check("設定が要るときに案内する", "カスタムディメンションを作成" in src, True)
    check("取れなくても落ちない", "except Exception as e:" in src, True)


def test_boost_finds_link_sources():
    """押し上げるページに、リンク元を見つけられること。

    検索語を空白で割るだけだと、空白の無い日本語の語が1つの塊のまま残る。
    実測で「aiかんたん集客」は分割されず、その文字列を3回以上含む記事が
    0本だったため、11.3位・表示88回のページに1本もリンクを送れなかった。
    「0本足しました」と表示されるだけで、原因は何も示されない。

    主力語の判定にも漏れがあった。サイト名が「AI集客ラボ」で主力商材が
    AIを使った集客そのものなのに、判定に ai集客 が入っていなかった。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import priority_boost as P
    import re as _re
    print(chr(10) + "■ 押し上げのリンク元探し")

    # サイトの主力語が判定に入っていること
    pat = _re.compile(P.MAIN_PATTERN["ai-lab"], _re.I)
    for kw in ("aiかんたん集客", "ai集客", "aio対策", "meo 病院", "seo 対策"):
        check(f"主力語として拾う: {kw}", bool(pat.search(kw)), True)
    check("無関係な語は拾わない", bool(pat.search("確定申告 やり方")), False)

    # 空白の無い語からも、リンク元を探せる語を作れること
    nl2 = chr(10)
    texts = {"x": nl2.join(["---", "title: AI集客とは？かんたんに始める方法",
                            "category: ai-marketing", "---", "本文"])}
    w = P.topic_words("x", [("aiかんたん集客", 11.3, 88)], texts)
    check("空白の無い語でも語を作れる", len(w) >= 2, True)
    check("タイトルからも語を取る", any("集客" in x for x in w), True)
    check("1文字の語は使わない", all(len(x) >= 2 for x in w), True)
    check("語を取りすぎない（無関係な記事に当たる）", len(w) <= 8, True)


def test_rank_data_is_verified():
    """順位改善が使う数字が、別の取り方と一致すること。

    GSCは見る次元で数字が変わる。query次元は検索数の少ない語を返さないため、
    実測で page次元50クリックが query次元では0と出た。この食い違いに
    気づかず「クリックが出ていない」と判断し、誤った結論を重ねた。

    同じページが「末尾スラッシュあり/なし」で2行に分かれることもあり、
    上書きすると表示が消える（実測で2ページ・37表示が消えた）。

    取り方は rank_up.fetch() の1か所に固定し、page次元を正とする。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import rank_up as R
    print(chr(10) + "■ 順位データの取り方")

    src = (ROOT / "scripts" / "rank_up.py").read_text(encoding="utf-8")
    check("取得の入口が1つ", src.count("def fetch(") == 1, True)
    check("page次元を使う", '["page"], 25000' in src, True)
    check("URLを鍵にする（slugで潰さない）", 'pages[url] =' in src, True)
    check("末尾スラッシュの重複を合算する", 'd["urls"] += 1' in src, True)
    check("表示の少ないページを対象にしない", R.MIN_IMP >= 20, True)
    # 1つの帯だけ見ても全体は動かない。実測で11〜20位は全323ページの22%だった
    names = [b[2] for b in R.BANDS]
    check("全順位帯を見る", len(R.BANDS), 5)
    for n in ("1〜3位", "4〜10位", "11〜20位", "21〜50位", "51位以下"):
        check(f"帯がある: {n}", n in names, True)
    # 帯ごとに違う手を当てる（1ページ目にいるページへリンクを足しても効かない）
    check("帯ごとにやることが違う", len({b[3] for b in R.BANDS}), 5)
    check("順位相応のクリック率を持っている", R.expected_ctr(5.0) > R.expected_ctr(15.0), True)
    check("効く順に渡す口がある", hasattr(R, "human_items"), True)

    # 直した記録を残し、効果を測れること
    check("記録を残す", "def save_log" in src, True)
    check("前後を比べる口がある", "--effect" in src, True)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("毎週走る", "rank_up.py --write" in wf, True)
    check("効果を先に記録する", wf.index("--effect") < wf.index("rank_up.py --write"), True)


def test_measurement_pitfalls_are_documented():
    """間違えやすい測り方が、手順として残っていること。

    1つのセッションで9回、誤った数字を報告した。どれも30秒の再確認で防げた。
    共通していたのは「自分の測り方が正しい」と仮定したこと。
    対象の性質ではなく、道具の癖を見ていた。

    人の注意に任せると忘れるので、手順を文書に残し、検算の道具を用意する。
    """
    print(chr(10) + "■ 測り方の落とし穴")
    md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    check("数字を出す前の手順がある", "数字を出す前に必ず通す手順" in md, True)
    for k in ("別の方法で同じ数字を出す", "内訳に分ける",
              "逆を探す", "前提を口に出して確かめる"):
        check(f"手順に含まれる: {k}", k in md, True)

    # 実際に踏んだ落とし穴が、名指しで残っていること
    for k in ("query次元", "末尾スラッシュ", "指名検索", "lead_capture"):
        check(f"落とし穴が明記されている: {k}", k in md, True)

    check("検算の道具がある", (ROOT / "scripts" / "data_sanity.py").is_file(), True)
    ds = (ROOT / "scripts" / "data_sanity.py").read_text(encoding="utf-8")
    for name, key in (("二重計上", "check_double_count"), ("無効な流入", "check_invalid"),
                      ("GA4とGSCの食い違い", "check_ga_vs_gsc"),
                      ("指名検索の割合", "check_brand_share")):
        check(f"検算する: {name}", key in ds, True)


def test_built_tools_actually_run():
    """作った道具が、実際に動いていること。

    scripts に96本あるうち22本が、ワークフローからも他スクリプトからも
    呼ばれていなかった。index_status.py と reindex.py はその典型で、
    未登録ページを拾う仕組みがあるのに一度も走っていなかった。
    作っただけで動いていない道具は、無いのと同じ。

    手で使う道具（営業資料・クライアント導入など）は定期実行しなくてよい。
    ここでは「毎週走るべきもの」だけを固定する。
    """
    print(chr(10) + "■ 作った道具が動いているか")
    wf = " ".join(p.read_text(encoding="utf-8", errors="replace")
                  for p in (ROOT / ".github" / "workflows").glob("*.yml"))
    # 読むだけの検査は findings.py がまとめて呼ぶ。YAMLに名前は出ないため、
    # その一覧も「毎週走るもの」として数える（間接呼び出しを追わないと、
    # まとめ役に移しただけで「動いていない」と誤検出する）
    check("まとめ役が毎週走る", "findings.py" in wf, True)
    import findings
    wf += " " + " ".join(sc for _, sc, _ in findings.CHECKS)
    for name, why in (("reindex.py", "登録されていないページを拾う"),
                      ("rank_up.py", "順位を上げる"),
                      ("anchor_audit.py", "リンクの文言に狙う語を入れる"),
                      ("aio_check.py", "AIO基盤のずれを見る"),
                      ("nap_check.py", "会社表記のずれを見る"),
                      ("data_sanity.py", "計測が壊れていないか")):
        check(f"毎週走る: {why}", name in wf, True)

    # 順序が逆だと、入れた狙う語が短縮で落ちる
    check("狙う語を入れてから詰める",
          wf.index("anchor_audit.py") < wf.index("shorten_anchors.py"), True)


def test_quality_fixes_run_before_publishing():
    """機械で直せる崩れは、公開する前に直すこと。

    記事は1日6本公開されるのに、崩れを直す工程は週1回しか走っていなかった。
    最大6日間そのまま公開される計算で、実測でも直近7日の記事に1本残っていた。
    読者が崩れたページを見てから直しても遅い。

    どの工程も地の文を変えず、検算に外れたら書き込まない作りになっている。
    公開前に置いても壊れない。
    """
    print(chr(10) + "■ 公開前の品質修正")
    for f in ("pipeline-multi.yml", "pipeline.yml"):
        wf = (ROOT / ".github" / "workflows" / f).read_text(encoding="utf-8")
        for name, label in (("fix_block_breaks.py", "段落の崩れ"),
                            ("split_paragraphs.py", "長すぎる段落"),
                            ("split_sentences.py", "長すぎる1文"),
                            ("shorten_anchors.py", "長すぎるアンカー"),
                            ("anchor_audit.py", "アンカーに狙う語")):
            check(f"{f} で公開前に直す: {label}", name in wf, True)
        # ビルド（＝公開物の生成）より前でなければ意味がない
        check(f"{f}: ビルドより前に直す",
              wf.index("fix_block_breaks.py") < wf.rindex("python scripts/build.py"), True)
        # 狙う語を入れてから詰める（逆だと語が落ちる）
        check(f"{f}: 狙う語を入れてから詰める",
              wf.index("anchor_audit.py") < wf.index("shorten_anchors.py"), True)


def test_findings_judges_by_marker_not_exit_code():
    """「見つかった」と「壊れた」を、終了コードで混同しないこと。

    auto_review は検出だけで終了コード1を返していた。CIのログでは
    本当に落ちたときと区別がつかず、正常な検出を不具合と読み違えた。
    判定は印（*_OK=）で行い、終了コードは検査が動いたかだけに使う。
    """
    import findings
    print("\n■ 検出と故障の見分け")
    cases = [
        ("見つかった（終了コードは0）", "NAP_OK=no", 0, "要対応"),
        ("見つからなかった", "NAP_OK=yes", 0, "問題なし"),
        ("印が故障より優先される", "AIO_OK=no", 1, "要対応"),
        ("印が無ければ終了コードを見る", "なにも出ていません", 1, "要対応"),
        ("印が無く終了コードも0", "なにも出ていません", 0, "問題なし"),
        ("検査が動かない", "（起動できません）", 127, "動かせず"),
    ]
    for name, text, rc, want in cases:
        check(name, findings.judge(text, rc), want)

    # 検査対象のスクリプトが実在すること（名前を変えたら気づける）
    for label, script, _ in findings.CHECKS:
        check("検査が実在: " + label, (ROOT / "scripts" / script).exists(), True)


def test_detection_scripts_do_not_fail_the_run():
    """検出だけのスクリプトが、終了コード1で止めないこと。

    例外は nap_check と deploy_check（人が手を動かすまで消えない問題）。
    """
    print("\n■ 検出＝0 の規約")
    src = (ROOT / "scripts" / "auto_review.py").read_text(encoding="utf-8")
    check("auto_review が印を出す", "REVIEW_OK=" in src, True)
    check("auto_review の検出が return 1 でない",
          'print("REVIEW_OK=no")\n        return 0' in src, True)
    src = (ROOT / "scripts" / "data_sanity.py").read_text(encoding="utf-8")
    check("data_sanity が印を出す", "SANITY_OK=" in src, True)


def test_notify_does_not_send_junk():
    """中身の無い通知を、本物の宛先に送らないこと。

    .env に RESEND_API_KEY と LEAD_TO_EMAIL があるため、手元での動作確認が
    info.ai へ本物のメールを出していた。実際に届いたのは2通:
      - 「（メッセージなし）」… 引数なしで呼んだもの
      - 「$icon …」        … 呼び出し側の引用符が壊れ、変数が展開されなかったもの
    通知は人の注意を使う。中身の無いものを送ると、次から読まれなくなる。
    """
    import notify_slack as N
    print("\n■ 送ってはいけない通知")
    check("空は送らない", bool(N.unsendable("")), True)
    check("空白だけも送らない", bool(N.unsendable("   \n  ")), True)
    check("未展開の変数は送らない", bool(N.unsendable("$icon 週次最適化: success")), True)
    check("Actionsの式も送らない", bool(N.unsendable("${{ job.status }}")), True)
    check("正常な本文は送れる", N.unsendable("✅ 記事パイプライン: success"), "")
    # 金額の $ を誤って弾かないこと（先頭でなければ通す）
    check("本文中のドルは弾かない", N.unsendable("月額 $99 のプランに変更"), "")

    src = (ROOT / "scripts" / "notify_slack.py").read_text(encoding="utf-8")
    check("手元では送らない歯止めがある", "GITHUB_ACTIONS" in src, True)


def test_routine_success_is_not_emailed():
    """うまくいっただけの回を、メールで送らないこと。

    届けるのは4つだけ: 問い合わせ / 異常のアラート / 月次レポート /
    変えたほうが良い点。1日2〜3通の成功報告が届くと、本当に見てほしい回が
    埋もれる。定時の工程は --routine を付けて呼び、知らせることがある回だけ送る。
    """
    import notify_slack as N
    print(chr(10) + "■ 定時の報告を送らない")
    ok = "✅ 記事パイプライン [ai-lab]: success" + chr(10) + "publish(ai-lab)"
    check("成功だけの回は送らない", N.worth_sending(ok, True), False)
    check("--routine が無ければ送る", N.worth_sending(ok, False), True)
    check("失敗は送る",
          N.worth_sending("🚨 記事パイプライン: failure", True), True)
    check("要対応があれば送る",
          N.worth_sending("✅ 週次最適化: success" + chr(10) + "要対応: 会社表記のゆれ", True), True)
    check("検査がすべてOKなら送らない",
          N.worth_sending("🔧 週次最適化: success" + chr(10) + "検査4件すべて問題なし", True), False)
    check("公開が止まっていれば送る",
          N.worth_sending("✅ パイプライン: success" + chr(10) + "BLOCKED記事あり", True), True)

    # 定時の工程が --routine を付けて呼んでいること（付け忘れると元に戻る）
    wfs = {p.name: p.read_text(encoding="utf-8", errors="replace")
           for p in (ROOT / ".github" / "workflows").glob("*.yml")}
    for name in ("pipeline-multi.yml", "pipeline.yml", "weekly-optimize.yml",
                 "digest.yml", "monthly-report.yml"):
        src = wfs.get(name, "")
        if "notify_slack.py" not in src:
            continue
        check(f"{name} が定時の報告を絞っている",
              "notify_slack.py --routine" in src, True)

    # 問い合わせは Apps Script が直接送るため、この絞り込みを通らない
    gas = " ".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in (ROOT / "automation" / "gas").glob("*.gs"))
    check("問い合わせは別経路で届く", "MailApp.sendEmail" in gas, True)


def test_every_site_gets_articles():
    """サイトを増やしたとき、どのサイトも0本にならないこと。

    日次は6つの時刻枠に 0/1/2 を直接書いていたため、4社目以降は一度も
    選ばれず記事が1本も書かれなかった。サイトを足しても静かに無視される。
    枠の番号をサイト数で割った余りにすると、全社へ行き渡る。
    ただし余りだけだと1社のとき同じサイトに6回回るため、1社2本の上限もかける。
    """
    print(chr(10) + "■ サイト数ごとの記事の割り当て")
    SLOTS = 20                      # cron の数（2本 × 10社）

    def assign(n):
        out = {}
        for slot in range(SLOTS):
            if slot >= n * 2:       # 1サイト2本まで
                continue
            i = slot % n
            out[i] = out.get(i, 0) + 1
        return out

    # 10社までは、どの社も1日2本ずつ受け取れること
    for n in (1, 2, 3, 5, 8, 10):
        got = assign(n)
        zero = [i for i in range(n) if got.get(i, 0) == 0]
        print("   %2d社 → 合計%2d本 / 1社あたり %d〜%d本"
              % (n, sum(got.values()), min(got.values()), max(got.values())))
        check("%d社で全サイトに記事が回る" % n, zero, [])
        check("%d社は全社2本ずつ" % n, (min(got.values()), max(got.values())), (2, 2))
        check("%d社の合計本数" % n, sum(got.values()), n * 2)

    # 上限を超えても0本の社は出さない（本数が減るだけ）。そのうえで知らせる
    over = assign(11)
    print("   11社 → 合計%d本 / 1社あたり %d〜%d本（上限超え）"
          % (sum(over.values()), min(over.values()), max(over.values())))
    check("11社でも0本の社は出ない", [i for i in range(11) if over.get(i, 0) == 0], [])

    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(
        encoding="utf-8", errors="replace")
    # 直書きに戻ると4社目が静かに消えるため、余りで選んでいることを固定する
    check("余りでサイトを選んでいる", "slot % N" in wf, True)
    check("1サイト2本の上限がある", "N * 2" in wf, True)
    check("枠が20ある（10社ぶん）", wf.count("* * *\"") >= 20, True)
    # 10社を超えたら、実行のたびに知らせる（黙って本数が減ると気づけない）
    check("10社超をエラーで知らせる", '[ "$N" -gt 10 ]' in wf, True)
    check("別リポジトリへ分けるよう示す", "別リポジトリに分けて" in wf, True)


def test_intake_sheets_are_not_published():
    """ヒアリングシートがリポジトリに入らないこと。

    シートには会社名・住所・電話・担当者のメールが入る。このリポジトリは
    public なので、置いたまま commit すると誰でも読める。取り込みは手元で
    実行し、生成された sites/*.json だけを commit する。
    """
    import subprocess
    print(chr(10) + "■ ヒアリングシートの扱い")
    for name in ("intake/A社.xlsx", "intake/done/A社.xlsx", "intake/todo/A社.xlsx"):
        r = subprocess.run(["git", "check-ignore", "-q", name],
                           cwd=str(ROOT), capture_output=True)
        check(f"{name} は公開されない", r.returncode == 0, True)

    # 置き場の説明だけは残す（フォルダが消えると使い方が分からなくなる）
    check("置き場の説明がある", (ROOT / "intake" / "README.md").is_file(), True)

    src = (ROOT / "scripts" / "intake_watch.py").read_text(encoding="utf-8")
    # 不備のあるシートを通すと、どのサイトでも書ける記事が量産される
    check("不備があれば登録しない", "intake/todo/ へ移しました" in src, True)
    # 上限を超えて受け入れると、記事の枠が足りず全社の本数が減る
    check("10社の上限で止める", "MAX_SITES = 10" in src, True)


def test_kw_plan_keeps_only_buyers():
    """計画の一新で、関連しない語・見込み客でない語が入らないこと。

    ラッコのLSIは「経理代行 求人」「記帳代行 儲かる」を重要度highで返す。
    検索している人は顧客ではなく求職者・副業者で、記事にしても問い合わせに
    ならない。担当領域の条件（kw_discover と同じ）に加えて、ここで落とす。
    一新は非破壊で、台帳の「未着手」だけを対象外にし、公開済み・執筆中は触らない。
    """
    import kw_plan
    import kw_intent
    print(chr(10) + "■ 計画の一新で入れてよい語")
    S = {"own_terms": ("経理", "記帳", "請求書"), "domain_terms": ("経理", "記帳", "費用", "相場"),
         "ng_terms": ("aio",), "industries": ["経理"], "intents": ["経理代行 費用"]}
    corpus, arts, owned, picked = [], [], [], []

    def ok(kw, vol=100):
        return kw_plan.relevant({"kw": kw, "vol": vol, "imp": 0}, S, corpus, arts, owned, picked)

    check("見込み客の語は通す", ok("経理代行 費用 相場"), "")
    check("求人は落とす", ok("経理代行 求人"), "見込み客でない")
    check("副業は落とす", ok("記帳代行 副業 在宅"), "見込み客でない")
    check("儲かるは落とす", ok("記帳代行 儲かる"), "見込み客でない")
    # 他社製品の指名検索。「請求書freee」を書いても経理BPOの相談には来ない
    check("他社製品名は落とす（freee）", ok("請求書freee"), "他社名")
    check("他社製品名は落とす（マネーフォワード）", ok("請求書マネーフォワード 使い方"), "他社名")
    check("他社サービス名は落とす（ドットコム）", ok("記帳代行ドットコム"), "他社名")
    check("他サイトの領域語は落とす", ok("経理 aio対策"), "除外語")
    check("領域語の無い語は落とす", ok("ホームページ 作成 費用"), "領域語なし")
    # 部分一致の罠。「日記帳」は「記帳」ではなく、「給付金請求書」は「請求書」ではない
    check("別の語の一部は落とす（日記帳）", ok("おすすめ 日記帳"), "領域語なし")
    check("別の語の一部は落とす（給付金請求書）", ok("年金生活者支援給付金請求書"), "領域語なし")
    check("番号を調べるだけの語は落とす", ok("適格請求書発行事業者登録番号"), "領域語なし")
    check("先頭一致は通す（請求書の封筒の書き方）", ok("請求書の封筒の書き方"), "")
    check("設定にある複合語は通す（経理代行）", ok("経理代行 相場"), "")
    subs = {"own_terms": ("補助金", "申請"), "domain_terms": ("補助金",), "ng_terms": (),
            "industries": ["運送業"], "intents": ["小規模事業者持続化補助金", "申請 代行"]}
    check("設定にある複合語は通す（〜補助金）",
          kw_plan.relevant({"kw": "小規模事業者持続化補助金 運送業", "vol": 50, "imp": 0}, subs, corpus, arts, owned, picked), "")
    # 業種はサブジェクトであって領域ではない。業種名だけでは通さない
    lab = {"own_terms": ("aio", "meo", "集客"), "domain_terms": ("aio",), "ng_terms": (),
           "industries": ["リフォーム", "飲食店"], "intents": ["AIO対策 失敗"]}
    def lab_ok(kw):
        return kw_plan.relevant({"kw": kw, "vol": 5000, "imp": 0}, lab, corpus, arts, owned, picked)
    check("業種名だけの語は落とす（リフォーム キッチン 費用）", lab_ok("リフォーム キッチン 費用"), "領域語なし")
    check("業種名だけの語は落とす（飲食店 近くの）", lab_ok("飲食店 近くの"), "領域語なし")
    check("業種×領域語は通す（リフォーム meo 対策）", lab_ok("リフォーム meo 対策"), "")
    lab2 = dict(lab, own_terms=("aio", "meo", "口コミ"))
    def lab2_ok(kw):
        return kw_plan.relevant({"kw": kw, "vol": 5000, "imp": 0}, lab2, corpus, arts, owned, picked)
    check("患者の評判検索は落とす（クリニック 口コミ）", lab2_ok("レジーナ クリニック 口コミ"), "領域語なし")
    check("事業者側の口コミは通す（口コミ 返信）", lab2_ok("クリニック 口コミ 返信 例文"), "")
    check("領域語を含む複合意図は通す（aio対策 失敗）", lab_ok("工務店 aio対策 失敗"), "")
    # 業種に掛ける領域語は設定で明示できる。無ければ owns の先頭
    check("core があればそれを使う",
          kw_plan.core_terms({"cfg": {"kw_seeds": {"core": ["集客", "MEO"]}}, "own_terms": ("aio", "llmo")}),
          ["集客", "meo"])
    check("core が無ければ owns の先頭",
          kw_plan.core_terms({"cfg": {}, "own_terms": ("aio", "llmo", "seo", "meo", "x")}),
          ["aio", "llmo", "seo", "meo"])
    check("買い手の意図（申請 代行）が上限内に残る", "申請 代行" in kw_plan.intents_for(
        {"intents": ["申請 代行"] + ["意図%d" % i for i in range(30)]}), True)
    check("検索数も表示も無い語は落とす", ok("経理 記帳 手順", vol=None), "検索数が少ない")
    check("検索数が無くても表示があれば通す",
          kw_plan.relevant({"kw": "経理 記帳 手順", "vol": None, "imp": 30}, S, corpus, arts, owned, picked), "")

    # 語順・助詞が違うだけの語は同じ検索。別枠で採ると採用枠を食い合う
    check("語順違いは同じ語", kw_plan.same("請求書 書き方 封筒", "請求書 封筒 書き方"), True)
    check("助詞の有無も同じ語", kw_plan.same("請求書の封筒の書き方", "請求書 封筒 書き方"), True)
    check("空白なし・助詞ありも同じ語", kw_plan.same("請求書封筒書き方", "請求書の書き方 封筒"), True)
    check("違う語は別", kw_plan.same("経理代行 費用", "記帳代行 副業"), False)
    # 優先業種（月1件の成約で費用が回収できる業種）は点が上がり、枠も厚い
    base = kw_plan.score({"kw": "美容室 meo 対策", "vol": 100, "kd": 30, "subject": "美容室"}, ["クリニック"])
    top = kw_plan.score({"kw": "クリニック meo 対策", "vol": 100, "kd": 30, "subject": "クリニック"}, ["クリニック"])
    check("優先業種の語に加点される", round(top - base, 2), kw_plan.PRIORITY_BONUS)
    check("優先業種の枠は他業種より厚い", kw_plan.PER_PRIORITY > kw_plan.PER_SUBJECT, True)
    check("ai-lab の優先業種が設定にある",
          set(kw_plan.priority_subjects({"cfg": __import__("json").load(open(ROOT / "sites" / "ai-lab.json", encoding="utf-8"))}))
          >= {"クリニック", "不動産", "リフォーム"}, True)
    check("補助金の優先が個人事業主と中小企業",
          set(kw_plan.priority_subjects({"cfg": __import__("json").load(open(ROOT / "sites" / "subsidy.json", encoding="utf-8"))})),
          {"個人事業主", "中小企業"})

    # 買い手の語は、検索数が少なくても上に来ること
    buyer = kw_plan.score({"kw": "経理代行 費用 相場", "vol": 210, "kd": 31})
    diy = kw_plan.score({"kw": "請求書 封筒 書き方", "vol": 5400, "kd": 33})
    check("外注を考える語が、自分でやる語より上", buyer > diy, True)

    # ルール: 課金の前に必ず見積もり、予算内でだけ取得する（手で走らせても同じ）
    src_plan = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("課金の前に見積もる", "if not budget_ok(S) and not DRY" in src_plan, True)
    import rakko as _rk
    S_est = {"cfg": {"kw_seeds": {"core": ["集客"]}}, "own_terms": ("aio",),
             "industries": ["クリニック", "歯科医院"], "intents": []}
    check("見積もりは問い合わせ数×1.5＋一括15", kw_plan.estimate(S_est), 2 * 1.5 + 15)
    # 一括調査でSEO難易度を取ると1語0.75で、500語なら375になる（今日の主因）。取らない
    check("一括調査で難易度を取らない", '"seoDifficulty": False' in src_plan and '"seoDifficulty": True' not in src_plan, True)
    saved_ms, saved_mb = _rk.month_spent, _rk.MONTHLY_BUDGET
    try:
        _rk.month_spent, _rk.MONTHLY_BUDGET = (lambda month=None: 995.0), 1000
        check("月の目安を超えるなら取得しない", kw_plan.budget_ok(S_est), False)
        _rk.month_spent = lambda month=None: 0.0
        check("予算内なら取得する", kw_plan.budget_ok(S_est), True)
    finally:
        _rk.month_spent, _rk.MONTHLY_BUDGET = saved_ms, saved_mb
    wf_m = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8", errors="replace")
    check("月次は dry-run を先に記録してから本番", wf_m.index("--dry-run") < wf_m.index("--if-needed --replace"), True)
    src_disc = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("週次補充も月の目安を見る", "rakko.month_spent() > rakko.MONTHLY_BUDGET" in src_disc, True)

    # 一括調査に送るのは価値の高い語だけ、1回ぶんまで（1万件を20回送って300クレジット払った）
    many = [{"kw": "補助金 その%d" % i} for i in range(700)] \
         + [{"kw": "補助金 申請 代行 費用"}, {"kw": "補助金 不採択 理由"}, {"kw": "補助金 とは", "imp": 30}]
    sel = kw_plan.worth_lookup(many)
    check("価値の無い語は一括調査に送らない", len(sel) <= kw_plan.LOOKUP_MAX and all(
        c.get("imp") or kw_plan.BUYER.search(c["kw"]) or kw_intent.score(c["kw"])[0] >= 2 for c in sel), True)
    check("買い手の語が先頭に来る", sel[0]["kw"], "補助金 申請 代行 費用")

    # 検索数を取る前に、安い条件で落とす（1万件を一括登録して500エラーになった）
    check("事前選別: 見込み客でない語", kw_plan.cheap_reject({"kw": "経理代行 求人"}, S), "見込み客でない")
    check("事前選別: 通る語", kw_plan.cheap_reject({"kw": "経理代行 費用 相場"}, S), "")
    check("一括登録は500件ずつ", [len(c) for c in kw_plan.chunks(list(range(1201)), kw_plan.BULK)], [500, 500, 201])

    # ラッコの 502/503/504 は数分続く。1回で諦めると計画が半分で止まる
    import io as _io, urllib.error, rakko
    calls = {"n": 0}
    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, _io.BytesIO(b"<html>502</html>"))
        return _io.BytesIO(b'{"result":true,"data":{"ok":1}}')
    saved = (rakko.urllib.request.urlopen, rakko.api_key, rakko.RETRY_WAIT, rakko._OUT_OF_CREDIT)
    rakko.urllib.request.urlopen, rakko.api_key, rakko.RETRY_WAIT = flaky, (lambda: "k"), (0, 0, 0)
    # 本物のキャッシュに触らない（前回のテストの応答が残っていると呼び出し回数が0になる）
    import tempfile, pathlib
    saved_cache = rakko.CACHE_DIR
    rakko.CACHE_DIR = pathlib.Path(tempfile.mkdtemp())
    try:
        r = rakko.call("/v1/x", {"a": 1})
        check("5xx は待ってやり直す", (r or {}).get("data"), {"ok": 1})
        check("やり直しの回数", calls["n"], 3)
        # 自動課金だと尽きずに請求が伸びる。上限に達したら以降は呼ばない
        def paid(req, timeout=0):
            return _io.BytesIO(b'{"result":true,"meta":{"consumedCredit":1.5},"data":{}}')
        rakko.urllib.request.urlopen = paid
        rakko.CONSUMED, rakko.BUDGET = 0.0, 3.0
        # 問い合わせを変える（同じ内容はキャッシュから返って課金されないため）
        got = [rakko.call("/v1/x", {"i": i}) is not None for i in range(4)]
        check("上限まで呼べる（1.5×2=3.0）", got[:2], [True, True])
        check("上限に達したら止まる", got[2:], [False, False])
        check("消費を数えている", rakko.spent(), 3.0)
        # 同じ問い合わせは期限内なら課金なしで返す。条件の調整で取り直して約1,000クレジット無駄にした
        rakko.CACHE_DIR = pathlib.Path(tempfile.mkdtemp())
        rakko.CONSUMED, rakko.BUDGET = 0.0, None
        hits = {"n": 0}
        def counted(req, timeout=0):
            hits["n"] += 1
            return _io.BytesIO(b'{"result":true,"meta":{"consumedCredit":1.5},"data":{"items":[1]}}')
        rakko.urllib.request.urlopen = counted
        a = rakko.call("/v1/suggest-keywords", {"keyword": "x"})
        b = rakko.call("/v1/suggest-keywords", {"keyword": "x"})
        check("同じ問い合わせは1回しか課金しない", (hits["n"], rakko.spent()), (1, 1.5))
        check("2回目も同じ中身が返る", a == b, True)
        rakko.call("/v1/search-volume", {"keywords": ["x"]}); rakko.call("/v1/search-volume", {"keywords": ["x"]})
        check("一括調査の登録は残さない（毎回別物）", hits["n"], 3)
    finally:
        rakko.urllib.request.urlopen, rakko.api_key, rakko.RETRY_WAIT, rakko._OUT_OF_CREDIT = saved
        rakko.CONSUMED, rakko.BUDGET = 0.0, None

    # 管制塔の一時的な404も待ってやり直す。取り下げ直後の追加で当たると未着手が0件で残る
    import hub_client
    hits = {"n": 0}
    def flaky_hub(req, timeout=0):
        hits["n"] += 1
        if hits["n"] < 3:
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, _io.BytesIO(b""))
        return _io.BytesIO(b'{"ok":true}')
    saved2 = (hub_client.urllib.request.urlopen, hub_client.RETRY_WAIT)
    hub_client.urllib.request.urlopen, hub_client.RETRY_WAIT = flaky_hub, (0, 0, 0)
    try:
        with hub_client._open(hub_client.urllib.request.Request("https://example.invalid/")) as r:
            check("管制塔の404は待ってやり直す", r.read(), b'{"ok":true}')
        check("やり直しの回数（管制塔）", hits["n"], 3)
    finally:
        hub_client.urllib.request.urlopen, hub_client.RETRY_WAIT = saved2

    # 計画ファイルの表を読み戻せること（レポートが検索数・難易度を引く経路）
    tmp = ROOT / "docs" / "kw-plan-_gate_.md"
    tmp.write_text("| 優先 | キーワード | 月間 | 難易度 | 開く理由 | 12か月 | 表示 | 出どころ |" + chr(10)
                   + "|:--|:--|--:|--:|--:|--:|--:|:--|" + chr(10)
                   + "| A | 記帳代行 相場 | 480 | 29 | +2 | -33% | — | rakko |" + chr(10)
                   + "| C | 経理 やり方 | — | — | +3 | — | 12 | suggest |" + chr(10),
                   encoding="utf-8")
    try:
        m = kw_plan.plan_metrics("_gate_")
        check("表から月間・難易度・優先を読める", m.get("記帳代行相場"), (480, 29, "A"))
        check("欠けている値は None", m.get("経理やり方"), (None, None, "C"))
    finally:
        tmp.unlink(missing_ok=True)

    # 意図の掛け合わせは上限まで（補助金サイトは26×30で時間切れになった）
    many = {"intents": ["意図%d" % i for i in range(30)]}
    check("意図は上限まで", len(kw_plan.intents_for(many)) <= kw_plan.MAX_INTENTS, True)

    # 新計画にもある語は取り下げない。配備中の管制塔は取り下げ済みの語の再追加を弾き、
    # その語が計画から消える（実際に17本消えた）
    r, k = kw_plan.split_retire(["経理 アウトソース 費用", "古い語 A", "請求書 封筒 書き方"],
                                ["経理 アウトソース 費用", "請求書の書き方 封筒"])
    check("新計画にある語は残す", sorted(k), ["経理 アウトソース 費用", "請求書 封筒 書き方"])
    check("新計画に無い語だけ取り下げる", r, ["古い語 A"])

    # 一新は「未着手」だけを対象外にする。公開済み・執筆中を落とすと生きている記事が消える
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("未着手だけを取り下げる", 'get("status") == "未着手"' in src, True)
    check("force で公開済みを落とさない", "force=True" not in src, True)


def main():
    for t in (test_kw_conflicts, test_tag_balance, test_char_count, test_hub_gas,
              test_self_exclusion, test_published_not_rewritten_as_new,
              test_token_check_probes_write, test_selfheal_watches_real_workflows,
              test_lab_links_to_corporate, test_daily_audit_ignores_unscored_drafts,
              test_every_article_has_a_lead_path,
              test_token_never_in_command_line,
              test_kw_intent_separates_click_need,
              test_lead_funnel_is_watched,
              test_cta_wording_is_measured_not_guessed,
              test_each_site_declares_what_it_sells,
              test_next_keyword_prefers_main_offer,
              test_improvements_apply_themselves,
              test_auto_fixes_are_reviewed,
              test_client_onboarding_is_one_sheet,
              test_quality_gate_holds_on_wordpress,
              test_daily_todo_fits_in_one_run,
              test_near_page1_is_pushed_every_week,
              test_main_category_actually_grows,
              test_paragraph_split_keeps_text,
              test_anchor_text_stays_readable,
              test_block_breaks_render_correctly,
              test_rendered_html_is_checked,
              test_import_has_no_side_effects,
              test_long_sentences_are_split,
              test_rewrite_is_verified_and_reverted,
              test_output_matches_source,
              test_inquiry_body_is_not_truncated,
              test_articles_are_not_uniform,
              test_facts_are_per_article,
              test_unindexed_pages_are_chased,
              test_rate_claims_need_evidence,
              test_submissions_are_not_double_counted,
              test_boost_finds_link_sources,
              test_rank_data_is_verified,
              test_measurement_pitfalls_are_documented,
              test_built_tools_actually_run,
              test_quality_fixes_run_before_publishing,
              test_findings_judges_by_marker_not_exit_code,
              test_detection_scripts_do_not_fail_the_run,
              test_notify_does_not_send_junk,
              test_routine_success_is_not_emailed,
              test_every_site_gets_articles,
              test_intake_sheets_are_not_published,
              test_kw_plan_keeps_only_buyers):
        try:
            t()
        except Exception as e:
            print(f"  NG  {t.__name__} が例外で止まりました: {type(e).__name__} {e}")
            FAIL.append(t.__name__)
    print(f"\n{'失敗 ' + str(len(FAIL)) + '件: ' + ', '.join(FAIL) if FAIL else 'すべて通りました'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
