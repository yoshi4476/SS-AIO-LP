# -*- coding: utf-8 -*-
"""通常の動画（5〜6分の掛け合い）を作るかどうかと、その題を YouTube のサジェストで決める。

**なぜ要るか**（実測 2026-10-05・公開中11本）: ショート5本は1本183〜543回再生、
通常の動画6本は0〜1回。通常の動画は記事の題をそのまま付けていて、YouTube で
その言い方を検索する人がいなかった。ショートで見られたのは「〜はいくら？」
「〜は何から始める？」のような問いの形。

- YouTube のサジェスト（kw_discover.suggest(source="youtube")・無料）に、記事の狙う語と
  業種に近い検索語が出るテーマだけ通常の動画を作る。出なければショートだけにする
- 題は、その検索語を先頭に置いた問いかけ型。記事に無い数字は入れない（duo_video.validate と同じ考え）
- サジェストが取れなかった（通信の失敗）ときは「無い」と決めない（unknown。翌日また判定する）

これから作る動画にだけ使う。上げ済みの動画の題・説明は変えない。

    python scripts/yt_demand.py <slug> [<slug> ...]   # 判定と題を見る（サジェストを数回引くだけ。作らない）
    python scripts/yt_demand.py --selftest
"""
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TITLE_SOFT = 70      # 検索結果で切れずに見える長さの目安。超えたら後ろの添え書きを落とす
TITLE_MAX = 100      # YouTube の題の上限（videos の snippet.title は100字まで）
MAX_QUERIES = 5      # 1記事でサジェストを引く回数の上限（狙う語＋1語ずつ落とした4組）

# 問いの形。ショートで再生が多かった「〜はいくら？」「〜は何から始める？」を基準にする
ASK = (
    (re.compile(r"とは$"), "{t}？"),
    (re.compile(r"違い$"), "{t}は？"),
    (re.compile(r"費用|料金|相場|価格|値段|いくら"), "{t}はいくら？"),
    (re.compile(r"選び方|比較|おすすめ|テンプレ|ツール"), "{t}はどれを選ぶ？"),
    (re.compile(r"書き方|作り方|出し方|例文"), "{t}はどう書く？"),
    (re.compile(r"補助金|助成金"), "{t}は何が使える？"),
)
ASK_DEFAULT = "{t}は何から始める？"


def _norm(s):
    return re.sub(r"[\s・／/、]+", "", (s or "").lower())


def tokens(keyword):
    return [t for t in re.split(r"[\s・／/、]+", (keyword or "").lower()) if t]


def _nums(s):
    import duo_video as DV
    return set(DV._nums(s))


def article(slug):
    """題・狙う語・本文（数字の照合に使う）"""
    import duo_video as DV
    art = DV.article(slug)
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")[:3000]
    m = re.search(r"^keyword:\s*(.+)$", t, re.M)
    art["keyword"] = m.group(1).strip().strip('"') if m else ""
    return art


def split_kw(keyword):
    """狙う語を、業種の語と話題の語に分ける（業種は industry_hub の定義で判定）"""
    import industry_hub as IH
    inds, _ = IH.load()
    ind, topic = [], []
    for t in tokens(keyword):
        (ind if IH.detect(t, "", inds) else topic).append(t)
    return ind, topic


def queries(keyword):
    """狙う語そのものと、1語ずつ落とした組（YouTube では長い語ほど候補が出ない）"""
    tk = tokens(keyword)
    out = [" ".join(tk)]
    if len(tk) >= 3:
        out += [" ".join(tk[:i] + tk[i + 1:]) for i in range(len(tk))]
    seen, uniq = set(), []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:MAX_QUERIES]


def fits(term, keyword, art_text):
    """サジェストの語が、記事の狙う語と業種に近いか。近ければ点（大きいほど近い）、遠ければ None"""
    ind, topic = split_kw(keyword)
    n = _norm(term)
    if ind and not any(_norm(t) in n for t in ind):
        return None
    # 英字の語（aio・llmo・meo…）は記事の手法そのもの。欠けた語は別の話題
    # （「税理士 法人 aio」→「税理士 法人税法」は税法の勉強の検索だった）
    if any(t.isascii() and _norm(t) not in n for t in topic):
        return None
    hits = sum(1 for t in topic if _norm(t) in n)
    # 話題の語が1つだけ合う語は別の話題が多い（「aio チェッカー」→「aio」はゲームの検索だった）。
    # 業種の語が合っていれば話題は半分でよい（「クリニック 建築 事例」→「クリニック 建築」）
    if topic and hits < math.ceil(len(topic) * (1 / 2 if ind else 2 / 3)):
        return None
    if not _nums(term) <= _nums(art_text):
        return None
    # 同点なら狙う語の先頭の語で始まるものを先に（「無料 請求書」より「請求書 テンプレート」）
    head = tokens(keyword)[:1]
    return hits + (1 if ind else 0), int(bool(head) and n.startswith(_norm(head[0])))


