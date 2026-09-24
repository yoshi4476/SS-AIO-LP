# -*- coding: utf-8 -*-
"""多言語（英語・中国語・韓国語）の要約ページを、記事から機械で作る。

**なぜ要るか**: 海外由来のAI（ChatGPT・Claude・Perplexity）は英語資料の引用比率が高く、
中国語・韓国語の検索も同じ仕組みで取れる。全文を訳すと Claude の枠を食い切るので、
AIが切り出す単位（題名・冒頭の断言・各H2の1文結論・FAQ）だけを訳した「要約ページ」を
`/en/<cat>/<slug>/`（zh・ko も同じ）に置き、日本語の記事と hreflang で結ぶ。

守ること:
  - 数字は1つも変えない（訳の前後で数字の集合が同じでなければ捨てる）
  - URL・社名は訳さない（社名は「Seven Senses Inc.」の表記だけ許す）
  - 訳は1記事1回。日本語の要約が変わったときだけ訳し直す（data/i18n/<lang>/<slug>.json に元のハッシュを持つ）

  python scripts/i18n.py                        # 訳す候補（表示の多い順）
  python scripts/i18n.py --write --limit 10     # 10記事 × 3言語を訳す（Claude）
  python scripts/i18n.py --langs en             # 英語だけ
出す印: I18N_OK=yes / TRANSLATED=<件>。ページの生成は build.py（translated() を読む）
"""
import argparse
import hashlib
import html as _h
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "i18n"
LANGS = {"en": ("English", "en"), "zh": ("简体中文", "zh-Hans"), "ko": ("한국어", "ko")}
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MAX_LEAD = 400


def _plain(s):
    s = re.sub(r"<[^>]+>", "", str(s))
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return re.sub(r"[*_`=]+", "", s).strip()


# 内部リンクの案内文（link_new の型）は主張ではないので、冒頭や1文結論として拾わない。
# 実測で「関連して、…もあわせてご確認ください」が冒頭として訳されていた
_LINK_LINE = re.compile(r"^(関連|あわせて|近い論点|前提となる|つまずき|費用の目安|選ぶときの|詳しくは|参考:|→)")


def _is_claim(ln):
    p = _plain(ln)
    return bool(p) and not _LINK_LINE.search(p) and len(p) >= 20


def summary(slug):
    """訳す元。題名・説明・冒頭の段落・各H2と直下の1文結論・FAQ（本文にあるものだけ）"""
    p = ROOT / "articles" / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        return None
    import yaml
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return None
    body = m.group(2)
    if int(fm.get("score") or 0) < 90:
        return None
    lead = ""
    for ln in body.split("\n"):
        ln = ln.strip()
        if ln.startswith("## "):
            break                                  # 冒頭は最初のH2まで（H2の中の文を冒頭にしない）
        if ln and not ln.startswith(("<", "|", "#", "!", "[", "-", "*", ">")) and _is_claim(ln):
            lead = _plain(ln)[:MAX_LEAD]
            break
    if not lead:
        lead = _plain(fm.get("description", ""))[:MAX_LEAD]
    secs = []
    heads = [(mm.group(1).strip(), mm.end()) for mm in re.finditer(r"^##\s+(.+)$", body, re.M)]
    for i, (h, pos) in enumerate(heads[:8]):
        if re.search(r"よくある質問|まとめ", h):
            continue
        rest = body[pos:heads[i + 1][1] - len(heads[i + 1][0]) - 3] if i + 1 < len(heads) else body[pos:pos + 900]
        ans = ""
        for ln in rest.split("\n"):
            ln = ln.strip()
            if ln and not ln.startswith(("<", "|", "#", "!", "[", "-", "*", ">")) and not re.match(r"^\d+\.\s", ln) \
                    and _is_claim(ln):
                ans = _plain(ln)[:220]
                break
        if ans:
            secs.append({"h2": _plain(h), "answer": ans})
    faq = [{"q": _plain(f.get("q", "")), "a": _plain(f.get("a", ""))} for f in (fm.get("faq") or [])[:5]
           if f.get("q") and f.get("a")]
    src = {"title": _plain(fm.get("title", "")), "description": _plain(fm.get("description", "")),
           "lead": lead, "sections": secs, "faq": faq, "category": fm.get("category", ""),
           "date": str(fm.get("date", "")), "modified": str(fm.get("modified") or fm.get("date", ""))}
    src["hash"] = hashlib.md5(json.dumps(src, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return src


def _digits(obj):
    """数字の集合。全角は半角に、桁区切りは外す。日本語の「10万」「3億」は 100000 / 300000000 にも展開して比べる
    （訳では 100,000 yen と書くのが正しく、これを「数字が変わった」と落とすと訳が1本も通らない）"""
    s = json.dumps(obj, ensure_ascii=False).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    s = re.sub(r"(?<=\d)[,，](?=\d{3})", "", s)
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)(万|億|千)?", s):
        n, unit = m.group(1), m.group(2)
        if unit:
            mult = {"千": 1000, "万": 10000, "億": 100000000}[unit]
            v = float(n) * mult
            out.append(str(int(v)) if v == int(v) else str(v))
        else:
            out.append(n.lstrip("0") or "0")
    return sorted(out)


_EN_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
             "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
             "fifty": "50", "hundred": "100", "thousand": "1000"}
