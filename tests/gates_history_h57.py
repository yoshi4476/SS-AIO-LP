# -*- coding: utf-8 -*-
"""記事の図解（2026-10-08 の依頼「表やグラフ、図も盛り込んで視覚的に見やすく」）。

  1. score 90以上の記事409本のうち291本（71%）が、flow・list・vs を1枚ずつ並べた同じ組み合わせだった。
     読み手に単調で、量産の跡にも見える → 中身に合う型を足す（steps・matrix・cycle・funnel・bars・pyramid・tree）
  2. 1200px で書き出していて、高精細の画面で粗く見えた → 論理の幅のまま SCALE 倍で書き出す。容量は上限で止める
  3. 項目数の上限を見ていたのは flow だけ（6個目以降が黙って切られた件）。描かれなかった図も素通りした
     → 全部の型で、描く側（make_diagram）とビルドと画像検査が同じ判定を使う
  4. bars に本文に無い数字を描くと、事実と違う図が公開される → 本文・表に同じ値が無ければ描かない
  5. 書き手への指示に新しい型が無ければ使われない → 指示（multi_site_prompt・site_brief）に書く
"""
import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

NEW = ("steps", "matrix", "cycle", "funnel", "bars", "pyramid", "tree")
BODY = ("当サイトの計測では、ChatGPTの回答で出典に選ばれたのは42回でした。\n\n"
        "| AI | 出典に選ばれた回数 |\n|:--|:--|\n| Gemini | 31回 |\n| Perplexity | 18回 |\n")
SAMPLES = {
    "steps": {"type": "steps", "title": "申請から入金までの流れ",
              "items": ["GビズIDを取る|発行まで2〜3週間", "計画を書く", "申請して待つ|結果まで約2か月", "報告する"],
              "labels": ["申請の前", "1か月目", "2〜3か月目", "採択の後"]},
    "steps-col": {"type": "steps", "title": "引用されるまでの6段階",
                  "items": ["クロールされる|止めていない", "登録される|URL検査で確かめる", "10位以内に入る",
                            "答えが先に来る|見出しの直下に1文", "独自の数字がある", "社名で探される"]},
    "matrix": {"type": "matrix", "title": "依頼先ごとにできること",
               "items": ["業務|税理士|経理代行|人材派遣", "記帳|○|◎|△", "給与計算|△|○|○", "決算|◎|×|×"]},
    "cycle": {"type": "cycle", "title": "口コミ対応を回す4つの手順",
              "items": ["集める|来店後に頼む", "返す|2日以内", "見直す|月に1回", "直す|接客に反映"], "center": "毎月まわす"},
    "funnel": {"type": "funnel", "title": "検索から相談までの絞り込み",
               "items": ["検索に出る|表示", "記事を開く|クリック", "診断を使う", "相談する"]},
    "bars": {"type": "bars", "title": "AIの出典に選ばれた回数", "unit": "回",
             "items": ["ChatGPT|42", "Gemini|31", "Perplexity|18"], "note": "出典：当サイトの計測"},
    "pyramid": {"type": "pyramid", "title": "選ばれる記事の土台",
                "items": ["社名で探される", "引用される|独自の数字", "読まれる|答えが先", "見つかる|登録される"]},
    "tree": {"type": "tree", "title": "補助金の分け方", "root": "目的で分ける",
             "items": ["設備|ものづくり補助金", "IT|デジタル化・AI導入補助金", "販路|持続化補助金"]},
}


def _md():
    import make_diagram as MD
    return MD


def _font_ok():
    try:
        _md().font(16)
        return True
    except SystemExit:
        print("  WARN  日本語フォントが無いため、図の描画は確かめられません")
        return False


@contextlib.contextmanager
def captured(cfg=None):
    """描いた画像を保存せずに受け取る（{ファイル名: 画像}）"""
    MD = _md()
    got = {}
    real = (MD.save_png, MD.site_for_slug)
    MD.save_png = lambda img, slug, name: got.__setitem__(name, img)
    MD.site_for_slug = lambda slug: cfg
    try:
        yield got
    finally:
        MD.save_png, MD.site_for_slug = real


def test_diagram_types_fit_the_content():
    print("\n■ 図解: 中身に合う型がある（時系列・比較の表・循環・絞り込み・数字・階層・分類）")
    MD = _md()
    check("型は10種（flow・list・vs に7種を足す）", sorted(MD.TYPES), sorted(MD.OLD_TYPES + NEW))
    if not _font_ok():
        return
    import sites as S
    bad, sizes = [], {}
    with captured(S.load("ai-lab")) as got:
        for key, dg in SAMPLES.items():
            try:
                MD.render("zz-h57", dict(dg, name=key), body=BODY)
            except SystemExit as e:
                bad.append(f"{key}: {e}")
    for key, img in got.items():
        if img.width != MD.W * MD.SCALE:
            bad.append(f"{key}: 幅 {img.width}px")
        sizes[key] = len(MD.encode_png(img))
    check("新しい型を描ける（止まらない・幅は論理の幅の SCALE 倍）", (bad, sorted(got)), ([], sorted(SAMPLES)))
    check(f"1枚の容量が上限（{MD.MAX_BYTES // 1024}KB）以内",
          [f"{k} {v // 1024}KB" for k, v in sizes.items() if v > MD.MAX_BYTES], [])
    lab, corp, sub = (MD.palette_for(S.load(s)) for s in ("ai-lab", "corporate", "subsidy"))
    check("コーポ・補助金の図はそのサイトの色（AI集客ラボの青のままにしない）",
          [corp["accent"] != lab["accent"], sub["accent"] != lab["accent"], corp["accent"] != sub["accent"] or corp["bg"] != sub["bg"]],
          [True, True, True])


