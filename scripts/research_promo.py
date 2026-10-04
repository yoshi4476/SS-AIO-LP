# -*- coding: utf-8 -*-
"""業種別の調査「AIは何を出典に答えるか」の数字を、note の下書きと掛け合い動画に回す。

**なぜ要るか**: AI検索での見え方は被リンクより言及で決まる（YouTube 0.71・リンク無しの言及 0.66。CLAUDE.md 0.3節）。
調査は「そこにしか無い数字」なので、社名とURLを添えて外に出すほど言及の元になる。

**数字は headline() だけから取る**（調査ページ・LP・提案書と同じ出どころ）。作文で数字を足さない。
「ポータルが中心」のような一律の言い方もしない。業種ごとに向きが違うため、その業種の判定（verdict）で文を選ぶ。

**ChatGPT の回答がそろった業種だけ**（answered.ChatGPT が質問数の半分以上）。そろっていない業種は
聞き直しで数字が変わるので出さない。1業種1回（data/research_promo.json に記録し、二度作らない）。

    python scripts/research_promo.py --list            # どの業種が出せるか
    python scripts/research_promo.py --note            # note の下書きを積む（social_post のキュー・週2業種まで）
    python scripts/research_promo.py --show <業種>      # 下書きを表示するだけ（積まない）
    python scripts/research_promo.py --selftest
出す印: RESEARCH_NOTE_OK=yes|no / RESEARCH_NOTE_MADE=<本>
"""
import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LEDGER = ROOT / "data" / "research_promo.json"
RESEARCH = ROOT / "data" / "research"
COMPANY = "セブンセンシズ株式会社（AI集客ラボ）"
SITE_URL = "https://ai.7senses.co.jp/"
PREFIX = "research-"


def _nums(s):
    """数字の集合。「04」と「4」、「1,700」と「1700」は同じに数える"""
    out = set()
    for x in re.findall(r"\d+(?:\.\d+)?", s.replace(",", "")):
        out.add(x if "." in x else str(int(x)))
    return out


def summary(ind):
    f = RESEARCH / f"{ind}-summary.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def eligible(ind):
    """ChatGPT の回答が質問数の半分以上そろった業種か"""
    s = summary(ind)
    if not s or not s.get("questions"):
        return False
    return (s.get("answered") or {}).get("ChatGPT", 0) * 2 >= s["questions"]


def headline(ind):
    import industry_ai_sources as IAS
    try:
        return IAS.headline(ind)
    except Exception:
        return None


def industries():
    """出してよい業種（集計があり、ChatGPT がそろっている）"""
    out = []
    for f in sorted(RESEARCH.glob("*-summary.json")):
        ind = f.name[:-len("-summary.json")]
        if eligible(ind) and headline(ind):
            out.append(ind)
    return out


def _jdate(d):
    return f"{int(d[:4])}年{int(d[5:7])}月{int(d[8:10])}日"


def facts(hl):
    """要点の文。数字は hl の値だけを差し込む。向きは verdict で選ぶ（一律に「ポータルが中心」と言わない）"""
    T = hl["T"]
    find = (f"{T['owner']}を探す質問（{T['find_ex']}など）では、出典の{hl['lp']}%が{T['portal']}、"
            f"{hl['lc']}%が{T['owner_site']}でした。回答ごとに数えると、{T['portal']}を出典にした回答は{hl['ap']}%、"
            f"{T['owner_site']}は{hl['ac']}%でした。")
    if hl["verdict"] == "portal":
        find += f"この業種では、{T['owner']}を探す質問で{T['portal']}のほうが多く使われていました。"
    elif hl["verdict"] == "owner":
        find += f"この業種では、{T['owner']}を探す質問で{T['owner_site']}のほうが多く使われていました。"
    else:
        find += "件数で数えた場合と回答ごとに数えた場合で向きがそろわないか差が小さいため、どちらかに偏った結果とは言えませんでした。"
    other = (f"{T['other_short']}を調べる質問では、出典の{hl['oc']}%が{T['owner_site']}で、"
             f"回答の{hl['oa']}%が{T['owner_site']}を出典のどれかに含んでいました。")
    return [find, other]


