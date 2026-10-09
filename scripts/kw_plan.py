# -*- coding: utf-8 -*-
"""対策キーワードの在庫を、成果に近い順（実証済みの語→シート→主力×業種→無料のサジェスト）で積み足す。

**いつ動くか（2026-10-09 運用者の決定）**: 書く記事（台帳の未着手）が1か月分（1日の本数×30）を切ったら、
その社だけ組む。月の途中でもよい。1社1か月1回（組んだ月は data/kw_plan_runs.json に社と年月だけ残す）。
毎日の在庫の見張り（daily-kpi.yml の kw-stock）が --all --if-needed で呼ぶ。

**流れ（成果に近いものから）**:
  1. 候補（無料）: 検索の実績で4〜30位・表示10回以上なのに狙う記事が無い語（需要と届く見込みが実証済み）を最優先。
     続けてシートの狙う語・kw_seeds の主力×業種・Google の無料サジェスト・AI検索の質問形（ai_kw）・30日以内のラッコの控え
  2. ふるい（無料）: kw_fit・食い合い（kw_guard と同じ GSC の実績）・既存の除外・台帳と記事との重複。
     実証済みの語のうち既存記事が順位を持つものは新しく書かず、その記事の書き直しへ回す（新記事は食い合う）
  3. 検索数（一括検索数の枠 30）: 上位の候補で検索数の無いものだけ、一括調査を1回（SEO難易度は付けない）
  4. 並べる: 点（score）に実証済みの加点。主力の語の割合を主力の配分以上に保ち、1か月分×1.2 まで積む。
     同じ主題の束では個別の記事を先・まとめ（ピラー）を後。語ごとの出どころを計画と台帳の備考に残す
  5. 見出し・共起語（枠 70）: これから書く優先度Aの上位と、4〜20位の自社記事の狙う語 → data/kw_serp（kw_serp.py が渡す）
  6. 実際の質問（枠 30）: 上位の約20語 → 執筆の FAQ の候補
  7. 予備（枠 20）: 無料の候補が足りないときだけ、ラッコのサジェスト・関連語

    python scripts/kw_plan.py --site corporate --dry-run  # 課金なし。候補の構成と目的ごとの見積もりだけ
    python scripts/kw_plan.py --all --if-needed           # 1か月分を切った社だけ積み足す（毎日の見張り）
    python scripts/kw_plan.py --site corporate --replace  # 一新（台帳の古い未着手を対象外にして計画を積む。手で使う）
    python scripts/kw_plan.py --site corporate --deep     # LSI/PAA も使う（1起点あたり22.5クレジット）

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
import kw_fit                     # noqa: E402  担当領域の判定（積む・選ぶ・書く前後で同じ基準）
import kw_intent                  # noqa: E402
import kw_reach                   # noqa: E402
import rakko                      # noqa: E402
from cannibal_check import dice, is_glossary, kw_conflicts, load_articles  # noqa: E402
from kw_status import is_written, written_corpus              # noqa: E402

MAX_PLAN = 120        # 一新（--replace）のときの計画本数。1日2本で60日分
STOCK_FACTOR = 1.2    # 積み足すときは1か月分×1.2 まで（2026-10-09 運用者の決定）
GSC_BAND = (3.5, 30.5)   # 実証済みの語: 検索の実績で4〜30位
GSC_MIN_IMP = 10         # 28日の表示。これ未満は偶然と区別しにくい
GSC_PROVEN = 5.0         # 実証済みの語の加点。需要と届く見込みが実測で分かっている語を候補の先頭に置く
                         # （+3 では検索数500の買い手の語と細い語の加点に負け、2番手以下に落ちた。2026-10-09 の門）
SERP_A = 10              # 見出し・共起語を取る「これから書く優先度A」の語（目安）
SERP_REWRITE = 10        # 見出し・共起語を取る「4〜20位の自社記事」（上限）
REWRITE_BAND = (3.5, 20.5)
REWRITE_MIN_IMP = 15
QA_TOP = 20              # 実際の質問を取る語（上位から）
SERP_COST = 6.0          # 見出し3＋共起語3（公式の資料 v1.21.0）
RUNS = ROOT / "data" / "kw_plan_runs.json"     # 組んだ月（{社: "YYYY-MM"}。社のIDと年月だけなので公開してよい）
ORIGIN = ROOT / "data" / "kw_origin.json"      # 積んだ語の出どころ（後で出どころ別の成果を比べる。お客様の分は置き場へ）
SRC_ORDER = ("gsc", "sheet", "seed", "question", "suggest", "cache", "rakko")
ENOUGH_DAYS = 30      # 未着手がこの日数分あるサイトは、--if-needed のとき組み直さない（2026-10-08 運用者「1か月分を切ったら」）
CREDIT_CAP = rakko.RUN_CAP   # 1サイト1回のラッコ消費の上限（150）。社の月の上限・全体の月の上限は rakko.allow が見る
                             # （超えるなら呼ばない。自動課金なので警告では止まらない。2026-10-08 運用者の決定）
PER_SUBJECT = 10      # 1サブジェクトから採る上限。1業種に偏らせない
PER_PRIORITY = 20     # 優先業種（kw_seeds.priority）の上限。月1件の成約で費用が回収できる業種を厚くする
PRIORITY_BONUS = 1.5  # 優先業種の語への加点。汎用性は他業種を残すことで保つ
REACH_WEIGHT = 0.7    # 15位以内に入れそうか（kw_reach・-2〜+2）の重み。振れ幅 2.8 を買い手の語（+3.0）より
                      # 小さくし、「買い手の語を先に」を崩さない
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
# 指名検索の除外（is_brand_query）は自社名だけを見ていた。一覧は kw_fit と共有する
# （計画にだけ持っていたため「sweeep 請求書」（9,900/月）が計画に入り、記事になった。2026-09-21）
RIVALS = kw_fit.RIVALS + kw_fit.PORTALS


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


def priority_subjects(S):
    return [str(t) for t in (S["cfg"].get("kw_seeds", {}).get("priority") or [])]


def sheet_terms(site_id):
    """ヒアリングシートの「狙う語」（data/clients/<id>/brief.json の keyword）。

    main・sub は起点（単体でラッコに聞く）と担当領域の語に、exclude は落とす語にする。
    シートの語は brief.json にだけ入り、計画は kw_seeds（業種×意図）しか見ていなかった。
    CONFLUX は「システム開発 外注」「AI エージェント 導入」を書いたのに、1語も起点にならなかった（2026-10-08）"""
    p = ROOT / "data" / "clients" / site_id / "brief.json"
    try:
        kw = (json.loads(p.read_text(encoding="utf-8")) or {}).get("keyword") or {}
    except (OSError, ValueError, AttributeError):
        return [], []

    def clean(xs):
        out = []
        for t in xs if isinstance(xs, list) else []:
            t = re.sub(r"[\s　]+", " ", str(t)).strip()
            if t and t.lower() not in [o.lower() for o in out]:
                out.append(t)
        return out
    return clean((kw.get("main") or []) + (kw.get("sub") or [])), clean(kw.get("exclude") or [])


def ng_phrase(low, S):
    """シートの「狙わない語」に当たるか。語句の言葉が全部入っていれば当たり（1語ずつだと
    「AI 導入補助金」の「AI」で AI の語が全部落ちる）"""
    for ph in S.get("sheet_ng") or ():
        toks = [t for t in re.split(r"[\s　]+", ph.lower()) if t]
        if toks and all(t in low for t in toks):
            return True
    return False


TITLE_TOKENS = 6     # 空白で区切って6語以上は、検索語ではなくページ・本の題（3サイトの計画と記事の狙う語680語に1つも無い）


def title_like(low):
    """ページや本の題のような語か。ラッコのサジェストは題をそのまま返し、検索数も付く。
    CONFLUX の計画に「ai エージェント 導入 開発 運用 トータル ガイド」（月40）が7位で入った（2026-10-08）。
    区切りの無い長い1語は見ない。AI集客ラボは「大阪でmeoとaioの両方を…教えてください。」のような
    AIへの質問の形を狙っている"""
    toks = [t for t in re.split(r"[\s　]+", low) if t]
    return len(toks) >= TITLE_TOKENS or bool(re.search(r"[「」『』【】]", low))


def ind_query(ind):
    """業種名をラッコに聞く形にする。「人材派遣・紹介」「飲食（多店舗）」のままでは
    「人材派遣・紹介 システム開発」と誰も打たない語になり、課金して何も返らない"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(ind))
    return re.split(r"[・／/]", s)[0].strip() or str(ind)