def test_diagram_text_never_overflows_and_limits_hold():
    print("\n■ 図解: 収まらない文字・型の数の外れは描かずに止める（黙って切らない・はみ出した絵を出さない）")
    MD = _md()
    out = {}
    for t, (lo, hi, unit, _) in MD.TYPES.items():
        dg = {"name": "x", "type": t, "title": "題", "root": "根", "items": [f"項目{i}|{i}" for i in range(hi + 2)]}
        out[t] = any(f"{lo}" in p and "描きません" in p for p in MD.declaration_problems(dg, BODY))
    check("全部の型で、項目が多すぎる宣言を止める", out, {t: True for t in MD.TYPES})
    if not _font_ok():
        return
    long = {"name": "x", "type": "cycle", "title": "題", "items": ["あ" * 60 + "|補足", "い", "う"]}
    with captured() as got:
        try:
            MD.render("zz-h57", long)
            stopped = False
        except SystemExit:
            stopped = True
        try:
            MD.render("zz-h57", {"name": "f", "type": "flow", "title": "題", "items": list("あいうえおか")})
            cut = False
        except SystemExit:
            cut = True
    check("縮めても折り返しても収まらない文字は描かない（検査は描く関数を保存せずに走らせて同じ判定）",
          [stopped, bool(MD.fit_problems(long)), "x" in got], [True, True, False])
    check("flow の6項目は5個に切らずに止める（以前は6個目以降が黙って消えた）", [cut, "f" in got], [True, False])
    d = MD.Pen()
    lines = MD.wrap(d, "IT導入支援事業者と契約内容を相談する", MD.font(22), 200)
    check("折り返しは文字を落とさず、英数字のかたまりを割らない",
          ["".join(lines), all(d.textlength(x, font=MD.font(22)) <= 200 for x in lines),
           any(x.endswith("I") or x.startswith("T") for x in lines)],
          ["IT導入支援事業者と契約内容を相談する", True, False])


def test_bars_draw_only_numbers_in_the_body():
    print("\n■ 図解: bars の数字は本文・表に同じ値で出ているものだけ描く（図にだけある数字を作らない）")
    MD = _md()
    bars = dict(SAMPLES["bars"], name="b")
    check("本文と表にある数字は通す", MD.declaration_problems(bars, BODY), [])
    check("本文に無い数字は止める",
          bool(MD.declaration_problems(dict(bars, items=["ChatGPT|42", "Gemini|31", "Claude|55"]), BODY)), True)
    alt = BODY + '<figure><img src="/images/x/b.png" alt="Copilot 9回"><figcaption>Copilot 9回</figcaption></figure>\n'
    check("図の alt・説明にだけある数字は本文と数えない",
          bool(MD.declaration_problems(dict(bars, items=["ChatGPT|42", "Gemini|31", "Copilot|9"]), alt)), True)
    check("ラベルと別の行にある数字（取り違え）は止める",
          bool(MD.declaration_problems(dict(bars, items=["ChatGPT|31", "Gemini|42", "Perplexity|18"]), BODY)), True)
    check("「1.2万件」は 12000 と同じ値として通す",
          MD.declaration_problems(dict(bars, items=["相談|12000", "ChatGPT|42", "Gemini|31"]),
                                  BODY + "相談は月1.2万件でした。\n"), [])
    check("本文が無ければ描くときは止める（確かめられない数字を描かない）",
          bool(MD.declaration_problems(bars, None, need_body=True)), True)
    if not _font_ok():
        return
    with captured() as got:
        try:
            MD.render("zz-h57", dict(bars, items=["ChatGPT|42", "Gemini|31", "Claude|55"]), body=BODY)
        except SystemExit:
            pass
    check("止めた bars は画像を書かない", "b" in got, False)


