# -*- coding: utf-8 -*-
"""2026-10-20 の全体点検（担当2: 品質の門と記事を書く指示）の門。

- B1 新しい記事が score_check で落ちても公開されていた → agent_guard.publish が「この回の新しい記事」だけを採点し、
  落ちたものを articles/_conflicted/ へ隔離する（公開済みの記事は動かさない。10-13 に公開中の280本を誤って隔離した）
- A1 一次情報の門が、全社の事実の社名・所在地まで目印にしていた → 2026-10-21 以降の記事はその社の事実（facts.load_for）だけ。
  当社の名前・所在地・創業の時期・店舗数は sites.OPERATOR_MARKS に入れ、お客様の記事に出たら止める
- B3 rubric.gate_ok が score: .nan・内訳の欠け・文字の値・内訳の平均が90未満を通していた
- B5 公開台帳が読めない回に、新しい記事の門が全部外れ、台帳がその回の記事だけで上書きされていた
- B6 題の字数（15〜45字）を採点で見ていなかった
- B7 republish_images が publish.py の門（表示の決まり・入れてはいけない HTML・お客様の使えない表現）を通していなかった
- D1 原稿と出力の塊の数が合わない記事も配信していた（画像の記法・行内のコードはリンクに数えない）
- D2 補助金サイトの記事の構造化データ（Article）に image が無かった
- A3/A4/A5/A7 指示書・CLAUDE.md・win_patterns・originality の食い違い
"""
import contextlib
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

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


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


class _Done:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _article(title="AIO対策のはじめ方を中小企業向けに解説", date="2026-10-25", category="aio", body="本文です。"):
    fm = {"title": title, "slug": "x", "date": date, "category": category, "keyword": "aio 対策",
          "description": "説明" * 60, "score": 90}
    import yaml
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True) + "---\n" + body + "\n"


def test_publish_quarantines_only_new_articles_that_fail_score_check():
    import agent_guard as G
    import score_check as SC
    print("\n■ AI が書いた新しい記事だけを採点し、落ちたものを隔離する（公開済みの記事は落ちていても動かさない）")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        for s in ("pub-fail", "new-fail", "new-ok"):
            (root / "articles" / f"{s}.md").write_text(_article(), encoding="utf-8")
        before = {"pub-fail": hashlib.sha1((root / "articles" / "pub-fail.md").read_bytes()).hexdigest()}
        called = []

        def fake_run(cmd, **k):
            called.append(cmd[-1])
            return _Done(0, "PUBLISHED\n")

        def fake_score(slug, path=None):
            bad = slug in ("pub-fail", "new-fail")
            return [("本文5,000字以上（depth: standard）", not bad, "", False), ("［警告］段落", False, "", True)]

        with patched((G, "_load_state", lambda: {"articles": before}), (G.subprocess, "run", fake_run),
                     (SC, "run", fake_score)):
            res, out = quiet(G.publish, root, None)
        check("隔離は新しい記事の落ちた1本だけ", sorted(p.stem for p in (root / "articles" / "_conflicted").glob("*.md")),
              ["new-fail"])
        check("公開済みの記事は採点に落ちていても articles/ に残る", (root / "articles" / "pub-fail.md").is_file(), True)
        check("配信（publish_flow）へ回すのは通った新しい記事だけ", called, ["new-ok"])
        check("数と要対応", (res["quality"], res["published"], "要対応:" in out), (1, 1, True))
        check("警告（warn）だけの記事は止めない", "new-ok" not in [p.stem for p in (root / "articles" / "_conflicted").glob("*.md")], True)

        # 採点そのものが動かない回は隔離しない（publish_flow と build.py の判定に任せる）
        (root / "articles" / "new2.md").write_text(_article(), encoding="utf-8")

        def broken(slug, path=None):
            raise SystemExit("フロントマターがありません")

        before2 = {p.stem: hashlib.sha1(p.read_bytes()).hexdigest() for p in (root / "articles").glob("*.md")
                   if p.stem != "new2"}
        called.clear()
        with patched((G, "_load_state", lambda: {"articles": before2}), (G.subprocess, "run", fake_run),
                     (SC, "run", broken)):
            res2, _ = quiet(G.publish, root, None)
        check("採点が動かなければ隔離せず配信の判定へ", ((root / "articles" / "new2.md").is_file(), called), (True, ["new2"]))
        # 控えが無い回（lock が動かなかった）は何もしない＝全部を新しい記事として隔離しない
        with patched((G, "_load_state", lambda: {}), (G.subprocess, "run", fake_run), (SC, "run", fake_score)):
            res3, _ = quiet(G.publish, root, None)
        check("lock の控えが無ければ1本も隔離しない", (res3["quality"], (root / "articles" / "pub-fail.md").is_file()), (0, True))


