# -*- coding: utf-8 -*-
"""2026-11-24 運用者「出し直しの不具合も直して」。お客様の社の記事1本が1週間に3〜5回出し直されていた。
新しい記事を公開するたびに link_new が既存の記事へリンクだけの段落を足し、週次の auto_review --fix が上限
（MAX_LINK_PARA）を超えた分を削り、次の公開でまた足していた。足す道具（link_new・auto_improve・priority_boost）は
見直しの上限に達した記事へ足さないこと。言い回しの選び方は実行ごとに変わらないこと。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _md(title, n_links):
    paras = "\n\n".join(f"近い論点を[記事{i}](/column/x{i}/)で扱っています。" for i in range(n_links))
    return (f"---\ntitle: {title}\n---\n## 経理BPOの費用の内訳\n\n本文です。費用の内訳を説明します。\n\n"
            f"## 経理BPOの費用の失敗\n\n本文です。\n\n{paras}\n\n## まとめ\n\n本文です。\n")


def test_link_tools_respect_review_cap():
    import auto_review as ar
    import inbound_links as il
    import link_new as ln
    print("\n■ 内部リンク: 足す道具は週次の見直しの上限に達した記事へ足さない（足しては削るの出し直しを止める）")
    arts = {
        "full": {"title": "経理BPOの費用の相場", "kw": "経理BPO 費用", "url": "/column/full/", "out": []},
        "room": {"title": "経理BPOの費用の内訳", "kw": "経理BPO 費用 内訳", "url": "/column/room/", "out": []},
        "new": {"title": "経理BPOの費用の比較", "kw": "経理BPO 費用 比較", "url": "/column/new/", "out": []},
    }
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "articles"
        d.mkdir()
        (d / "full.md").write_text(_md("経理BPOの費用の相場", ar.MAX_LINK_PARA), encoding="utf-8")
        (d / "room.md").write_text(_md("経理BPOの費用の内訳", 1), encoding="utf-8")
        (d / "new.md").write_text(_md("経理BPOの費用の比較", 0), encoding="utf-8")
        check("前提: 上限ちょうどの記事を見直しが数える", len(ar.scan(d / "full.md")[2]), ar.MAX_LINK_PARA)
        with mock.patch.object(ln, "ROOT", Path(td)), mock.patch.object(il, "load_articles", lambda s: arts):
            got = ln.send_links("xco", ["new"], want=2, dry=True, quiet=True)
        check("link_new: 上限に達した記事へは足さず、余裕のある記事へだけ足す", sorted(got), ["room"])
    src = {n: (ROOT / "scripts" / n).read_text(encoding="utf-8") for n in ("auto_improve.py", "priority_boost.py", "link_new.py")}
    check("auto_improve・priority_boost も見直しの上限を見てから足す",
          [n for n in ("auto_improve.py", "priority_boost.py") if "ar.MAX_LINK_PARA" not in src[n]], [])
    check("言い回しの種に、実行ごとに変わる hash() を使わない（link_new・auto_review の振り直し）",
          [n for n, t in (("link_new.py", src["link_new.py"]),
                          ("auto_review.py", (ROOT / "scripts" / "auto_review.py").read_text(encoding="utf-8")))
           if "hash(s)" in t or "hash(p.stem)" in t], [])