def score(c, prio=(), held=()):
    """並べ替えの点。買い手の語・開く理由・検索数・難易度・伸び・実証・優先業種・15位に届くかを足す"""
    vol = c.get("vol") or 0
    kd = c.get("kd")
    intent = kw_intent.score(c["kw"])[0]
    s = math.log1p(vol) * 0.6
    # 開く理由の重み。0.8 → 1.0 に上げた。
    # `validate_rules` で、成果を分けている判断は「語の性質」と「公開からの日数」の
    # 2つだけだった（品質スコア・内部リンク・記事の長さは分けていないか逆）。
    # それなのに買い手の語（+3.0）より軽く、実測で効くと分かっている要素が
    # 埋もれていた。実際、AI集客ラボは「強」の語が13.9%しかなく（他サイトは22〜24%）、
    # CTRも0.77%と他サイトの3分の1だった。
    # ただし 1.6 まで上げると「請求書 封筒 書き方」（自分でやる・強い語・大量検索）が
    # 「経理代行 費用 相場」（外注を考える・弱め・少量検索）を検索数の差で上回ってしまい、
    # 「買い手の語を先に置く」（本章-1）が崩れる。買い手の語（+3.0）を上回らない
    # 1.0 を上限にする
    s += intent * 1.0
    if BUYER.search(c["kw"].lower()):
        s += 3.0
    if kd is not None:
        s += max(0.0, (60 - kd)) / 60.0          # 難易度が低いほど加点（60超は0）
    tr = c.get("trend")
    if tr is not None and tr > 0.3:
        s += 1.0                                  # 12か月で3割以上伸びている
    if c.get("imp"):
        s += math.log1p(c["imp"]) * 0.6           # 自サイトに表示実績がある
    if c.get("proven"):
        s += GSC_PROVEN                           # 4〜30位・表示10回以上で狙う記事が無い（需要と届く見込みが実証済み）
    if prio and (c.get("subject") in prio or any(ind_query(p).lower() in c["kw"].lower() for p in prio)):
        s += PRIORITY_BONUS                        # 月1件で費用が回収できる業種
    # 公開1〜4週に15位以内（3回以上表示）に入った記事だけが6週以降も残った（2026-10-05・3サイト）。
    # 広い語（1語・大きい検索数・高い難易度）を下げ、条件つきの細い語と、自サイトが近い語で
    # 既に15位以内にいる主題を上げる。検索数の対数の加点（大きい語ほど得）を打ち消しすぎない重み
    s += kw_reach.reach(c["kw"], vol, kd, held) * REACH_WEIGHT
    return round(s, 2)


DRY = False   # True のとき、ラッコは呼ばず（キャッシュにあれば使う）、課金の見積もりだけ出す
DEEP = False  # --deep（LSI/PAA を1起点22.5で取る）。見積もりに含めるため main で立てる


def _put(cands, kw, subject, src, vol=None, kd=None, trend=None, imp=None, pos=None, proven=False):
    """候補を1つ足す（同じ語は出どころを足し、欠けている値だけ埋める）"""
    kw = re.sub(r"\s+", " ", str(kw)).strip()
    if len(kw) < 4:
        return
    k = norm(kw)
    c = cands.get(k)
    if c is None:
        c = cands[k] = {"kw": kw, "subject": subject, "src": set()}
    c["src"].add(src)
    if proven and not c.get("proven"):
        c["proven"], c["subject"] = True, "GSC実証"
    for f, v in (("vol", vol), ("kd", kd), ("trend", trend), ("imp", imp), ("pos", pos)):
        if v is not None and c.get(f) is None:
            c[f] = v


def primary_src(c):
    """語の出どころ（成果に近い順で1つ）。gsc / sheet / seed / question / suggest / cache / rakko"""
    src = {{"rising": "gsc", "lsi": "rakko", "paa": "rakko"}.get(s, s) for s in c.get("src") or ()}
    return next((s for s in SRC_ORDER if s in src), "/".join(sorted(src)) or "—")


def gsc_proven(site_id):
    """検索の実績（data/ranks/<site>.json の最新の日＝28日の語×ページ）で、4〜30位・表示10回以上の語。
    Search Console は呼ばない（毎晩の rank_track が残した分を読む。お客様の分は client_private が戻す）"""
    p = kw_reach.RANKS / f"{site_id}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows = d[sorted(d)[-1]] if d else []
    except (OSError, ValueError, KeyError, IndexError):
        return []
    agg = defaultdict(lambda: {"imp": 0, "ps": 0.0, "pages": []})
    for r in rows:
        a = agg[str(r.get("kw") or "")]
        imp = int(r.get("imp") or 0)
        a["imp"] += imp
        a["ps"] += float(r.get("pos") or 0) * imp
        a["pages"].append((str(r.get("url") or ""), float(r.get("pos") or 0), imp))
    out = []
    for kw, a in agg.items():
        if not kw or a["imp"] < GSC_MIN_IMP:
            continue
        pos = a["ps"] / a["imp"]
        if GSC_BAND[0] <= pos <= GSC_BAND[1]:
            out.append({"kw": kw, "imp": a["imp"], "pos": round(pos, 1), "pages": sorted(a["pages"], key=lambda x: x[1])})
    return sorted(out, key=lambda q: -q["imp"])


def _ai_questions(site_id):
    """AI検索で答えが出る質問形の語（週次の ai_kw_research が残す。書いた語は除く）"""
    p = ROOT / "data" / "ai_kw" / f"{site_id}.json"
    try:
        items = json.loads(p.read_text(encoding="utf-8")).get("items") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [it for it in items if it.get("kw") and not it.get("written")]


def _queries(S):
    """ラッコに聞く問い合わせ（経路, 中身, サブジェクト）。控え（30日）の鍵と見積もりと予備の取得が同じものを使う。
    起点が領域語そのもの（経理・記帳）なら単体で聞く。業種名（クリニック・飲食店）は単体で聞くと患者・消費者の
    検索しか返らない（クリックポスト／ペインクリニック）ので、業種×領域語で聞く。シートの「狙う語」は単体で聞く"""
    qs = []
    for seed in S.get("sheet") or []:
        qs += [(rakko.RELATED, rakko.related_body(seed), seed), (rakko.SUGGEST, rakko.suggest_body(seed), seed)]
    core = core_terms(S)
    for ind in S["industries"]:
        if ind.lower() in S["own_terms"]:
            qs += [(rakko.RELATED, rakko.related_body(ind), ind), (rakko.SUGGEST, rakko.suggest_body(ind), ind)]
        else:
            qs += [(rakko.SUGGEST, rakko.suggest_body(f"{ind_query(ind)} {t}"), ind) for t in core]
    return qs


def collect_free(site_id, S, cands=None):
    """課金しない候補を、成果に近い順に集める。(正規化した語 -> 候補dict)"""
    cands = {} if cands is None else cands
    # 1. 検索の実績。4〜30位・表示10回以上は需要と届く見込みが実証済み（proven）。90日の表示・伸びている語も足す
    for q in gsc_proven(site_id):
        _put(cands, q["kw"], "GSC実証", "gsc", imp=q["imp"], pos=q["pos"], proven=True)
    for q in KD.gsc_queries(S.get("gsc")):
        _put(cands, q["kw"], "GSC実証", "gsc", imp=q["imp"], pos=q["pos"])
    for q in KD.gsc_rising(S.get("gsc")):
        _put(cands, q["kw"], "GSC実証", "rising", imp=q["imp"], pos=q["pos"])
    # 2. ヒアリングシートの「狙う語」（お客様が挙げた領域の語。検索数は一括で埋める）
    for seed in S.get("sheet") or []:
        _put(cands, seed, seed, "sheet")
    # 3. kw_seeds の主力×業種（業種名は聞ける形に。起点が領域語ならそのまま）
    core = core_terms(S)
    for ind in S["industries"]:
        seeds = [ind] if ind.lower() in S["own_terms"] else [f"{ind_query(ind)} {t}" for t in core]
        for s in seeds:
            _put(cands, s, ind, "seed")
    # 4. Google の無料サジェスト（起点×意図・シートの語）。補助金サイトは起点26×意図30＝780通りで10分を
    # 超えたため、意図は「開く理由の強い順」に上位だけ使う
    for ind in S["industries"]:
        for it in intents_for(S):
            for s in KD.suggest(f"{ind_query(ind)} {it}"):
                _put(cands, s, ind, "suggest")
        time.sleep(0.2)
    for seed in S.get("sheet") or []:
        for s in KD.suggest(seed):
            _put(cands, s, seed, "suggest")
    # 5. AI検索で答えが出る質問形の語（ai_kw_research）
    for it in _ai_questions(site_id):
        _put(cands, it["kw"], "AIの質問", "question", imp=it.get("imp"), pos=it.get("pos"))
    # 6. 30日以内のラッコの控え（取得済みの応答。課金しない）
    for path, body, subject in _queries(S):
        hit = rakko._cache_get(path, body, "POST")
        for kw, vol, kd in rakko.as_rows(rakko._rows(hit)) if hit else ():
            _put(cands, kw, subject, "cache", vol=vol, kd=kd)
    return cands