def test_rubric_gate_rejects_nan_missing_and_low_average():
    import rubric as R
    print("\n■ 公開の門: nan・内訳の欠け・文字の値・内訳の平均が90未満を通さない（旧6観点は今までどおり）")
    v3 = {"originality": 94, "extractability": 92, "decision": 93}
    old = {"aio": 19, "design": 19, "editorial": 18, "expert": 19, "persona": 18, "seo": 19}
    cases = [
        ({"score": 93, "score_breakdown": v3}, True),
        ({"score": 90}, True),
        ({"score": 93, "score_breakdown": old}, True),
        ({"score": 90, "score_breakdown": {"originality": 85, "extractability": 88, "decision": 86}}, False),
        ({"score": float("nan")}, False),
        ({"score": float("inf")}, False),
        ({"score": True}, False),
        ({"score": 95, "score_breakdown": [94, 92, 93]}, False),
        ({"score": 95, "score_breakdown": {"originality": 94, "extractability": 92}}, False),
        ({"score": 95, "score_breakdown": {"originality": 94, "extractability": "92", "decision": 93}}, False),
        ({"score": 95, "score_breakdown": {"originality": 94, "extractability": float("nan"), "decision": 93}}, False),
        ({"score": 95, "score_breakdown": {"seo": 19, "aio": 19}}, False),
        ({"score": 95, "score_breakdown": {"foo": 99}}, False),
        ({"score": 89, "score_breakdown": v3}, False),
        ({"score": 93, "score_breakdown": {**v3, "decision": 79}}, False),
    ]
    check("判定の表", [R.gate_ok(m) for m, _ in cases], [w for _, w in cases])
    check("理由が書かれる", bool(R.gate_why({"score": float("nan")})), True)

    # 今ある記事は、前の判定で通ったものが全部通る（旧6観点の361本を含む。公開中の記事を取り下げない）
    import yaml

    def old_gate(meta):
        sc = meta.get("score")
        if isinstance(sc, bool) or not isinstance(sc, (int, float)) or sc < R.PASS_TOTAL:
            return False
        return not R.weak_axes(meta)

    n = moved = old6 = 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", p.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        if old_gate(meta):
            n += 1
            moved += not R.gate_ok(meta)
            old6 += set(meta.get("score_breakdown") or {}) == set(R.OLD_AXES)
    check("前の判定で通った記事は全部通る", (moved, n > 300, old6 > 300), (0, True, True))
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.py も同じ判定（nan を通さない）で止める", "rubric.gate_why(meta)" in b, True)


