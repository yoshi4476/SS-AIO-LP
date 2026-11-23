# -*- coding: utf-8 -*-
"""材料の質問シートを、社の公開ページから自動で埋める（2026-11-23 運用者「シートなどは自動で埋めるように」）。

質問シートの答えを、これまでは人が記録や社のサイトを読んで探していた（2026-11-23 のリズコム34問・CONFLUX 12問）。
社が自分で公開しているページ（会社・サービス・事例・進め方・代表の言葉など）を読み、そこに書いてあることだけで答える。

**作らないための決まり**:
- 読むのは社の公開ページだけ。当社が書いた記事（articles の slug と同じ URL）と、他社向けの見本（/samples/）は読まない
  （当社の記事を出典にすると、記事の文が一次情報に戻って回る）
- 答えには、出典のページの文をそのまま引用させる。引用がそのページの本文に無い答え、引用に無い数字を含む答えは捨てる
- 残った答えは material_sheet.plan に通す（既存の一次情報の言い直しは重複として捨て、食い違う答えは保留にする）
- 登録した答えは記録（material_prefill.json）に残し、質問シートの答えの欄に「自動記入・出典つき」で入れる。
  お客様に聞くのは、公開ページに無かった質問だけになる

  python scripts/material_prefill.py [--site <id>] [--write]   # 見るだけ／登録まで（週次は --write。依頼が変わった社だけ）
"""
import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
MAX_PAGES, PAGE_CHARS = 20, 5000
SKIP_PATH = re.compile(r"/(samples|tags?|category|categories|page|wp-json|feed|api|404|thanks)(/|$)", re.I)
# 先に読むページ（会社・サービス・事例など、社が自分の言葉で書くページ）
FIRST = re.compile(r"/(about|company|corporate|profile|message|ceo|service|services|cases?|works|process|flow|price|faq|"
                   r"operator|supervisor|products?|team|history|achievements?|results?|column)(/|$)", re.I)
FILE = "material_prefill.json"


def _get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001  1ページ読めなくても、ほかのページで答える
        return ""


def text_of(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer)\b.*?</\1>", " ", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t).strip()


def own_article_slugs():
    """当社が書いた記事の slug（公開側の articles と、非公開の置き場の articles）"""
    import private_store as P
    out = {p.stem for p in (ROOT / "articles").glob("*.md")}
    out |= {p.stem for p in (P.base() / "articles").rglob("*.md")}
    return out


def pick_urls(locs, slugs, limit=MAX_PAGES):
    keep = []
    for u in locs:
        path = re.sub(r"^https?://[^/]+", "", u)
        last = [s for s in path.split("/") if s][-1:] or [""]
        if SKIP_PATH.search(path) or last[0] in slugs:
            continue
        keep.append(u)
    keep.sort(key=lambda u: (not FIRST.search(re.sub(r"^https?://[^/]+", "", u)), len(u)))
    return keep[:limit]


def public_pages(site, fetch=_get):
    """[(url, 本文)]。sitemap から、当社の記事と見本を除いた社のページ"""
    import sites as S
    cfg = S.load_all().get(site) or {}
    dom = cfg.get("domain")
    if not dom:
        return []
    sm = fetch(f"https://{dom}/sitemap.xml")
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", sm)
    if not any(re.sub(r"^https?://[^/]+", "", u).strip("/") == "" for u in locs):
        locs.insert(0, f"https://{dom}/")
    out = []
    for u in pick_urls(locs, own_article_slugs()):
        t = text_of(fetch(u))
        if len(t) > 200:
            out.append((u, t[:PAGE_CHARS]))
    return out


def _flat(s):
    return re.sub(r"\s+", "", str(s or ""))


def verify(a, pages):
    """(使えるか, 理由)。引用が出典のページにそのまま有り、答えの数字がすべて引用に有ること"""
    import material_sheet as M
    src = dict(pages).get(a.get("url", ""))
    q = str(a.get("quote") or "")
    if not src:
        return False, "出典のページが読んだページに無い"
    if len(_flat(q)) < 8 or _flat(q) not in _flat(src):
        return False, "引用がページの本文に無い"
    extra = sorted(M._nums(a.get("answer")) - M._nums(q))
    if extra:
        return False, f"引用に無い数字: {', '.join(extra[:4])}"
    if len(str(a.get("answer") or "").strip()) < 10:
        return False, "答えが短すぎる"
    return True, ""


