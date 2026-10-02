# -*- coding: utf-8 -*-
"""業種別の「AIに聞かれている質問」集（/research/<業種>-ai-sources/questions/）。

    python scripts/question_pages.py --data   # 手元の調査の生データから質問ごとの集計を作る（data/research/<業種>-questions.json）
    python scripts/question_pages.py --kw     # 質問の種類ごとに「答えるページの作り方」の記事の語を台帳へ（食い合い審査を通った語だけ）

ページは build.py が集計（コミット済みの JSON）から毎回作る。生データ（*-raw.json）は Git に置かないため、
CI では集計だけを読む。1問1ページにはしない。中身が出典の数字だけのページが500並ぶと、
Google の「大量生成されたコンテンツ」に当たり、サイト全体の評価を落とすおそれがあるため（2026-10-03 決定）。
質問への答えは、品質審査を通った記事として月の上限の中で順に書く（--kw）。

数え方は調査ページの「回答ごと」（industry_ai_sources.per_answer）と同じ。
回答（AI×質問）ごとに、その種類のサイトを1つでも出典にしたかを数える。
"""
import html
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data" / "research"
INDS = ["dental", "clinic", "fudosan", "koumuten", "shigyou"]
E = html.escape

# 質問の種類ごとの記事の語（読者は事業者。「その質問に答えるページをどう作るか」を書く）
KWS = {
    "dental": {"地域で探す": "歯科医院 地域名 検索 上位", "費用": "歯科医院 ホームページ 料金表 書き方",
               "治療の選び方": "歯科医院 ホームページ 治療説明 書き方", "症状": "歯科医院 症状 ページ 作り方",
               "受診のしかた": "歯科医院 ホームページ 初診 案内"},
    "clinic": {"地域で探す": "クリニック 地域名 検索 上位", "費用": "クリニック ホームページ 料金 載せ方",
               "選び方": "クリニック 選ばれる ホームページ", "症状": "クリニック 症状 ページ 作り方",
               "受診のしかた": "クリニック ホームページ 予約 案内"},
    "fudosan": {"地域で探す": "不動産会社 地域名 検索 上位", "費用": "不動産会社 ホームページ 手数料 説明",
                "選び方": "不動産会社 選ばれる ホームページ", "手続き・トラブル": "不動産会社 ホームページ よくある質問",
                "物件・街の探し方": "不動産会社 地域情報 ページ"},
    "koumuten": {"地域で探す": "工務店 地域名 検索 上位", "費用": "工務店 ホームページ 価格 載せ方",
                 "選び方": "工務店 選ばれる ホームページ", "進め方・トラブル": "工務店 ホームページ よくある質問",
                 "住まいの悩み": "リフォーム会社 悩み 記事 集客"},
    "shigyou": {"地域で探す": "士業 地域名 検索 上位", "費用": "士業 ホームページ 報酬 載せ方",
                "選び方": "士業事務所 選ばれる ホームページ", "手続き・悩み": "士業 ホームページ よくある質問",
                "制度・ルール": "士業 制度 解説 記事 集客"},
}


def url(ind):
    return f"/research/{ind}-ai-sources/questions/"


