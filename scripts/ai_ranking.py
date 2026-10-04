# -*- coding: utf-8 -*-
"""月次: AIが出典にするサイトのランキング（/research/ranking/）。

業種ごとに「地域で探す」質問（各20問）を Gemini（Google検索つき）に聞き、出典になったサイトを
「何問で出典になったか」で並べる。毎月の順位の動きが分かるので、業界紙やSNSで取り上げられやすく、
社名が書かれる機会になる。Gemini は無料枠（超えると 429 で止まり、課金されない）。5業種で約100回。

    python scripts/ai_ranking.py            # 今月分を調べて data/research/ranking/<年-月>.json に残す
    python scripts/ai_ranking.py --show     # いま残っている月の一覧

ページは build.py が JSON から作る。調べきれなかった業種がある月は残さない（途中の数字を公開しない）。
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "research" / "ranking"
GROUP = "地域で探す"
MIN_ANSWERED = 15          # 20問のうち、出典つきの答えがこれ未満の業種がある月は残さない
JST = timezone(timedelta(hours=9))


def months():
    return sorted(p.stem for p in OUT.glob("*.json"))


def load(ym):
    p = OUT / f"{ym}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def run():
    import ai_recheck as AR
    import industry_ai_sources as IAS
    import question_pages as QP
    known = json.loads(IAS.CLASS_FILE.read_text(encoding="utf-8")) if IAS.CLASS_FILE.is_file() else {}
    now = datetime.now(JST)
    ym = now.strftime("%Y-%m")
    out = {"ym": ym, "date": now.strftime("%Y-%m-%d"), "engine": "Gemini（Google検索つき）", "group": GROUP, "industries": {}}
    new_domains = set()
    for ind in QP.INDS:
        qs = [q for g, q in IAS.questions(ind) if g == GROUP]
        cnt, answered = Counter(), 0
        for q in qs:
            try:
                _, hosts = AR.ask(q)
            except Exception as e:
                print(f"  {ind}: Gemini が止まりました（{str(e)[:60]}）。今月分は残しません")
                print("RANKING_OK=no")
                return None
            if hosts:
                answered += 1
            for h in set(hosts):
                cnt[h] += 1
        if answered < MIN_ANSWERED:
            print(f"  {ind}: 出典つきの答えが {answered}/{len(qs)} 問だけでした。今月分は残しません")
            print("RANKING_OK=no")
            return None

        def cls(d):
            c = IAS.rule_class(d) or known.get(f"{ind}|{d}") or known.get(d)
            if not c:
                new_domains.add(d)
            return c or "other"
        out["industries"][ind] = {"questions": len(qs), "answered": answered,
                                  "top": [[d, cls(d), n] for d, n in cnt.most_common(25)]}
        print(f"  {ind}: {answered}/{len(qs)}問 上位 {', '.join(d for d, _, _ in out['industries'][ind]['top'][:3])}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{ym}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    if new_domains:
        # 種類が決まっていないサイトは「その他」で出る。人が確かめて data/research/source_class.json に足す
        print(f"要対応: ランキングに種類の決まっていないサイトが {len(new_domains)} 件あります（「その他」で表示中）: "
              + "・".join(sorted(new_domains)[:10]) + "（data/research/source_class.json に種類を足す）")
    print("RANKING_OK=yes")
    return out


def _study(ind):
    """業種調査の「何つのAI・何問」。固定の文にすると、AIが上限で答えなかった回に実際と食い違う"""
    import industry_ai_sources as IAS
    p = ROOT / "data" / "research" / f"{ind}-summary.json"
    s = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    return f"{IAS.n_engines(s)}つのAI・{s.get('questions', 0)}問" if s else "業種別の調査"


def body():
    """ランキングのページ（最新の月・前月との比較）。月が無ければ None"""
    import html
    import question_pages as QP
    ms = months()
    if not ms:
        return None
    cur = load(ms[-1])
    prev = load(ms[-2]) if len(ms) > 1 else None
    E = html.escape
    y, m = cur["ym"].split("-")
    secs = []
    for ind in QP.INDS:
        d = cur["industries"].get(ind)
        if not d:
            continue
        lab, T = QP.labels(ind)
        import industry_ai_sources as IAS
        name = IAS.headline(ind)["name"]
        before = {}
        if prev and prev["industries"].get(ind):
            before = {dom: i for i, (dom, _, _) in enumerate(prev["industries"][ind]["top"], 1)}
        rows = []
        for i, (dom, c, n) in enumerate(d["top"][:10], 1):
            b = before.get(dom)
            move = "—" if not prev else ("初登場" if b is None else ("→" if b == i else (f"↑{b - i}" if b > i else f"↓{i - b}")))
            rows.append(f'<tr><td class="rk-n">{i}</td><td class="rk-d">{E(dom)}</td><td>{E(lab.get(c, c))}</td>'
                        f'<td class="rk-c">{n}/{d["answered"]}問</td><td class="rk-m">{move}</td></tr>')
        secs.append(f'<section class="rk-sec"><h2>{E(name)}</h2>'
                    f'<p class="qa-lead">「地域名＋{E(T["owner"])}を探す」{d["questions"]}問のうち、出典つきで答えた{d["answered"]}問で、'
                    '何問の出典になったかの順です。</p>'
                    '<div class="rk-wrap"><table class="rk"><thead><tr><th>順位</th><th>サイト</th><th>種類</th><th>出典になった質問</th><th>前月</th></tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table></div>'
                    f'<p class="qa-how"><a href="/research/{ind}-ai-sources/">{E(name)}の調査（{_study(ind)}）</a> ／ '
                    f'<a href="{QP.url(ind)}">質問ごとの出典</a></p></section>')
    hist = "・".join(f'{x[:4]}年{int(x[5:])}月' for x in ms)
    intro = ('<section class="qa-intro"><p class="qa-how">毎月1日に、業種ごとの「地域で探す」質問を Gemini（Google検索つき）に聞き、'
             '答えの出典になったサイトを数えています。AIの答えは日によって変わるため、1か月の順位だけで判断せず、どの種類のサイトが'
             f'上位に並ぶかを見てください。これまでの調べ: {E(hist)}</p></section>')
    cta = ('<section class="qa-cta"><h2>御社のサイトは、AIの答えの出典に入っていますか</h2>'
           '<p class="qa-btns"><a class="btn btn-primary" href="/tools/ai-check/" data-cta="ranking_ai">AI診断で確かめる</a>'
           '<a class="btn btn-ghost" href="/tools/" data-cta="ranking_tools">無料ツールの一覧</a></p></section>')
    title = f"AIが出典にするサイトのランキング（{y}年{int(m)}月）"
    desc = (f"歯科・クリニック・不動産・工務店・士業で、地域の事業者を探す質問にAI（Gemini）が出典にしたサイトを、"
            f"出典になった質問の数で並べました（{cur['date']}調べ・毎月更新）。")
    return title, desc, intro + "".join(secs) + cta


def main():
    if "--show" in sys.argv:
        print("\n".join(months()) or "まだありません")
        return 0
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
