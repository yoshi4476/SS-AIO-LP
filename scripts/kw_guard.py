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
          3=判定不能（GSCを読めない。鍵・通信を確かめてから審査し直す）
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from cannibal_check import (dice, is_glossary, kw_conflicts, load_articles,  # noqa: E402
                            norm_kw, terms, topic_overlap)

# GSCで既存ページがこの順位以内に入っている語は、すでにそのページのもの
OWNED_POS = 30.0
OWNED_IMP = 5        # 表示がこれ未満は偶然の露出とみなす
TITLE_WARN = 0.55
# 主題の重なり。実際に食い合った組で較正した（全ペアの上位2%が0.20前後）。
# 文章の似かたは弱い指標なので、ここでは止めずに参考として出すだけにする
TOPIC_NOTE = 0.20
# GSC の鍵。テストで差し替えられるよう1か所に置く
CRED = ROOT / "indexing-service-account.json"
# 判定不能。GSC を読めない日に「要差別化（1）」を返すと、呼び出し側は
# 「既存記事と食い合います」と読み、食い合っていない書き換えや統合を差し戻していた
UNKNOWN = 3


def gsc_rows(site_id):
    """直近90日のGSC実績（語×ページ）。取れなければ空を返す

    自サイトだけでなく、グループの全サイトを見る。1サイトだけ見ていたため、
    補助金サイトが「aioコンサルティング」で18.2位を取っている状態に気づかず、
    ラボ側で同じ語を狙う記事を書いてしまった。
    自社どうしの食い合いは、ドメインをまたいでも同じように起きる。
    """
    # 取れなかったことを残す。空の結果だけ返すと「順位を持つページなし＝着手可」と読まれ、
    # GSC が落ちていた日に食い合いの語を通していた（2026-09-25 の点検で発見）
    gsc_rows.failed = ""
    try:
        import gcreds
        import sites as S
        from googleapiclient.discovery import build as gbuild
        from datetime import date, timedelta
    except Exception as e:
        gsc_rows.failed = f"部品を読み込めません（{type(e).__name__}）"
        return []
    if not Path(CRED).is_file():
        gsc_rows.failed = f"鍵ファイルがありません（{Path(CRED).name}）"
        return []
    try:
        sc = gbuild("searchconsole", "v1", credentials=gcreds.load(
            CRED,
            ["https://www.googleapis.com/auth/webmasters.readonly"]))
        end = date.today() - timedelta(days=3)
        group = set(S.group_of(site_id)) if site_id else None
        all_conf = {k: v for k, v in S.load_all().items() if group is None or k in group}
    except Exception as e:
        print(f"   （GSC照合はスキップ: {type(e).__name__}）")
        gsc_rows.failed = f"GSC に接続できません（{type(e).__name__}）"
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
        except Exception as e:
            if sid == site_id:
                gsc_rows.failed = f"{dom} の実績を取れません（{type(e).__name__}）"
            continue          # 他サイトの権限の無いプロパティは黙って飛ばす
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
    hit = [o for o in own if norm_kw(o["q"]) == n]
    return sorted(hit, key=lambda x: x["pos"])


def gsc_related(kw, own):
    """その語を含む・その語に含まれる語で順位を持つページ

    包含まで禁止にすると、ピラーの語が順位を持った時点で
    その語を含むクラスターの語が全部止まる。kw_conflicts の包含と同じく要差別化に留める。
    """
    n = norm_kw(kw)
    hit = [o for o in own if norm_kw(o["q"]) != n
           and (n in norm_kw(o["q"]) or norm_kw(o["q"]) in n)]
    return sorted(hit, key=lambda x: x["pos"])


def glossary_source(page, site_id, cache={}):
    """用語集のページ（/glossary/<id>/）の定義を出した記事の slug。分からなければ空"""
    gid = page.split("/glossary/", 1)[-1].strip("/").split("#")[0]
    if not gid or not site_id:
        return ""
    if site_id not in cache:
        try:
            import glossary as GL
            cache[site_id] = {r["id"]: r["slug"] for r in GL.collect(site_id)}
        except Exception:
            cache[site_id] = {}
    return cache[site_id].get(gid, "")


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