def test_published_ledger_broken_falls_back_to_head_or_stops():
    import build as B
    print("\n■ 公開台帳が読めないとき: HEAD の台帳で続け、それも無ければ止める（初回と取り違えない）")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        led = root / "data" / "published.json"
        led.parent.mkdir()
        led.write_text(json.dumps(["a", "b"]), encoding="utf-8")
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "add", "-A"], check=True)
        subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
        with patched((B, "ROOT", root), (B, "PUBLISHED_LEDGER", led)):
            ok, _ = quiet(B.published_slugs)
            led.write_text('["a", "b"', encoding="utf-8")            # 壊れた JSON
            broken, out = quiet(B.published_slugs)
            led.write_text('"ab"', encoding="utf-8")                  # 配列でない（文字の集合になっていた形）
            notlist, _ = quiet(B.published_slugs)
            led.unlink()
            gone, out2 = quiet(B.published_slugs)
            led.write_text("{", encoding="utf-8")
            subprocess.run(["git", "-C", d, "add", "-A"], check=True)
            subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "y"], check=True)
            try:
                quiet(B.published_slugs)
                stopped = False
            except SystemExit as e:
                stopped = "要対応" in str(e)
        check("読める台帳はそのまま", ok, {"a", "b"})
        check("壊れていれば HEAD の台帳で続け、要対応を出す", (broken, "要対応" in out), ({"a", "b"}, True))
        check("配列でない台帳も壊れた扱い", notlist, {"a", "b"})
        check("消えていても HEAD があれば初回扱いにしない", (gone, "要対応" in out2), ({"a", "b"}, True))
        check("HEAD も読めなければビルドを止める", stopped, True)
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "published.json"
        with patched((B, "PUBLISHED_LEDGER", led)):
            first, _ = quiet(B.published_slugs)
        check("台帳も git の記録も無い初回は None（何も止めない）", first, None)


