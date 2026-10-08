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
import kw_fit                     # noqa: E402  担当領域の判定（積む・選ぶ・書く前後で同じ基準）
import kw_intent                  # noqa: E402
import kw_reach                   # noqa: E402
import rakko                      # noqa: E402
from cannibal_check import dice, kw_conflicts, load_articles  # noqa: E402
from kw_status import is_written, written_corpus              # noqa: E402

MAX_PLAN = 120        # 1サイトの計画本数。1日2本で60日分
ENOUGH = 40           # 未着手がこれ以上あるサイトは、--if-needed のとき組み直さない（20日分）
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
    if prio and (c.get("subject") in prio or any(ind_query(p).lower() in c["kw"].lower() for p in prio)):
        s += PRIORITY_BONUS                        # 月1件で費用が回収できる業種
    # 公開1〜4週に15位以内（3回以上表示）に入った記事だけが6週以降も残った（2026-10-05・3サイト）。
    # 広い語（1語・大きい検索数・高い難易度）を下げ、条件つきの細い語と、自サイトが近い語で
    # 既に15位以内にいる主題を上げる。検索数の対数の加点（大きい語ほど得）を打ち消しすぎない重み
    s += kw_reach.reach(c["kw"], vol, kd, held) * REACH_WEIGHT
    return round(s, 2)


DRY = False   # True のとき、ラッコは呼ばず（キャッシュにあれば使う）、課金の見積もりだけ出す
DEEP = False  # --deep（LSI/PAA を1起点22.5で取る）。見積もりに含めるため main で立てる


def gather(site_id, S, deep):
    """サブジェクト（起点）ごとに候補を集める。(kw -> 候補dict)"""
    cands = {}
    paid = {"calls": 0}

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

    def paid_call(fn, *a, **k):
        """課金の呼び出し。--dry-run ではキャッシュにあるときだけ返し、無ければ数だけ数える"""
        if DRY:
            path, body = ((rakko.RELATED, rakko.related_body(a[0])) if fn is rakko.related
                          else (rakko.SUGGEST, rakko.suggest_body(a[0])))
            hit = rakko._cache_get(path, body, "POST")
            if hit is None:
                paid["calls"] += 1
                return []
            return rakko._rows(hit)
        return fn(*a, **k)

    # 2-0. シートの「狙う語」。それ自体が領域の語なので、業種に掛けず単体で聞く。
    # 語そのものも候補に入れる（検索数は一括で埋める）
    for seed in S.get("sheet") or []:
        put(seed, seed, "sheet")
        rows = rakko.as_rows(paid_call(rakko.related, seed)) + rakko.as_rows(paid_call(rakko.suggest, seed))
        for kw, vol, kd in rows:
            put(kw, seed, "rakko", vol=vol, kd=kd)

    for ind in S["industries"]:
        if ind.lower() in S["own_terms"]:
            queries = [ind]
            rows = rakko.as_rows(paid_call(rakko.related, ind))
        else:
            queries = [f"{ind_query(ind)} {t}" for t in own_core]
            rows = []
        for q in queries:
            rows += rakko.as_rows(paid_call(rakko.suggest, q))
        for kw, vol, kd in rows:
            put(kw, ind, "rakko", vol=vol, kd=kd)
        if deep and not DRY:
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
            for s in KD.suggest(f"{ind_query(ind)} {it}"):
                put(s, ind, "suggest")
        time.sleep(0.2)
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
    if (vol is None or vol < MIN_VOL) and (c.get("imp") or 0) < GSC_KEEP_IMP:
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


def choose(cands, S, site_id):
    corpus, arts = written_corpus(), load_articles()
    owned = gsc_owned(site_id)
    prio = priority_subjects(S)
    held = kw_reach.held_queries(site_id)
    ranked = sorted(cands.values(), key=lambda c: -score(c, prio, held))
    picked, why_drop, per_subject = [], defaultdict(int), defaultdict(int)
    picked_norms = []
    weak_room = max(1, int(MAX_PLAN * WEAK_SHARE))
    for c in ranked:
        if len(picked) >= MAX_PLAN:
            break
        r = relevant(c, S, corpus, arts, owned, picked_norms)
        cap = PER_PRIORITY if c["subject"] in prio else PER_SUBJECT
        weak = kw_intent.score(c["kw"])[0] < 0
        if not r and per_subject[c["subject"]] >= cap:
            r = "サブジェクト上限"
        if not r and weak and weak_room <= 0:
            r = "弱い語の上限"
        if r:
            why_drop[r] += 1
            c["why"] = r          # シートの語が入らなかった理由を計画に書くため
            continue
        c["score"] = score(c, prio, held)
        c["intent"] = kw_intent.score(c["kw"])[0]
        c["reach"] = kw_reach.reach(c["kw"], c.get("vol"), c.get("kd"), held)
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