def gather(site_id, S, deep, into=None, free=True):
    """候補を集める。free=False は課金の問い合わせ（予備の枠: ラッコのサジェスト・関連語・--deep の LSI/PAA）だけを
    into に足す。--dry-run では控えにあるときだけ使い、無ければ回数だけ数える"""
    cands = {} if into is None else into
    if free:
        collect_free(site_id, S, cands)
    paid = {"calls": 0}
    for path, body, subject in _queries(S):
        if DRY:
            hit = rakko._cache_get(path, body, "POST")
            if hit is None:
                paid["calls"] += 1
                continue
            rows = rakko._rows(hit)
        else:
            rows = rakko._rows(rakko.call(path, body))
        for kw, vol, kd in rakko.as_rows(rows):
            _put(cands, kw, subject, "rakko", vol=vol, kd=kd)
    if deep and not DRY:
        for ind in S["industries"]:
            res = rakko.call("/v1/other-keywords", {"keyword": ind, "sortBy": "importance"})
            for it in (res or {}).get("data", {}).get("items", []):
                m = it.get("metrics") or {}
                kw = it.get("question") or it.get("keyword")
                _put(cands, kw, ind, "paa" if it.get("type") == "paa" else "lsi",
                     vol=m.get("searchVolume"), kd=m.get("seoDifficulty"))
    if DRY:
        print(f"   [dry-run] ラッコのサジェスト／関連語: キャッシュ外 {paid['calls']}回 → 約{paid['calls'] * 1.5:.0f}クレジット")
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
    # シートの「狙う語」はお客様が挙げた領域の語。「問い合わせ対応 自動化」は owns に無くても通す
    heads.update(str(t).lower() for t in S.get("sheet") or ())
    return heads


def _starts_at_token(toks, head):
    """語の区切りから始まって head が続くか。head は空白を含んでよい（「ai エージェント」）。
    1語ずつ比べていたため、空白を含む owns（CONFLUX の「AI エージェント」「Excel 脱却」）が
    どの語にも当たらず、「aiエージェント 費用」も「ai エージェント 費用」も領域語なしで落ちていた"""
    h = re.sub(r"[\s　のをにへとがで]+", "", head)    # 語の側と同じ区切りで外す
    return bool(h) and any("".join(toks[i:]).startswith(h) for i in range(len(toks)))


# 領域語でも、消費者の検索に多い語は文脈を要求する。「レジーナ クリニック 口コミ」は
# 患者が評判を調べる検索で、MEOの相談には来ない
OWN_NEEDS = {"口コミ": re.compile(r"返信|対策|管理|増や|集め|依頼|削除|悪い|評価 上げ|書いてもらう")}


def own_hit(low, S):
    heads = known_heads(S)      # 毎回計算する。設定を差し替えても古い先頭語が残らない
    toks = [t for t in re.split(r"[\s　のをにへとがで]+", low) if t]
    for h in heads:
        if _starts_at_token(toks, h):
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
    if ng_phrase(low, S):
        return "狙わない語"
    if any(t in low for t in S["ng_terms"]):
        return "除外語"
    if any(t in low for t in NOT_BUYER):
        return "見込み客でない"
    if any(t in low for t in RIVALS):
        return "他社名"
    if KD.is_brand_query(low):
        return "指名検索"
    if title_like(low):
        return "題のような語"
    return outside(c["kw"], S)


def outside(kw, S):
    """担当領域の外（kw_fit の判定2）なら理由。同じ字で別の意味の語（「記帳」と通帳の記帳）は
    語の先頭一致（own_hit）では見分けられず、「通帳 記帳できない 原因」（320/月）が計画に入った（2026-09-21）。
    サイト設定の無い呼び出し（門の作り物の S）では見ない"""
    if not S.get("id"):
        return ""
    lv, why = kw_fit.judge(kw, S["id"])
    return f"担当の外（{why}）" if lv >= 2 else ""


def relevant(c, S, corpus, arts, owned, picked_norms):
    """採用してよいか。理由を返す（空なら採用）"""
    kw, low = c["kw"], c["kw"].lower()
    # 汎用語（費用・方法・とは）だけでは通さない。「ホームページ 作成 費用」が
    # 経理サイトの計画に入る。担当領域の語（owns）を必ず含むこと。
    # ただし部分一致だと「日記帳」が「記帳」に、「給付金請求書」が「請求書」に
    # 当たる。語の先頭か、サイト設定にある複合語（IT導入補助金・経理代行）だけを認める
    if not own_hit(low, S):
        return "領域語なし"
    if ng_phrase(low, S):
        return "狙わない語"
    if any(t in low for t in S["ng_terms"]):
        return "除外語"
    if any(t in low for t in NOT_BUYER):
        return "見込み客でない"
    if any(t in low for t in RIVALS):
        return "他社名"
    if KD.is_brand_query(low):
        return "指名検索"
    if title_like(low):
        return "題のような語"
    why = outside(kw, S)
    if why:
        return why
    if is_written(kw, corpus):
        return "執筆済み"
    if kw_conflicts(kw, arts):
        return "既存記事と食い合う"
    if owned:
        import kw_guard
        # 計画は自動で積むため、要差別化（包含）の語も入れない
        if kw_guard.gsc_owner(kw, owned) or kw_guard.gsc_related(kw, owned):
            return "自社ページが順位を持つ"
    if any(same(kw, p) for p in picked_norms):
        return "採用済みと重複"
    vol = c.get("vol")
    # vol_pending は dry-run だけ: 本番では一括調査で検索数を取る語。見積もりの段で落とすと、本番の計画と違って見える
    if (vol is None or vol < MIN_VOL) and (c.get("imp") or 0) < GSC_KEEP_IMP and not c.get("vol_pending"):
        return "検索数が少ない"
    return ""


BULK = 500   # 1回の一括登録の件数。2,000件超で500エラーになった。
             # 最低料金15クレジット＝500件×0.03 なので、500件ずつなら分けても損しない


def chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


VOL_CACHE = ROOT / "data" / "rakko_volume.json"
LOOKUP_MAX = BULK    # 一括調査に送る語は1サイト1回ぶん（500件＝15クレジット）まで


def pre_score(c):
    """課金なしで付けられる点。一括調査に送る語を選ぶために使う"""
    # 本番の点（score）と同じ重みにする。ここが軽いと、開く理由の強い語が
    # 一括調査に送られる前に落ちてしまう
    s = kw_intent.score(c["kw"])[0] * 1.0
    if BUYER.search(c["kw"].lower()):
        s += 3.0
    if c.get("imp"):
        s += math.log1p(c["imp"])
    return s


def worth_lookup(cands):
    """検索数を取りに行く価値のある語だけを、価値の高い順に上限まで返す。
    無料サジェスト由来の候補は補助金サイトで1万件になり、全部を一括調査に
    送ると500件ずつ20回（300クレジット）払っていた。買い手の語・開く理由の
    強い語・表示実績のある語に限る"""
    good = [c for c in cands
            if "sheet" in c.get("src", ()) or c.get("imp") or BUYER.search(c["kw"].lower())
            or kw_intent.score(c["kw"])[0] >= 2]
    # シートに書いた語そのものは必ず測る（入らなかった理由を「検索数」で言えるように）
    good.sort(key=lambda c: (-("sheet" in c.get("src", ())), -pre_score(c)))
    return good[:LOOKUP_MAX]


VOL_DAYS = 90    # 検索数は月次で大きくは動かない。90日は使い回す
VOL_NONE_DAYS = 7


