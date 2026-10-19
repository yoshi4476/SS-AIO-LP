# -*- coding: utf-8 -*-
"""指名検索（社名・サービス名・人名での検索）の伸びを測る。

AIO型のメディアをクリック率で測ると、構造上かならず低く出る。
実測で、AI集客ラボは順位相応のクリックの15%しか取れていなかった。
主題（AIO・SEO・MEO）がAI Overviewの出る領域で、検索結果の時点で
用が済む語ばかりだったため。表示20回以上の23語に「開かないと済まない語」が
1つも無かった。

一方で指名検索は28日で11→38表示（+245%）に伸びていた。
CLAUDE.md が設計方針に置いている「引用でブランド認知 → 指名検索 → CV」が
実際に起きている。**クリック率ではなくこちらを主指標にする。**

  python scripts/brand_search.py            # 直近28日と、その前の28日を比べる
  python scripts/brand_search.py --days 14
  python scripts/brand_search.py --list     # どの語で検索されたかを出す
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 指名検索とみなす語。社名・サービス名・人名のゆれを吸収する。
# ここに一般語（AIO、集客など）を入れてはいけない。指名でない検索が混ざると、
# 伸びているように見えて実態が分からなくなる
BRAND = re.compile(
    r"セブンセンシズ|せぶんせんしず|7\s*senses|seven\s*senses|"
    r"原口\s*優|原口優|haraguchi|"
    r"g-?ran|ジーラン|"
    r"ラクシフト|rakushift|"
    r"ai集客ラボ|AI集客ラボ",
    re.I)


CORP = re.compile(r"株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|医療法人(?:社団|財団)?|"
                  r"社会福祉法人|特定非営利活動法人|NPO法人|[（(]株[）)]|㈱|[（(]有[）)]|㈲|\s")
LAST_FAILED = []      # 直前の collect() で GSC から取れなかった社（呼び出し側が「減っていない」と読まないため）


def pattern_for(site_id):
    """その社の指名検索の語。自社は BRAND、お客様の社は company.json の社名（法人の種類を外した部分）。
    作れなければ None（その社の指名検索は出さない）。
    全社に当社の語（セブンセンシズ・AI集客ラボ）を当てていたため、お客様のレポートの「指名検索」は
    お客様の社名ではなく当社の名前の検索を数えていた（2026-10-20）"""
    import sites as S
    if not S.is_client(site_id):
        return BRAND
    try:
        import private_store
        name = (private_store.read_json(site_id, "company.json", {}) or {}).get("name") or ""
    except Exception:
        name = ""
    core = CORP.sub("", name)
    return re.compile(re.escape(core), re.I) if len(core) >= 2 else None


def shown(site_id, cfg):
    """ログに出す社の名前。お客様の社は公開の id（CI のログは public）"""
    import sites as S
    return S.public_id(site_id) if S.is_client(site_id) else cfg.get("name", site_id)


def collect(days=28, only=None):
    """{社の id: {name, prev, cur, span}}。only を渡すとその社だけ GSC に聞く。
    取れなかった社は入れず LAST_FAILED に残す。指名の語が作れないお客様の社は入れない（失敗ではない）"""
    import gsc_detail as G
    import sites as S
    del LAST_FAILED[:]
    sc = G.client()
    end = date.today() - timedelta(days=3)          # GSCの確定分
    cur = (end - timedelta(days=days - 1), end)
    prev = (cur[0] - timedelta(days=days), cur[0] - timedelta(days=1))
    out = {}
    for sid, cfg in S.load_all().items():
        if only and sid not in only:
            continue
        pat = pattern_for(sid)
        if pat is None:
            continue
        got = []
        for a, b in (prev, cur):
            try:
                rows = G.q(sc, cfg["domain"], str(a), str(b), ["query"], 25000,
                           raise_errors=True)
            except Exception:
                # 取れなかった期を0と数えると「指名検索が減った」と誤って知らせる。そのサイトごと外す
                got = None
                LAST_FAILED.append(sid)
                break
            hit = [r for r in rows if pat.search(r["keys"][0])]
            got.append({
                "imp": sum(r["impressions"] for r in hit),
                "clicks": sum(r["clicks"] for r in hit),
                "words": len(hit),
                "rows": sorted(hit, key=lambda r: -r["impressions"]),
            })
        if got is None:
            continue
        out[sid] = {"name": shown(sid, cfg), "prev": got[0], "cur": got[1],
                    "span": (str(cur[0]), str(cur[1])), "client": S.is_client(sid)}
    return out


def growth(a, b):
    if not a:
        return "新規" if b else "―"
    return f"{(b / a - 1) * 100:+.0f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--list", action="store_true", help="検索された語を出す")
    a = ap.parse_args()

    # 取れなかった回に BRAND_OK の印を出さずに終わると、findings は「問題なし」と読んでいた（2026-10-20）
    try:
        d = collect(a.days)
    except Exception as e:
        print(f"  GSCに接続できませんでした（{type(e).__name__}）")
        print("BRAND_OK=unknown")
        return 0
    if not d:
        print("  GSCから取得できませんでした")
        print("BRAND_OK=unknown")
        return 0
    span = list(d.values())[0]["span"]
    print(f"■ 指名検索の推移（{span[0]} 〜 {span[1]} と、その前の{a.days}日）\n")
    print(f"  {'サイト':<20}{'前期':>14}{'今期':>14}{'伸び':>8}")
    print("  " + "-" * 58)
    ti = tc = pi = pc = 0
    for sid, v in d.items():
        p, c = v["prev"], v["cur"]
        ti += c["imp"]; tc += c["clicks"]; pi += p["imp"]; pc += p["clicks"]
        print(f"  {v['name'][:18]:<20}{p['imp']:>6}表示/{p['clicks']:>2}ｸﾘｯｸ"
              f"{c['imp']:>6}表示/{c['clicks']:>2}ｸﾘｯｸ{growth(p['imp'], c['imp']):>8}")
    print("  " + "-" * 58)
    print(f"  {'合計':<20}{pi:>6}表示/{pc:>2}ｸﾘｯｸ{ti:>6}表示/{tc:>2}ｸﾘｯｸ"
          f"{growth(pi, ti):>8}")

    if a.list:
        print("\n■ どの語で検索されたか（今期）")
        for sid, v in d.items():
            rows = v["cur"]["rows"]
            if not rows or v.get("client"):        # お客様の社の検索語（社名）はログに出さない
                continue
            print(f"\n  {v['name'][:20]}")
            for r in rows[:8]:
                print(f"    {r['position']:>5.1f}位 表示{r['impressions']:>4} "
                      f"ｸﾘｯｸ{r['clicks']:>2}  {r['keys'][0][:32]}")

    print("\n  ※ AIO型のメディアはクリック率では測れない。検索結果で答えが済む語が"
          "多いため。\n     引用でブランドを知った人が社名で検索し直す動きが、"
          "ここに出る")
    print(f"  BRAND_IMP={ti} BRAND_CLICKS={tc} BRAND_GROWTH={growth(pi, ti)}")

    # 指名検索は「引用でブランドを知った人が社名で検索し直す」動きの代理指標。
    # AI検索での可視性との相関は 0.392 で、被リンク（0.218）の約2倍
    # （Ahrefs・75,000ブランド・2025-12）。減っていれば知らせる対象にする
    if ti < pi:
        print(f"  前の28日より減っています（{pi} → {ti}表示）。"
              "引用が減ったか、外部での言及が止まっている可能性があります")
        print("BRAND_OK=no")
    elif LAST_FAILED:
        # 取れなかった社を外した合計で「減っていない」とは言えない
        print(f"  {len(LAST_FAILED)}社は GSC から取れず、比べられませんでした")
        print("BRAND_OK=unknown")
    else:
        print("BRAND_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