def write_plan(site_id, S, picked, dropped, deep, sheet_fate=None, cands=None):
    out = ROOT / "docs" / (f"kw-plan-{site_id}.md" if not DRY else f"kw-plan-{site_id}.dry.md")
    by = defaultdict(list)
    for c in picked:
        by[c["subject"]].append(c)
    L = [f"# {S['cfg']['name']}（{S['cfg']['domain']}）の対策キーワード計画",
         "",
         f"作成: {date.today().isoformat()} ／ 根拠: ラッコキーワード（月間検索数・SEO難易度・12か月の伸び）"
         f"＋Search Console（自サイトの表示実績）{'＋LSI/PAA' if deep else ''}",
         "",
         f"優先業種（枠{PER_PRIORITY}本・加点{PRIORITY_BONUS}）: "
         + ("／".join(priority_subjects(S)) or "指定なし") + f" ／ その他は枠{PER_SUBJECT}本",
         "",
         (f"ラッコの消費: 約{rakko.spent():.0f}クレジット（1回の上限 {CREDIT_CAP}）" if not DRY else
          "ラッコの消費: なし（dry-run。控え data/rakko_cache・rakko_volume.json にある応答だけで組み直し）"),
         "",
         f"採用 {len(picked)}本（A={sum(c['priority']=='A' for c in picked)} / "
         f"B={sum(c['priority']=='B' for c in picked)} / C={sum(c['priority']=='C' for c in picked)}）。"
         "点は「検索数・開く理由・難易度の低さ・伸び・自サイトの表示実績」の合計。",
         "",
         "落とした理由: " + " / ".join(f"{k} {v}件" for k, v in sorted(dropped.items(), key=lambda x: -x[1])),
         ""]
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
    items = [{"keyword": c["kw"], "priority": c["priority"], "aim": c["subject"],
              "note": "月間%s/KD%s/意図%+d" % (c.get("vol", "—"), c.get("kd", "—"), c["intent"])}
             for c in picked]
    added = 0
    for i in range(0, len(items), CHUNK):
        r = hub_client.add_kw(site_id, items[i:i + CHUNK]) or {}
        added += r.get("added", 0)
    print(f"   新しい計画 {added}件を台帳に積みました（site={site_id}）")
    remember_added(site_id, [c["kw"] for c in picked])


def paid_queries(S):
    """このサイトで課金になる問い合わせの一覧（キャッシュにあるものは除く）"""
    core = core_terms(S)
    qs = []
    for seed in S.get("sheet") or []:      # シートの「狙う語」は単体で関連語とサジェスト（gather と同じ）
        qs += [(rakko.RELATED, rakko.related_body(seed)), (rakko.SUGGEST, rakko.suggest_body(seed))]
    for ind in S["industries"]:
        if ind.lower() in S["own_terms"]:
            qs += [(rakko.RELATED, rakko.related_body(ind)), (rakko.SUGGEST, rakko.suggest_body(ind))]
        else:
            qs += [(rakko.SUGGEST, rakko.suggest_body(f"{ind_query(ind)} {t}")) for t in core]
    return [(path, body) for path, body in qs if rakko._cache_get(path, body, "POST") is None]


BULK_COST = 15   # 一括調査1回（検索数のみ・500語まで）。難易度を付けると +0.75/語 になるので付けない


def estimate_parts(S):
    """課金の見積もり（目的ごとのクレジット）。実際より小さく出ると上限が効かないので、実際以上に出す（安全側）。
    単価は公式の資料のまま（rakko.price）。控えに無い問い合わせ ＋ --deep の LSI/PAA（1起点22.5）
    ＋ 一括調査（LOOKUP_MAX 語を BULK 語ずつ・1回最低15）＋ 一括調査の登録のやり直し1回ぶん
    （_fill_part は requestId が返らないと登録し直す）。2026-10-08 の CONFLUX は実際 121回・195 → 見積もり 210"""
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
    return rakko.allow(S["cfg"].get("id", ""), parts, dry=DRY)


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