def title(hl):
    return f"{hl['name']}の質問に、AIは何を出典に答えるか（{hl['questions']}問の調査）"


def note_text(hl):
    """note の転載用の下書き。社名・出典・調査日・質問数・使ったAI・元ページのURLを必ず入れる"""
    T = hl["T"]
    find, other = facts(hl)
    lines = [title(hl), "",
             f"{COMPANY}の調査です。{T['asker']}が実際に調べそうな{hl['questions']}問を{hl['engines_text']}に聞き、"
             "回答の出典になったサイトを種類ごとに数えました。", "",
             f"■ {T['owner']}を探す質問", find, "",
             f"■ {T['other_short']}の質問", other, "",
             "この結果は、この業種の質問についてのものです。同じ調査でも、業種によって向きは違いました。", "",
             "■ 調査の概要",
             f"・調査: {COMPANY}",
             f"・調査日: {_jdate(hl['date'])}",
             f"・質問数: {hl['questions']}問",
             f"・使ったAI: {hl['engines_text']}",
             "・個別の事業者名は公開していません（サイトの種類ごとの集計だけ）", "",
             "質問の一覧・種類ごとの内訳・集計データ（CSV）は調査ページにまとめています。",
             f"調査ページ: {hl['url']}", "",
             f"引用するときは「{COMPANY}の調査」と出典を書いてください。",
             f"{COMPANY}", SITE_URL]
    return "\n".join(lines)


# 業種によらず言い切る言い方。どの業種の数字からも言えない
ALWAYS_NG = re.compile(r"業種を問わず|どの業種でも|どの業種も|全業種で|すべての業種で|全ての業種で|多くの業種で")
LEAN = r"(?:が中心|中心に|が主流|が優勢|が圧倒|のほうが多|が多く|が多い|が上回)"


def uniform_ng(text, hl):
    """一律の言い方・その業種の判定と逆の言い切り。問題の一覧を返す（空なら合格）"""
    T = hl["T"]
    ng = [f"一律の言い方「{m.group(0)}」" for m in ALWAYS_NG.finditer(text)]
    portal = "|".join(map(re.escape, {"ポータル", T["portal"]}))
    owner = "|".join(map(re.escape, {"公式サイト", T["owner_site"]}))
    if hl["verdict"] != "portal":
        ng += [f"この業種は{T['portal']}が多いとは言えない「{m.group(0)}」"
               for m in re.finditer(rf"(?:{portal})[^。、]{{0,6}}{LEAN}", text)]
    if hl["verdict"] != "owner":
        ng += [f"この業種は{T['owner_site']}が多いとは言えない「{m.group(0)}」"
               for m in re.finditer(rf"(?:{owner})[^。、]{{0,6}}{LEAN}", text)]
    return ng


def number_ng(text, hl):
    """headline に無い数字"""
    have = _nums(json.dumps(hl, ensure_ascii=False))
    return [f"調査の要点に無い数字「{n}」" for n in sorted(_nums(text) - have)]