_ZH_NUM = {"一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
_KO_NUM = {"한": "1", "두": "2", "세": "3", "네": "4", "다섯": "5", "여섯": "6", "일곱": "7", "여덟": "8", "아홉": "9", "열": "10"}


def _normalize_numwords(obj, lang):
    """訳に出た数詞（six / 六个 / 여섯 개）を数字に戻してから数字の集合を比べる。
    指示では数字で書かせるが、モデルが語で書く回があり、その訳を捨てると通る訳が無くなる"""
    s = json.dumps(obj, ensure_ascii=False)
    if lang == "en":
        s = re.sub(r"\b(" + "|".join(_EN_WORDS) + r")\b", lambda m: _EN_WORDS[m.group(1).lower()], s, flags=re.I)
    elif lang == "zh":
        s = re.sub(r"([一二两三四五六七八九十])(?=[个种条项步点位家名次年月日例])", lambda m: _ZH_NUM[m.group(1)], s)
    elif lang == "ko":
        s = re.sub(r"(다섯|여섯|일곱|여덟|아홉|한|두|세|네|열)(?=\s?(개|가지|단계|명|번|년|개월|건|곳))", lambda m: _KO_NUM[m.group(1)], s)
    try:
        return json.loads(s)
    except ValueError:
        return obj


def _digits_ok(src, out):
    """訳の数字が元と一致するか。「10万」は 10 と 100000 のどちらで書かれてもよい"""
    a, b = _digits(src), _digits(out)
    if a == b:
        return True, ""
    # 元の「N万」を展開前（N）で書いた訳も許す
    raw_src = sorted((x.lstrip("0") or "0") for x in re.findall(
        r"\d+(?:\.\d+)?", json.dumps(src, ensure_ascii=False).translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace(",", "")))
    if sorted(b) == raw_src:
        return True, ""
    # 「2026年9月」は訳では "September 2026" になり、月の数字だけが消える。月（◯月）だけは無くてもよい
    src_txt = json.dumps(src, ensure_ascii=False).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    months = sorted(re.findall(r"(?<!\d)(\d{1,2})(?=月)", src_txt))
    a2 = list(a)
    for m_ in months:
        if m_ in a2:
            a2.remove(m_)
    if sorted(a2) == b:
        return True, ""
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    diff = {k: (ca.get(k, 0), cb.get(k, 0)) for k in set(ca) | set(cb) if ca.get(k, 0) != cb.get(k, 0)}
    return False, "数字が変わった " + str(dict(list(diff.items())[:5]))


PROMPT = """Translate the following Japanese article summary into {lang_name}. Output **only** a JSON object with the same keys
("title", "description", "lead", "sections" (list of {{"h2","answer"}}), "faq" (list of {{"q","a"}})).
Rules:
- Keep every number exactly as in the source (same digits, same order of magnitude). Do not add or drop numbers.
- Always write numbers as Arabic numerals (write "6 examples", never "six examples"; write "2 principles", never "two principles").
- Do not add URLs, links, or facts that are not in the source. Do not translate product names; render the company as "Seven Senses Inc." (セブンセンシズ株式会社).
- Natural, concise, professional tone for business owners. Keep each section answer self-contained (it may be quoted alone by an AI search engine).
- The article is Japanese-market specific: keep Japanese program names in Japanese with a short gloss in parentheses the first time (e.g., "AI導入補助金 (AI Adoption Subsidy)").
Source JSON:
{src}"""


def translate(src, lang):
    import auto_rewrite as AR
    name = LANGS[lang][0]
    prompt = PROMPT.format(lang_name=name, src=json.dumps(
        {k: src[k] for k in ("title", "description", "lead", "sections", "faq")}, ensure_ascii=False))
    r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "1", *AR.model_args(), "--allowedTools", ""],
              timeout=600, stdin_text=prompt)
    out = (r.stdout or "").strip()
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, "JSONが返らない"
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None, "JSONが壊れている"
    for k in ("title", "description", "lead", "sections", "faq"):
        if k not in d:
            return None, f"{k} が無い"
    src_sub = {k: src[k] for k in ("title", "description", "lead", "sections", "faq")}
    # そのまま／数詞を数字に戻した形、のどちらかで数字の集合が一致すれば通す
    # （"one of the reasons" の one を 1 に変えると余計な数字が生えるため、両方を試す）
    ok, why = _digits_ok(src_sub, d)
    if not ok:
        ok2, why2 = _digits_ok(src_sub, _normalize_numwords(d, lang))
        ok, why = (True, "") if ok2 else (False, why)
    if not ok:
        return None, why
    if re.search(r"https?://", json.dumps(d, ensure_ascii=False)):
        return None, "URLが入った"
    n_src = len(json.dumps(src, ensure_ascii=False))
    n_out = len(json.dumps(d, ensure_ascii=False))
    if not (0.3 <= n_out / max(n_src, 1) <= 3.5):
        return None, f"長さが極端（{n_out}/{n_src}）"
    return d, ""