PROMPT = """あなたは、ある会社の公開ページだけを読んで、記事の材料の質問に答える係です。

決まり:
- 答えてよいのは、下の「公開ページ」に書いてあることだけ。書いていないことは答えない（推測・一般論・言い換えで数字を足すのは禁止）。
- 答えには、その根拠になった文を、ページの本文からそのまま（一字も変えずに）引用する。引用は1か所、20〜200字。
- 答えの数字（件数・年・金額・期間）は、引用の中にあるものだけを使う。
- その質問に答えられる文が無ければ、その質問は出さない（空の答えを出さない）。
- 出力は JSON だけ: {{"answers": [{{"no": 質問の番号, "answer": "答えの文", "url": "出典のページのURL", "quote": "引用"}}]}}

質問:
{questions}

公開ページ:
{pages}
"""


def ask_answers(rows, pages, ask=None):
    import material_sheet as M
    qs = "\n".join(f"{i}. {q}" for i, (_k, _lab, q, *_x) in enumerate(rows, 1))
    ps = "\n\n".join(f"[{u}]\n{t}" for u, t in pages)
    raw = (ask or M._ask)(PROMPT.format(questions=qs, pages=ps))
    got = M._json(raw).get("answers")
    return [a for a in got if isinstance(a, dict)] if isinstance(got, list) else []


def record_path(site):
    import client_private as CP
    return CP.private_path(site, FILE)


def load_record(site):
    try:
        return json.loads(record_path(site).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def req_hash(site, rows):
    return hashlib.sha1(json.dumps([r[2] for r in rows], ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def run(site, write=False, ask=None, fetch=_get, today=None):
    """(登録した一次情報・体験の数, 捨てた答えの理由の一覧)。質問が前の回と同じ社は読み直さない"""
    import material_sheet as M
    import sites as S
    today = today or date.today().isoformat()
    rows = [r for r in M.rows_for(site, M.requests_of(site)) if r[0] != "tpl:voice"]   # お客様の声は機械で登録しない
    rec = load_record(site)
    h = req_hash(site, rows)
    if rec.get("_hash") == h:
        print(f"  {S.public_id(site)}: 質問が前の回と同じため読み直しません")
        return 0, []
    pages = public_pages(site, fetch)
    if not pages:
        print(f"  {S.public_id(site)}: 公開ページを読めません")
        return 0, ["公開ページを読めない"]
    got = ask_answers(rows, pages, ask)
    answers, dropped = [], []
    for a in got:
        try:
            no = int(a.get("no"))
        except (TypeError, ValueError):
            continue
        if not 1 <= no <= len(rows):
            continue
        ok, why = verify(a, pages)
        if not ok:
            dropped.append(f"問{no}: {why}")
            continue
        key, lab, q = rows[no - 1][:3]
        answers.append({"no": str(no), "key": key, "item": lab, "question": q, "answer": str(a["answer"]).strip(),
                        "period": "", "count": "", "ok": "可", "target": "", "bind": M._bind(key, lab), "added": False,
                        "url": a["url"], "quote": a["quote"]})
    f, e, held = M.plan(site, answers, ask) if answers else ([], [], [])
    print(f"  {S.public_id(site)}: 公開ページ {len(pages)}件・答えの候補 {len(got)}件 → 引用で確かめて残った {len(answers)}件 → "
          f"一次情報 {len(f)}件・体験 {len(e)}件{'を登録' if write else '（--write で登録）'}・保留 {len(held)}件・捨てた {len(dropped)}件")
    if write:
        if f or e:
            M.write(site, f, e, source=f"社の公開ページから自動記入（{today}）")
        done = {str(x.get("no")) for x in f + e}
        rec = {"_hash": h, "_at": today}
        for a in answers:
            if a["no"] in done:
                rec[a["key"]] = {"answer": a["answer"], "url": a["url"], "at": today}
        p = record_path(site)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return len(f) + len(e), dropped + [f"問{n}: {w}" for n, w in held]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-push", action="store_true", help="非公開の置き場へ送らない（週次は鍵を戻した後に送る）")
    a = ap.parse_args()
    import material_sheet as M
    import private_store as P
    n = 0
    for s in M.targets(a.site):
        got, _ = run(s, write=a.write)
        n += got
    if a.write and n and not a.no_push:
        P.push(f"質問シートを社の公開ページから自動記入（{n}件）")
    print(f"MATERIAL_PREFILL={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
