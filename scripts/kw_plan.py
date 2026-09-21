# -*- coding: utf-8 -*-
"""対策キーワードの計画を、実測（ラッコ＋GSC）で組み直す。

これまでの在庫は、無料のサジェストを順に積んだもので、検索数も難易度も
分からないまま「上から順に書く」しかなかった。ラッコで月間検索数・SEO難易度・
伸び率が取れるようになったので、サブジェクト（業種・業務の起点）ごとに
候補を集め、点をつけて並べ直す。

    python scripts/kw_plan.py --site corporate           # 計画を作って見る（台帳は触らない）
    python scripts/kw_plan.py --site corporate --deep    # LSI/PAA も使う（1起点あたり22.5クレジット）
    python scripts/kw_plan.py --site corporate --replace # 台帳の「未着手」を対象外にし、新しい計画を積む
    python scripts/kw_plan.py --all --replace            # 3サイトまとめて

出力: docs/kw-plan-<site>.md（サブジェクトごとの表）

**関連しない語は入れない。** 採用条件は kw_discover と同じ（担当領域語を含む／
他サイトの領域語・除外語を含まない／指名検索でない／既存記事と食い合わない）。
さらに「求人・副業・資格」など見込み客でない語を落とす。ラッコのLSIは
「経理代行 求人」「記帳代行 儲かる」を高重要度で返すが、読者は顧客ではない。

**台帳の一新は非破壊。** --replace は「未着手」を「対象外」に変えるだけで、
公開済み・執筆中は触らない。行も消さない。
"""
import argparse
import io
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kw_discover as KD          # noqa: E402  採用条件・GSC取得を共有する
import kw_intent                  # noqa: E402
import rakko                      # noqa: E402
from cannibal_check import dice, kw_conflicts, load_articles  # noqa: E402
from kw_status import is_written, written_corpus              # noqa: E402

MAX_PLAN = 120        # 1サイトの計画本数。1日2本で60日分
PER_SUBJECT = 14      # 1サブジェクトから採る上限。1業種に偏らせない
WEAK_SHARE = 0.2      # 「開く理由の弱い語」が占めてよい割合（kw_discover と同じ）
MIN_VOL = 10          # これ未満は、GSCに表示が無ければ採らない
GSC_KEEP_IMP = 10     # 検索数が取れなくても、この表示数があれば採る
CHUNK = 40            # 台帳へ一度に送る本数（応答が30秒で切れるため）
CORE_TERMS = 4        # 業種に掛ける領域語の数（sites/*.json の owns の先頭から）

# 見込み客でない検索。ラッコのLSIは重要度highで返すが、読者は顧客ではない
NOT_BUYER = ("求人", "転職", "副業", "在宅ワーク", "フリーランス", "資格", "儲かる",
             "年収", "給料", "時給", "未経験", "パート", "バイト", "独立", "開業 資金",
             "面接", "志望動機", "学校", "スクール", "講座", "検定", "試験")


# 他社の製品・サービス名。その名前で検索する人はその製品を使いたい人で、
# 「請求書freee」（9,900/月）を書いても経理BPOの相談には来ない。
# 指名検索の除外（is_brand_query）は自社名だけを見ていた
RIVALS = ("freee", "フリー会計", "マネーフォワード", "money forward", "弥生", "やよい",
          "ジョブカン", "楽楽精算", "楽楽明細", "奉行", "pca", "jdl", "tkc", "勘定奉行",
          "ドットコム", "misoca", "board", "invoice", "バクラク", "concur", "sansan",
          "bill one", "kintone", "salesforce", "hubspot", "canva", "chatgpt plus",
          "kinmaq", "キンマク", "レジーナ", "湘南美容", "ホットペッパー", "エキテン", "ぐるなび",
          "食べログ", "リクルート", "indeed", "タウンページ", "ミツモア", "くらしのマーケット")


def norm(kw):
    return re.sub(r"[\s　]+", "", str(kw)).lower()


