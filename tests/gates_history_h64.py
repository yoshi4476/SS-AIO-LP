# -*- coding: utf-8 -*-
"""2026-10-08 補助金サイトの文言と図表の見直し（運用者の依頼）から。

- 補助金サイトの語の種（kw_seeds）に「申請 代行」があり、申請の代行（行政書士法）と読める語で記事を積んでいた
- 調査ページ（/research/ai-hojokin/）が、取り下げ・統合で消えた記事の旧題（問いの形でない題
  「AI導入補助金の申請代行を京都で頼む前に…」）を問いとして載せ、転送されるURLへリンクしていた。
  載せた問いは20問なのに、根拠のページは載せない問いの答えまで数えていた
- 受付の自動返信が、補助金の相談にも AI集客ラボ（AIO）の動画と ai.7senses.co.jp/lp/ を添えていた
  （後追いメールの followUp が補助金・コーポレートの行を外しているのと同じ理由で、相談と関係のない営業メールになる）
- 補助金サイトの /unsubscribe/ で配信停止した人（管制塔の「配信除外」）に、AI集客ラボのニュースレター（同じ会社）が届き続けていた
- トップに出す調査の数字は、調査のデータから機械で読む（手で書かない）
"""
import importlib.util
import json
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _research():
    """scripts/research.py（リサーチ工程）と名前がぶつかるので、ファイルから読む"""
    spec = importlib.util.spec_from_file_location("subsidy_research_h64", ROOT / "scripts" / "subsidy" / "research.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_subsidy_kw_seeds_do_not_read_as_daikou():
    print("\n■ 補助金サイトの語の種に「代行」を入れない（申請の代行と読める記事を作らない）")
    cfg = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    seeds = cfg.get("kw_seeds", {})
    words = [w for k, v in seeds.items() if isinstance(v, list) for w in v]
    check("補助金: kw_seeds に「代行」の語が無い", [w for w in words if "代行" in w], [])
    # 台帳に積んである「代行」の語も書かない（next_kw が drop_kw の語を飛ばす）
    import hub_client as HC
    check("補助金: 台帳に残った「代行」の語は次に書く語に選ばない", bool(re.search(HC._drop_pattern("subsidy") or "^$", "it導入補助金 申請代行 費用")), True)


def _moved():
    out = {}
    f = ROOT / "data" / "retractions.jsonl"
    for ln in f.read_text(encoding="utf-8").splitlines() if f.is_file() else []:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("site") == "subsidy" and r.get("from") and r.get("to"):
            out[r["from"]] = r["to"]
    return out


def _title(slug):
    for p in (ROOT / "articles" / f"{slug}.md", ROOT / "articles" / "_legacy" / f"{slug}.md"):
        if p.is_file():
            m = re.search(r'^title:\s*"?(.+?)"?\s*$', p.read_text(encoding="utf-8"), re.M)
            return m.group(1).strip() if m else ""
    return ""


def test_research_page_follows_merges_and_lists_only_questions():
    print("\n■ 調査ページ: 消えた記事の旧題を問いにせず、転送の先の記事（今の題）へつなぐ")
    R = _research()
    d = R.data("subsidy", "https://lp.7senses.co.jp")
    if not d:
        check("補助金の調査の材料がある", d is not None, True)
        return
    moved = _moved()
    rows = d["rows"]
    check("調査: 転送されるURL（統合・取り下げで消えた記事）へリンクしない",
          sorted({r["url"] for r in rows if r["url"] in moved}), [])
    qform = re.compile(r"([?？]|ますか|ませんか|ですか|でしょうか)\s*$")
    check("調査: 問いの形でない行（記事の題）を問いとして載せない",
          [r["q"] for r in rows if not qform.search(r["q"].strip())], [])
    body = R.html_body(d)
    check("調査: 統合済みの記事の旧題（京都で頼む前に）を出さない", "申請代行を京都で頼む前に" in body, False)
    # 転送の先の記事は、今の題を添える（記事の原稿から読む）
    want = sorted({_title(r["url"].strip("/").split("/")[-1]) for r in rows if r.get("now_title")})
    check("調査: 転送の先の記事の今の題を、原稿の題のまま添える",
          (bool(want) and all(t and t in body for t in want),
           sorted({r["now_title"] for r in rows if r.get("now_title")}) == want), (True, True))
    # 根拠のページは載せた問いの答えだけで数える（「N問聞いたところ…根拠N件」と合わせる）
    import subsidy_survey as SV
    shown, src = {r["q"] for r in rows}, {}
    for p in sorted((ROOT / "data" / "subsidy_survey").glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec = dict(rec, answers={q: a for q, a in rec.get("answers", {}).items() if q in shown})
        for k, v in SV.tally(rec)["sources"].items():
            src[k] = src.get(k, 0) + v
    check("調査: 根拠のページは載せた問いの答えだけで数える", {k: v for k, v in d["sources"].items() if v},
          {k: v for k, v in src.items() if v})


def test_top_research_chart_reads_the_data():
    print("\n■ トップの調査のグラフ: 数字は調査のデータから機械で読み、図の中身を文字でも書く")
    R = _research()
    d = R.data("subsidy", "https://lp.7senses.co.jp")
    h = R.top_html(d) if d and hasattr(R, "top_html") else ""
    s = (d or {}).get("sources", {})
    total = sum(s.values())
    need = [f"{len(d['rows'])}問", f"{d['split']}問", f"{total}件", f"{s.get('public', 0)}件",
            f"{s.get('private', 0)}件", f"{d['public_pct']}%"] if d else ["材料"]
    check("トップの図: 問いの数・割れた数・根拠の件数・公的機関の割合が調査のデータと同じ",
          [x for x in need if x not in h], [])
    check("トップの図: role=\"img\" と説明（aria-label）があり、図の外にも同じことを文字で書く",
          (h.count('role="img"') >= 2, h.count("aria-label=") >= 2, h.count("<figcaption") >= 2), (True, True, True))
    check("トップの図: 調査ページへつなぐ", 'href="/research/ai-hojokin/"' in h, True)
    pages = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("一覧づくり: 配信のたびにトップの目印のあいだへ入れ直す", "_RS.put_top(ROOT, DOMAIN)" in pages, True)


def test_auto_reply_materials_follow_the_site():
    print("\n■ 受付の自動返信: 添える案内は問い合わせが来たサイトのものだけ")
    from gates_history_d import node_run
    gas = ROOT / "automation" / "gas"
    src = "\n".join((gas / f).read_text(encoding="utf-8") for f in ("hub.gs", "contact.hub.gs"))
    cases = {"subsidy": "AI導入補助金サポート (lp.7senses.co.jp)", "subsidy_id": "subsidy",
             "ai": "AI集客ラボ (ai.7senses.co.jp)", "ai_id": "ai-lab", "ai_name": "AI集客ラボ",
             "corp": "セブンセンシズ コーポレートサイト (corp.7senses.co.jp)"}
    js = ("var __m=[];MailApp={sendEmail:function(o){__m.push(o);}};"
          "UrlFetchApp={fetch:function(){throw new Error('offline');}};"
          "PropertiesService={getScriptProperties:function(){return {getProperty:function(){return null;}};}};"
          f"var __c={json.dumps(cases, ensure_ascii=False)};var __o={{}};"
          "Object.keys(__c).forEach(function(k){__m=[];"
          "leadReply_(__c[k],'contact',{type:'contact',email:'a@example.com',name:'山田',message:'相談です'});"
          "__o[k]=__m.length?__m[0].body:'';});globalThis.__out=__o;")
    out = node_run(src, js)
    if out is None:
        print("  WARN  node が無いため、送られる文面は確かめられません")
        return
    out = out if isinstance(out, dict) else {}
    lab = ("ai.7senses.co.jp/videos/aio-pr.mp4", "ai.7senses.co.jp/lp/")
    check("補助金の相談に AI集客ラボの動画・LP を添えない",
          {k: any(x in out.get(k, "") for x in lab) for k in ("subsidy", "subsidy_id")}, {"subsidy": False, "subsidy_id": False})
    check("補助金の相談には補助金サイトの案内（申請サポート・要項・調査）を添える",
          {k: all(u in out.get(k, "") for u in ("https://lp.7senses.co.jp/service/hojokin/", "https://lp.7senses.co.jp/youkou/",
                                                 "https://lp.7senses.co.jp/research/ai-hojokin/"))
           for k in ("subsidy", "subsidy_id")}, {"subsidy": True, "subsidy_id": True})
    check("AI集客ラボの相談には今までどおり動画とLPを添える（表示名・ID・名前のどれでも）",
          {k: all(x in out.get(k, "") for x in lab) for k in ("ai", "ai_id", "ai_name")},
          {"ai": True, "ai_id": True, "ai_name": True})
    check("コーポレート（経理BPO）の相談に AIO の動画を添えない",
          any(x in out.get("corp", "") for x in lab), False)
    check("どのサイトにも連絡の目安（3営業日以内）は残す",
          all("3営業日以内" in out.get(k, "") for k in cases), True)


def test_newsletter_skips_unsubscribed_people():
    print("\n■ ニュースレター: 管制塔の「配信除外」に入った人を、送る前に購読者から外す（照らせなければ送らない）")
    import newsletter_exclude as NE
    calls = []
    contacts = [{"id": "c1", "email": "Stop@Example.com", "unsubscribed": False},
                {"id": "c2", "email": "keep@example.com", "unsubscribed": False},
                {"id": "c3", "email": "already@example.com", "unsubscribed": True}]

    def call(key, method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"object": "list", "has_more": False, "data": contacts}
        return {"object": "contact", "id": path.rsplit("/", 1)[-1]}

    asked = []

    def post(body):
        asked.append(body)
        return {"ok": True, "excluded": [e for e in body["emails"] if e.startswith("stop@")]}
    n = NE.apply("k", call=call, post=post)
    check("配信除外の人だけを Resend で配信停止にする（大文字小文字は同じ人）",
          (n, [(m, p, b) for m, p, b in calls if m == "PATCH"]), (1, [("PATCH", "/contacts/c1", {"unsubscribed": True})]))
    check("照らすのは配信中の購読者だけ（停止済みは送らない）", asked[0]["emails"], ["keep@example.com", "stop@example.com"])
    check("管制塔へは合言葉つきの action で聞く（フォームの受付に流れない）", asked[0]["action"], "newsletter_excluded")
    for name, bad in (("古い GAS（action を知らずフォームの受付に流れる）", {"ok": False, "error": "メールアドレスの形式をご確認ください。"}),
                      ("返事が無い", None)):
        try:
            NE.apply("k", call=call, post=lambda b, bad=bad: bad)
            got = "送る"
        except NE.NotChecked:
            got = "止める"
        check(f"照らせないときは送らない: {name}", got, "止める")
    for f in ("send_digest.py", "season_feature.py"):
        t = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        i, j = t.find("NE.apply(key)"), t.find('api("/broadcasts"')
        check(f"{f}: 一斉配信を作る前に配信除外を当てる", 0 <= i < j, True)
    wf = (ROOT / ".github" / "workflows" / "digest.yml").read_text(encoding="utf-8")
    step = wf.split("name: ダイジェスト配信", 1)[1].split("- name:", 1)[0] if "name: ダイジェスト配信" in wf else ""
    check("週刊ニュースレターの工程に管制塔の鍵（HUB_URL・HUB_SECRET）を渡す",
          ("HUB_URL: ${{ secrets.HUB_URL }}" in step, "HUB_SECRET: ${{ secrets.HUB_SECRET }}" in step), (True, True))
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    hub = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    fn = (re.search(r"^function newsletterExcluded_\(.*?^}", gs, re.S | re.M) or [""])[0]
    check("GAS: 配信除外の判定は excluded_ と同じものを使い、聞かれたアドレスのうち当たった分だけ返す",
          ("excludeSet_()" in fn, "excluded_(" in fn, "case 'newsletter_excluded':" in hub), (True, True, True))
    # 本物の受付と同じ経路で配信停止 → ニュースレターの照会で当たるか（会社のドメインの除外も同じ判定）
    from gates_history_h56 import FAKE
    from gates_history_d import node_run
    scen = ("form_({type:'unsubscribe',form_type:'unsubscribe',site:'subsidy',email:'Taro@Example.co.jp',website:'',ts:1});"
            "excludeSheet_().appendRow(['client.co.jp','','既存客','','2026-10-08','手']);"
            "globalThis.__out=newsletterExcluded_({emails:['taro@example.co.jp','someone@client.co.jp','keep@gmail.com','keep@other.co.jp']});")
    got = node_run(FAKE + "\n" + hub + "\n" + gs, scen)
    if got is None:
        print("  WARN  node が無いため、GAS の照会は確かめられません")
    else:
        check("GAS: 補助金サイトで配信停止した人と、配信除外のドメインの人だけがニュースレターの照会で当たる",
              (got or {}).get("excluded") if isinstance(got, dict) else got, ["taro@example.co.jp", "someone@client.co.jp"])