def translated(lang=None):
    """{lang: {slug: {...}}}（build.py が読む）"""
    out = {}
    for lg in ([lang] if lang else LANGS):
        d = OUT / lg
        out[lg] = {}
        if d.is_dir():
            for p in d.glob("*.json"):
                try:
                    out[lg][p.stem] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return out


def candidates(site_id, langs):
    """訳す順: 表示回数の多い記事から。訳済みで元が変わっていないものは飛ばす"""
    import sites as S
    imp = {}
    p = ROOT / "data" / "ranks" / f"{site_id}.json"
    if p.is_file():
        try:
            hist = json.loads(p.read_text(encoding="utf-8"))
            for r in hist[sorted(hist)[-1]]:
                s = str(r.get("url", "")).rstrip("/").split("/")[-1]
                imp[s] = imp.get(s, 0) + int(r.get("imp", 0))
        except Exception:
            pass
    have = translated()
    rows = []
    for md in (ROOT / "articles").glob("*.md"):
        cat = re.search(r"^category:\s*(\S+)", md.read_text(encoding="utf-8-sig")[:800], re.M)
        if not cat or S.find_category_owner(cat.group(1)) != site_id:
            continue
        src = summary(md.stem)
        if not src or not src["sections"]:
            continue
        need = [lg for lg in langs if have.get(lg, {}).get(md.stem, {}).get("src_hash") != src["hash"]]
        if need:
            rows.append((imp.get(md.stem, 0), md.stem, src, need))
    rows.sort(key=lambda x: -x[0])
    return rows


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--langs", default="en,zh,ko")
    ap.add_argument("--limit", type=int, default=10, help="1回に訳す記事数")
    ap.add_argument("--budget-min", type=int, default=25)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    langs = [l for l in a.langs.split(",") if l in LANGS]
    sid = a.site or S.primary()
    rows = candidates(sid, langs)
    print(f"■ {sid}: 訳す候補 {len(rows)}記事（{'・'.join(langs)}）")
    for imp, slug, _, need in rows[:8]:
        print(f"   表示{imp:>5} {slug[:40]:<40} {'/'.join(need)}")
    if not a.write:
        print(f"I18N_OK=yes\nTRANSLATED=0")
        return 0
    t0, n = time.time(), 0
    for imp, slug, src, need in rows[:a.limit]:
        for lg in need:
            if (time.time() - t0) / 60 >= a.budget_min:
                break
            d, why = translate(src, lg)
            ok = d is not None
            if ok:
                (OUT / lg).mkdir(parents=True, exist_ok=True)
                d.update({"src_hash": src["hash"], "slug": slug, "category": src["category"], "lang": lg,
                          "date": src["date"], "modified": src["modified"], "made": time.strftime("%Y-%m-%d")})
                (OUT / lg / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                n += 1
            print(f"   {'○' if ok else '×'} {lg} {slug[:40]:<40} {why}")
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "i18n", "slug": slug,
                                    "kind": f"i18n-{lg}", "ok": ok, "note": why or "訳した"}, ensure_ascii=False) + "\n")
    print(f"I18N_OK=yes\nTRANSLATED={n}")
    return 0