def bag(kw):
    """語順を無視した鍵。「請求書 書き方 封筒」と「請求書 封筒 書き方」を同じにする。
    空白の無い「請求書の封筒の書き方」も、助詞を外して同じ袋に入れる"""
    s = re.sub(r"[のをにへとがで]", " ", str(kw).lower())
    return " ".join(sorted(t for t in re.split(r"[\s　]+", s) if t))


def core(kw):
    """空白も助詞も外した形。「請求書の書き方 封筒」と「請求書封筒書き方」を比べるため"""
    return re.sub(r"[のをにへとがで]", "", norm(kw))


def same(a, b):
    """同じ検索とみなすか。語順違い・助詞違い・表記のわずかな差を吸収する"""
    if bag(a) == bag(b):
        return True
    return dice(core(a), core(b)) >= 0.7


def gsc_owned(site_id):
    """自社ページが既に順位を持つ語。ここに当たる候補は新規で書かない（食い合う）"""
    try:
        import kw_guard
        return kw_guard.owned(kw_guard.gsc_rows(site_id))
    except Exception as e:
        print(f"   （GSCの所有語を取れないため、この照合は飛ばします: {str(e)[:60]}）")
        return []


# 外注・比較を考えている人の語。検索数は少ないが、問い合わせに近い。
# 検索数だけで並べると「請求書 封筒 書き方」（5,400/月・自分でやる人）が
# 「経理代行 費用 相場」（210/月・外注を考える人）より上に来てしまう
BUYER = re.compile(r"代行|外注|委託|依頼|会社|業者|サービス|比較|おすすめ|選び方|"
                   r"費用|料金|相場|見積|導入|申請 代行|コンサル|支援|丸投げ")


def score(c):
    """並べ替えの点。買い手の語・開く理由・検索数・難易度・伸び・実証を足す"""
    vol = c.get("vol") or 0
    kd = c.get("kd")
    intent = kw_intent.score(c["kw"])[0]
    s = math.log1p(vol) * 0.6
    s += intent * 0.8
    if BUYER.search(c["kw"].lower()):
        s += 3.0
    if kd is not None:
        s += max(0.0, (60 - kd)) / 60.0          # 難易度が低いほど加点（60超は0）
    tr = c.get("trend")
    if tr is not None and tr > 0.3:
        s += 1.0                                  # 12か月で3割以上伸びている
    if c.get("imp"):
        s += math.log1p(c["imp"]) * 0.6           # 自サイトに表示実績がある
    return round(s, 2)


def gather(site_id, S, deep):
    """サブジェクト（起点）ごとに候補を集める。(kw -> 候補dict)"""
    cands = {}

    def put(kw, subject, src, vol=None, kd=None, trend=None, imp=None, pos=None):
        kw = re.sub(r"\s+", " ", str(kw)).strip()
        if len(kw) < 4:
            return
        k = norm(kw)
        c = cands.get(k)
        if c is None:
            c = cands[k] = {"kw": kw, "subject": subject, "src": set()}
        c["src"].add(src)
        for f, v in (("vol", vol), ("kd", kd), ("trend", trend), ("imp", imp), ("pos", pos)):
            if v is not None and c.get(f) is None:
                c[f] = v

    # 1. 自サイトに出ている語（実証。伸びている語は優先）
    for q in KD.gsc_queries(S["gsc"]):
        put(q["kw"], "GSC実証", "gsc", imp=q["imp"], pos=q["pos"])
    for q in KD.gsc_rising(S["gsc"]):
        put(q["kw"], "GSC実証", "rising", imp=q["imp"], pos=q["pos"])

    # 2. サブジェクトごとに、ラッコで検索数つきの候補を集める。
    # 起点が領域語そのもの（経理・記帳）なら単体で聞く。起点が業種名
    # （クリニック・飲食店）のときは単体で聞くと患者・消費者の検索しか返らない
    # （クリックポスト／ペインクリニック）。業種×領域語で聞く
    own_core = core_terms(S)
    for ind in S["industries"]:
        if ind.lower() in S["own_terms"]:
            queries = [ind]
            rows = rakko.as_rows(rakko.related(ind))
        else:
            queries = [f"{ind} {t}" for t in own_core]
            rows = []
        for q in queries:
            rows += rakko.as_rows(rakko.suggest(q))
        for kw, vol, kd in rows:
            put(kw, ind, "rakko", vol=vol, kd=kd)
        if deep:
            res = rakko.call("/v1/other-keywords", {"keyword": ind, "sortBy": "importance"})
            for it in (res or {}).get("data", {}).get("items", []):
                m = it.get("metrics") or {}
                kw = it.get("question") or it.get("keyword")
                put(kw, ind, "paa" if it.get("type") == "paa" else "lsi",
                    vol=m.get("searchVolume"), kd=m.get("seoDifficulty"))
        # 3. 無料のサジェスト（起点×意図）。検索数は後で一括で埋める。
        # 補助金サイトは起点26×意図30＝780通りで、全通り叩くと10分を超えて
        # 時間切れになった。意図は「開く理由の強い順」に上位だけ使う
        for it in intents_for(S):
            for s in KD.suggest(f"{ind} {it}"):
                put(s, ind, "suggest")
        time.sleep(0.2)
    return cands