def _vol_cache():
    """語ごとの検索数の記録。日付が古いものは無いものとして扱う"""
    try:
        raw = json.loads(VOL_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    import time as _t
    out = {}
    for k, v in raw.items():
        # 応答を受け取った印の無い vol=None は、失敗・時間切れの塊を残していた古い記録
        # （実測で500件が同じ1分に保存されていた）。短い期限で取り直しに回す
        days = VOL_DAYS if v.get("vol") is not None or v.get("answered") else VOL_NONE_DAYS
        if _t.time() - float(v.get("at") or 0) <= days * 86400:
            out[k] = v
    return out


def fill_volume(cands):
    """検索数の無い候補を、一括登録で埋める（500件ずつ）。
    一度取った語は data/rakko_volume.json に残し、次からは登録しない
    （登録は1回最低15クレジット。条件を直すたびに払っていた）"""
    known = _vol_cache()
    hit = 0
    for k, c in cands.items():
        if c.get("vol") is None and k in known:
            v = known[k]
            c["vol"], c["trend"] = v.get("vol"), v.get("trend")
            if c.get("kd") is None:
                c["kd"] = v.get("kd")
            hit += 1
    need = [c for c in cands.values()
            if c.get("vol") is None and norm(c["kw"]) not in known]
    missing = [c["kw"] for c in worth_lookup(need)]
    if hit:
        print(f"   検索数を手元の記録から埋めました: {hit}件（課金なし）")
    if len(need) > len(missing):
        print(f"   検索数の無い候補 {len(need)}件のうち、価値の高い {len(missing)}件だけ一括調査に送ります"
              f"（{max(1, -(-len(missing) // BULK)) if missing else 0}回・約{15 * max(1, -(-len(missing) // BULK)) if missing else 0}クレジット）")
    if DRY:
        n = max(1, -(-len(missing) // BULK)) if missing else 0
        print(f"   [dry-run] 一括調査: {len(missing)}件を{n}回 → 約{15 * n}クレジット（登録しません）")
        for k, c in cands.items():
            if c["kw"] in set(missing):
                c["vol_pending"] = True          # 本番では検索数を取る語。dry-run の計画で落とさない
        return hit
    if not missing or not rakko.enabled() or not rakko.granted("volume"):
        return hit                                  # 上限で止めた回は登録しない（手元の記録の分だけ）
    total, answered = hit, set()
    for part in chunks(missing, BULK):
        n, got = _fill_part(cands, part)
        total += n
        answered |= got
    # 応答を受け取った語は、検索数が無くても残す（取れない語を毎回登録し直さないため）。
    # 失敗・時間切れの語は残さない。残すと90日間「検索数が少ない」で落ち続ける
    for k, c in cands.items():
        if k not in known and c["kw"] in answered:
            known[k] = {"vol": c.get("vol"), "kd": c.get("kd"), "trend": c.get("trend"),
                        "answered": True, "at": time.time()}
    VOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VOL_CACHE.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
    return total


def _fill_part(cands, missing):
    # SEO難易度は取らない。同時取得は1語 +0.5（API 1.5倍で 0.75）で、500語なら 375 に
    # なる（検索数だけなら 15）。今日の大量消費の主因はこれだった。難易度は
    # サジェスト・関連語の応答に付いてくる分で足りる
    body = {"keywords": missing, "seoDifficulty": False}
    r = rakko.call("/v1/search-volume", body)
    rid = (r or {}).get("data", {}).get("requestId")
    if not rid:
        time.sleep(3)                               # 一過性の500は少し待つと通る
        r = rakko.call("/v1/search-volume", body)
        rid = (r or {}).get("data", {}).get("requestId")
    if rid:
        print(f"   一括調査を登録: {len(missing)}件（消費 {((r or {}).get('meta') or {}).get('consumedCredit')}）")
    if not rid:
        print(f"   （一括の検索数取得に失敗: {len(missing)}件。この分は検索数なしのまま）")
        return 0, set()
    done = False
    for _ in range(120):                       # 1,000件超は数分かかる。200秒では足りなかった
        st = rakko.call(f"/v1/search-volume/{rid}/status", method="GET")
        if (st or {}).get("data", {}).get("isCompleted"):
            done = True
            break
        time.sleep(5)
    if not done:
        print(f"   （一括の検索数取得が時間内に終わりません: {len(missing)}件。次回に持ち越し）")
        return 0, set()
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
    # 応答が空なら受け取れていない。空を「検索数なし」として残さない
    return n, (set(missing) if items else set())


def ledger_keys(kw):
    """台帳との重複を見る鍵（表記ゆれ・語順・助詞の違いを吸収）"""
    return {norm(kw), bag(kw), core(kw)}


def lead_signal(c, rule=None):
    """問い合わせに近いと言える根拠があるか。実証済み・表示実績・シートの語・買い手の語・主力の語・開く理由（+1以上）。
    検索数だけが取り柄の語（「au の請求書」「請求書フォーマット」）は、在庫を積み足す回には入れない"""
    kw = c["kw"]
    return bool(c.get("proven") or c.get("imp") or "sheet" in (c.get("src") or ()) or BUYER.search(kw.lower())
                or (rule and rule(kw)) or kw_intent.score(kw)[0] >= 1)


def choose(cands, S, site_id, limit=MAX_PLAN, main=None, ledger=(), owned=None, floor=False):
    """点の順に、採用条件（relevant）と枠を通る語を limit 本まで選ぶ。

    main=(主力の語か判定する関数, 主力の語の本数) を渡すと、先に主力の語でその本数を満たしてから残りを点の順で埋める
    （主力の割合を主力の配分以上に保つ。2026-10-09 運用者の決定）。ledger は台帳にある語の鍵（重複は積まない）。
    owned は GSC で順位を持つ語（用語集は除く。kw_guard も用語集を「着手禁止」にしない）。
    floor=True は問い合わせに近い根拠（lead_signal）の無い語を入れない（在庫を積み足す回）"""
    corpus, arts = written_corpus(), load_articles()
    if owned is None:
        owned = [o for o in gsc_owned(site_id) if not is_glossary(o["page"])]
    prio = priority_subjects(S)
    held = kw_reach.held_queries(site_id)
    ranked = sorted(cands.values(), key=lambda c: -score(c, prio, held))
    picked, why, per_subject = [], {}, defaultdict(int)
    picked_norms = []
    weak_room = [max(1, int(limit * WEAK_SHARE))]
    ledger = set(ledger or ())

    rule, need_main = main or (None, 0)

    def take(c):
        r = relevant(c, S, corpus, arts, owned, picked_norms)
        if not r and ledger & ledger_keys(c["kw"]):
            r = "台帳と重複"
        if not r and floor and not lead_signal(c, rule):
            r = "買い手の根拠が無い（検索数だけ）"
        cap = PER_PRIORITY if c["subject"] in prio else PER_SUBJECT
        weak = kw_intent.score(c["kw"])[0] < 0
        # 実証済みの語（4〜30位）は1つのサブジェクトに集まるが、成果に一番近いので枠で落とさない
        if not r and not c.get("proven") and per_subject[c["subject"]] >= cap:
            r = "サブジェクト上限"
        if not r and weak and weak_room[0] <= 0:
            r = "弱い語の上限"
        if r:
            why[norm(c["kw"])] = r
            c["why"] = r          # シートの語が入らなかった理由を計画に書くため
            return False
        c["score"] = score(c, prio, held)
        c["intent"] = kw_intent.score(c["kw"])[0]
        c["reach"] = kw_reach.reach(c["kw"], c.get("vol"), c.get("kd"), held)
        c.pop("why", None)
        why.pop(norm(c["kw"]), None)
        picked.append(c)
        picked_norms.append(c["kw"])
        per_subject[c["subject"]] += 1
        if weak:
            weak_room[0] -= 1
        return True

    if rule and need_main > 0:
        got = 0
        for c in ranked:
            if got >= need_main or len(picked) >= limit:
                break
            if rule(c["kw"]) and take(c):
                got += 1
    for c in ranked:
        if len(picked) >= limit:
            break
        if not any(p is c for p in picked):
            take(c)
    picked.sort(key=lambda c: -c["score"])
    picked = order_pillars(picked)
    # 優先度: 並びの上位1/3をA、次をB、残りをC
    n = len(picked)
    for i, c in enumerate(picked):
        c["priority"] = "A" if i < n / 3 else "B" if i < 2 * n / 3 else "C"
    dropped = defaultdict(int)
    for r in why.values():
        dropped[r] += 1
    return picked, dict(dropped)


def _toks(kw):
    return {t for t in re.split(r"[\s　のをにへとがで]+", str(kw).lower()) if t}


def order_pillars(picked):
    """同じ主題の束では、個別の記事を先に、まとめ（ピラー）を後に置く。ピラー＝その語の言葉を全部含む、
    より長い語が同じ計画にある語（「経理代行」と「経理代行 費用」なら「経理代行」）。ピラーは束の最後の個別の語の直後へ。
    先にピラーを書くと、後から書く個別の記事が広い側に吸われて食い合う（クラスター先→ピラー後）"""
    for c in picked:
        c.pop("pillar", None)
    ids = {id(c): _toks(c["kw"]) for c in picked}
    pillars = [c for c in picked if any(ids[id(c)] < ids[id(o)] for o in picked if o is not c)]
    pid = {id(c) for c in pillars}
    order = [c for c in picked if id(c) not in pid]
    for p in sorted(pillars, key=lambda c: -len(ids[id(c)])):      # 狭いピラーを先に置き、広いピラーをその後へ
        kids = [i for i, o in enumerate(order) if ids[id(p)] < ids[id(o)]]
        order.insert(max(kids) + 1 if kids else len(order), p)
        p["pillar"] = True
    return order


def _prev_rows(site_id, keep):
    """前回までの計画の表の行のうち、台帳に未着手で残っている語の行（検索数・難易度を引く経路を残す）"""
    p = ROOT / "docs" / f"kw-plan-{site_id}.md"
    try:
        lines = p.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        m = re.match(r"^\|\s*[ABC]\s*\|\s*(.+?)\s*\|", ln)
        if m and norm(m.group(1)) in keep and ln not in out:
            out.append(ln)
    return out


def write_plan(site_id, S, picked, dropped, deep, sheet_fate=None, cands=None, ctx=None):
    out = ROOT / "docs" / (f"kw-plan-{site_id}.md" if not DRY else f"kw-plan-{site_id}.dry.md")
    ctx = ctx or {}
    by = defaultdict(list)
    for c in picked:
        by[c["subject"]].append(c)
    srcs = defaultdict(int)
    for c in picked:
        srcs[primary_src(c)] += 1
    L = [f"# {S['cfg']['name']}（{S['cfg']['domain']}）の対策キーワード計画",
         "",
         f"作成: {date.today().isoformat()} ／ 根拠: Search Console（4〜30位の実証済みの語・表示実績）＋ラッコキーワード"
         f"（月間検索数・SEO難易度・12か月の伸び・上位ページの見出し・共起語・実際の質問）{'＋LSI/PAA' if deep else ''}",
         "",
         f"優先業種（枠{PER_PRIORITY}本・加点{PRIORITY_BONUS}）: "
         + ("／".join(priority_subjects(S)) or "指定なし") + f" ／ その他は枠{PER_SUBJECT}本",
         ""]
    if ctx.get("stock"):
        L += [ctx["stock"], ""]
    if ctx.get("main"):
        L += [ctx["main"], ""]
    L += [(f"ラッコの消費: 約{rakko.spent():.0f}クレジット（1回の上限 {CREDIT_CAP}）" if not DRY else
           "ラッコの消費: なし（dry-run。控え data/rakko_cache・rakko_volume.json にある応答だけで組み直し）")
          + ("" if not ctx.get("est") else " ／ 見積もり（目的ごと）: "
             + "・".join(f"{rakko.PURPOSES.get(p, p)} {v:.0f}" for p, v in ctx["est"].items())),
          "",
          f"採用 {len(picked)}本（A={sum(c['priority']=='A' for c in picked)} / "
          f"B={sum(c['priority']=='B' for c in picked)} / C={sum(c['priority']=='C' for c in picked)}）。"
          "点は「検索数・開く理由・難易度の低さ・伸び・自サイトの表示実績・実証済み（4〜30位）」の合計。"
          "同じ主題の束では個別の記事を先・まとめ（ピラー）を後に並べた。",
          "",
          "出どころ（成果に近い順で1つ）: " + (" / ".join(f"{s} {srcs[s]}本" for s in SRC_ORDER if srcs.get(s))
                                       or "なし"),
          "",
          "落とした理由: " + " / ".join(f"{k} {v}件" for k, v in sorted(dropped.items(), key=lambda x: -x[1])),
          ""]
    for title, rows in (("新しく書かず、書き直しへ回した語（実証済みだが既存記事が順位を持つ。新記事は食い合う）",
                         ctx.get("to_rewrite")),
                        ("積めない語（実証済みだが記事以外のページか他サイトが順位を持ち、kw_guard が着手禁止にする）",
                         ctx.get("blocked"))):
        if rows:
            L += [f"## {title}", "", "| 語 | 順位 | 表示 | 順位を持つページ |", "|:--|--:|--:|:--|"]
            L += [f"| {r['kw']} | {r['pos']} | {r['imp']} | {r['page']} |" for r in rows[:30]]
            L.append("")
    if ctx.get("serp"):
        L += ["## 上位ページの見出し・共起語・実際の質問を取った語（data/kw_serp → 執筆と書き直しの指示）", ""]
        L += [f"- {r}" for r in ctx["serp"]]
        L.append("")
    if S.get("sheet"):
        L += ["## シートに書いた語の行方", "", "| 語 | 月間 | 結果 |", "|:--|--:|:--|"]
        for seed in S["sheet"]:
            c = (cands or {}).get(norm(seed)) or {}
            L.append("| %s | %s | %s |" % (seed, c.get("vol") if c.get("vol") is not None else "—",
                                          (sheet_fate or {}).get(norm(seed), "—")))
        L.append("")
    sheet = {s.lower() for s in S.get("sheet") or ()}
    for subj in sorted(by, key=lambda s: -sum(c["score"] for c in by[s])):
        L += [f"## {subj}" + ("（シートの語）" if subj.lower() in sheet else ""), "",
              "| 優先 | キーワード | 月間 | 難易度 | 開く理由 | 12か月 | 表示 | 出どころ |",
              "|:--|:--|--:|--:|--:|--:|--:|:--|"]
        for c in by[subj]:            # 並び（個別の記事→ピラー）のまま
            tr = c.get("trend")
            L.append("| %s | %s | %s | %s | %+d | %s | %s | %s |" % (
                c["priority"], c["kw"],          # 語の列は語だけ（plan_metrics が台帳の語と突き合わせる）
                c.get("vol") if c.get("vol") is not None else "—",
                c.get("kd") if c.get("kd") is not None else "—",
                c["intent"],
                (f"{tr*100:+.0f}%" if tr is not None else "—"),
                c.get("imp") or "—",
                primary_src(c) + ("（4〜30位）" if c.get("proven") else "")
                + ("・ピラー（後に書く）" if c.get("pillar") else "")))
        L.append("")
    prev = _prev_rows(site_id, ctx.get("keep") or set()) if not DRY else []
    if prev:
        L += ["## 前回までに積んで、台帳に未着手で残っている語", "",
              "| 優先 | キーワード | 月間 | 難易度 | 開く理由 | 12か月 | 表示 | 出どころ |",
              "|:--|:--|--:|--:|--:|--:|--:|:--|"] + prev + [""]
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


ADDED = ROOT / "data" / "kw_plan_added.json"   # kw_plan が積んだ語の記録（サイト別）


def added_before(site_id):
    import client_private as CP
    return set(CP.load_dict("data/kw_plan_added.json", pub=ADDED).get(site_id, []))


def remember_added(site_id, kws):
    """積んだ語を記録する。次の再実行で取り下げないため。お客様の社の語は public に置かない（client_private）"""
    import client_private as CP
    d = CP.load_dict("data/kw_plan_added.json", pub=ADDED)
    cur = set(d.get(site_id, []))
    cur.update(norm(k) for k in kws)
    d[site_id] = sorted(cur)
    CP.save_dict("data/kw_plan_added.json", d, CP.site_key,
                 dump=lambda o: json.dumps(o, ensure_ascii=False, indent=0), pub=ADDED)


def split_retire(todo, plan_kws, own_norms=()):
    """未着手のうち、取り下げる語と残す語に分ける。

    取り下げるのは kw_plan 以前の古い在庫だけ。新計画にもある語と、kw_plan が
    以前に積んだ語は残す。再実行のたびに前回の計画まで取り下げると、点の
    付け方が少し変わるだけで在庫がかき混ぜられ、減る方向に働く（実際に1回で
    25本減った）。同じ検索とみなせる語（語順・助詞違い）も残す"""
    retire, keep = [], []
    for kw in todo:
        if norm(kw) in own_norms or any(same(kw, p) for p in plan_kws):
            keep.append(kw)
        else:
            retire.append(kw)
    return retire, keep


def replace_ledger(site_id, picked, retire_old=True, sheet=()):
    """台帳の「未着手」を対象外にし、新しい計画を積む。公開済み・執筆中は触らない。
    retire_old=False（ラッコの上限で止めた回）は足すだけ。検索数の欠けた薄い計画で在庫を減らさない。
    シートに書いた語（sheet）は、検索数が0でも取り下げない（お客様が狙うと言った語）"""
    import hub_client
    if not hub_client.enabled():
        print("   管制塔が未接続のため、台帳は更新しません")
        return
    rows = hub_client.all_kw(strict=True)
    todo = [r["keyword"] for r in rows if r.get("site") == site_id and r.get("status") == "未着手"]
    retire, keep = split_retire(todo, [c["kw"] for c in picked],
                                added_before(site_id) | {norm(s) for s in sheet})
    if not retire_old and retire:
        print(f"   ラッコの上限で止めた回なので、未着手 {len(retire)}件は取り下げずに残します")
        keep, retire = keep + retire, []
    if retire:
        for i in range(0, len(retire), CHUNK):
            hub_client.retire_kw(site_id, retire[i:i + CHUNK],
                                 "計画を一新（ラッコの実測で組み直し）")
    print(f"   未着手 {len(todo)}件のうち {len(retire)}件を「対象外」に、"
          f"新計画にもある {len(keep)}件はそのまま残しました")
    items = [ledger_item(c) for c in picked]
    added = 0
    for i in range(0, len(items), CHUNK):
        r = hub_client.add_kw(site_id, items[i:i + CHUNK]) or {}
        added += r.get("added", 0)
    print(f"   新しい計画 {added}件を台帳に積みました（site={site_id}）")
    remember_added(site_id, [c["kw"] for c in picked])
    remember_origin(site_id, picked)


def ledger_item(c):
    """台帳に積む1行。備考の先頭に出どころ（後で出どころ別の成果を比べる）"""
    return {"keyword": c["kw"], "priority": c["priority"], "aim": c["subject"],
            "note": "出どころ:%s/月間%s/KD%s/意図%+d" % (primary_src(c), c.get("vol", "—"), c.get("kd", "—"),
                                                     c.get("intent", 0))}


def add_ledger(site_id, picked):
    """台帳に足すだけ（今の未着手は触らない）。積めたか（管制塔が受け付けたか）を返す"""
    import hub_client
    if not hub_client.enabled():
        print("   管制塔が未接続のため、台帳は更新しません")
        return False
    items, added, ok = [ledger_item(c) for c in picked], 0, True
    for i in range(0, len(items), CHUNK):
        r = hub_client.add_kw(site_id, items[i:i + CHUNK]) or {}
        ok = ok and r.get("ok") is not False and bool(r)
        added += r.get("added", 0)
    print(f"   台帳に {added}件を積みました（候補 {len(items)}件。管制塔が重複を弾いた分は積まれません。site={site_id}）")
    remember_added(site_id, [c["kw"] for c in picked])
    remember_origin(site_id, picked)
    return ok


def remember_origin(site_id, picked):
    """積んだ語の出どころ・月・優先度を残す（後で出どころ別の順位・クリック・問い合わせを比べる）。
    お客様の社の語は public に置かない（client_private の置き場）"""
    import client_private as CP
    d = CP.load_dict("data/kw_origin.json", pub=ORIGIN)
    cur = dict(d.get(site_id) or {})
    month = date.today().strftime("%Y-%m")
    for c in picked:
        cur.setdefault(norm(c["kw"]), {"kw": c["kw"], "src": primary_src(c), "month": month,
                                       "priority": c.get("priority"), "proven": bool(c.get("proven"))})
    d[site_id] = cur
    CP.save_dict("data/kw_origin.json", d, CP.site_key,
                 dump=lambda o: json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True) + "\n", pub=ORIGIN)


def runs_done(site_id):
    """その社を最後に組んだ月（'YYYY-MM'）。無ければ空"""
    try:
        return str((json.loads(RUNS.read_text(encoding="utf-8")) or {}).get(site_id) or "")
    except (OSError, ValueError, AttributeError):
        return ""


def mark_done(site_id, month):
    try:
        d = json.loads(RUNS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d[site_id] = month
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    RUNS.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main_rule(site_id):
    """(主力の語か, 主力の配分%, 主力の名前)。補助金は制度の配分（scheme_mix）の一番大きい制度、
    ほかはカテゴリの配分（category_mix）の main_category。どちらも無ければ (None, 0, '')"""
    try:
        import sites
        cfg = sites.load_all().get(site_id) or {}
    except Exception:
        cfg = {}
    smix = {k: v for k, v in (cfg.get("scheme_mix") or {}).items()
            if not str(k).startswith("_") and isinstance(v, (int, float))}
    if smix:
        import site_brief
        top = max(smix, key=smix.get)
        return (lambda kw: site_brief.scheme_of(kw) == top), smix[top], top
    mix = {k: v for k, v in (cfg.get("category_mix") or {}).items()
           if not str(k).startswith("_") and isinstance(v, (int, float))}
    mc = cfg.get("main_category")
    if mc not in mix:
        return None, 0, ""
    try:
        import hub_client
        pat = hub_client._main_offer_pattern(site_id)
    except Exception:
        pat = ""
    name = str((cfg.get("categories") or {}).get(mc, ""))
    words = [norm(t) for t in re.split(r"[・／/\s　]+", name) if len(norm(t)) >= 2]

    def rule(kw):
        return bool(pat and re.search(pat, str(kw).lower())) or any(w in norm(kw) for w in words)
    return rule, mix[mc], name or mc


def stock(site_id):
    """台帳の今の在庫。{"ok", "todo": [語], "a": [優先度Aの未着手], "keys": 同じ組の台帳の語の鍵}。
    管制塔と同じく、組の中のどの状態の語も積み直さない（取り下げた語を戻すと、食い合いで退避した語がまた積まれる）"""
    out = {"ok": False, "todo": [], "a": [], "keys": set()}
    try:
        import hub_client
        import sites
        if not hub_client.enabled():
            return out
        rows = hub_client.all_kw(strict=True)
        group = set(sites.group_of(site_id))
    except Exception as e:
        print(f"   （台帳を読めません: {str(e)[:60]}。重複の照合と在庫の数は管制塔が受け付けるときに見ます）")
        return out
    for r in rows:
        kw = str(r.get("keyword") or "")
        if r.get("site") in group and kw:
            out["keys"] |= ledger_keys(kw)
        if r.get("site") == site_id and str(r.get("status", "")).strip() == "未着手" and kw:
            out["todo"].append(kw)
            if str(r.get("priority") or "").strip() == "A":
                out["a"].append(kw)
    out["ok"] = True
    return out


def _page_slug(url):
    return str(url or "").split("#")[0].rstrip("/").split("/")[-1]


def site_articles(site_id):
    """この社の記事 {slug: 狙う語}"""
    import sites
    out = {}
    for a in load_articles():
        try:
            if sites.find_category_owner(a["cat"]) == site_id and a.get("kw"):
                out[a["slug"]] = a["kw"]
        except Exception:
            continue
    return out


def route_proven(site_id, cands, owned, arts):
    """実証済みの語（4〜30位）のうち、新しく書くと食い合う語を分ける。(書き直しへ回す, 積めない)。
    既存記事が順位を持つ → その記事の書き直し（見出し・共起語の対象）へ。記事以外のページ・他サイトが持つ →
    kw_guard が着手禁止にする（積んでも執筆前のゲートが退避する）ので積まずに計画に書く"""
    import kw_guard
    to_rw, blocked = [], []
    for c in cands.values():
        if not c.get("proven"):
            continue
        own = kw_guard.gsc_owner(c["kw"], owned)
        if not own:
            continue
        o = own[0]
        row = {"kw": c["kw"], "pos": c.get("pos"), "imp": c.get("imp"), "page": o["page"].split("//")[-1]}
        if o.get("own", True) and o.get("site", site_id) == site_id and _page_slug(o["page"]) in arts:
            to_rw.append(dict(row, slug=_page_slug(o["page"])))
        else:
            blocked.append(row)
    return to_rw, blocked


def rewrite_targets(site_id, arts, extra=()):
    """4〜20位にいる自社記事（ページ単位・28日・表示15回以上）。表示×(21−順位) の大きい順。
    狙う語は記事の keyword（書き直しの指示がこの語の上位ページを読む）。extra は実証済みの語を持つ記事（先に置く）"""
    p = kw_reach.RANKS / f"{site_id}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows = d[sorted(d)[-1]] if d else []
    except (OSError, ValueError, KeyError, IndexError):
        rows = []
    pages = defaultdict(lambda: {"imp": 0, "ps": 0.0})
    for r in rows:
        x = pages[_page_slug(r.get("url"))]
        imp = int(r.get("imp") or 0)
        x["imp"] += imp
        x["ps"] += float(r.get("pos") or 0) * imp
    out, seen = [], set()
    for r in extra:
        if r["slug"] in arts and r["slug"] not in seen:
            seen.add(r["slug"])
            out.append({"slug": r["slug"], "kw": arts[r["slug"]], "why": f"実証済みの語「{r['kw']}」を持つ記事"})
    ranked = []
    for slug, x in pages.items():
        if slug not in arts or not x["imp"] or x["imp"] < REWRITE_MIN_IMP:
            continue
        pos = x["ps"] / x["imp"]
        if REWRITE_BAND[0] <= pos <= REWRITE_BAND[1]:
            ranked.append((x["imp"] * (21 - pos), slug, pos, x["imp"]))
    for _v, slug, pos, imp in sorted(ranked, reverse=True):
        if slug not in seen:
            seen.add(slug)
            out.append({"slug": slug, "kw": arts[slug], "why": f"{pos:.1f}位・表示{imp}回の自社記事"})
    return out


def serp_plan(site_id, a_kws, rewrites):
    """見出し・共起語を取る語の並び。これから書く優先度Aと、書き直しの記事を交互に（片方だけで枠を使い切らない）。
    同じ語は1回。[(種類, 語, 理由)]"""
    a = [("write", k, "これから書く優先度A") for k in a_kws[:SERP_A]]
    rw = [("rewrite", r["kw"], f"書き直し {r['slug']}（{r['why']}）") for r in rewrites[:SERP_REWRITE]]
    out, seen = [], set()
    for i in range(max(len(a), len(rw))):
        for lst in (a, rw):
            if i < len(lst) and norm(lst[i][1]) not in seen:
                seen.add(norm(lst[i][1]))
                out.append(lst[i])
    return out


def _serp_cached(site_id, kw, part):
    """この語のこの部分（headline / cooccur / questions）が、kw_serp かラッコの控えに残っているか"""
    import kw_serp
    rec = kw_serp.get(site_id, kw)
    if rec and rec.get(part):
        return True
    path, body = {"headline": (rakko.HEADLINE, rakko.headline_body(kw)),
                  "cooccur": (rakko.COOCCUR, rakko.cooccur_body(kw)),
                  "questions": (rakko.QUESTION, rakko.question_body(kw))}[part]
    return rakko._cache_get(path, body, "POST") is not None


def serp_cost(site_id, plan, qa_kws):
    """(見出し・共起語の見積もり, 実際の質問の見積もり)。kw_serp かラッコの控えにある分は数えない"""
    h = sum(rakko.price(rakko.HEADLINE) * (not _serp_cached(site_id, kw, "headline"))
            + rakko.price(rakko.COOCCUR) * (not _serp_cached(site_id, kw, "cooccur")) for _k, kw, _w in plan)
    q = sum(rakko.price(rakko.QUESTION) * (not _serp_cached(site_id, kw, "questions")) for kw in qa_kws)
    return round(h, 2), round(q, 2)


def fetch_serp(site_id, plan, qa_kws, est):
    """見出し・共起語（headline の枠）と実際の質問（qa の枠）を取り、kw_serp に残す。
    見積もり（est）を超えては呼ばない（見積もりが実際以上であることを保つ）。--dry-run では呼ばずに、
    枠に収まる予定だけを返す。取れた（取る予定の）語の行を返す"""
    import kw_serp
    left = {"headline": float(est.get("headline") or 0), "qa": float(est.get("qa") or 0)}
    names = {"headline": "見出し", "cooccur": "共起語", "questions": "実際の質問"}
    done = []
    for kind, kw, why in plan:
        parts, plan_parts = {}, []
        for part, fn, comp in (("headline", rakko.headline, kw_serp.compact_headline),
                               ("cooccur", rakko.cooccur, kw_serp.compact_cooccur)):
            rec = kw_serp.get(site_id, kw)
            if rec and rec.get(part):
                continue                                   # もう残っている（60日以内）
            path = rakko.HEADLINE if part == "headline" else rakko.COOCCUR
            cost = 0.0 if _serp_cached(site_id, kw, part) else rakko.price(path)
            if left["headline"] + 1e-9 < cost:
                continue
            left["headline"] -= cost
            plan_parts.append(part)
            if DRY:
                continue
            res = fn(kw)
            if res and res.get("result"):
                parts[part] = comp(res)
        if DRY and plan_parts:
            done.append(f"{kw}（{why}・{'・'.join(names[p] for p in plan_parts)}・予定）")
        elif parts and kw_serp.put(site_id, kw, why=why, **parts):
            done.append(f"{kw}（{why}・{'・'.join(names[p] for p in parts)}）")
    for kw in qa_kws:
        rec = kw_serp.get(site_id, kw)
        if rec and rec.get("questions"):
            continue
        cost = 0.0 if _serp_cached(site_id, kw, "questions") else rakko.price(rakko.QUESTION)
        if left["qa"] + 1e-9 < cost:
            continue
        left["qa"] -= cost
        if DRY:
            done.append(f"{kw}（実際の質問・予定）")
            continue
        rows = rakko.questions(kw)
        if rows and kw_serp.put(site_id, kw, why="これから書く語（FAQ の候補）",
                                questions=kw_serp.compact_questions(rows)):
            done.append(f"{kw}（実際の質問 {len(rows)}件）")
    return done


def plan_need(S, cands, plan, qa_kws, short, lookup=True):
    """この回の課金の見積もり（目的ごと）。今月の目的ごとの残りを超える分は見積もらない（その分は呼ばない）。
    一括検索数: 検索数の無い上位の候補（1回最低15・500語まで）＋登録のやり直し1回ぶん。
    予備: 無料の候補が足りないとき（short）だけ、控えに無いサジェスト・関連語（--deep は LSI/PAA も）"""
    site = S["cfg"].get("id", "")
    u = rakko.usage(site, rakko.this_month(), rakko.shared_usage()) if site else {"purposes": {}}
    split = rakko.budget_split(site) if site else dict(rakko.BUDGET_SPLIT)
    room = {p: max(0.0, split[p] - float(u["purposes"].get(p, 0))) for p in split}
    need = defaultdict(float)
    missing = lookup_list(cands) if lookup else []      # 積む本数が0の回は検索数を取らない
    if missing:
        n = -(-len(missing) // BULK)
        need["volume"] = rakko.price("/v1/search-volume", {"keywords": [""] * BULK}) * (n + 1)
    if short:
        need["reserve"] = sum(rakko.price(p, b) or 0 for p, b in paid_queries(S))
        if DEEP:
            need["qa"] += len(S["industries"]) * rakko.price("/v1/other-keywords")
    h, q = serp_cost(site, plan, qa_kws)
    need["headline"] += h
    need["qa"] += q
    return {p: round(min(v, room.get(p, 0.0)), 2) for p, v in need.items() if min(v, room.get(p, 0.0)) > 0}


def lookup_list(cands):
    """一括調査に送る語（検索数が無く、手元の記録にも無い、価値の高い語。fill_volume と同じ選び方）"""
    known = _vol_cache()
    need = [c for k, c in cands.items() if c.get("vol") is None and k not in known]
    return [c["kw"] for c in worth_lookup(need)]


def paid_queries(S):
    """このサイトで課金になる問い合わせの一覧（控えにあるものは除く。gather と同じ中身）"""
    return [(path, body) for path, body, _s in _queries(S) if rakko._cache_get(path, body, "POST") is None]


BULK_COST = 15   # 一括調査1回（検索数のみ・500語まで）。難易度を付けると +0.75/語 になるので付けない


def estimate_parts(S):
    """課金の見積もり（目的ごとのクレジット）。実際より小さく出ると上限が効かないので、実際以上に出す（安全側）。
    単価は公式の資料のまま（rakko.price）。控えに無い問い合わせ ＋ --deep の LSI/PAA（1起点22.5）
    ＋ 一括調査（LOOKUP_MAX 語を BULK 語ずつ・1回最低15）＋ 一括調査の登録のやり直し1回ぶん
    （_fill_part は requestId が返らないと登録し直す）。2026-10-08 の CONFLUX は実際 121回・195 → 見積もり 210。
    run() が S["need"]（この回の目的ごとの見積もり: plan_need）を入れたときはそれを使う"""
    if S.get("need") is not None:
        return {p: round(float(v), 2) for p, v in S["need"].items() if v}
    parts = defaultdict(float)
    for path, body in paid_queries(S):
        p = rakko.price(path, body)
        parts[rakko.PURPOSE_OF.get(path, "reserve")] += rakko.RUN_CAP if p is None else p
    if DEEP:
        parts["qa"] += len(S["industries"]) * rakko.price("/v1/other-keywords")
    parts["volume"] += rakko.price("/v1/search-volume", {"keywords": [""] * BULK}) * (-(-LOOKUP_MAX // BULK) + 1)
    return {p: round(v, 2) for p, v in parts.items()}


def estimate(S):
    return round(sum(estimate_parts(S).values()), 2)


def budget_ok(S):
    """課金の前に必ず見積もり、上限（rakko.allow: 1サイト月150・全体月600・1回150・目的ごとの枠）を通す。
    手で走らせても同じ。超えるならラッコは呼ばない（自動課金なので、警告ではなく止める。2026-10-08 運用者の決定）。
    枠を超える目的だけを外して続けた回も False（計画が欠けるので台帳は足すだけにする）。
    dry-run は判定を見せるだけで、許可は出さない"""
    parts = estimate_parts(S)
    print(f"RAKKO_EST={sum(parts.values()):.0f}")
    print("RAKKO_EST_PARTS=" + (",".join(f"{p}:{v:g}" for p, v in parts.items()) or "なし"))
    if not parts:
        print("   ラッコの課金は要りません（控えと無料の材料で組めます）")
        print("RAKKO_GUARD=ok")
        return True
    return rakko.allow(S["cfg"].get("id", ""), parts, dry=DRY)


def month_need(site_id):
    """1か月分の本数＝1日の本数×30（月の上限まで）。量産の兆候で本数を絞った社は、絞った本数で数える
    （1日0本の社は0＝組み直さない）"""
    import daily_audit as DA
    per_day = DA.DAILY_TARGET
    try:
        import pace
        per_day = min(per_day, pace.quota(site_id))
    except Exception:
        pass
    return min(per_day * ENOUGH_DAYS, DA.MONTHLY_CAP)


def todo_count(site_id):
    try:
        import hub_client
        st = hub_client.status(site_id) or {}
        # 取れなかった（HUB_URL 未設定・管制塔の失敗）を 0 本と数えると、在庫が十分でも課金して組み直す
        if st.get("ok") is False:
            return None
        return int(st.get("todo") or 0)
    except Exception:
        return None


def _drop_rejects(cands, S, sheet_fate):
    """外部に問い合わせずに落とせる語を消す。{理由: 件数}"""
    pre = defaultdict(int)
    for k in list(cands):
        why = cheap_reject(cands[k], S)
        if why:
            pre[why] += 1
            if "sheet" in cands[k]["src"]:
                sheet_fate[k] = why
            del cands[k]
    return pre


def _copy(cands):
    return {k: dict(c, src=set(c["src"])) for k, c in cands.items()}


def run(site_id, deep, replace, if_needed=False, main_first=0):
    """main_first=N は、主力の語だけを最大N本、優先度Aで積み足す（今の未着手は消さない・月1回の組みとは数えない）。
    補助金で、未着手106本中の主力が2本だった。一新（--replace）は主力の候補が11本しか無く、
    在庫を28本まで減らして残りをまた周辺の制度で埋めるだけだった（2026-10-09 の試算）"""
    S = KD.site_config(site_id)
    print(f"\n■ {site_id}（{S['cfg']['name']}）")
    month = rakko.this_month()
    if if_needed:
        n = todo_count(site_id)
        if n is None:
            print("   在庫を確認できないため組み直しません（管制塔の状態が取れない。課金しない）")
            return
        need = month_need(site_id)
        if n >= need:
            print(f"   未着手が {n} 本あるので、今回は組み直しません（1か月分 {need}本を切ったら組み直す）")
            return
        if runs_done(site_id) == month:
            print(f"   未着手 {n} 本は1か月分 {need}本に足りませんが、今月（{month}）はもう組みました（1社1か月1回）")
            return
        print(f"   未着手 {n} 本は1か月分 {need}本に足りないので組みます")
    rakko.BUDGET = rakko.spent() + CREDIT_CAP      # このサイトの分だけ上限をかける
    S["sheet"], S["sheet_ng"] = sheet_terms(site_id)
    if S["sheet"] or S["sheet_ng"]:
        print(f"   シートの狙う語 {len(S['sheet'])}件を起点に、狙わない語 {len(S['sheet_ng'])}件を除外に使います")
    if not S["industries"] and not S["sheet"]:
        print("   kw_seeds が未定義のため作れません")
        return
    # 積む本数: 1か月分×1.2 から今の未着手を引いた分（一新は MAX_PLAN）
    st = stock(site_id)
    need_m = month_need(site_id)
    target = math.ceil(need_m * STOCK_FACTOR)
    limit = MAX_PLAN if replace else (max(0, target - len(st["todo"])) if st["ok"] else target)
    rule, share, main_name = main_rule(site_id)
    have_main = sum(1 for k in st["todo"] if rule and rule(k))
    need_main = 0 if replace or not rule else min(limit, max(0, math.ceil(share / 100 * (len(st["todo"]) + limit)) - have_main))
    if main_first:
        if not rule:
            print("   主力の決まり（scheme_mix / category_mix）が無いため、主力だけを積むことはできません")
            return
        limit = need_main = main_first
    stock_line = (f"在庫: 未着手 {len(st['todo'])}本 ／ 1か月分 {need_m}本 ／ 積む目標 {target}本（1か月分×{STOCK_FACTOR}）"
                  f" → 今回 {limit}本まで積む" if st["ok"] else f"在庫: 台帳を読めないため {limit}本まで組む（積む前に管制塔が重複を弾く）")
    print("   " + stock_line)
    if limit <= 0:
        print("   積む本数が0です（在庫が目標に届いています）")
    # 1〜2. 候補（無料）とふるい（無料）
    cands = collect_free(site_id, S)
    sheet_fate = {}
    pre = _drop_rejects(cands, S, sheet_fate)
    print(f"   無料の候補 {len(cands) + sum(pre.values())}件 → 事前選別で {sum(pre.values())}件を除外（"
          + " / ".join(f"{k} {v}" for k, v in sorted(pre.items(), key=lambda x: -x[1])) + "）")
    owned = [o for o in gsc_owned(site_id) if not is_glossary(o["page"])]
    arts = site_articles(site_id)
    to_rw, blocked = route_proven(site_id, cands, owned, arts)
    rewrites = rewrite_targets(site_id, arts, to_rw)
    # 足りるかを、検索数を取る前に見積もる（検索数を取る語は通る前提で数える。多めに見て2倍に届かなければ予備を使う）
    trial = _copy(cands)
    pending = set(lookup_list(trial))
    for c in trial.values():
        if c["kw"] in pending:
            c["vol_pending"] = True
    pre_pick, _ = choose(trial, S, site_id, limit=max(1, limit) * 2, main=(rule, need_main), ledger=st["keys"],
                         owned=owned, floor=not replace)
    short = limit > 0 and len(pre_pick) < limit * 2
    a_kws = [c["kw"] for c in pre_pick[:max(1, math.ceil(limit / 3))]] + st["a"]
    plan = serp_plan(site_id, a_kws, rewrites)
    qa_kws = [c["kw"] for c in pre_pick[:QA_TOP]]
    # 課金の前に必ず見積もる（目的ごと・今月の残りまで）。上限を超えるならラッコは呼ばず、無料の材料と控えだけで組む
    S["need"] = plan_need(S, cands, plan, qa_kws, short, lookup=limit > 0)
    granted = budget_ok(S)
    est = dict(S["need"])
    if not rakko.enabled() and not DRY:
        print("   RAKKO_API_KEY が未設定です（無料の材料と控えだけで組みます）。python scripts/set_key.py RAKKO_API_KEY")
    # 3. 検索数（一括検索数の枠）。積む本数が0の回は取らない
    n = fill_volume(cands) if limit > 0 else 0
    print(f"   検索数を埋めました: {n}件（未取得 {sum(1 for c in cands.values() if c.get('vol') is None)}件）")
    # 4. 並べる（主力の割合を保つ・問い合わせに近い根拠の無い語は入れない）
    picked, dropped = choose(cands, S, site_id, limit=limit, main=(rule, need_main), ledger=st["keys"], owned=owned,
                             floor=not replace)
    # 8. 予備: 無料の候補で足りないときだけ、ラッコのサジェスト・関連語
    if len(picked) < limit and (est.get("reserve") or DRY):
        print(f"   無料の候補で {len(picked)}/{limit}本しか積めないので、予備（ラッコのサジェスト・関連語）を使います")
        more = gather(site_id, S, deep, into={}, free=False)
        for k, c in more.items():
            if k not in cands:
                cands[k] = c
        _drop_rejects(cands, S, sheet_fate)
        fill_volume(cands)
        picked, dropped = choose(cands, S, site_id, limit=limit, main=(rule, need_main), ledger=st["keys"],
                                 owned=owned, floor=not replace)
    if main_first:
        picked = [c for c in picked if rule(c["kw"])][:main_first]
        for c in picked:
            c["priority"] = "A"
    # 5〜6. 見出し・共起語（これから書く優先度Aの上位＋4〜20位の自社記事）と実際の質問（上位約20語）
    a_kws = [c["kw"] for c in picked if c["priority"] == "A"] + st["a"]
    plan = serp_plan(site_id, a_kws, rewrites)
    qa_kws = [c["kw"] for c in picked[:QA_TOP]]
    got = fetch_serp(site_id, plan, qa_kws, est)
    for seed in S["sheet"]:
        k = norm(seed)
        if k in sheet_fate:
            continue
        c = cands.get(k) or {}
        sheet_fate[k] = ("採用" if any(norm(p["kw"]) == k for p in picked) else
                         c.get("why") or f"点が今回積む本数（{limit}本）に届かない")
    main_now = sum(1 for c in picked if rule and rule(c["kw"]))
    main_line = (f"主力（{main_name}）の語: 配分 {share}% ／ 今の未着手 {have_main}/{len(st['todo'])}本 → 今回 {main_now}/{len(picked)}本"
                 f"（積んだ後 {(have_main + main_now) / max(1, len(st['todo']) + len(picked)) * 100:.0f}%）"
                 + ("" if main_now >= need_main else f" ※主力の候補が足りず目標の {need_main}本に届かない")) if rule else ""
    ctx = {"stock": stock_line, "main": main_line, "est": est, "to_rewrite": to_rw, "blocked": blocked,
           "serp": got, "keep": {norm(k) for k in st["todo"]}}
    out = write_plan(site_id, S, picked, dropped, deep, sheet_fate, cands, ctx)
    print(f"   採用 {len(picked)}本 → {out.relative_to(ROOT).as_posix()}"
          f"（ラッコ消費 {rakko.spent():.0f} クレジット）")
    if main_line:
        print("   " + main_line)
    print("   落とした理由: " + " / ".join(f"{k} {v}" for k, v in sorted(dropped.items(), key=lambda x: -x[1])[:6]))
    print(f"   書き直しへ回した実証済みの語 {len(to_rw)}件 ／ 記事以外・他サイトが持つ実証済みの語 {len(blocked)}件")
    for c in picked[:20]:
        print("     %s %-30s 月間%-5s KD%-3s 意図%+d 出どころ:%s%s" % (
            c["priority"], c["kw"][:30], c.get("vol", "—"), c.get("kd", "—"), c["intent"], primary_src(c),
            "（4〜30位）" if c.get("proven") else ""))
    if DRY:
        return
    if replace:
        replace_ledger(site_id, picked, retire_old=granted, sheet=S["sheet"])
    elif picked and not add_ledger(site_id, picked):
        print("   台帳に積めなかったため、今月の組みは済んだことにしません（翌日の見張りがやり直す）")
        return
    if main_first:
        print(f"   主力の語 {len(picked)}本を優先度Aで積み足しました（今の未着手は残し、月1回の組みとは数えません）")
        return
    if rakko.enabled():
        mark_done(site_id, month)          # 1社1か月1回（鍵の無い回は、鍵が入ったらすぐ組み直せるよう残さない）
        print(f"KW_PLAN_DONE={site_id}:{month}")


def main():
    ap = argparse.ArgumentParser(description="対策キーワードの計画を実測で組み直す")
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--deep", action="store_true", help="LSI/PAA も使う（1起点22.5クレジット）")
    ap.add_argument("--replace", action="store_true", help="台帳の未着手を対象外にして積み直す")
    ap.add_argument("--if-needed", action="store_true",
                    help="未着手が1か月分（1日の本数×30）を切った社だけ、1か月1回積み足す（毎日の在庫の見張り）")
    ap.add_argument("--dry-run", action="store_true",
                    help="ラッコを呼ばず（キャッシュは使う）、候補の構成と課金の見積もりだけ出す")
    ap.add_argument("--main-first", type=int, default=0, metavar="N",
                    help="主力の語だけを最大N本、優先度Aで積み足す（今の未着手は消さない。手で使う）")
    a = ap.parse_args()
    global DRY, DEEP
    DRY, DEEP = a.dry_run, a.deep
    if DRY and a.replace:
        raise SystemExit("--dry-run と --replace は同時に使えません（見積もりで台帳は変えない）")
    if a.main_first and (a.replace or a.if_needed):
        raise SystemExit("--main-first は --replace・--if-needed と同時に使えません")
    import sites as S_
    ids = sorted(S_.load_all()) if a.all else ([a.site] if a.site else [S_.primary()])
    for sid in ids:
        try:
            run(sid, a.deep, a.replace, a.if_needed, a.main_first)
        except Exception as e:           # 1社の失敗で他の社の在庫を止めない（組みは済んだことにしない＝翌日やり直す）
            import traceback
            traceback.print_exc()
            print(f"KW_PLAN_ERROR={sid}: {type(e).__name__}: {str(e)[:120]}")
    if not DRY:
        rakko.sync_shared()                 # この回の消費を管制塔の台帳へ写す（手元とCIで同じ合計にする）
    print(f"\nRAKKO_SPENT={rakko.spent():.0f}（今月の合計 {rakko.month_spent():.0f} / 全体の上限 {rakko.TOTAL_CAP}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
