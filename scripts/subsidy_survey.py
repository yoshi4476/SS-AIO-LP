# -*- coding: utf-8 -*-
"""補助金の記事ごとに、AIへの聞き取り調査をして「当社で測った数字（母数つき）」を作る。

補助金サイトは採択率・支援社数・お客様の声を載せない方針のため、記事に書ける自社の数字が無く、
採点の一次性が基準（80点）に届かなかった（2026-10-04: 旧記事13本が全部不合格）。
読者が実際にする「AIに聞く」を当社が代わりに行い、AIが根拠に挙げたページの種類を数える。
公的機関のページを根拠にしない回答が多いことは、読者が公式で確かめるべき理由そのもので、
ほかのサイトには無い数字になる。

課金APIは使わない（ChatGPT・Claude はサブスク、Gemini は無料枠。答えは30日キャッシュ）。
分類はルールだけで行う（公的機関＝go.jp・lg.jp など。判断の割れる分類を機械に任せない）。

  python scripts/subsidy_survey.py <slug> [<slug> ...]   # 聞いて data/subsidy_survey/<slug>.json に残す
  python scripts/subsidy_survey.py --facts <slug>        # 記事に書ける文だけ出す
"""
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "subsidy_survey"
# どれもドメインの末尾で判定する。部分一致にすると hojokin-dx.com が「x.com（SNS）」に数えられた（2026-10-04）
PUBLIC = re.compile(r"(^|\.)(go\.jp|lg\.jp|ac\.jp|monodukuri-hojo\.jp)$")
MEDIA = re.compile(r"(^|\.)(yahoo\.co\.jp|nikkei\.com|asahi\.com|yomiuri\.co\.jp|mainichi\.jp|nhk\.or\.jp|wikipedia\.org|"
                   r"youtube\.com|note\.com|x\.com|twitter\.com|facebook\.com|instagram\.com)$")
# Gemini の出典は転送URLで、期限が切れると行き先が分からない。分からないものは数えない
UNKNOWN = re.compile(r"(^|\.)vertexaisearch\.cloud\.google\.com$")
OWN = ("7senses.co.jp",)
MIN_ANSWERS = 6          # これ未満は割合として書かない（偶然と区別できない）


def domain(u):
    h = urllib.parse.urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def kind(d):
    if any(d.endswith(o) for o in OWN):
        return "own"
    if PUBLIC.search(d):
        return "public"
    if MEDIA.search(d):
        return "media"
    return "private"


def article(slug):
    for p in (ROOT / "articles" / f"{slug}.md", ROOT / "articles" / "_legacy" / f"{slug}.md"):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise SystemExit(f"記事がありません: {slug}")


def questions(slug):
    """読者が AI に打ちそうな問い3つ。題名の主題と、本文の質問形の見出し・FAQ から取る（作文しない）"""
    t = article(slug)
    title = (re.search(r"^title:\s*\"?(.+?)\"?\s*$", t, re.M) or [0, slug])[1]
    # 題名の【2026年版】などは外し、｜の後ろも主題の一部として残す（前だけだと「AI導入補助金2026」しか残らない題がある）
    main = re.sub(r"\s+", " ", re.sub(r"【[^】]*】|\[[^\]]*\]", "", title).replace("｜", " ").replace("|", " ")).strip(" 　?？\"")[:45]
    qs = [main]
    heads = [re.sub(r"[*_`]", "", h).strip() for h in re.findall(r"^#{2,3}\s+(.+[?？])\s*$", t, re.M)]
    faqs = re.findall(r"^\s*-?\s*q:\s*\"?(.+?)\"?\s*$", t, re.M)
    faqs += re.findall(r"^\*\*Q\d*[.．、]?\s*(.+?[?？])\*\*\s*$", t, re.M)
    faqs += re.findall(r"^#{3,4}\s*Q\d*[.．、:：]?\s*(.+?[?？])\s*$", t, re.M)
    # 質問形が足りない記事は、本文の見出し（目次・FAQ・事例・まとめ・相談の節を除く）を問いにする
    plain = [re.sub(r"[*_`]", "", h).strip() for h in re.findall(r"^##\s+(.+)$", t, re.M)
             if not re.search(r"目次|要点|よくある質問|FAQ|事例|まとめ|相談|お問い合わせ", h)]
    for q in heads + faqs + plain:
        q = re.sub(r"\s*\{#[^}]*\}", "", q).strip(" 　")
        if "AI導入補助金" not in q and "IT導入補助金" not in q:
            q = f"AI導入補助金 {q}"
        if q not in qs and len(q) <= 60:
            qs.append(q)
        if len(qs) >= 3:
            break
    return qs


