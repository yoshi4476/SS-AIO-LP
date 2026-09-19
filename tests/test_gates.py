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
              test_rank_data_is_verified):
        try:
            t()
        except Exception as e:
            print(f"  NG  {t.__name__} が例外で止まりました: {type(e).__name__} {e}")
            FAIL.append(t.__name__)
    print(f"\n{'失敗 ' + str(len(FAIL)) + '件: ' + ', '.join(FAIL) if FAIL else 'すべて通りました'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