def core_terms(S):
    """業種に掛ける領域語。sites/<id>.json の kw_seeds.core があればそれを使う。
    無ければ owns の先頭から。owns は「AIO / LLMO / SEO / MEO」の順で、
    そのまま使うと「クリニック llmo」のようなほぼ検索されない組ができ、
    いちばん自然な「クリニック 集客」が入らなかった"""
    core = S["cfg"].get("kw_seeds", {}).get("core") or []
    core = [str(t).lower() for t in core if str(t).strip()]
    return core[:CORE_TERMS] if core else [t for t in S["own_terms"][:CORE_TERMS]]


MAX_INTENTS = 14


def intents_for(S):
    """起点に掛ける意図。開く理由の強い順に上限まで。
    kw_intent は「代行」を点に含めないため、買い手の語（申請 代行）が落ちていた。
    ここでは買い手の語にも加点して選ぶ"""
    its = list(S["intents"])
    its.sort(key=lambda t: -(kw_intent.score(t)[0] + (2 if BUYER.search(t.lower()) else 0)))
    return its[:MAX_INTENTS]


def known_heads(S):
    """語の先頭として認める語。担当領域語（owns）と、領域語を含む複合意図
    （小規模事業者持続化補助金・AIO対策）。業種名は入れない。
    業種はサブジェクトであって領域ではない。業種を認めると、AI集客サイトに
    「リフォーム キッチン 費用」（660万/月）が、補助金サイトに「飲食店 近くの」
    （150万/月）が入る。検索数が大きいぶん上位を占め、計画が丸ごとずれる"""
    own = [t.lower() for t in S["own_terms"]]
    heads = set(own)
    for t in S.get("intents", []):
        for tok in re.split(r"[\s　]+", str(t).lower()):
            if len(tok) >= 3 and any(o in tok for o in own):
                heads.add(tok)
    return heads


# 領域語でも、消費者の検索に多い語は文脈を要求する。「レジーナ クリニック 口コミ」は
# 患者が評判を調べる検索で、MEOの相談には来ない
OWN_NEEDS = {"口コミ": re.compile(r"返信|対策|管理|増や|集め|依頼|削除|悪い|評価 上げ|書いてもらう")}


def own_hit(low, S):
    heads = known_heads(S)      # 毎回計算する。設定を差し替えても古い先頭語が残らない
    toks = [t for t in re.split(r"[\s　のをにへとがで]+", low) if t]
    for tok in toks:
        for h in heads:
            if tok.startswith(h):
                need = OWN_NEEDS.get(h)
                if need and not need.search(low):
                    continue
                return True
    return False


def cheap_reject(c, S):
    """外部に問い合わせずに落とせる理由。検索数を取る前に使う。
    補助金サイトは候補が1万件を超え、そのまま一括登録すると500エラーで
    落ちたうえ、どうせ落とす語に料金を払っていた"""
    low = c["kw"].lower()
    if not own_hit(low, S):
        return "領域語なし"
    if any(t in low for t in S["ng_terms"]):
        return "除外語"
    if any(t in low for t in NOT_BUYER):
        return "見込み客でない"
    if any(t in low for t in RIVALS):
        return "他社名"
    if KD.is_brand_query(low):
        return "指名検索"
    return ""


