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
    main = re.sub(r"\s+", " ", re.sub(r"【[^】]*】|\[[^\]]*\]", " ", title).replace("｜", " ").replace("|", " ")).strip(" 　\"")
    # 題名が問いの形なら、問いの部分だけを聞く（「…は対象?対象範囲と注意点を解説」→「…は対象?」）
    m = re.search(r"^(.+?[?？])", main)
    main = (m.group(1) if m else main.strip("?？"))[:45]
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
    AC.NEED_TEXT = True        # 「何と答えたか」を数えるので、本文の無い古いキャッシュは使わない
    eng = AC.subscription_engines()
    qs = questions(slug)
    tasks = [(q, n) for q in qs for n in eng]

    def one(t):
        q, n = t
        try:
            urls = eng[n](q) or []
            return q, n, urls, AC.answer_text(eng[n], q), ""
        except Exception as e:
            return q, n, [], "", str(e)[:160]
    ans = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for q, n, urls, text, err in ex.map(one, tasks):
            ans.setdefault(q, {})[n] = {"urls": urls, "text": text, "error": err}
    rec = {"slug": slug, "date": date.today().isoformat(), "engines": sorted(eng), "questions": qs, "answers": ans}
    rec["stance"] = classify(rec)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


LABELS = {"yes": "対象になる（できる）", "cond": "条件による", "no": "対象外（できない）", "none": "問いに直接答えていない"}


def _read_once(items):
    """AI の答えを、問いへの結論で読み分ける（claude に1回読ませる）。根拠の一文も返させる"""
    import subprocess
    import tempfile
    import auto_rewrite as AR
    body = "\n\n".join(f"### {i}\n問い: {q}\n答え:\n{t[:2500]}" for i, (q, t) in items.items())
    prompt = ("次はそれぞれ、ある問いに対する AI の答えです。各答えの結論を、問いに対して次のどれか1つに分けてください。\n"
              "yes=対象になる・できる と言い切っている / cond=条件しだい・ケースによる としている / "
              "no=対象外・できない と言い切っている / none=問いに直接答えていない（問いが『はい・いいえ』で答える形でない場合も none）。\n"
              "迷ったら cond ではなく、答えの最初の結論の文で決める。各答えから、その判断の根拠になる一文をそのまま抜き出す。\n"
              "出力は JSON のオブジェクト1つだけ: {\"<番号>\": {\"label\": \"yes|cond|no|none\", \"quote\": \"<そのままの一文>\"}}\n\n" + body)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        r = subprocess.run([AR.claude_bin(), "-p", "--model", "claude-sonnet-5-5"], input=prompt, cwd=tmp,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    m = re.search(r"\{.*\}", r.stdout or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def classify(rec):
    """答えを2回独立に読み分け、2回が一致したものだけを採る（一致しないものは split として数えない）。
    根拠の一文が答えの本文に本当にあるかも確かめる（無ければ split）"""
    items, where = {}, {}
    for q, by in rec["answers"].items():
        for name, r in by.items():
            if r.get("text") and not r.get("error"):
                i = str(len(items) + 1)
                items[i], where[i] = (q, r["text"]), (q, name)
    if not items:
        return {}
    a, b = _read_once(items), _read_once(items)
    norm = lambda s: re.sub(r"\s+", "", s or "")
    out = {}
    for i, (q, name) in where.items():
        la, lb = (a.get(i) or {}).get("label"), (b.get(i) or {}).get("label")
        quote = (a.get(i) or {}).get("quote", "")
        ok = la == lb and la in LABELS and norm(quote)[:20] in norm(items[i][1])
        out.setdefault(q, {})[name] = {"label": la if ok else "split", "quote": quote if ok else ""}
    return out


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
    out = []
    # 本題の問いに、AI が何と答えたか（はい・いいえで答える問いだけ。読み分けが2回一致した答えだけ数える）
    for k, (q, by) in enumerate((rec.get("stance") or {}).items(), 1):
        c = {lb: sum(1 for v in by.values() if v["label"] == lb) for lb in ("yes", "cond", "no", "none", "split")}
        decided = c["yes"] + c["cond"] + c["no"]
        if decided < 2 or c["none"] > decided:
            continue                      # 問いが「はい・いいえ」の形でない、または読み分けが割れすぎた
        names = "・".join(sorted(by))
        parts = "、".join(f"「{LABELS[lb]}」が{c[lb]}回答" for lb in ("yes", "cond", "no") if c[lb])
        rest = c["none"] + c["split"]
        out.append({
            "id": f"survey-{slug}-q{k}",
            "claim": (f"当社が{y}年{m}月に{names}へ「{q}」と聞いたところ、{parts}でした"
                      + (f"（ほか{rest}回答は結論が読み取れず除外）" if rest else "") + "（当社調べ）"),
            "source": "セブンセンシズ株式会社によるAIへの聞き取り調査", "as_of": rec["date"][:7]})
    out += [{
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
