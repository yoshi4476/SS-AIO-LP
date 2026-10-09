# -*- coding: utf-8 -*-
"""記事と動画の作成速度（2026-10-08 の依頼「作成速度も上げられるか。記事も動画も」）。検査と決まりは緩めない。

  1. 記事動画の候補に、監修待ち（HELD・公開されていない）の記事が入っていた（CONFLUX の
     business-system-development-cost が通常の動画の判定にかかり、ショートの候補にも残った）
     → 通常の動画もショートも、公開済み（score 90 以上・監修の記録あり）の記事だけ
  2. 動画の所要時間の内訳が見えなかった（ログは最後の10行だけ。16分以上1行も出ない回があった）
     → 工程ごとに `VIDEO_TIME <工程> <秒>` を出し、CI はその行をその場で流す
  3. 声を1行ずつ「作る→聞き直す」していた（手元の実測: 45行で声44秒・聞き直し2,116秒）
     → 声は同時に作り、1回目の聞き取りも同時に行う。ずれの判定・作り直し・辞書に覚える所は台本の順のまま
  4. 毎コマ、画面全体の大きさの透明な字幕の板を貼っていた → 余白を落として貼る（コマは1画素も変わらない）
  5. 記事の枠: 本番の確認の前に毎回45秒固定で待っていた／依存を1つずつ入れていた／
     ブリーフとカニバリの検査を、ワークフローと claude が2回ずつ実行していた／
     claude が自分でコミットし、後の工程（既存記事からのリンク・多言語・食い合いの再検査）が新しい記事を見失っていた
"""
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

ART = """---
title: {title}
description: テスト用の記事です。
slug: {slug}
keyword: テスト 語
category: aio
date: {date}
score: 92
---
本文です。
"""


@contextlib.contextmanager
def _patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def test_held_articles_never_become_videos():
    print("\n■ 記事動画: 監修待ち（HELD）の記事は、通常の動画にもショートにもしない")
    from datetime import date
    import article_videos as AV
    import duo_short as DS
    import editorial_review as ER
    import youtube_upload as YT
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "articles").mkdir()
        today = date.today().isoformat()
        for slug, title in (("ok-video-x", "AIOの始め方を3つの手順で"), ("held-video-x", "AIOの費用を3つの項目で")):
            (root / "articles" / f"{slug}.md").write_text(ART.format(title=title, slug=slug, date=today), encoding="utf-8")
        tok = root / "tok.json"
        tok.write_text("{}", encoding="utf-8")
        tried = []

        def script(slug):
            tried.append(slug)
            return None
        AV._REVIEWS = None          # 監修の記録を読み直させる（下で差し替えた記録を、後の門に残さない）
        with _patched(AV, ROOT=root, LEDGER=root / "videos.json"), \
                _patched(ER, needs_review=lambda s: s == "held-video-x", load=lambda: {}), \
                _patched(YT, token_path=lambda site=None: tok), \
                _patched(DS, load_script=script, write_script=script), \
                contextlib.redirect_stdout(io.StringIO()):
            got = [r["slug"] for r in AV.candidates(30, 10)]
            ledger = {s: {"site": "ai-lab", "long": {"decision": "skip", "date": today}}
                      for s in ("ok-video-x", "held-video-x")}
            AV.shorts(ledger, 5, False, False)
        AV._REVIEWS = None
    check("通常の動画の候補: 公開済みの記事は入り、監修待ちの記事は入らない", sorted(got), ["ok-video-x"])
    check("ショートの候補: 監修待ちの記事は台本も作らない", sorted(set(tried)), ["ok-video-x"])