def run(site_id, deep, replace, if_needed=False):
    S = KD.site_config(site_id)
    print(f"\n■ {site_id}（{S['cfg']['name']}）")
    if if_needed:
        n = todo_count(site_id)
        if n is None:
            print("   在庫を確認できないため組み直しません（管制塔の状態が取れない。課金しない）")
            return
        if n >= ENOUGH:
            print(f"   未着手が {n} 本あるので、今回は組み直しません（{ENOUGH}本未満で組み直す）")
            return
    rakko.BUDGET = rakko.spent() + CREDIT_CAP      # このサイトの分だけ上限をかける
    S["sheet"], S["sheet_ng"] = sheet_terms(site_id)
    if S["sheet"] or S["sheet_ng"]:
        print(f"   シートの狙う語 {len(S['sheet'])}件を起点に、狙わない語 {len(S['sheet_ng'])}件を除外に使います")
    if not S["industries"] and not S["sheet"]:
        print("   kw_seeds が未定義のため作れません")
        return
    # 課金の前に必ず見積もる。予算内でなければ取得しない（--dry-run は見積もりだけ）
    # 上限を超えるならラッコは呼ばず（call() が断る）、無料の材料と控えだけで組む。
    # そのときの計画は検索数が欠けて薄いので、台帳は足すだけにして今の在庫を取り下げない
    granted = budget_ok(S)
    if not rakko.enabled():
        print("   RAKKO_API_KEY が未設定です。python scripts/set_key.py RAKKO_API_KEY")
        return
    cands = gather(site_id, S, deep)
    pre = defaultdict(int)
    sheet_fate = {}
    for k in list(cands):
        why = cheap_reject(cands[k], S)
        if why:
            pre[why] += 1
            if "sheet" in cands[k]["src"]:
                sheet_fate[k] = why
            del cands[k]
    print(f"   候補 {len(cands) + sum(pre.values())}件（起点 {len(S['industries'])}件）→ "
          f"事前選別で {sum(pre.values())}件を除外（"
          + " / ".join(f"{k} {v}" for k, v in sorted(pre.items(), key=lambda x: -x[1])) + "）")
    n = fill_volume(cands)
    print(f"   検索数を一括で埋めました: {n}件（未取得 "
          f"{sum(1 for c in cands.values() if c.get('vol') is None)}件）")
    picked, dropped = choose(cands, S, site_id)
    for seed in S["sheet"]:
        k = norm(seed)
        if k in sheet_fate:
            continue
        c = cands.get(k) or {}
        sheet_fate[k] = ("採用" if any(norm(p["kw"]) == k for p in picked) else
                         c.get("why") or f"点が計画の上限（{MAX_PLAN}本）に届かない")
    out = write_plan(site_id, S, picked, dropped, deep, sheet_fate, cands)
    print(f"   採用 {len(picked)}本 → {out.relative_to(ROOT).as_posix()}"
          f"（ラッコ消費 {rakko.spent():.0f} クレジット）")
    print("   落とした理由: " + " / ".join(f"{k} {v}" for k, v in sorted(dropped.items(), key=lambda x: -x[1])[:6]))
    for c in picked[:8]:
        print("     %s %-30s 月間%-5s KD%-3s 意図%+d %s" % (
            c["priority"], c["kw"][:30], c.get("vol", "—"), c.get("kd", "—"), c["intent"], c["subject"]))
    if replace:
        replace_ledger(site_id, picked, retire_old=granted, sheet=S["sheet"])
    else:
        print("   （--replace を付けると、台帳の未着手を対象外にして新計画を積みます）")


def main():
    ap = argparse.ArgumentParser(description="対策キーワードの計画を実測で組み直す")
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--deep", action="store_true", help="LSI/PAA も使う（1起点22.5クレジット）")
    ap.add_argument("--replace", action="store_true", help="台帳の未着手を対象外にして積み直す")
    ap.add_argument("--if-needed", action="store_true",
                    help=f"未着手が{ENOUGH}本未満のサイトだけ組み直す（月次の定常運転用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="ラッコを呼ばず（キャッシュは使う）、候補の構成と課金の見積もりだけ出す")
    a = ap.parse_args()
    global DRY, DEEP
    DRY, DEEP = a.dry_run, a.deep
    if DRY and a.replace:
        raise SystemExit("--dry-run と --replace は同時に使えません（見積もりで台帳は変えない）")
    import sites as S_
    ids = sorted(S_.load_all()) if a.all else ([a.site] if a.site else [S_.primary()])
    for sid in ids:
        run(sid, a.deep, a.replace, a.if_needed)
    if not DRY:
        rakko.sync_shared()                 # この回の消費を管制塔の台帳へ写す（手元とCIで同じ合計にする）
    print(f"\nRAKKO_SPENT={rakko.spent():.0f}（今月の合計 {rakko.month_spent():.0f} / 全体の上限 {rakko.TOTAL_CAP}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