def page_html(d, ja_url, lang):
    """訳した要約ページの中身（外枠は build が包む）"""
    secs = "".join(f'<div class="latest-block"><div class="cat-head"><h2>{_h.escape(s["h2"])}</h2></div>'
                   f'<p class="hub-lead">{_h.escape(s["answer"])}</p></div>' for s in d.get("sections", []))
    faq = "".join(f'<details class="faq-item"><summary>{_h.escape(f["q"])}</summary><div class="a"><p>{_h.escape(f["a"])}</p></div></details>'
                  for f in d.get("faq", []))
    note = {"en": "This is a translated summary of the Japanese article. Figures and sources are in the original.",
            "zh": "本页为日文文章的翻译摘要。数据与出处请参阅原文。",
            "ko": "이 페이지는 일본어 기사의 번역 요약입니다. 수치와 출처는 원문을 참조하세요."}[lang]
    orig = {"en": "Read the original (Japanese)", "zh": "阅读原文（日语）", "ko": "원문 보기（일본어）"}[lang]
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": d["title"], "description": d["description"],
          "inLanguage": LANGS[lang][1], "translationOfWork": {"@type": "Article", "url": ja_url, "inLanguage": "ja"},
          "datePublished": d.get("date", ""), "dateModified": d.get("modified", ""),
          "author": {"@type": "Person", "name": "Yu Haraguchi", "url": "https://ai.7senses.co.jp/author/haraguchi/"},
          "publisher": {"@type": "Organization", "name": "Seven Senses Inc."}}
    faq_ld = ({"@context": "https://schema.org", "@type": "FAQPage",
               "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                              for f in d.get("faq", [])]} if d.get("faq") else None)
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(d["title"])}</h2></div>'
            f'<p class="hub-lead"><strong>{_h.escape(d["lead"])}</strong></p><p class="hub-note">{note} '
            f'<a href="{ja_url}">{orig} →</a></p></div>{secs}'
            + (f'<div class="latest-block"><div class="cat-head"><h2>FAQ</h2></div><div class="faq-list">{faq}</div></div>' if faq else "")
            + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>"
            + ('<script type="application/ld+json">' + json.dumps(faq_ld, ensure_ascii=False) + "</script>" if faq_ld else ""))


if __name__ == "__main__":
    sys.exit(main())
