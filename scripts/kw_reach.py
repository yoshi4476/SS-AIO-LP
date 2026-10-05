# -*- coding: utf-8 -*-
"""語が「公開1〜4週のうちに15位以内に入れそうか」を点にする（狙う語を選ぶとき・次に書く語を選ぶときに使う）。

**なぜ要るか**（2026-10-05 の3サイトの分析）: 記事は公開1〜3週で表示の山、6週で山の約1/4に落ちる。
6週以降も残った記事は、公開1〜4週に「ある語で15位以内（3回以上表示）」に入っていた
（入った11本中5〜7本が残る／入らなかった28本中3〜5本）。山の週の平均順位が20位より下の記事
（「aio対策」「士業 seo」のような広い語）は消えた。残った記事の6週目以降の表示の73%は、
1〜4週から出ていた細い語（「ai導入 中小企業 費用」「経理 代行 個人事業」）だった。
一方、開く理由の強さ（kw_intent）は残るかどうかと差が無かった。

点の中身（-2〜+2。重みは呼び出し側で控えめに掛ける。買い手の語（+3）を上回らせない）:
  広い語を下げる  … 語が1つだけ／検索数が大きい／SEO難易度が高い
  細い語を上げる  … 3語以上／「費用」「書き方」などの条件を含む（業種名は3語以上の語でだけ数える）
  近い主題を上げる … 自サイトが既に15位以内（3回以上表示）を持つ語と、語を2つ以上共有する

  python scripts/kw_reach.py "aio対策" "工務店 meo 費用 相場" --site ai-lab
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANKS = ROOT / "data" / "ranks"
NEAR_POS, NEAR_IMP = 15, 3      # 分析で「残る」を分けた線（15位以内・3回以上表示）
LO, HI = -2.0, 2.0

# 具体的な条件。答えが1つに絞られ、上位の顔ぶれが大手のまとめ記事になりにくい
SPECIFIC = re.compile(
    r"費用|料金|相場|いくら|見積|内訳|書き方|やり方|手順|方法|進め方|始め方|事例|期限|締切|いつから|"
    r"条件|対象|要件|違い|比較|選び方|注意点|失敗|できない|上がらない|出ない|表示されない|"
    r"個人事業|中小企業|小規模|一人|開業|自分で|無料|地方|地域|エリア")
# 業種名。「士業 seo」「工務店 seo」のような2語は業種×手法の見出し語で、上位はまとめ記事が占める
# （分析で消えた側）。業種名は3語以上の語でだけ具体さに数える
INDUSTRY = re.compile(r"クリニック|歯科|整骨院|接骨院|不動産|工務店|リフォーム|住宅|飲食店|美容室|士業|"
                      r"税理士|社労士|建設業|製造業")


def _industry_words(cache={}):
    """data/industries.json の業種名と言い換え。業種名を含む語は主題が絞られている"""
    if "w" not in cache:
        words = []
        try:
            d = json.loads((ROOT / "data" / "industries.json").read_text(encoding="utf-8"))
            for ind in d.get("industries") or []:
                words += [ind.get("name", "")] + list(ind.get("synonyms") or [])
        except (OSError, ValueError):
            pass
        cache["w"] = [w.lower() for w in words if len(w) >= 2]
    return cache["w"]


def tokens(kw):
    """空白で割った語。空白の無い自然文（「請求書の書き方」）は助詞で割る"""
    parts = [t for t in re.split(r"[\s　]+", str(kw).lower().strip()) if t]
    if len(parts) == 1 and len(parts[0]) >= 4:
        sub = [t for t in re.split(r"[のをでにへはが]", parts[0]) if len(t) >= 2]
        if len(sub) >= 2:
            return sub
        # 空白の無い複合語に条件の語が付いている（「経費精算書書き方例」）なら、主題＋条件の2語とみなす
        m = SPECIFIC.search(parts[0])
        if m and len(parts[0]) - len(m.group(0)) >= 2:
            return [parts[0][:m.start()] or parts[0][m.end():], m.group(0)]
    return parts


def specific(kw):
    """具体的な条件を含むか。業種名は3語以上の語でだけ数える"""
    low = str(kw).lower()
    if SPECIFIC.search(low):
        return True
    return len(tokens(kw)) >= 3 and (bool(INDUSTRY.search(low)) or any(w in low for w in _industry_words()))


def near(kw, held):
    """自サイトが15位以内を持つ語（held）と、語を2つ以上共有するか。同じ語そのものは数えない
    （同じ語は食い合いの検査が受け持つ）"""
    mine = {t for t in tokens(kw) if len(t) >= 2}
    if len(mine) < 2:
        return False
    flat = re.sub(r"\s", "", str(kw).lower())
    for q in held:
        if re.sub(r"\s", "", q.lower()) == flat:
            continue
        if len(mine & {t for t in tokens(q) if len(t) >= 2}) >= 2:
            return True
    return False


def held_queries(site_id):
    """data/ranks/<site>.json の最新の28日（rank_track が毎日残す）で、15位以内・3回以上表示の語。
    Search Console を呼ばない（次に書く語を選ぶ記事CIでも、課金・鍵なしで使える）"""
    f = RANKS / f"{site_id}.json"
    try:
        hist = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not hist:
        return []
    rows = hist[sorted(hist)[-1]]
    return sorted({r["kw"] for r in rows
                   if (r.get("pos") or 99) <= NEAR_POS and (r.get("imp") or 0) >= NEAR_IMP and r.get("kw")})


def reach(kw, vol=None, kd=None, held=()):
    """15位以内に入れそうかの点（-2〜+2）"""
    n = len(tokens(kw))
    s = -1.0 if n <= 1 else (0.6 if n >= 3 else 0.0)
    # 条件の語で割っただけの複合語（「中小企業補助金」）は、その条件を2語目として数えた。重ねて足さない
    compound = len(re.split(r"[\s　]+", str(kw).strip())) == 1 and not re.search(r"[のをでにへはが]", str(kw))
    if n >= 2 and specific(kw) and not compound:
        s += 0.5
    if vol is not None:
        s -= 0.8 if vol >= 5000 else 0.4 if vol >= 1000 else 0.0
    if kd is not None:
        s -= 0.6 if kd >= 50 else 0.3 if kd >= 30 else 0.0
    if held and near(kw, held):
        # +1.0 だと「請求書 封筒 書き方」（自分でやる・5,400/月）が「経理代行 費用 相場」（外注を考える）を
        # 上回り、買い手の語を先に置く決まり（kw_plan）が崩れた。崩れない幅にとどめる
        s += 0.6
    return round(max(LO, min(HI, s)), 2)


def band(pts):
    """並べ替えに使う段（1=届きそう / 0=並 / -1=広い）。台帳の語には検索数が無いので、段で粗く分ける"""
    return 1 if pts >= 0.5 else (-1 if pts <= -0.5 else 0)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kw", nargs="+")
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    held = held_queries(a.site) if a.site else []
    for kw in a.kw:
        p = reach(kw, held=held)
        print(f"{p:+.2f} 段{band(p):+d}  {kw}" + ("  （近い語で15位以内あり）" if held and near(kw, held) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
