"""h153: 伸びている記事は伸ばす（2026-11-03 運用者「伸びている記事は伸ばして・伸びていない記事はリライト」）。
伸びている記事の本文は変えない決まり（2026-10-22）はそのままに、外から伸ばす: 話題の合う記事から内部リンクを送り
（送り元にも伸びている記事を使わない）、古くても動画の候補に入れる（毎日の枠の半分まで）"""
import sys

from test_gates import check, ROOT


def test_link_boost_sends_links_to_growing_articles():
    sys.path.insert(0, str(ROOT / "scripts"))
    import link_boost as L
    print("\n■ 伸びている記事へ、本文を変えずに他の記事から内部リンクを送る（被リンクの少ない順・上限つき）")
    health = {"g-few": "growing", "g-many": "growing", "g-full": "growing", "w": "weak", "r": "read"}
    arts = {s: {} for s in health}
    cnt = {"g-few": 1, "g-many": 6, "g-full": L.RESCUE_FLOOR, "w": 0, "r": 0}
    got = L.growing_targets("zz", arts, cnt, of=health.get)
    check("伸びている記事だけを、被リンクの少ない順に（下限に届いた記事は外す）", got, ["g-few", "g-many"])
    many = {f"g{i}": {} for i in range(L.GROWING_MAX + 3)}
    check("1回に送る先は上限まで", len(L.growing_targets("zz", many, {}, of=lambda s: "growing")), L.GROWING_MAX)
    src = (ROOT / "scripts" / "link_boost.py").read_text(encoding="utf-8")
    check("伸びている記事は送り元にもしない（段落の方式・文中リンクの方式とも）",
          ('if growing and grown(src) == "growing"' in src,
           'skip_src={s for s in arts if grown(s) == "growing"}' in src,
           "if src in skip_src" in src), (True, True, True))
    check("効果は effect_ab が種類ごとに測る（link_growing で残す）", src.count('"link_growing"') >= 2, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    line = next((x for x in wf.splitlines() if "--growing" in x), "")
    check("週次で全社に回し、ログは件数の1行だけ（お客様の記事の slug を出さない）",
          ("--write" in line, "tail -1" in line), (True, True))


def test_videos_include_growing_articles():
    sys.path.insert(0, str(ROOT / "scripts"))
    import article_videos as V
    print("\n■ 古くても伸びている記事は動画の候補に入れる（枠の半分まで。残りは新しい記事）")
    src = (ROOT / "scripts" / "article_videos.py").read_text(encoding="utf-8")
    check("古い記事は伸びている記事だけ候補にする", 'if grow and not _growing(p.stem, sid)' in src, True)
    check("伸びている記事は枠の半分まで", '[r for r in rows if r["growing"]][:limit // 2]' in src, True)
    import article_health as AH
    of = AH.of
    try:
        AH.of = lambda *a, **k: (_ for _ in ()).throw(OSError("記録なし"))
        check("順位の記録が読めなければ古い記事は候補にしない（今までどおり）", V._growing("zz-a", "zz"), False)
        AH.of = lambda *a, **k: "growing"
        check("伸びている記事は候補にする", V._growing("zz-a", "zz"), True)
    finally:
        AH.of = of


def test_daily_video_reads_client_ranks():
    print("\n■ 毎日の動画の工程も、お客様の社の順位の記録を戻してから伸びている記事を選ぶ（読むだけ・残さない）")
    wf = (ROOT / ".github" / "workflows" / "daily-video.yml").read_text(encoding="utf-8")
    at, made = wf.find("with: {mode: restore, kinds: ranks}"), wf.find("python scripts/article_videos.py --write")
    check("動画を作る前に順位の記録を戻す", 0 <= at < made, True)
