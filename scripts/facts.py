# -*- coding: utf-8 -*-
"""記事に使える一次情報を出す（自社実績＋自サイトの実測データ）

使い方: python scripts/facts.py <site_id> [KW]

AI検索が最も引用したがるのは「そこにしかない数値」。外部統計の引き写しだけでは
どのサイトでも書ける記事になり、引用先に選ばれない。
自社実績と自サイトのGSC実測を、出典と時点つきで提示する。
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "first_party_facts.json"
RANKS = ROOT / "data" / "ranks"
# これ未満の表示回数は、増減が偶然と区別できない。記事に数字として書かない
MIN_IMP = 20


def own_data_facts(site_id):
    """自サイトの実測から言えること（記事に書ける形にして返す）"""
    f = RANKS / f"{site_id}.json"
    if not f.is_file():
        return []
    hist = json.loads(f.read_text(encoding="utf-8"))
    if not hist:
        return []
    rows = hist[sorted(hist)[-1]]
    if not rows:
        return []
    total = sum(r["imp"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    top10 = len([r for r in rows if r["pos"] <= 10])
    # 自社の数字は、実績として読まれるものだけ出す。
    # 立ち上げ期に「クリック0回」を記事へ書くと、読者には実力が無いと映る。
    # 嘘は書かないが、弱い数字をわざわざ公表する必要もない。
    out = []
    if clicks >= 10 or top10 >= 3:
        out.append({
            "id": "own-gsc",
            "claim": f"当サイトの実測では、直近28日で{len(rows)}個の検索語から"
                     f"のべ{total:,}回表示され、{clicks}回のクリックがありました",
            "source": "自社サイトのSearch Console実測",
            "as_of": date.today().strftime("%Y-%m"), "verifiable": True,
        })
    else:
        out.append({
            "id": "own-gsc-qualitative",
            "claim": "当サイトはAIO対策の実装内容と検索での見え方を日次で計測しており、"
                     "順位・表示回数・クリックの動き方の順序を自社データで確認しています",
            "source": "自社サイトのSearch Console計測",
            "as_of": date.today().strftime("%Y-%m"), "verifiable": True,
        })
    return out


def _tokens(s):
    """語を比べるための単位に割る。2字未満は共通語が多すぎて当たらない"""
    import re
    return {w for w in re.split(r"[\s　/・,、。（）()【】\[\]|｜]+", (s or "").lower())
            if len(w) >= 2}


def own_query_facts(site_id, kw="", days=40):
    """その記事の語について、自サイトが実際に測った数字を返す。

    全記事に同じ「3,200店舗」を書いても、記事ごとの独自性にはならない。
    実測では126本（37%）が同じ数字を載せていた。同じ一文が並ぶだけで、
    その記事にしかない情報として扱われない。

    自サイトのGSC実測は記事ごとに違う。「この語が何位で、何回表示され、
    何回クリックされたか」は、ほかのどのサイトも書けない。
    出典と時点を必ず添え、少ない表示回数のものは出さない（偶然と区別できない）。
    """
    f = RANKS / f"{site_id}.json"
    if not f.is_file() or not kw:
        return []
    try:
        hist = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    if not hist:
        return []
    latest = sorted(hist)[-1]
    rows = [r for r in hist[latest] if r.get("imp", 0) >= MIN_IMP]
    if not rows:
        return []

    want = _tokens(kw)
    near = [(len(want & _tokens(r["kw"])), r) for r in rows]
    near = sorted([(n, r) for n, r in near if n], key=lambda x: (-x[0], -x[1]["imp"]))
    out = []

    if near:
        r = near[0][1]
        # 同じ事実でも、書き方で意味が変わる。
        # 「クリック0回でした」は自社が無力に見えるだけで、読者の役に立たない。
        # 上位に出ているのにクリックが無いのは「検索結果で答えが済む語」だという
        # 観察であり、そちらを書けば読者の判断材料になる。数字は変えない。
        if r["clicks"] == 0 and r["pos"] <= 10.5:
            claim = (f"当サイトの実測では、「{r['kw']}」は平均{r['pos']:.1f}位に表示されながら、"
                     f"{r['imp']}回の表示でクリックが発生しませんでした。"
                     f"検索結果の時点で答えが済む語だと考えられます")
        elif r["clicks"] == 0:
            claim = (f"当サイトの実測では、「{r['kw']}」は平均{r['pos']:.1f}位で"
                     f"{r['imp']}回表示されました。1ページ目に届くまでは"
                     f"クリックがほとんど発生しません")
        else:
            claim = (f"当サイトの実測では、「{r['kw']}」は平均{r['pos']:.1f}位で"
                     f"{r['imp']}回表示され、{r['clicks']}回クリックされました"
                     f"（クリック率{r['ctr']:.1f}%）")
        out.append({
            "id": "own-query", "claim": claim,
            "source": "自社サイトのSearch Console実測（直近28日）",
            "as_of": latest[:7], "verifiable": True,
        })

    # 同じ順位帯でクリック率が分かれた例。順位ではなく語の性質で決まることを、
    # 自社の数字で示せる。外部の一般論ではなく実測なので、引用の対象になりやすい
    band = [r for r in rows if 3.5 < r["pos"] <= 10.5]
    if len(band) >= 4:
        band.sort(key=lambda r: -r["ctr"])
        hi, lo = band[0], band[-1]
        if hi["ctr"] - lo["ctr"] >= 3:
            out.append({
                "id": "own-ctr-gap",
                "claim": f"当サイトの実測では、同じ4〜10位でも「{hi['kw']}」は"
                         f"クリック率{hi['ctr']:.1f}%、「{lo['kw']}」は{lo['ctr']:.1f}%と"
                         f"差が出ました。順位より検索語の性質がクリックを左右します",
                "source": "自社サイトのSearch Console実測（直近28日）",
                "as_of": latest[:7], "verifiable": True,
            })
    return out


def load_for(site_id):
    """そのサイトで使ってよい一次情報だけを返す。

    受託運用では、クライアントの記事に自社（運用会社）の実績を書くと
    事実と違う記事になる。クライアント用の登録がある場合は、そちらだけを
    使い、自社分は混ぜない。
    """
    def read(path):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
        except (ValueError, OSError) as e:
            print(f"  （{path.name} を読めませんでした: {e}）")
            return None

    client = ROOT / "data" / "clients" / site_id / "facts.json"
    if client.is_file():
        d = read(client)
        if d is not None:
            return d, list(d.get("facts", []))
        # 読めないときに自社の一次情報へ落とすと、他社の実績を書いてしまう
        return {"facts": []}, []
    data = read(SRC) if SRC.is_file() else {"facts": []}
    if data is None:
        return {"facts": []}, []
    return data, [f for f in data.get("facts", []) if site_id in f.get("sites", [])]


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/facts.py <site_id> [KW]")
    site_id = sys.argv[1]
    kw = sys.argv[2] if len(sys.argv) > 2 else ""

    data, picked = load_for(site_id)
    if kw:
        # KWに関係するものを先に出す（関係ないファクトを無理に入れると不自然になる）
        picked.sort(key=lambda f: -sum(1 for t in f["topic"] if t in kw))
    # その記事にしかない数字を先に出す。同じ「3,200店舗」を全記事に書いても
    # 記事ごとの独自性にはならない（実測で126本が同じ数字を載せていた）
    picked = own_query_facts(site_id, kw) + picked + own_data_facts(site_id)

    print(f"■ {site_id} で使える一次情報（記事に最低1つ入れること）")
    for f in picked:
        print(f"\n  ・{f['claim']}")
        print(f"    出典: {f['source']}（{f['as_of']}時点）")
    if data.get("pending"):
        print("\n  ＜まだ書けない数値＞")
        for p in data["pending"]:
            print(f"    - {p['note']}")
    print("\n  ※ ここに無い自社数値は書かないこと。確認できない数値は信頼を失う")


if __name__ == "__main__":
    main()