def page_text(ind):
    """調査ページの本文（render と同じもの）をただの文にする。動画の台本の検算に使う"""
    import industry_ai_sources as IAS
    try:
        _, _, body, _, _ = IAS.render(ind)
    except Exception:
        return ""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    # 調査ページの決まり文句「4つのAI」は、回答が取れたAIの数と違う業種がある。台本の根拠にさせない
    t = re.sub(r"\d+つのAI", "AI", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", t)).strip()


def source(ind):
    """duo_video の「記事」の代わり。text は headline の要点と調査ページの本文だけ"""
    hl = headline(ind)
    if not hl or not eligible(ind):
        return None
    T = hl["T"]
    text = (f"# {title(hl)}\n{COMPANY}の調査。調査日 {_jdate(hl['date'])}。{hl['questions']}問を"
            f"{hl['engines_text']}に聞いた（{hl['n_engines']}つのAI）。{T['asker']}が調べそうな質問。\n\n"
            + "\n".join(facts(hl)) + "\n\n" + page_text(ind))
    return {"slug": PREFIX + ind, "title": title(hl), "category": "aio", "text": text,
            "research": ind, "hl": hl, "url": hl["url"]}


def describe(ind):
    """YouTube の説明欄。調査ページのURLを先頭に、社名を末尾に"""
    hl = headline(ind)
    if not hl:
        return "", PREFIX + ind, []
    desc = (f"▼ 調査ページ（質問の一覧・内訳・CSV）\n{hl['url']}\n\n"
            + "\n".join(f"・{x}" for x in facts(hl))
            + f"\n\n調査: {COMPANY}\n調査日: {_jdate(hl['date'])}／質問数: {hl['questions']}問／使ったAI: {hl['engines_text']}\n\n"
            f"{COMPANY}\n{SITE_URL}")
    return desc, f"{hl['name']}の質問、AIは何を出典に答える？｜{COMPANY}の調査", []


def load_ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.is_file() else {}


def note_item(ind):
    hl = headline(ind)
    return {"id": PREFIX + ind, "site": "ai-lab", "kind": "research", "title": title(hl), "url": hl["url"],
            "made": date.today().isoformat(), "posts": {"note": note_text(hl)}}


def check_item(it, hl):
    t = it["posts"]["note"]
    ng = number_ng(t, hl) + uniform_ng(t, hl)
    for must in (COMPANY, hl["url"], hl["engines_text"], f"{hl['questions']}問", _jdate(hl["date"])):
        if must not in t:
            ng.append(f"必ず入れるもの「{must}」が無い")
    return ng


def make_notes(limit):
    import social_post as SP
    led = load_ledger()
    done = led.setdefault("note", {})
    rows = SP.load()
    queued = {r["id"] for r in rows}
    made, ok = 0, True
    for ind in industries():
        if made >= limit:
            break
        if ind in done or PREFIX + ind in queued:
            continue
        it = note_item(ind)
        ng = check_item(it, headline(ind))
        if ng:
            ok = False
            print(f"   × {ind}: {' / '.join(ng[:3])}")
            continue
        rows.append(it)
        done[ind] = it["made"]
        made += 1
        print(f"   ○ {ind:<12} {it['title']}")
    SP.save(rows)
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return made, ok


def selftest():
    ok = True
    inds = industries()
    if not inds:
        print("RESEARCH_PROMO_SELFTEST=ng（出せる業種が無い）")
        return 1
    hl = headline(inds[0])
    it = note_item(inds[0])
    ok &= not check_item(it, hl)
    bad = json.loads(json.dumps(it))
    bad["posts"]["note"] += "\n導入した事業者の85%で成果が出ました。"
    ok &= any("85" in x for x in check_item(bad, hl))
    ok &= bool(uniform_ng("業種を問わずポータルが中心です。", dict(hl, verdict="even")))
    print("RESEARCH_PROMO_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--note", action="store_true")
    ap.add_argument("--limit", type=int, default=2, help="1回に積む業種の数")
    ap.add_argument("--show", metavar="IND")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.show:
        if not eligible(a.show) or not headline(a.show):
            print("  対象外です（集計が無いか、ChatGPT の回答がそろっていません）")
            return 0
        print(note_text(headline(a.show)))
        return 0
    if a.note:
        made, ok = make_notes(a.limit)
        print(f"RESEARCH_NOTE_OK={'yes' if ok else 'no'}")
        print(f"RESEARCH_NOTE_MADE={made}")
        return 0
    led = load_ledger()
    for f in sorted(RESEARCH.glob("*-summary.json")):
        ind = f.name[:-len("-summary.json")]
        s = summary(ind)
        st = ("済み " + led.get("note", {}).get(ind, "")) if ind in led.get("note", {}) else ("出せる" if eligible(ind) else "待ち")
        print(f"   {ind:<12} ChatGPT {(s.get('answered') or {}).get('ChatGPT', 0):>3}/{s.get('questions')}  {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