def test_score_check_facts_by_site_and_title_length():
    import facts as F
    import score_check as SC
    import sites as S
    print("\n■ 一次情報はその社の事実だけ（2026-10-21 以降の記事）・名前は目印にしない・題の字数を採点で見る")
    check("当社の店舗数・所在地・創業の時期もお客様の記事に出してはいけない印",
          all(m in S.OPERATOR_MARKS for m in ("3,200店舗", "東成区", "2020年3月")), True)
    cfg = {"operator_ok": ["株式会社ゼットゼット"]}
    check("お客様の記事に当社の店舗数が出たら止める", bool(S.operator_leaks("G以外で3,200店舗を支援", cfg)), True)

    strict = SC.fact_tokens("自社3サイトで計測した196本をもとに集計（継続率100%）。「検索順位ごとの内部リンク本数」", strict=True)
    check("3桁の数字は単位つきでだけ目印にする", ("196本" in strict, "196" in strict, "100%" in strict), (True, False, True))
    check("「」で括った名前は目印にする", "検索順位ごとの内部リンク本数" in strict, True)
    check("単位の無い3桁は目印にしない", SC.fact_tokens("対象は150の候補", strict=True), [])
    check("古い判定（strict でない）は今までどおり", SC.fact_tokens("196本と100%") , ["196", "100"])

    facts = [{"id": "zz-1", "claim": "セブンセンシズ株式会社と大阪市東成区で、のべ1,234件を記録した"},
             {"id": "zz-2", "claim": "株式会社ゼットゼットの「ゼット式点検」を開発した"}]
    with patched((F, "load_for", lambda sid: ({"facts": facts}, facts))):
        marks = SC.site_fact_marks("client-zz", cfg)
    check("社名・所在地は目印にしない（数字と「」の名前は残す）", marks, {"zz-1": ["1,234"], "zz-2": ["ゼット式点検"]})

    def checks_for(body, date, title="AIO対策のはじめ方を中小企業向けに解説"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text(_article(title=title, date=date, body=body), encoding="utf-8")
            with patched((F, "load_for", lambda sid: ({"facts": facts}, facts))):
                cs, _ = quiet(SC.run, "x", path=p)
        return {c[0]: c[1] for c in cs}

    key = "自社の一次情報が1つ以上ある"
    check("新しい記事: 社名だけでは一次情報にならない", checks_for("セブンセンシズが書きました。", "2026-10-25")[key], False)
    check("新しい記事: その社の事実の数字があれば通る", checks_for("のべ1,234件を記録しました。", "2026-10-25")[key], True)
    check("新しい記事: その社の「」の名前があれば通る", checks_for("ゼット式点検で確かめます。", "2026-10-25")[key], True)
    check("決まりの前の記事は今の判定のまま（社名で通る）", checks_for("セブンセンシズが書きました。", "2026-10-01")[key], True)
    tkey = "タイトル15〜45字"
    check("題の字数: 短すぎ・長すぎは FAIL、範囲内は PASS",
          [checks_for("本文", "2026-10-25", title=t)[tkey] for t in ("短い題", "あ" * 46, "AIO対策のはじめ方を中小企業向けに解説")],
          [False, False, True])


def test_render_gaps_block_publish_without_false_alarms():
    import publish as P
    print("\n■ 原稿と出力の塊の数が合わない記事は配信しない（画像の記法・行内のコードはリンクに数えない）")
    nl = chr(10)
    good = ("本文です。" + nl + nl + "![図の説明](/images/x/a.png)" + nl + nl + "書き方は `- [題](URL)` です。" + nl + nl
            + "[解説](/aio/x/)を読む。" + nl + nl + "| A | B |" + nl + "|:--|:--|" + nl + "| 1 | 2 |" + nl)
    check("画像と行内のコードがある正しい原稿は止めない", P.render_gaps(good), [])
    check("空行の無い表は止める", bool(P.render_gaps("本文です。" + nl + "| A | B |" + nl + "|:--|:--|" + nl + "| 1 | 2 |")), True)
    check("生の HTML の中のリンクは止める", bool(P.render_gaps('<div class="box">詳細は[解説](/seo/x/)です。</div>')), True)
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    i, j = src.find("gaps = render_gaps(body)"), src.find('if cfg["type"] == "self-static":\n        if hold')
    check("配信の門（全方式が通る所）で止める", 0 < i < j, True)
    n = 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        if not re.search(r"^score:\s*(9[0-9]|100)\s*$", t, re.M):
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            n += bool(P.render_gaps(P.parse_article(p)[1]))
    check("今ある記事で止まるものは無い", n, 0)


def test_external_html_article_gets_image():
    import publish as P
    print("\n■ 別リポジトリの静的サイトの Article に og:image と同じ写真を入れる")
    page = ('<meta property="og:image" content="https://zz.example/images/blog/x/thumbnail.webp">\n'
            '<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@graph": [\n'
            '    { "@type": "Article",\n      "headline": "題",\n      "author": { "@type": "Person", "name": "z" } },\n'
            '    { "@type": "FAQPage", "mainEntity": [] }\n  ]\n}\n</script>')
    out = P.ld_image(page)
    ld = json.loads(re.search(r'ld\+json">(.*?)</script>', out, re.S).group(1))
    check("Article に image が入る", ld["@graph"][0].get("image"), "https://zz.example/images/blog/x/thumbnail.webp")
    check("ほかの実体には入れない", "image" in ld["@graph"][1], False)
    check("2回通しても同じ", P.ld_image(out), out)
    check("og:image が無ければ何もしない", P.ld_image(page.split("\n", 1)[1]), page.split("\n", 1)[1])
    has = page.replace('"headline": "題",', '"headline": "題", "image": "https://zz.example/a.png",')
    check("image が既にあれば変えない", P.ld_image(has), has)
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("write_external_html が書き出しの前に通す", "out = ld_image(out)" in src, True)


def test_republish_images_uses_the_same_gates_as_publish():
    print("\n■ 画像の描き直しも publish.py と同じ門（publish_rerender.redeliver_problems・render_gaps）を通す")
    src = (ROOT / "scripts" / "republish_images.py").read_text(encoding="utf-8")
    i, j = src.find("redeliver_problems(cfg, meta, body, md, dest)"), src.find("publish.write_nextjs_json")
    check("書き出しの前に門を通す", 0 < i < j, True)
    check("原稿と出力の数も見る", "publish.render_gaps(body)" in src, True)
    check("お客様の記事の slug をログに出さない", re.search(r'print\(f"   ○ \{slug\}', src) is None, True)


def test_prompts_and_docs_match_the_rubric_and_operation():
    import agent_memory as M
    print("\n■ 指示書・CLAUDE.md・win_patterns の食い違い（v3 の採点・通過印の 90・当社の実績は自社3サイトだけ）")
    ms = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    pp = (ROOT / "automation" / "pipeline_prompt.txt").read_text(encoding="utf-8")
    cm = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    wp = (ROOT / "scripts" / "win_patterns.py").read_text(encoding="utf-8")
    check("旧基準（10点・24点・6観点の採点）が指示書に残っていない",
          [w in ms for w in ("各10点", "24点以上", "7点未満", "6観点採点は", "6点になり")], [False] * 5)
    check("v3（各100点・80点未満は不合格・平均90）を書く", all(w in ms for w in ("各100点", "80点未満", "平均が90点以上")), True)
    check("当社の実績・立場は自社3サイトだけと書く", ms.count("自社3サイト") >= 3, True)
    check("pipeline_prompt も自分で採点しない（通過印の 90）", ("自分で点数は付けない" in pp, "score_breakdown（例" in pp), (True, False))
    check("CLAUDE.md の題・説明文の字数と飾りの年号",
          [w in cm for w in ("【2026年最新】検討", "タイトル30文字以内", "メタディスク120文字以内", "「◯年の実務経験から」等",
                             "自分の体験・感想を先に述べ", "一人称の観察・体験談2箇所以上")], [False] * 6)
    check("CLAUDE.md Phase 5 に今の運用（通過印の 90・score_audit）を書く", "機械採点の通過印" in cm, True)
    check("win_patterns は見出しの並びを写させない", ("土台にして" in wp, "これに揃える" in wp, "写さない" in wp), (False, False, True))
    check("書く AI の CLAUDE.md に「受託運用での分離」が残る", "受託運用での分離" in M.slim(cm, "writer"), True)


def test_originality_add_needs_own_site():
    import originality as O
    print("\n■ 体験の登録は社を必ず決める（空は全社に流れる）・お客様の体験は公開側に書かない")
    with tempfile.TemporaryDirectory() as d:
        exp = Path(d) / "experiences.json"

        def run(*argv):
            with patched((sys, "argv", ["originality.py", *argv]), (O, "EXPERIENCES", exp)):
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        quiet(O.main)
                    return 0
                except SystemExit as e:
                    return e.code
        base = ("--add", "--key", "目印", "--text", "あったこと", "--when", "2026-09")
        check("--site が無ければ止める", (run(*base), exp.exists()), (2, False))
        check("自社でない社は止める", (run(*base, "--site", "client-zz"), exp.exists()), (2, False))
        check("自社の社は登録できる（sites が入る）",
              (run(*base, "--site", "ai-lab"), json.loads(exp.read_text(encoding="utf-8"))["experiences"][0]["sites"]),
              (0, ["ai-lab"]))
    sk = (ROOT / ".claude" / "skills" / "original-content" / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md: お客様の体験は非公開の experiences.json", ("brief.json の事例" in sk, "experiences.json" in sk), (False, True))


def test_opening_bold_is_closed_in_fixed_articles():
    print("\n■ 冒頭段落の閉じていない ** を直した2本（** の数が偶数）")
    out = []
    for s in ("ai-hojokin-jissekihoukoku-kakikata", "nougyou-kikai-hojokin"):
        t = (ROOT / "articles" / f"{s}.md").read_text(encoding="utf-8-sig")
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", t, flags=re.S)
        first = next(ln for ln in body.splitlines() if ln.strip() and not ln.startswith(("<", "#")))
        out.append((first.startswith("**"), first.count("**") % 2))
    check("冒頭は ** で始まり、閉じている", out, [(True, 0), (True, 0)])
