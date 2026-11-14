"""1位を狙う語の台帳の検索の量を、ラッコの一括調査で1回取り、量が0の語を台帳から外す（2026-11-15 運用者「取ってよい」）。
台帳120語のうち114語は量が分からず、量の無い語に記事を寄せても集客にならない。一括調査は500語で15クレジット。
kw_plan と同じ控え（data/rakko_volume.json・90日）と同じ枠（一括検索数）を使い、別の課金の道を作らない"""
import re
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def test_ledger_volume_lookup_and_zero_drop():
    import key_queries as K
    print("\n■ 台帳: 量の分からない語だけをラッコの一括調査で1回取り、量が0の語を外す")
    import sites as S
    cfg = S.load("ai-lab")
    base = K.build_ledger(cfg, {}, [], {}, {}, today="2026-11-15")
    qs = [r["q"] for r in base]
    check("検出器の前提: 量が無くても組み合わせの語で台帳ができる", len(qs) > 20, True)
    zero, keep = qs[0], qs[1]
    rows = K.build_ledger(cfg, {}, [], {}, {K.norm(zero): 0, K.norm(keep): 320}, today="2026-11-15")
    got = {r["q"]: r for r in rows}
    check("量が0と分かった語は台帳から外す", zero in got, False)
    check("量の分かった語は残し、出どころを rakko にする", (got.get(keep) or {}).get("vol_src"), "rakko")
    check("量が分からない語は外さない（調べる前に捨てない）", qs[2] in got, True)

    raw = {"a": {"vol": 0, "answered": True}, "b": {"vol": None, "answered": True}, "c": {"vol": 90},
           "d": {"vol": None}}
    check("控えの読み方: 調べて量が無かった語は0、調べていない語は数えない",
          K.volumes(raw), {"a": 0, "b": 0, "c": 90})

    calls = []

    class FakeRakko:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def allow(site, est, dry=False, purpose="reserve"):
            calls.append(("allow", site, est))
            return True

    class FakePlan:
        @staticmethod
        def fill_volume(cands):
            calls.append(("fill", sorted(c["kw"] for c in cands.values())))
            return len(cands)

    rows = [{"q": "x 外注", "vol_src": "なし"}, {"q": "y 費用", "vol_src": "gsc"}, {"q": "z 会社", "vol_src": "なし"}]
    n = K.lookup_volumes("ai-lab", rows, rakko=FakeRakko, plan=FakePlan)
    check("調べるのは量の分からない語だけ", [c for c in calls if c[0] == "fill"], [("fill", ["x 外注", "z 会社"])])
    check("課金の前に一括検索数の枠（volume・15クレジット）で allow を通す",
          [c for c in calls if c[0] == "allow"], [("allow", "ai-lab", {"volume": 15})])
    check("調べた数を返す", n, 2)
    calls.clear()
    check("量の分からない語が無ければラッコを呼ばない",
          (K.lookup_volumes("ai-lab", [{"q": "y", "vol_src": "rakko"}], rakko=FakeRakko, plan=FakePlan), calls), (0, []))

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    m = re.search(r"- name: 11〜30位で止まっている記事へ内部リンクを寄せる\n(.*?)\n      - name:", wf, re.S)
    check("週次の台帳の工程にラッコの鍵を渡している", bool(m and "RAKKO_API_KEY" in m.group(1)), True)