def survey(slug):
    import ai_cite_check as AC
    eng = AC.subscription_engines()
    qs = questions(slug)
    tasks = [(q, n) for q in qs for n in eng]

    def one(t):
        q, n = t
        try:
            return q, n, eng[n](q) or [], ""
        except Exception as e:
            return q, n, [], str(e)[:160]
    ans = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for q, n, urls, err in ex.map(one, tasks):
            ans.setdefault(q, {})[n] = {"urls": urls, "error": err}
    rec = {"slug": slug, "date": date.today().isoformat(), "engines": sorted(eng), "questions": qs, "answers": ans}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def tally(rec):
    n = pub = only_private = 0
    srcs = {"public": 0, "private": 0, "media": 0, "own": 0}
    engines = set()
    for q, by in rec["answers"].items():
        for name, r in by.items():
            doms = {domain(u) for u in r.get("urls") or [] if domain(u) and not UNKNOWN.search(domain(u))}
            if r.get("error") or not doms:
                continue
            n += 1
            engines.add(name)
            ks = [kind(d) for d in doms]
            for k in ks:
                srcs[k] += 1
            pub += "public" in ks
            only_private += set(ks) <= {"private", "media"}
    return {"answers": n, "with_public": pub, "only_private": only_private, "sources": srcs,
            "engines": sorted(engines)}


def claims(slug):
    """記事に書ける文（数字は集計そのもの。言い回しは固定し、機械が作文しない）"""
    p = OUT / f"{slug}.json"
    if not p.is_file():
        return []
    rec = json.loads(p.read_text(encoding="utf-8"))
    t = tally(rec)
    if t["answers"] < MIN_ANSWERS:
        return []
    y, m = rec["date"][:4], int(rec["date"][5:7])
    who = "・".join(t["engines"])
    q0 = rec["questions"][0]
    total = sum(t["sources"].values())
    out = [{
        "id": f"survey-{slug}-1",
        "claim": (f"当社が{y}年{m}月に{who}の{len(t['engines'])}つのAIへ「{q0}」など{len(rec['questions'])}問を聞いたところ、"
                  f"出典つきで答えた{t['answers']}回答のうち、公的機関（go.jp など）のページを根拠に挙げたのは"
                  f"{t['with_public']}回答でした（当社調べ）"),
        "source": "セブンセンシズ株式会社によるAIへの聞き取り調査", "as_of": rec["date"][:7]}]
    if total:
        out.append({
            "id": f"survey-{slug}-2",
            "claim": (f"同じ調査でAIが根拠に挙げたページ{total}件の内訳は、公的機関{t['sources']['public']}件、"
                      f"支援業者・ツール会社などの民間サイト{t['sources']['private']}件、"
                      f"ニュース・動画・SNS{t['sources']['media']}件でした（当社調べ）"),
            "source": "セブンセンシズ株式会社によるAIへの聞き取り調査", "as_of": rec["date"][:7]})
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--facts" in sys.argv:
        for s in args:
            for c in claims(s):
                print(c["claim"])
        return 0
    for s in args:
        rec = survey(s)
        t = tally(rec)
        print(f"{s}: {t['answers']}回答（公的機関を根拠 {t['with_public']}）/ 出典 {t['sources']} / {rec['engines']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