def relevant(c, S, corpus, arts, owned, picked_norms):
    """採用してよいか。理由を返す（空なら採用）"""
    kw, low = c["kw"], c["kw"].lower()
    # 汎用語（費用・方法・とは）だけでは通さない。「ホームページ 作成 費用」が
    # 経理サイトの計画に入る。担当領域の語（owns）を必ず含むこと。
    # ただし部分一致だと「日記帳」が「記帳」に、「給付金請求書」が「請求書」に
    # 当たる。語の先頭か、サイト設定にある複合語（IT導入補助金・経理代行）だけを認める
    if not own_hit(low, S):
        return "領域語なし"
    if any(t in low for t in S["ng_terms"]):
        return "除外語"
    if any(t in low for t in NOT_BUYER):
        return "見込み客でない"
    if any(t in low for t in RIVALS):
        return "他社名"
    if KD.is_brand_query(low):
        return "指名検索"
    if is_written(kw, corpus):
        return "執筆済み"
    if kw_conflicts(kw, arts):
        return "既存記事と食い合う"
    if owned:
        import kw_guard
        if kw_guard.gsc_owner(kw, owned):
            return "自社ページが順位を持つ"
    if any(same(kw, p) for p in picked_norms):
        return "採用済みと重複"
    vol = c.get("vol")
    if (vol is None or vol < MIN_VOL) and (c.get("imp") or 0) < GSC_KEEP_IMP:
        return "検索数が少ない"
    return ""


BULK = 500   # 1回の一括登録の件数。2,000件超で500エラーになった。
             # 最低料金15クレジット＝500件×0.03 なので、500件ずつなら分けても損しない


def chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def fill_volume(cands):
    """検索数の無い候補を、一括登録で埋める（500件ずつ）"""
    missing = [c["kw"] for c in cands.values() if c.get("vol") is None]
    if not missing or not rakko.enabled():
        return 0
    total = 0
    for part in chunks(missing, BULK):
        total += _fill_part(cands, part)
    return total


def _fill_part(cands, missing):
    r = rakko.call("/v1/search-volume", {"keywords": missing, "seoDifficulty": True})
    rid = (r or {}).get("data", {}).get("requestId")
    if not rid:
        time.sleep(3)                               # 一過性の500は少し待つと通る
        r = rakko.call("/v1/search-volume", {"keywords": missing, "seoDifficulty": True})
        rid = (r or {}).get("data", {}).get("requestId")
    if not rid:
        print(f"   （一括の検索数取得に失敗: {len(missing)}件。この分は検索数なしのまま）")
        return 0
    done = False
    for _ in range(120):                       # 1,000件超は数分かかる。200秒では足りなかった
        st = rakko.call(f"/v1/search-volume/{rid}/status", method="GET")
        if (st or {}).get("data", {}).get("isCompleted"):
            done = True
            break
        time.sleep(5)
    if not done:
        print(f"   （一括の検索数取得が時間内に終わりません: {len(missing)}件。次回に持ち越し）")
        return 0
    res = rakko.call(f"/v1/search-volume/{rid}/results", {"limit": len(missing) + 50})
    items = (res or {}).get("data", {}).get("items", []) or []
    if not items:
        # 「完了」の直後に取りに行くと空で返ることがあった（サーバー側の反映待ち）
        time.sleep(10)
        res = rakko.call(f"/v1/search-volume/{rid}/results", {"limit": len(missing) + 50})
        items = (res or {}).get("data", {}).get("items", []) or []
    n, unmatched = 0, []
    for it in items:
        c = cands.get(norm(it.get("keyword", "")))
        if not c:
            unmatched.append(it.get("keyword", ""))
            continue
        m = it.get("metrics") or {}
        c["vol"] = m.get("searchVolume")
        if c.get("kd") is None:
            c["kd"] = m.get("seoDifficulty")
        tr = ((it.get("trends") or {}).get("changeRate") or {}).get("12m")
        if tr is not None:
            c["trend"] = tr
        n += 1
    # 照合できない語が多いときは、鍵の作り方か応答の形が変わっている。黙らせない
    if items and n < len(items) * 0.5:
        print(f"   （一括の応答 {len(items)}件のうち照合できたのは {n}件。"
              f"返った語の例: {unmatched[:3]} / こちらの鍵の例: {missing[:3]}）")
    return n


