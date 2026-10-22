"""伸びている記事を直しから守り、需要のある弱い記事から直す（2026-10-22 運用者「今までの記事の質が悪いので
改善の方向に向かうように。但し伸びているものは変えるとまずい。ちゃんと判断して」）。

棚卸し（2026-10-22・公開済み450本）: 書いた本人の採点は445本が90点以上だったが、別工程の抜き取り（22本）は平均71点。
公開35日以上の約320本のうち、28日の表示が10回未満が約200本。直す順を検索の実績で決め、伸びている記事は触らない。
"""
from test_gates import check, ROOT


def test_classify_and_protect():
    import article_health as AH
    print("\n■ 記事の調子: 伸びている・読まれている記事は守り、落ちている・表示はあるが弱い記事から直す")
    c = AH.classify
    check("分け方（若い・伸びている・読まれている・落ちている・弱い・ほぼ表示なし）",
          [c([100, 0, 20], [50, 0, 25], 10),       # 公開35日未満は判定しない
           c([100, 0, 20], [50, 0, 25], 60),       # 表示が2倍 → 伸びている
           c([40, 0, 9], [40, 0, 15], 60),         # 順位が6上がった → 伸びている
           c([200, 5, 8], [210, 6, 8], 60),        # クリック5 → 読まれている
           c([20, 0, 25], [80, 0, 20], 60),        # 80→20 → 落ちている
           c([15, 0, 30], [12, 0, 31], 60),        # 表示はあるが弱い
           c([2, 0, 50], [3, 0, 50], 60)],         # ほぼ表示なし
          ["young", "growing", "growing", "read", "falling", "weak", "dormant"])
    old = AH.of
    try:
        AH.of = lambda slug, site=None, meta=None: {"g": "growing", "r": "read", "f": "falling"}.get(slug)
        got = (AH.protected("g", "aio"), AH.protected("r", "title"), AH.protected("r", "aio"),
               AH.protected("f", "title"), AH.protected("x", "title"))
        kept = [x["slug"] for x in AH.drop_protected([{"slug": s, "kind": "stuck"} for s in ("g", "r", "f", "x")])]
    finally:
        AH.of = old
    check("伸びている記事には何も当てない・読まれている記事は足すだけの直し（aio・fresh）だけ・判定できない記事は止めない",
          got, (True, True, False, False, False))
    check("書き直しの候補から守る記事を外す", kept, ["f", "x"])


def test_loops_use_the_health():
    print("\n■ 採点し直しと書き直しが記事の調子を見る（名指しの書き直しは運用者の判断なので外さない）")
    ql = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    ar = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    rt = (ROOT / "scripts" / "rank_track.py").read_text(encoding="utf-8")
    check("採点し直しは守る記事を外し、調子の順（落ちている → 弱い → ほぼ表示なし）に並べる",
          ('if AH.protected(s, "quality", sid):' in ql, "AH.ORDER.get(health, 2)" in ql), (True, True))
    check("書き直しは名指しの無い回だけ守る記事を外す",
          "    if not a.slugs:\n        # 伸びている記事には何も当てず" in ar and "article_health.drop_protected(items, a.kind)" in ar, True)
    check("毎晩の順位の記録がページ単位の28日×2期間も残す（語×ページはクリックを取りこぼす）",
          ('def fetch_pages(' in rt, '{sid}.pages.json' in rt), (True, True))
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    cp = (ROOT / "scripts" / "client_private.py").read_text(encoding="utf-8")
    check("お客様の分は公開側に置かずキャッシュで持ち越す・自社の分はコミットする",
          ('"data/ranks/{}.pages.json"' in cp, "!data/ranks/ai-lab.pages.json" in gi), (True, True))
