# -*- coding: utf-8 -*-
"""書く前に、自社ページ同士の食い合いを止めるゲート

公開後に検出しても遅い。順位が割れたあと統合すると、
どちらのページも評価を落として作り直しになる。

実際、タイトル類似80%のゲートは通ったのに、
見出しが8記事と重なって51語・表示484回でクリック0になった記事があった。
タイトルだけを見ても防げない。狙う語・見出し・GSCの実績の3つで判定する。

使い方:
    # Phase 1（KW選定）: 語だけで先に弾く
    python scripts/kw_guard.py "aio診断" --site ai-lab

    # Phase 3（構成確定）: 見出し案まで含めて審査する
    python scripts/kw_guard.py "aio診断" --site ai-lab \
        --title "AIO診断のやり方｜無料チェック8項目" \
        --h2 "AIO診断とは" --h2 "診断でチェックする8つの視点"

終了コード: 0=着手可 / 1=差別化が必要 / 2=着手禁止（既存記事に統合する）
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from cannibal_check import (dice, kw_conflicts, load_articles,  # noqa: E402
                            norm_kw, terms, topic_overlap)

# GSCで既存ページがこの順位以内に入っている語は、すでにそのページのもの
OWNED_POS = 30.0
OWNED_IMP = 5        # 表示がこれ未満は偶然の露出とみなす
TITLE_WARN = 0.55
# 主題の重なり。実際に食い合った組で較正した（全ペアの上位2%が0.20前後）。
# 文章の似かたは弱い指標なので、ここでは止めずに参考として出すだけにする
TOPIC_NOTE = 0.20


def gsc_rows(site_id):
    """直近90日のGSC実績（語×ページ）。取れなければ空を返す

    自サイトだけでなく、グループの全サイトを見る。1サイトだけ見ていたため、
    補助金サイトが「aioコンサルティング」で18.2位を取っている状態に気づかず、
    ラボ側で同じ語を狙う記事を書いてしまった。
    自社どうしの食い合いは、ドメインをまたいでも同じように起きる。
    """
    try:
        import gcreds
        import sites as S
        from googleapiclient.discovery import build as gbuild
        from datetime import date, timedelta
    except Exception:
        return []
    try:
        sc = gbuild("searchconsole", "v1", credentials=gcreds.load(
            ROOT / "indexing-service-account.json",
            ["https://www.googleapis.com/auth/webmasters.readonly"]))
        end = date.today() - timedelta(days=3)
        all_conf = S.load_all()
    except Exception as e:
        print(f"   （GSC照合はスキップ: {type(e).__name__}）")
        return []
    rows = []
    for sid, conf in all_conf.items():
        dom = conf.get("domain")
        if not dom:
            continue
        try:
            r = sc.searchanalytics().query(
                siteUrl="https://" + dom + "/", body={
                    "startDate": str(end - timedelta(days=90)), "endDate": str(end),
                    "dimensions": ["query", "page"], "rowLimit": 5000}).execute().get("rows", [])
        except Exception:
            continue          # 権限の無いプロパティは黙って飛ばす
        for x in r:
            x["_site"] = sid
            x["_own"] = (sid == site_id)
        rows += r
    return rows


def owned(rows):
    """すでに自社ページが順位を持っている語だけに絞る"""
    return [{"q": r["keys"][0], "page": r["keys"][1],
             "pos": r["position"], "imp": r["impressions"],
             "site": r.get("_site", ""), "own": r.get("_own", True)}
            for r in rows
            if r["position"] <= OWNED_POS and r["impressions"] >= OWNED_IMP]


def gsc_owner(kw, own):
    """その語そのものを、すでに取っているページ"""
    n = norm_kw(kw)
    hit = [o for o in own if norm_kw(o["q"]) == n
           or n in norm_kw(o["q"]) or norm_kw(o["q"]) in n]
    return sorted(hit, key=lambda x: x["pos"])


def h2_owner(heading, own):
    """見出し案の主題を、すでに取っているページ

    タイトルと狙う語を差別化しても、見出しが既存記事の主題まで
    伸びていると、そこで食い合う。実際それで51語・表示484回・
    クリック0の記事ができた。見出しは1本ずつ実績に当てる。
    """
    ht = terms(heading)
    if len(ht) < 2:
        return []
    best = {}
    for o in own:
        qt = terms(o["q"])
        if len(qt) < 2 or not qt <= ht:   # 語がすべて見出しに含まれるものだけ
            continue
        k = o["page"]
        if k not in best or o["pos"] < best[k]["pos"]:
            best[k] = o
    return sorted(best.values(), key=lambda x: x["pos"])


def judge(kw, site_id, title="", h2=None, use_gsc=True):
    """着手可否を返す。(終了コード, 見出し, 理由の一覧)"""
    arts = load_articles()
    if site_id:
        try:
            import sites as S
            arts = [a for a in arts if S.find_category_owner(a["cat"]) == site_id]
        except Exception:
            pass
    reasons, level = [], 0

    # ① 狙う語のぶつかり。表記ゆれを吸収して同一視する
    for _score, a, kind in kw_conflicts(kw, arts):
        if kind == "完全一致":
            level = max(level, 2)
            reasons.append(("禁止", f"狙う語が既存記事と完全一致: {a['slug']}（{a['kw']}）",
                            "同じ語を2記事で狙うと順位が割れます。既存記事を書き足してください"))
        else:
            # ピラーとクラスターの関係なら成立する。ただし広い側が
            # 狭い側の中身まで書くと食い合うため、書き分けの確認は要る
            level = max(level, 1)
            reasons.append((
                "要差別化", f"狙う範囲が既存記事に含まれる: {a['slug']}（{a['kw']}）",
                "広い側は要約1〜2段落にとどめ、詳細は狭い側へリンクします。"
                "両方が同じ深さで書くと食い合います"))

    # ② GSCの実績。すでに順位を持っているページがあるか（最も確かな指標）
    own = owned(gsc_rows(site_id)) if (use_gsc and site_id) else []
    for o in gsc_owner(kw, own)[:5]:
        level = max(level, 2)
        if o.get("own", True):
            reasons.append((
                "禁止", f"既に順位を持つページがある: {o['page'].split('//')[-1]}",
                f"「{o['q']}」で{o['pos']:.1f}位・表示{o['imp']}。"
                f"新記事を当てると順位が割れます。このページを書き足してください"))
        else:
            reasons.append((
                "禁止", f"他サイト（{o['site']}）が既に取っている語: "
                f"{o['page'].split('//')[-1]}",
                f"「{o['q']}」で{o['pos']:.1f}位・表示{o['imp']}。"
                f"ドメインが違っても自社どうしの食い合いになります。"
                f"担当をどちらに寄せるか決めてから書いてください"))

    # ③ 見出し案の主題を、実績に1本ずつ当てる。
    #    タイトルを差別化しても、見出しが既存記事の主題まで伸びていれば食い合う
    for head in (h2 or []):
        for o in h2_owner(head, own)[:2]:
            level = max(level, 1)
            reasons.append((
                "要差別化", f"見出しの主題を既存ページが取っている: 「{head[:26]}」",
                f"{o['page'].split('//')[-1]} が「{o['q']}」で{o['pos']:.1f}位。"
                f"この見出しは要約にとどめ、本文はそのページへリンクします"))

    # ④ タイトル案の似かた
    if title:
        for a in arts:
            d = dice(title, a["title"])
            if d >= TITLE_WARN:
                level = max(level, 2 if d >= 0.8 else 1)
                reasons.append(("禁止" if d >= 0.8 else "要差別化",
                                f"タイトルが類似{d:.0%}: {a['slug']}", a["title"]))

    # ⑤ 主題の重なり。文章の似かたは弱い指標なので、止めずに参考として出す
    if h2 or title:
        plan_terms = terms(title, list(h2 or []), kw)
        for r, a, shared in topic_overlap(plan_terms, arts)[:3]:
            if r >= TOPIC_NOTE:
                reasons.append(("参考", f"主題が近い記事: {a['slug']}（重なり{r:.0%}）",
                                f"{a['title'][:34]} / 共通の語: " + "・".join(shared)))
    return level, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword")
    ap.add_argument("--site", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--h2", action="append", default=[])
    ap.add_argument("--no-gsc", action="store_true", help="GSC照合を省く（オフライン時）")
    a = ap.parse_args()

    level, reasons = judge(a.keyword, a.site, a.title, a.h2, use_gsc=not a.no_gsc)
    print(f'■ 食い合い審査: 「{a.keyword}」'
          f'{"（" + a.site + "）" if a.site else ""}\n')
    if not reasons:
        print("   ぶつかる既存記事はありません。")
    for tag, head, detail in reasons:
        print(f"   [{tag}] {head}\n           {detail}")
    verdict = {0: "着手可", 1: "要差別化（切り口をずらしてから書く）",
               2: "着手禁止（既存記事を書き足す）"}[level]
    print(f"\n   判定: {verdict}")
    sys.exit(level)


if __name__ == "__main__":
    main()