def build_data(ind):
    """生データから質問ごとの集計を作る（生データが無ければ None）"""
    import industry_ai_sources as IAS
    raw_p = DATA / f"{ind}-raw.json"
    if not raw_p.is_file():
        return None
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    known = json.loads(IAS.CLASS_FILE.read_text(encoding="utf-8")) if IAS.CLASS_FILE.is_file() else {}
    cls = lambda d, u="": IAS.rule_class(d, u) or known.get(f"{ind}|{d}") or known.get(d, "other")
    order = [q for _, q in IAS.questions(ind)]
    items = []
    for q in order:
        by = raw["answers"].get(q)
        if not by:
            continue
        answered, kinds, doms = 0, Counter(), Counter()
        dom_kind = {}
        for name, r in by.items():
            if name == "group" or not r.get("urls"):
                continue
            answered += 1
            seen = {}
            for u in r["urls"]:
                d = IAS.domain(u)
                if d:
                    seen.setdefault(d, u)
            for k in {cls(d, u) for d, u in seen.items()}:
                kinds[k] += 1
            for d, u in seen.items():
                doms[d] += 1
                dom_kind[d] = cls(d, u)
        items.append({"q": q, "group": by.get("group", ""), "answered": answered, "kinds": dict(kinds),
                      "top": [[d, dom_kind[d], n] for d, n in doms.most_common(3)]})
    out = {"industry": ind, "date": raw.get("date", ""), "engines": raw.get("engines", []), "items": items}
    (DATA / f"{ind}-questions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load(ind):
    p = DATA / f"{ind}-questions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def labels(ind):
    import industry_ai_sources as IAS
    T = IAS.headline(ind)["T"]
    lab = dict(IAS.CATS)
    lab.update({"clinic": T["owner_site"], "portal": T["portal"], "public": T.get("public_label", lab["public"])})
    return lab, T


def group_stats(d):
    """種類ごと: 回答の数・公式サイト／ポータルを出典にした回答の数"""
    st = {}
    for it in d["items"]:
        s = st.setdefault(it["group"], Counter())
        s["questions"] += 1
        s["answers"] += it["answered"]
        for k, n in it["kinds"].items():
            s[k] += n
    return st


def pct(a, b):
    return f"{a / b * 100:.1f}" if b else "0.0"


def body(ind):
    """ページの本文（BLOG_PAGE の {items} に入れる）と、題・説明"""
    d = load(ind)
    import industry_ai_sources as IAS
    hl = IAS.headline(ind)
    lab, T = labels(ind)
    st = group_stats(d)
    engines = "・".join(d["engines"])
    n = len(d["items"])
    secs = []
    for g, s in st.items():
        rows = []
        for it in [x for x in d["items"] if x["group"] == g]:
            chips = "".join(f'<span class="qa-chip qa-{E(k)}">{E(lab.get(k, k))} {v}/{it["answered"]}</span>'
                            for k, v in sorted(it["kinds"].items(), key=lambda kv: -kv[1])[:3])
            top = "・".join(E(t[0]) for t in it["top"])
            rows.append(f'<li class="qa-item"><p class="qa-q">{E(it["q"])}</p>'
                        + (f'<p class="qa-chips">{chips}</p><p class="qa-top">主な出典: {top}</p>' if it["answered"]
                           else '<p class="qa-top">出典を示した回答はありませんでした</p>') + "</li>")
        lead = (f'この{s["questions"]}問への{s["answers"]}回答のうち、{E(T["owner_site"])}を出典にした回答は'
                f'<strong>{pct(s["clinic"], s["answers"])}%</strong>、{E(T["portal"])}は{pct(s["portal"], s["answers"])}%でした。')
        secs.append(f'<section class="qa-group" id="g-{len(secs) + 1}"><h2>{E(g)}（{s["questions"]}問）</h2>'
                    f'<p class="qa-lead">{lead}</p><ul class="qa-list">{"".join(rows)}</ul></section>')
    toc = "".join(f'<a href="#g-{i}">{E(g)}</a>' for i, g in enumerate(st, 1))
    intro = (f'<section class="qa-intro">'
             f'<p class="qa-how">「{E(T["owner_site"])} 3/4」は、出典を示した4つの回答のうち3つが、その種類のサイトを1つ以上出典にしていたことを表します。'
             f'集計の方法と全体の数字は<a href="/research/{ind}-ai-sources/">調査の本文</a>にあります。</p>'
             f'<nav class="qa-toc" aria-label="質問の種類">{toc}</nav></section>')
    cta = ('<section class="qa-cta"><h2>この質問に、御社のサイトは答えられていますか</h2>'
           '<p>AIが答えに使うのは、質問に答えているページです。御社がAIにどう紹介されているかは、無料で確かめられます。</p>'
           '<p class="qa-btns"><a class="btn btn-primary" href="/tools/ai-check/" data-cta="questions_' + ind + '_ai">AI診断で確かめる</a>'
           f'<a class="btn btn-ghost" href="/download/?ind={IAS.RESEARCH_TO_CHECKLIST.get(ind, "")}" data-cta="questions_{ind}_checklist">'
           'チェックリスト（PDF）を受け取る</a></p></section>')
    title = f'{hl["name"]}でAIに聞かれる質問{n}と出典'
    desc = (f'{hl["name"]}について調べられそうな質問{n}問を{engines}に聞き、答えの出典になったサイトの種類と'
            f'主なサイトを質問ごとにまとめました（{d["date"]}）。')
    return title, desc, intro + "".join(secs) + cta


def link_html(ind):
    """調査の本文から質問集へ"""
    d = load(ind)
    if not d:
        return ""
    return (f'<section><h2>質問ごとの出典</h2><p>{len(d["items"])}問それぞれについて、どの種類のサイトが出典になったかを'
            f'<a href="{url(ind)}" data-cta="research_{ind}_questions">質問集</a>にまとめています。</p></section>\n')


def add_kws():
    import hub_client as HC
    picks = []
    for ind, m in KWS.items():
        for g, kw in m.items():
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "kw_guard.py"), kw, "--site", "ai-lab"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                picks.append({"keyword": kw, "priority": "B", "category": "aio", "note": f"質問集: {ind} {g}"})
            else:
                print(f"  見送り（食い合い審査 {r.returncode}）: {kw}")
    added = (HC.add_kw("ai-lab", picks) or {}).get("added", 0) if picks else 0
    print(f"QUESTIONS_KW_ADDED={added}（候補 {len(picks)}）")


def main():
    if "--data" in sys.argv:
        for ind in INDS:
            d = build_data(ind)
            print(ind, "生データなし" if d is None else f"{len(d['items'])}問")
        return 0
    if "--kw" in sys.argv:
        add_kws()
        return 0
    for ind in INDS:
        d = load(ind)
        print(ind, "集計なし" if not d else f"{len(d['items'])}問 {url(ind)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