def test_diagrams_are_sharp_but_light():
    print("\n■ 図解: 高精細の画面で粗く見えない倍率で書き、容量の上限を超えたら止め、同じ中身なら書き直さない")
    MD = _md()
    check("書き出しは論理の幅の2倍以上（表示の大きさは CSS が決めるので変わらない）", MD.SCALE >= 2 and MD.W == 1200, True)
    if not _font_ok():
        return
    with captured() as got:
        MD.draw_list("zz-h57", "l", "題", ["一", "二", "三"])
    img = got["l"]
    check("旧い型（list）も2倍で描く", img.size, (MD.W * MD.SCALE, (120 + 3 * 74 + 60) * MD.SCALE))
    real = MD.MAX_BYTES
    try:
        MD.MAX_BYTES = 1024
        try:
            MD.encode_png(img)
            stopped = False
        except SystemExit:
            stopped = True
    finally:
        MD.MAX_BYTES = real
    check("上限を超える図は止める（記事の表示を遅くしない）", stopped, True)
    with tempfile.TemporaryDirectory() as td:
        root = MD.ROOT
        try:
            MD.ROOT = Path(td)
            MD.save_png(img, "s", "l")
            f = Path(td) / "site" / "images" / "s" / "l.png"
            os.utime(f, (1, 1))
            MD.save_png(img, "s", "l")
            same = f.stat().st_mtime == 1
        finally:
            MD.ROOT = root
    check("中身が同じなら書き直さない（描き直しのたびに差分を出さない）", same, True)


def test_build_and_checks_share_the_diagram_rules():
    print("\n■ 図解: ビルド・画像検査・描く側が同じ判定（描かれなかった図・数の外れ・新しい記事の型の重なりと置き忘れ）")
    MD = _md()
    import image_check as I
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.py が図解の宣言を make_diagram.article_problems で見て、公開前の記事を止める",
          ["article_problems(meta, body" in src, 'QUALITY_ISSUES.setdefault(meta["slug"], []).append(f"図解:' in src],
          [True, True])
    with tempfile.TemporaryDirectory() as td:
        site = Path(td)
        (site / "images" / "s").mkdir(parents=True)
        (site / "images" / "s" / "a.png").write_bytes(b"x")
        dgs = [{"name": "a", "type": "list", "title": "題", "items": ["一", "二", "三"]},
               {"name": "b", "type": "list", "title": "題", "items": ["一", "二", "三"]}]
        body = '<figure><img src="/images/s/a.png" alt="題"></figure>'
        new = MD.article_problems({"date": MD.DIAGRAM_RULES_FROM, "diagrams": dgs}, body, site, "s")
        old = MD.article_problems({"date": "2026-09-01", "diagrams": dgs}, body, site, "s")
    check("描かれていない図を拾う", any("画像がありません: /images/s/b.png" == p for p in new), True)
    check("新しい記事: 同じ型の重なりと、本文に置いていない図を拾う",
          [any("同じ型の図" in p for p in new), any("本文に置いていません: b" in p for p in new)], [True, True])
    check("既存の記事には新しい決まりを当てない（宣言を書き換えると本文と図の対応が崩れる）",
          [p for p in old if "同じ型" in p or "置いていません" in p], [])
    if not _font_ok():
        return
    ok = {k: I.diagram_problems(dict(v, name=k), body=BODY) for k, v in SAMPLES.items()}
    check("画像検査: 新しい型を「未対応」にせず、収まる宣言は何も出さない", ok, {k: [] for k in SAMPLES})
    check("画像検査: 本文に無い bars の数字を拾う",
          bool(I.diagram_problems(dict(SAMPLES["bars"], name="b", items=["ChatGPT|42", "Gemini|31", "Claude|55"]), body=BODY)),
          True)


def test_writers_are_told_to_pick_the_shape():
    print("\n■ 図解: 書き手への指示に新しい型と選び方（中身で選ぶ・同じ型を重ねない・直近と同じ組み合わせにしない）")
    MD = _md()
    prompt = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("記事の指示: 10種の型が全部書いてある", [t for t in MD.TYPES if t not in prompt], [])
    check("記事の指示: 選び方・重ねない・本文にある数字だけ",
          ["同じ記事で同じ型を重ねない" in prompt, "比較なら matrix" in prompt, "bars の数字は本文" in prompt],
          [True, True, True])
    sb = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("site_brief が図解の案内（型・例・直近の組み合わせ）を出す", "make_diagram.brief(" in sb, True)
    t = time.time()
    lines = "\n".join(MD.brief("ai-lab"))
    check("案内: 全部の型・書き方の例・直近の組み合わせ",
          [[x for x in MD.TYPES if f"  {x} " not in lines], "type: matrix" in lines, "直近" in lines],
          [[], True, True])
    print(f"  （案内の作成 {time.time() - t:.1f}秒）")


def test_make_images_keeps_going_and_redraws_all():
    print("\n■ 図解: 1枚が止まっても残りは描き、全記事の図だけを描き直せる（解像度・見た目を変えたとき）")
    import make_images as MI
    MD = _md()
    src = (ROOT / "scripts" / "make_images.py").read_text(encoding="utf-8")
    check("make_images に --all（図解だけを全部描き直す）がある", "--all" in src and "def redraw_all" in src, True)
    drawn = []

    def fake(slug, dg, body=None, save=True):
        if dg["name"] == "b":
            raise SystemExit("止めた")
        drawn.append(dg["name"])
    real = MD.render
    try:
        MD.render = fake
        failed = MI.draw_diagrams("s", {"diagrams": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}, "")
    finally:
        MD.render = real
    check("止まった図の理由を返し、残りは描く", [drawn, [f.split(":")[0] for f in failed]], [["a", "c"], ["b"]])
