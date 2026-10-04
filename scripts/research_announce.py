# -*- coding: utf-8 -*-
"""毎月のランキング更新に合わせた「お知らせ」の下書き（プレスリリース風の文面と SNS 用の短文）。

**なぜ要るか**: AI検索での見え方は被リンクより言及で決まる（YouTube 0.71・リンク無しの言及 0.66 ＞ 被リンク 0.22。
CLAUDE.md 0.3節）。毎月の順位の動きは業界紙・SNSで取り上げられやすいので、出せる形の文面を毎月そろえておく。

**配信・送信はしない。** docs/announcements/<年-月>.md に書き、social_post のキューに積むだけ。出すかは人が決める。
**数字は集計（data/research/ranking/<年-月>.json）そのものだけ**。割合を計算し直したり、業種をまとめて
「どの業種でも」と言い切ったりしない（research_promo の検査をそのまま使う）。

    python scripts/research_announce.py            # 最新の月の下書きを表示するだけ
    python scripts/research_announce.py --write    # 書いてキューに積む（同じ月は二度作らない）
    python scripts/research_announce.py --selftest
出す印: ANNOUNCE_OK=yes|no / ANNOUNCE_MADE=0|1
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "docs" / "announcements"
PREFIX = "announce-ranking-"


def _names(cur):
    import industry_ai_sources as IAS
    return {ind: (IAS.headline(ind) or {}).get("name") or IAS.QUESTIONS[ind]["name"] for ind in cur["industries"]}


def _labels(ind):
    import industry_ai_sources as IAS
    try:
        import question_pages as QP
        return QP.labels(ind)[0]
    except Exception:
        return dict(IAS.CATS)


def compose(cur, prev):
    """(題, md本文, SNSの投稿 dict, 図のHTML)。数字は cur・prev の値をそのまま差し込む"""
    import ai_ranking as AR
    import research_cite as RC
    names = _names(cur)
    ym = RC.ym_text(cur["date"])
    page_title = f"AIが出典にするサイトのランキング（{ym}）"
    title = f"{page_title}を公開しました"
    org = RC.org_label(RC.LAB)
    inds = [i for i, d in cur["industries"].items() if d.get("top")]
    q = sorted({cur["industries"][i]["questions"] for i in inds})
    qtxt = "・".join(f"{n}問" for n in q)
    lead = (f"{org}は、{'・'.join(names[i] for i in inds)}の業種ごとに、地域の事業者を探す質問（各{qtxt}）を"
            f"{cur['engine']}に聞き、答えの出典になったサイトを数えたランキングの{ym}版を公開しました（{cur['date']}調べ）。")

    firsts = []
    for i in inds:
        d = cur["industries"][i]
        dom, c, n = d["top"][0]
        firsts.append(f"{names[i]}は {dom}（{_labels(i).get(c, c)}）で、出典つきで答えた{d['answered']}問のうち{n}問の出典でした")
    p1 = "各業種の1位: " + "。".join(firsts) + "。"
    if prev:
        same = [names[i] for i in inds if prev["industries"].get(i, {}).get("top")
                and prev["industries"][i]["top"][0][0] == cur["industries"][i]["top"][0][0]]
        moved = [names[i] for i in inds if names[i] not in same]
        p2 = ("前月との比較: " + (f"1位が前月と同じサイトだった業種は{'・'.join(same)}。" if same else "")
              + (f"1位が入れ替わった業種は{'・'.join(moved)}。" if moved else ""))
    else:
        p2 = "前月との比較: 今月が最初の調べです。前月からの順位の動きは、来月の版から載せます。"
    tops = []
    for i in inds:
        lab = _labels(i)
        kinds = "／".join(lab.get(c, c) for _, c, _ in cur["industries"][i]["top"][:3])
        tops.append(f"{names[i]}は {kinds}")
    p3 = "上位3つのサイトの種類（1位から順に）: " + "。".join(tops) + "。業種によって上位に並ぶサイトの種類は違います。"

    spec = AR.chart_spec(cur)
    w, h = RC.size(spec)
    img = RC.LAB_URL + AR.IMG_PATH
    fig = RC.embed_html(img, AR.PAGE_URL, f"{page_title}の各業種の1位", f"{org}「{page_title}」", w, h)
    line = RC.cite_line(org, page_title, cur["date"], AR.PAGE_URL)
    method = [f"質問: 業種ごとに「{cur['group']}」の質問（地域名＋業種名で事業者を探す言い回し、各{qtxt}）",
              f"AI: {cur['engine']}",
              f"調べた日: {cur['date']}",
              "数え方: 出典つきで答えた質問のうち、そのサイトが何問の出典になったかで並べました（1つの答えで同じサイトは1回）",
              "AIの答えは日によって変わります。この結果は調べた日時点のものです"]
    md = [f"# {title}", "",
          "> 下書きです（自動作成）。配信・送信はしていません。出すかどうか・どこに出すかは人が決めます。", "",
          lead, "",
          "## 要点", "",
          f"1. {p1}", f"2. {p2}", f"3. {p3}", "",
          "## 図", "",
          f"![{page_title}の各業種の1位]({img})", "",
          "貼るときのHTML:", "", "```html", fig, "```", "",
          "## 調査の方法", ""] + [f"- {x}" for x in method] + [
          "", "## 引用の条件", "", RC.TERMS, "", "出典の書き方（そのまま貼れます）:", "", line, "",
          "## 会社概要・お問い合わせ", "",
          f"- {org}", f"- 調査ページ: {AR.PAGE_URL}", f"- サイト: {RC.LAB_URL}/", f"- お問い合わせ: {RC.CONTACT_URL}", ""]
    ex = firsts[0] if firsts else ""
    x = (f"{page_title}を公開しました。地域の事業者を探す質問で、AIが出典にしたサイトを業種ごとに数えています。"
         f"{ex}。\n{AR.PAGE_URL}")
    import social_post as SP
    if len(x) > SP.LIMITS["x"]:
        x = f"{page_title}を公開しました。地域の事業者を探す質問で、AIが出典にしたサイトを業種ごとに数えています。\n{AR.PAGE_URL}"
    fb = "\n".join([title, "", lead, "", f"・{p1}", f"・{p2}", f"・{p3}", "", AR.PAGE_URL, "", f"引用の条件: {RC.TERMS}"])
    note = "\n".join([title, "", lead, "", "■ 要点", p1, p2, p3, "", "■ 調査の方法"] + [f"・{m}" for m in method]
                     + ["", f"調査ページ: {AR.PAGE_URL}", "出典の書き方（そのまま貼れます）:", "", line, "", org, f"{RC.LAB_URL}/",
                        f"お問い合わせ: {RC.CONTACT_URL}"])
    posts = {"x": x, "facebook": fb[:SP.LIMITS["facebook"]], "threads": fb[:SP.LIMITS["threads"]],
             "linkedin": fb[:SP.LIMITS["linkedin"]], "note": note}
    return title, "\n".join(md), posts, (w, h)


def problems(text, cur, prev, wh):
    """集計に無い数字・一律の言い方（research_promo と同じ検査）"""
    import ai_ranking as AR
    import research_cite as RC
    import research_promo as RP
    have = RP._nums(json.dumps(cur, ensure_ascii=False) + json.dumps(prev or {}, ensure_ascii=False)
                    + AR.PAGE_URL + RC.LAB_URL + RC.CONTACT_URL + f" {wh[0]} {wh[1]} 1〜3")
    ng = [f"集計に無い数字「{n}」" for n in sorted(RP._nums(text) - have)]
    ng += [f"一律の言い方「{m.group(0)}」" for m in RP.ALWAYS_NG.finditer(text)]
    return ng


def latest():
    import ai_ranking as AR
    ms = AR.months()
    if not ms:
        return None, None
    return AR.load(ms[-1]), (AR.load(ms[-2]) if len(ms) > 1 else None)


def write(cur, prev):
    import social_post as SP
    title, md, posts, wh = compose(cur, prev)
    ng = problems(md + "\n" + "\n".join(posts.values()), cur, prev, wh)
    if ng:
        print("要対応: 月次のお知らせの下書きを作れません（" + " / ".join(ng[:3]) + "）")
        return False, 0
    made = 0
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{cur['ym']}.md"
    if not f.is_file():
        # 人が手を入れた下書きを上書きしない
        f.write_text(md + "\n", encoding="utf-8", newline="\n")
        made = 1
        print(f"   書きました: {f.relative_to(ROOT)}")
    rows = SP.load()
    iid = PREFIX + cur["ym"]
    if not any(r["id"] == iid for r in rows):
        import ai_ranking as AR
        rows.append({"id": iid, "site": "ai-lab", "kind": "announce", "title": title, "url": AR.PAGE_URL,
                     "made": date.today().isoformat(), "posts": posts})
        SP.save(rows)
        made = 1
        print(f"   キューに積みました: {iid}")
    return True, made


def selftest():
    cur, prev = latest()
    if not cur:
        print("ANNOUNCE_SELFTEST=skip（ランキングの集計がありません）")
        return 0
    title, md, posts, wh = compose(cur, prev)
    ok = not problems(md + "\n".join(posts.values()), cur, prev, wh)
    ok &= any("98765" in x for x in problems(md + "上位のサイトは98765問の出典でした。", cur, prev, wh))
    ok &= bool(problems(md + "どの業種でもポータルが中心です。", cur, prev, wh))
    ok &= "セブンセンシズ株式会社" in md and "/research/ranking/" in posts["x"] and "/contact/" in md
    print("ANNOUNCE_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    cur, prev = latest()
    if not cur:
        print("ANNOUNCE_OK=yes\nANNOUNCE_MADE=0（ランキングの集計がまだありません）")
        return 0
    if not a.write:
        title, md, posts, wh = compose(cur, prev)
        print(md)
        print("\n--- X ---\n" + posts["x"])
        ng = problems(md + "\n" + "\n".join(posts.values()), cur, prev, wh)
        print("ANNOUNCE_OK=" + ("no " + " / ".join(ng[:3]) if ng else "yes"))
        return 0
    ok, made = write(cur, prev)
    print(f"ANNOUNCE_OK={'yes' if ok else 'no'}")
    print(f"ANNOUNCE_MADE={made}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
