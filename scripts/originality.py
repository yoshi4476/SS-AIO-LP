# -*- coding: utf-8 -*-
"""記事がオリジナルとして認められるかを機械で見る（2026-10-19）。

Google は「AI が書いたか」ではなく、独自の経験・一次情報・読者の役に立つか・大量生成でないかで評価する
（公式の AI 最適化ガイドとスパムポリシー。CLAUDE.md 0.3）。AI の文章を人の文章に見せかける加工はしない。
効くのは中身そのもの。ここでは、機械で判定できる2つを見る。

1. 出どころの無い体験談の決まり文句（「私たちが相談を受ける中でも」など）
   2026-10-19 の点検で、全471本のうち164本に同じ形の言い回しがあった。本当の体験なら強いが、
   出どころの無い体験談は作り話になりうるうえ、同じ文句が多くの記事に並ぶと量産の指紋になる。
   **本当にあった体験は data/experiences.json に登録し、書く AI はそこから書く。**登録した体験の
   目印（key）を含む文は通す。
2. 検索上位の見出しに無い節（情報の増分）
   上位ページの見出し（kw_serp・CI のキャッシュ）と比べ、上位が扱っていない節が2つ以上あるか。
   データの無い語は「確かめていない」と返す（合格にしない）。

    python scripts/originality.py --list [--site ai-lab]           # 登録した体験
    python scripts/originality.py --add --site ai-lab --key "<文中に入る目印>" --text "<何があったか>" --when 2026-09
    python scripts/originality.py --check <slug>                    # 1本を見る
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
EXPERIENCES = ROOT / "data" / "experiences.json"

# 出どころを書かずに体験を語る決まり文句。見つかるはずの例と、見つかってはいけない例は門（h109）で確かめる
# 「なか」のひらがな書き・「ある歯科では」「ある店舗では」も同じ決まり文句（2026-10-20 に漏れていた）。
# 「駅前にある医院では」「対象である会社では」のような所在・説明の「ある」（に・で・て の後）は拾わない
_PLACE = (r"(歯科医院|歯科クリニック|歯医者|歯科|医院|病院|クリニック|整骨院|接骨院|工務店|会社|企業|事業者|"
          r"お店|店舗|飲食店|美容室|サロン|お客様|顧客|事務所)")
STOCK = re.compile(
    r"(私たち|私|当社|弊社)(が|も|は)?[^。\n]{0,12}(ご?相談を受ける(中|なか)で|支援する(中|なか)で|支援の現場で)(も|は)?"
    r"|(相談|支援)の現場では?、?(よく|何度も)"
    r"|何度も(聞いて|見て|経験して)きました"
    r"|(よく|多く)(聞く|いただく|寄せられる)(声|相談|質問)(です|が)"
    r"|当社が支援した(ある|あるお客様|医院|歯科|会社|工務店)"
    r"|(?<![にでて])ある" + _PLACE + r"では")
MIN_NOVEL = 2
NOVEL_SHARE = 0.4       # 節の語のうち、上位の見出しに出る語がこの割合以下なら「上位に無い節」


def load_experiences(site=None):
    """体験の台帳。自社の分は data/experiences.json、お客様の社の分は非公開の clients/<id>/experiences.json
    （ヒアリングシートの「お客さんの一言」・掲載してよい事例。client_intake.to_experiences）"""
    try:
        rows = json.loads(EXPERIENCES.read_text(encoding="utf-8")).get("experiences", [])
    except (OSError, ValueError):
        rows = []
    if site:
        try:
            import private_store
            import sites as S
            if (S.load_all().get(site) or {}).get("client"):
                p = private_store.client_path(site, "experiences.json")
                if p.is_file():
                    rows = rows + json.loads(p.read_text(encoding="utf-8")).get("experiences", [])
        except Exception:
            pass
    return [r for r in rows if not r.get("retired") and (not site or not r.get("sites") or site in r["sites"])]


def stock_phrases(body, site=None):
    """登録した体験の目印を含まない、決まり文句の体験談の文（[(文, 一致した語)]）"""
    keys = [r["key"] for r in load_experiences(site) if r.get("key")]
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    out = []
    for sent in re.split(r"(?<=[。！？])|\n", body):
        m = STOCK.search(sent)
        if m and not any(k in sent for k in keys):
            out.append((sent.strip()[:80], m.group(0)))
    return out


def _terms(text):
    import kw_serp
    return set(kw_serp.terms(text))


def info_gain(site, keyword, h2s):
    """(上位の見出しに無い節の数, 見た節の数, 上位のページ数)。上位の見出しのデータが無ければ None"""
    try:
        import kw_serp
        rec = kw_serp.get(site, keyword) if site and keyword else None
    except Exception:
        rec = None
    pages = [p for p in ((rec or {}).get("headline") or {}).get("pages") or [] if not p.get("ours") and p.get("heads")]
    if not pages:
        return None
    seen = set()
    for p in pages:
        for _, h in p["heads"]:
            seen |= _terms(h)
    novel = 0
    for h in h2s:
        ts = _terms(h)
        if ts and len(ts & seen) / len(ts) <= NOVEL_SHARE:
            novel += 1
    return novel, len(h2s), len(pages)


def brief_lines(site):
    """執筆の案内（site_brief）に出す、書いてよい体験"""
    rows = load_experiences(site)
    out = ["", "■ 一人称で書いてよい体験（登録済み。これ以外の体験談を作らない）"]
    if not rows:
        out.append("  登録された体験はありません。一人称は「当社の判断とその理由」として書き、"
                   "「相談を受ける中で」「ある医院では」のような出来事を作らない（score_check が止める）")
        return out
    for r in rows[:12]:
        tag = f"［{r['industry']}］" if r.get("industry") else ""
        out.append(f"  - {tag}{r['text']}（{r.get('when', '時期不明')}。文に必ず「{r['key']}」を入れる）")
    trends = sorted({r["trend"] for r in rows if r.get("trend")})
    for t in trends:
        out.append(f"  ※ {t}")
    out.append("  使うのは記事の主題（業種・相談の中身）に合う体験だけ。時期が未確認の体験に日付を書かない")
    return out


def add(site, key, text, when):
    d = {"experiences": []}
    if EXPERIENCES.is_file():
        d = json.loads(EXPERIENCES.read_text(encoding="utf-8"))
    rid = f"exp-{len(d['experiences']) + 1:03d}"
    d["experiences"].append({"id": rid, "sites": [site] if site else [], "key": key, "text": text, "when": when,
                             "added": date.today().isoformat()})
    EXPERIENCES.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"登録しました: {rid}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--site", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--when", default="")
    a = ap.parse_args()
    if a.add:
        if not (a.key and a.text and a.when):
            ap.error("--key・--text・--when が要ります（本当にあったことだけを登録する）")
        add(a.site, a.key, a.text, a.when)
    elif a.check:
        t = (ROOT / "articles" / f"{a.check}.md").read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        import yaml
        import sites
        meta, body = yaml.safe_load(m.group(1)), m.group(2)
        site = sites.find_category_owner(str(meta.get("category") or ""))
        for s, w in stock_phrases(body, site):
            print(f"  決まり文句の体験談「{w}」: {s}")
        h2s = [h for h in re.findall(r"^## (.+)$", body, re.M) if "よくある質問" not in h and not h.startswith("まとめ")]
        g = info_gain(site, meta.get("keyword"), h2s)
        print("  上位の見出しのデータが無いため、上位との差は確かめていません" if g is None
              else f"  上位の見出しに無い節: {g[0]}/{g[1]}（上位{g[2]}ページと比べた）")
    else:
        for line in brief_lines(a.site or None)[1:]:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