def test_video_steps_report_their_time():
    print("\n■ 記事動画: 工程ごとの所要時間を出し、CI はその行をその場で流す")
    import video_make as VM
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with VM.timed("test.step"):
            pass
    check("VIDEO_TIME <工程> <秒> の1行で出す", bool(re.fullmatch(r"VIDEO_TIME test\.step \d+\.\d\n", buf.getvalue())), True)
    src = {n: (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
           for n in ("article_videos", "duo_video", "duo_short", "yomi_guard")}
    want = {"article_videos": ['"videos.plan"', '"long.script"', '"long.make"', '"long.upload"', '"short.script"',
                               '"short.make"', '"short.upload"', '"videos.total"'],
            "duo_video": ['f"{tag}.voice"', '"duo.audio"', '"duo.render"', '"duo.render.draw"', '"duo.render.encode_wait"'],
            "duo_short": ['"short.audio"', '"short.render"', '"short.render.draw"'],
            "yomi_guard": ['"yomi.load"', 'spend("hear"']}
    check("台本・声・聞き直し・音・描画・書き出し・上げる、の各工程が時間を出す",
          {n: [w for w in ws if w not in src[n]] for n, ws in want.items()}, {n: [] for n in want})
    wf = (ROOT / ".github" / "workflows" / "daily-video.yml").read_text(encoding="utf-8")
    check("CI: VIDEO_TIME の行を最後の10行に埋もれさせず、その場で流す",
          ("grep --line-buffered '^VIDEO_TIME'" in wf, "PYTHONUNBUFFERED=1 python scripts/article_videos.py" in wf,
           "| tail -10 || true" in wf), (True, True, False))
    prep = _step(wf, "準備")
    check("CI の準備: apt・npm を pip と同時に入れ、ffmpeg と claude を使う前に待つ",
          ("& apt=$!" in prep, "& npm=$!" in prep,
           prep.find("wait $apt") < prep.find("command -v ffmpeg"), prep.find("wait $npm") < prep.find("claude --version")),
          (True, True, True, True))


def test_voices_are_made_together_but_checked_in_order():
    print("\n■ 声: 同時に作り、聞き直しは台本の順。覚えた読みは後の行に効かせ、作り直した声は聞き直す")
    import video_make as VM
    import yomi_guard as YG
    learned = {}
    made, guarded = [], []

    def synth_factory(*a, **k):
        def synth(spoken, out):
            made.append(spoken)
            Path(out).write_text(spoken, encoding="utf-8")
        return synth

    def guard(text, path, synth, heard=None):
        guarded.append((text, heard))
        if text.startswith("一"):                 # 1行目の聞き直しで「施工」の読みを覚えた
            learned["施工"] = "せこう"
            synth(VM.read_text(text), path)
        return []

    def apply_dict(s):
        for w, k in learned.items():
            s = s.replace(w, k)
        return s
    with tempfile.TemporaryDirectory() as tmp:
        items = [(t, Path(tmp) / f"v{i}.mp3", None, None, None)
                 for i, t in enumerate(["一つ目は施工です。", "二つ目も施工です。", "三つ目です。"])]
        with _patched(VM, _synth=synth_factory), \
                _patched(YG, available=lambda: True, guard=guard, apply_dict=apply_dict,
                         hear_many=lambda paths: {i: f"先に聞いた{i}" for i in range(len(paths))}):
            VM.say_many(items, workers=3)
            second = (Path(tmp) / "v1.mp3").read_text(encoding="utf-8")
    check("聞き直しは全行・台本の順", [t for t, _ in guarded], [t for t, *_ in items])
    check("先に聞いた書き起こしを使う（作り直していない行だけ）", [h for _, h in guarded], ["先に聞いた0", None, "先に聞いた2"])
    check("1行目で覚えた読みで2行目の声を作り直す", "せこう" in second, True)


def test_render_pastes_only_what_is_visible():
    print("\n■ 描画: 透明な余白を落として貼っても、コマは1画素も変わらない")
    from PIL import Image, ImageDraw
    import duo_video as DV
    base = Image.new("RGB", (640, 360), (240, 243, 249))
    ImageDraw.Draw(base).line([(0, 0), (640, 360)], fill=(10, 20, 30), width=9)
    lay = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle([90, 250, 560, 340], 20, fill=(255, 255, 255, 242), outline=(27, 42, 74, 255), width=5)
    d.text((120, 270), "字幕", fill=(20, 26, 38, 255))
    a, b = base.copy(), base.copy()
    a.paste(lay, (0, 0), lay)
    crop, x, y = DV.crop_layer(lay)
    b.paste(crop, (x, y), crop)
    check("全体を貼った絵と、余白を落として貼った絵が同じ", a.tobytes() == b.tobytes(), True)
    check("貼る面積が減る", crop.size[0] * crop.size[1] < lay.size[0] * lay.size[1] / 4, True)
    for n in ("duo_video", "duo_short"):
        s = (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
        body = s.split("def make(", 1)[1]
        check(f"{n}: 字幕・キャラクターは余白を落とした絵を貼る（画面全体の透明な板を毎コマ貼らない）",
              ("crop_layer(" in body, "frame.paste(sub_cache[sk], (0, 0), sub_cache[sk])" in body), (True, False))
        check(f"{n}: 字幕の区切りと読みの重みはセリフごとに1回", "line_cs[i] = (" in body, True)
        check(f"{n}: 声は say_many（同時に作る・聞き直しは順に）", "VM.say(" not in body, True)


def _step(wf, name):
    m = re.search(r"- name: " + re.escape(name) + r".*?\n(.*?)(?=\n      - (?:name|uses):|\Z)", wf, re.S)
    return m.group(1) if m else ""


def test_article_slot_does_not_wait_or_repeat():
    print("\n■ 記事の枠: 固定の待ち・順番待ちのインストール・同じ検査の2回実行・claude の自前コミットをやめる")
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    live = _step(wf, "本番に届いたかの確認")
    check("本番の確認: 固定の sleep 45 が無く、新しい版を返すまで短い間隔で確かめる（上限つき）",
          ("sleep 45" in live, "deadline=" in live and "deploy_check.py) && break" in live), (False, True))
    deps = _step(wf, "依存インストール")
    check("依存: pip・apt・npm を同時に入れ、どれか失敗したら止める",
          (deps.count(" & p") == 3, "wait $p1 ||" in deps and "wait $p3 ||" in deps, '[ "$ok" = 1 ] || exit 1' in deps),
          (True, True, True))
    check("依存: yt-dlp もまとめて入れる（一次情報の工程で入れ直さない）",
          ("yt-dlp" in deps, "pip install --quiet yt-dlp" in _step(wf, "一次情報の収集")), (True, False))
    brief = _step(wf, "執筆ブリーフの表示")
    # お客様の社の案内はログに出さない（2026-10-10 守秘義務・h76）。ファイルへ書き、失敗はそのまま工程を落とす
    check("ブリーフ: 出力を claude が読むファイルに残す（失敗は隠さない）",
          ("> automation/logs/brief.txt" in brief, "|| true" in brief.split("> automation/logs/brief.txt")[0][-200:]),
          (True, False))
    check("カニバリ・食い合いゲートの結果も同じファイルへ",
          (">> automation/logs/brief.txt" in _step(wf, "全サイト横断のカニバリ・領域チェック"),
           ">> automation/logs/brief.txt" in _step(wf, "食い合いゲート（執筆前）")), (True, True))
    check("書き直しの回は、古くなったブリーフを使わせない", "rm -f automation/logs/brief.txt" in _step(wf, "記事生成（Phase 1〜7）"), True)
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("ブリーフのファイルはコミットされない（automation/logs/ は .gitignore）", "automation/logs/*" in gi, True)
    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("執筆の指示: ブリーフのファイルを読み、同じコマンドを実行し直さない（無いときだけ実行）",
          ("automation/logs/brief.txt" in pr, "同じコマンドを実行し直さない" in pr, "無いときだけ自分で site_brief.py" in pr),
          (True, True, True))
    check("執筆の指示: 食い合いゲートが替えた語を使う", "ゲートの語を採用する" in pr, True)
    check("執筆の指示: このリポジトリの commit・push はしない（後の工程が未コミットの新しい記事を探す）",
          "git commit・push はしない" in pr, True)
    link = _step(wf, "公開直後に既存記事から新記事へリンクを張る")
    check("後の工程は未コミットの記事を探している（だから claude にコミットさせない）",
          "git ls-files --others --exclude-standard articles/*.md" in link, True)
    check("執筆の指示: CLAUDE.md を読み直さない（起動時に読み込まれている）", "Read で読み直さない" in pr, True)
    # 検査そのものは残す（速くするために外していない）
    for name in ("食い合いゲート（執筆前）", "食い合いゲート（執筆後）", "公開前に、機械で直せる崩れを直す", "監修待ちを知らせる"):
        check(f"検査の工程が残っている: {name}", bool(_step(wf, name)), True)