def choose(cands, S, site_id):
    corpus, arts = written_corpus(), load_articles()
    owned = gsc_owned(site_id)
    ranked = sorted(cands.values(), key=lambda c: -score(c))
    picked, why_drop, per_subject = [], defaultdict(int), defaultdict(int)
    picked_norms = []
    weak_room = max(1, int(MAX_PLAN * WEAK_SHARE))
    for c in ranked:
        if len(picked) >= MAX_PLAN:
            break
        r = relevant(c, S, corpus, arts, owned, picked_norms)
        if r:
            why_drop[r] += 1
            continue
        if per_subject[c["subject"]] >= PER_SUBJECT:
            why_drop["サブジェクト上限"] += 1
            continue
        weak = kw_intent.score(c["kw"])[0] < 0
        if weak and weak_room <= 0:
            why_drop["弱い語の上限"] += 1
            continue
        c["score"] = score(c)
        c["intent"] = kw_intent.score(c["kw"])[0]
        picked.append(c)
        picked_norms.append(c["kw"])
        per_subject[c["subject"]] += 1
        if weak:
            weak_room -= 1
    # 優先度: 点の上位1/3をA、次をB、残りをC
    n = len(picked)
    for i, c in enumerate(picked):
        c["priority"] = "A" if i < n / 3 else "B" if i < 2 * n / 3 else "C"
    return picked, dict(why_drop)


def write_plan(site_id, S, picked, dropped, deep):
    out = ROOT / "docs" / f"kw-plan-{site_id}.md"
    by = defaultdict(list)
    for c in picked:
        by[c["subject"]].append(c)
    L = [f"# {S['cfg']['name']}（{S['cfg']['domain']}）の対策キーワード計画",
         "",
         f"作成: {date.today().isoformat()} ／ 根拠: ラッコキーワード（月間検索数・SEO難易度・12か月の伸び）"
         f"＋Search Console（自サイトの表示実績）{'＋LSI/PAA' if deep else ''}",
         "",
         f"採用 {len(picked)}本（A={sum(c['priority']=='A' for c in picked)} / "
         f"B={sum(c['priority']=='B' for c in picked)} / C={sum(c['priority']=='C' for c in picked)}）。"
         "点は「検索数・開く理由・難易度の低さ・伸び・自サイトの表示実績」の合計。",
         "",
         "落とした理由: " + " / ".join(f"{k} {v}件" for k, v in sorted(dropped.items(), key=lambda x: -x[1])),
         ""]
    for subj in sorted(by, key=lambda s: -sum(c["score"] for c in by[s])):
        L += [f"## {subj}", "",
              "| 優先 | キーワード | 月間 | 難易度 | 開く理由 | 12か月 | 表示 | 出どころ |",
              "|:--|:--|--:|--:|--:|--:|--:|:--|"]
        for c in sorted(by[subj], key=lambda c: -c["score"]):
            tr = c.get("trend")
            L.append("| %s | %s | %s | %s | %+d | %s | %s | %s |" % (
                c["priority"], c["kw"],
                c.get("vol") if c.get("vol") is not None else "—",
                c.get("kd") if c.get("kd") is not None else "—",
                c["intent"],
                (f"{tr*100:+.0f}%" if tr is not None else "—"),
                c.get("imp") or "—",
                "/".join(sorted(c["src"]))))
        L.append("")
    # kw_status が読む1行（「**〜（N本）**: a / b / c」）
    L.append(f"**計画 {date.today().isoformat()}（{len(picked)}本）**: "
             + " / ".join(c["kw"] for c in picked))
    out.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    return out