def judge(kw, site_id, title="", h2=None, use_gsc=True, exclude_slug=""):
    """着手可否を返す。(終了コード, 見出し, 理由の一覧)

    exclude_slug: 審査対象の記事そのもの。書いた直後の検査では、その記事が
    もうディスクにあるため、除かないと必ず自分自身と「完全一致」になる。
    実際、正当な新記事3本が全部この誤検出で止まり、その回の執筆が無駄になった。
    """
    arts = load_articles()
    # カンマ区切りで複数（統合の検算では、残す記事と消す記事の両方を外す）
    ex = {s.strip() for s in str(exclude_slug or "").split(",") if s.strip()}
    if ex:
        arts = [a for a in arts if a["slug"] not in ex]
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
            # 題名まで同じなら、保存したばかりの自記事を拾っている可能性が高い。
            # 自記事を相手に「着手禁止」と読み、正当な記事を捨てたことがある（2026-09-06 / 09-23）
            self_hint = (f"（題名も同じです。書いた直後の自記事なら --exclude-slug {a['slug']} を付けて読み直す）"
                         if title and dice(title, a.get("title", "")) >= 0.95 else "")
            reasons.append(("禁止", f"狙う語が既存記事と完全一致: {a['slug']}（{a['kw']}）",
                            "同じ語を2記事で狙うと順位が割れます。既存記事を書き足してください" + self_hint))
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
    if use_gsc and site_id and getattr(gsc_rows, "failed", ""):
        level = max(level, 1)
        reasons.append(("要確認", f"GSCの実績を照合できませんでした: {gsc_rows.failed}",
                        "照合できないことは、食い合いが無いことではありません。"
                        "GSC を確かめてから審査し直してください（オフラインなら --no-gsc を明示）"))
    if ex:
        own = [o for o in own if not any(f"/{e}/" in o["page"] or o["page"].rstrip("/").endswith("/" + e)
                                         for e in ex)]
    # 用語集は記事の定義から作るページなので、記事と同じ扱い（書き足す先・着手禁止）にはしない。
    # 審査中の記事自身の定義から作った用語集は相手に数えない（数えると、その記事の書き直しが
    # 自分の写しを相手に毎回差し戻される）。残りは用語集が上に出る語として知らせる
    gl_own = [o for o in own if is_glossary(o["page"])]
    own = [o for o in own if not is_glossary(o["page"])]
    for o in gsc_owner(kw, gl_own)[:3]:
        src = glossary_source(o["page"], o.get("site") or site_id)
        if src and src in ex:
            continue
        level = max(level, 1)
        reasons.append((
            "要対応", f"用語集がこの語で順位を持っている: {o['page'].split('//')[-1]}"
            + (f"（定義の出典: {src}）" if src else ""),
            f"「{o['q']}」で{o['pos']:.1f}位・表示{o['imp']}。記事を当てるなら、用語集より記事が上に出るよう"
            f"出典の記事へ寄せてください（用語集の noindex・正規URLは機械では変えません）"))
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
    for o in gsc_related(kw, own)[:3]:
        level = max(level, 1)
        reasons.append((
            "要差別化", f"近い語で順位を持つページがある: {o['page'].split('//')[-1]}",
            f"「{o['q']}」で{o['pos']:.1f}位・表示{o['imp']}。"
            f"同じ深さで書くと食い合います。広い側は要約にとどめ、相互にリンクしてください"))

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
    # GSC を読めなかったときは、確かな「着手禁止」以外は判定不能として返す。
    # 照合できないことは、食い合いが無いことでも、食い合うことでもない
    if use_gsc and site_id and getattr(gsc_rows, "failed", "") and level < 2:
        level = UNKNOWN
    return level, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword")
    ap.add_argument("--site", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--h2", action="append", default=[])
    ap.add_argument("--no-gsc", action="store_true", help="GSC照合を省く（オフライン時）")
    ap.add_argument("--exclude-slug", default="", help="審査対象の記事自身（自分と照合しない）")
    a = ap.parse_args()

    level, reasons = judge(a.keyword, a.site, a.title, a.h2,
                           use_gsc=not a.no_gsc, exclude_slug=a.exclude_slug)
    print(f'■ 食い合い審査: 「{a.keyword}」'
          f'{"（" + a.site + "）" if a.site else ""}\n')
    if not reasons:
        print("   ぶつかる既存記事はありません。")
    for tag, head, detail in reasons:
        print(f"   [{tag}] {head}\n           {detail}")
    verdict = {0: "着手可", 1: "要差別化（切り口をずらしてから書く）",
               2: "着手禁止（既存記事を書き足す）",
               UNKNOWN: "判定不能（GSCを読めません）"}[level]
    print(f"\n   判定: {verdict}")

    # 食い合わなくても、検索結果で用が済む語は書いても読まれない。
    # 止めはしないが、書く前に開く理由を用意させる
    try:
        import kw_intent
        v, pt, why = kw_intent.verdict(a.keyword)
        print(f"\n■ 開く理由: [{v}] {pt}点（{why}）")
        if v == "弱":
            print("   この語は検索結果に答えが出た時点で用が済みます。"
                  "実測でも、例文・診断系は8〜9位で表示88回・クリック0でした。")
            print("   書くなら、検索結果には出せないもの"
                  "（違反例・失敗例・自社の一次データ）をタイトルに置いてください。")
    except Exception:
        pass
    sys.exit(level)


if __name__ == "__main__":
    main()
