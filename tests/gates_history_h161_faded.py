# -*- coding: utf-8 -*-
"""2026-11-12 3サイトで直近28日の表示が0の記事は107本あったが、統合の候補（公開90日以上・90日の表示0）に
当てはまるのは2本だけだった。残りは「公開から約1か月だけ表示され、その後消えた」記事で、
調子の判定は「ほぼ表示なし＝後回し」、統合は「一度も出ない記事だけ」と、どの手当ても拾っていなかった"""
import sys
from datetime import date

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_faded_articles_become_merge_candidates():
    import retire_stale as RS
    print("\n■ 消えた記事の整理: 公開60日以上・直近28日の表示0・90日のクリック0 を統合の候補にする")
    today = date(2026, 11, 12)
    u = "https://x.example/blog/a/"
    old, young = {"date": "2026-08-20"}, {"date": "2026-10-20"}
    check("公開から約1か月だけ表示されて消えた記事（いま表示なし・クリックなし）は候補", RS.faded(old, u, set(), set(), today), True)
    check("いま表示がある記事は候補にしない", RS.faded(old, u, {u}, set(), today), False)
    check("90日にクリックがあった記事（読まれた実績）は候補にしない", RS.faded(old, u, set(), {u}, today), False)
    check("公開60日未満は候補にしない（順位が落ち着く前に統合しない）", RS.faded(young, u, set(), set(), today), False)
    check("公開日の無い記事は候補にしない", RS.faded({"date": ""}, u, set(), set(), today), False)
    check("日数の決まり（公開60日・表示28日・クリック90日）と、近さの下限",
          (RS.AGE_DAYS, RS.WINDOW_DAYS, RS.CLICK_DAYS, RS.MIN_SIM >= 0.3), (60, 28, 90, True))
    src = (ROOT / "scripts" / "retire_stale.py").read_text(encoding="utf-8")
    check("近い記事がはっきりある組から先に統合する", 'return sorted(out, key=lambda r: -r["sim"])' in src, True)
    check("一次性の整理（--quality）は今までどおり90日の実績で見る", "stats_by[sid] = page_stats(cfg)" in src, True)
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週の本数は増やさない（2本まで。統合は AI が書き、検算に外れたら戻す）", "retire_stale.py --write --limit 2" in wk, True)