def plan_metrics(site_id):
    """計画ファイルの表から {正規化KW: (月間, 難易度, 優先)} を返す。

    台帳のAPIは note 列を返さず、管制塔のコードも手元から配れない（clasp が403）。
    検索数と難易度はここ（コミット済みの計画ファイル）から引く。
    """
    p = ROOT / "docs" / f"kw-plan-{site_id}.md"
    out = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\|\s*([ABC])\s*\|\s*(.+?)\s*\|\s*([\d,]+|—)\s*\|\s*(\d+|—)\s*\|", ln)
        if not m:
            continue
        vol = None if m.group(3) == "—" else int(m.group(3).replace(",", ""))
        kd = None if m.group(4) == "—" else int(m.group(4))
        out[norm(m.group(2))] = (vol, kd, m.group(1))
    return out


def replace_ledger(site_id, picked):
    """台帳の「未着手」を対象外にし、新しい計画を積む。公開済み・執筆中は触らない"""
    import hub_client
    if not hub_client.enabled():
        print("   管制塔が未接続のため、台帳は更新しません")
        return
    rows = hub_client.all_kw(strict=True)
    todo = [r["keyword"] for r in rows if r.get("site") == site_id and r.get("status") == "未着手"]
    if todo:
        for i in range(0, len(todo), CHUNK):
            hub_client.retire_kw(site_id, todo[i:i + CHUNK],
                                 "計画を一新（ラッコの実測で組み直し）")
        print(f"   未着手 {len(todo)}件を「対象外」にしました（行は残っています）")
    items = [{"keyword": c["kw"], "priority": c["priority"], "aim": c["subject"],
              "note": "月間%s/KD%s/意図%+d" % (c.get("vol", "—"), c.get("kd", "—"), c["intent"])}
             for c in picked]
    added = 0
    for i in range(0, len(items), CHUNK):
        r = hub_client.add_kw(site_id, items[i:i + CHUNK]) or {}
        added += r.get("added", 0)
    print(f"   新しい計画 {added}件を台帳に積みました（site={site_id}）")


def run(site_id, deep, replace):
    S = KD.site_config(site_id)
    print(f"\n■ {site_id}（{S['cfg']['name']}）")
    if not S["industries"]:
        print("   kw_seeds が未定義のため作れません")
        return
    if not rakko.enabled():
        print("   RAKKO_API_KEY が未設定です。python scripts/set_key.py RAKKO_API_KEY")
        return
    cands = gather(site_id, S, deep)
    pre = defaultdict(int)
    for k in list(cands):
        why = cheap_reject(cands[k], S)
        if why:
            pre[why] += 1
            del cands[k]
    print(f"   候補 {len(cands) + sum(pre.values())}件（起点 {len(S['industries'])}件）→ "
          f"事前選別で {sum(pre.values())}件を除外（"
          + " / ".join(f"{k} {v}" for k, v in sorted(pre.items(), key=lambda x: -x[1])) + "）")
    n = fill_volume(cands)
    print(f"   検索数を一括で埋めました: {n}件（未取得 "
          f"{sum(1 for c in cands.values() if c.get('vol') is None)}件）")
    picked, dropped = choose(cands, S, site_id)
    out = write_plan(site_id, S, picked, dropped, deep)
    print(f"   採用 {len(picked)}本 → {out.relative_to(ROOT).as_posix()}")
    print("   落とした理由: " + " / ".join(f"{k} {v}" for k, v in sorted(dropped.items(), key=lambda x: -x[1])[:6]))
    for c in picked[:8]:
        print("     %s %-30s 月間%-5s KD%-3s 意図%+d %s" % (
            c["priority"], c["kw"][:30], c.get("vol", "—"), c.get("kd", "—"), c["intent"], c["subject"]))
    if replace:
        replace_ledger(site_id, picked)
    else:
        print("   （--replace を付けると、台帳の未着手を対象外にして新計画を積みます）")


def main():
    ap = argparse.ArgumentParser(description="対策キーワードの計画を実測で組み直す")
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--deep", action="store_true", help="LSI/PAA も使う（1起点22.5クレジット）")
    ap.add_argument("--replace", action="store_true", help="台帳の未着手を対象外にして積み直す")
    a = ap.parse_args()
    import sites as S_
    ids = sorted(S_.load_all()) if a.all else ([a.site] if a.site else [S_.primary()])
    for sid in ids:
        run(sid, a.deep, a.replace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