def _display(term, title):
    """英字の大文字小文字は記事の題に合わせる（サジェストは小文字で返る）"""
    def fix(m):
        w = m.group(0)
        i = title.lower().find(w.lower())
        return title[i:i + len(w)] if i >= 0 else w
    return re.sub(r"[A-Za-z][A-Za-z0-9]*", fix, term)


def make_title(term, art):
    """検索語を先頭に置いた問いかけ型の題。記事に無い数字は入れない"""
    t = _display(term, art["title"])
    ask = next((f for p, f in ASK if p.search(t)), ASK_DEFAULT)
    q = ask.format(t=t)
    # 添え書きは記事の題のうち、検索語と重ならない側（「｜」か「？」で分かれた後ろ）
    parts = [p for p in re.split(r"｜|(?<=？)", art["title"]) if p.strip()]
    sub = min(parts, key=lambda p: sum(1 for x in tokens(term) if _norm(x) in _norm(p))) if parts else ""
    sub = sub.strip()
    if sub and _norm(sub.rstrip("？")) != _norm(q.rstrip("？")):
        cand = f"{q}｜{sub}"
        if len(cand) <= TITLE_SOFT:
            q = cand
    return q[:TITLE_MAX]


def title_ng(title, term, art):
    """題として通してよいか（空なら合格）"""
    ng = []
    if not title.startswith(_display(term, art["title"])):
        ng.append("検索語が題の先頭に無い")
    if "？" not in title:
        ng.append("問いの形になっていない")
    if len(title) > TITLE_MAX:
        ng.append(f"題が{len(title)}字（上限{TITLE_MAX}）")
    extra = _nums(title) - _nums(art["text"])
    if extra:
        ng.append(f"記事に無い数字 {sorted(extra)}")
    return ng


def _fetch(q):
    import kw_discover as K
    return K.suggest(q, source="youtube", strict=True)


def judge(slug, fetch=None, art=None):
    """通常の動画を作るか。decision は make / skip / unknown（サジェストが取れなかった）"""
    fetch = fetch or _fetch
    art = art or article(slug)
    kw = art.get("keyword") or art["title"]
    rec = {"date": date.today().isoformat(), "keyword": kw}
    got, failed, qs = [], 0, queries(kw)
    for q in qs:
        try:
            got += [s for s in fetch(q) if s not in got]
        except Exception:
            failed += 1
    rec["queries"] = qs
    if qs and failed == len(qs):
        return dict(rec, decision="unknown", reason="YouTube のサジェストを取れませんでした（翌日また判定）")
    scored = [(fits(s, kw, art["text"]), -i, s) for i, s in enumerate(got)]  # 同点なら先に出た語（需要が大きい）
    scored = [x for x in scored if x[0] is not None]
    if not scored:
        return dict(rec, decision="skip", suggestions=got[:10],
                    reason="YouTube のサジェストに、狙う語と業種に近い検索語が出ませんでした（ショートだけにする）")
    term = max(scored)[2]
    title = make_title(term, art)
    ng = title_ng(title, term, art)
    if ng:
        return dict(rec, decision="skip", term=term, reason="題が検査に通りません: " + " / ".join(ng))
    return dict(rec, decision="make", term=term, title=title, reason=f"YouTube のサジェストに「{term}」が出ます")


def selftest():
    art = {"title": "農業の初期費用は平均755万円｜費目別に使える補助金4つ", "keyword": "農業 初期 費用 補助金",
           "text": "# 農業の初期費用は平均755万円｜費目別に使える補助金4つ\n平均755万円。補助金は4つ。"}
    ok = True
    j = judge("x", fetch=lambda q: ["農業 初期費用", "農業 補助金 2031", "農業 ドローン 補助金"], art=art)
    ok &= j["decision"] == "make" and j["title"].startswith("農業 初期費用") and "2031" not in j["title"]
    ok &= judge("x", fetch=lambda q: ["農業 ドローン 補助金", "工務店 集客"], art=art)["decision"] == "skip"
    ok &= judge("x", fetch=lambda q: [], art=art)["decision"] == "skip"

    def down(q):
        raise OSError("network")
    ok &= judge("x", fetch=down, art=art)["decision"] == "unknown"
    print("YT_DEMAND_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    for slug in args:
        art = article(slug)
        j = judge(slug, art=art)
        print(f"■ {slug}\n  記事の題: {art['title']}\n  判定: {j['decision']}（{j['reason']}）")
        if j.get("title"):
            print(f"  動画の題: {j['title']}")
        print("  " + json.dumps({k: j.get(k) for k in ("queries", "suggestions") if j.get(k)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
