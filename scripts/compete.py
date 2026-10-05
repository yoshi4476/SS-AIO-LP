# -*- coding: utf-8 -*-
"""競合と比べて測り、負けている所を出す（競合比較のループの「測る」「理由を出す」「知らせる」）。

**なぜ要るか**: 引用の実測（ai_cite_check）は「自社が出典に出たか」しか見ておらず、
誰に負けているのか・先月より近づいたのかが分からなかった。受託のお客様に毎月
「競合と比べてどこまで来たか・次に何をするか」を見せるには、同じ語で相手も測る必要がある。

新しく調べる道具ではなく、既存の材料をつなぐ（同じ役目を2つ作らない）:
  検索 … data/ranks/<site>.json（GSC の順位。自社だけ。検索上位の顔ぶれは課金APIで取らない）
  AI   … ai_cite_check のエンジン（30日キャッシュ・Gemini の月の予算・鍵のあるAIだけ）
  種類 … industry_ai_sources.rule_class と data/research/source_class.json（業種調査で分けた12,000件）
  埋める … auto_rewrite --kind compete（週2本・既存の検算すべて）
  効き … effect_ab --rewrites（種類別・28日・対照群）と rewrite_rollback（効かなければ戻す）

  python scripts/compete.py --measure --dry-run      # 何回AIに聞くことになるか（課金なし）
  python scripts/compete.py --measure                # 月次: data/compete/<site>/<YYYY-MM>.json
  python scripts/compete.py --measure --cache-only   # キャッシュだけで出す（課金なし・古い答えも使う）
  python scripts/compete.py --gaps                   # 負けている語の差 → data/compete/<site>/gaps.json
  python scripts/compete.py --check                  # 週次: AIのシェアが下がった語・一次データの要望を要対応に
出す印: COMPETE_OK=yes|no|unknown
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "compete"
USAGE = OUT / "_usage.json"
BEFORE = ROOT / "data" / "rewrite_before"
MAX_KW = 20
AI_CAP = 60               # サイトあたり月の「新しく聞く」回数（キャッシュに当たる分は数えない）。sites/<id>.json の compete.ai_cap で変える
MIN_N = 10                # これ未満の母数は割合にしない（0.1節）
MIN_REPEAT = 2            # 競合と呼ぶのは2語以上で出典に出たドメインだけ（1語は偶然と区別できない）
PAGES_PER_SITE = 12       # 1回に読む競合ページの上限（robots を守り、相手に負荷をかけない）。1語1ページで広く見る
PAGES_PER_DOMAIN = 2
UA = "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; +https://ai.7senses.co.jp/)"
ENGINE_NAMES = ("ChatGPT", "Gemini", "Perplexity", "Claude", "Grok")

TYPES = {"peer": "同業・競合サイト", "portal": "ポータル・比較サイト", "public": "公的機関・学会・業界団体",
         "wiki": "百科事典・辞書", "media": "ニュース・メディア・まとめ", "video": "動画・SNS・ブログ",
         "review": "口コミ・地図"}
# 業種調査の分類（clinic・maker・other）は「その業種の事業者」なので同業に入れる
PEER_FROM_RESEARCH = {"clinic", "maker", "other"}
EXTRA_RULES = [
    (r"(^|\.)(weblio\.jp|kotobank\.jp|dictionary\.goo\.ne\.jp|wikiwand\.com)$", "wiki"),
    (r"prtimes\.jp|itmedia\.co\.jp|impress\.co\.jp|ascii\.jp|toyokeizai\.net|businessinsider\.jp|"
     r"gendai\.media|nikkeibp\.co\.jp|matome|hatenablog|qiita\.com|zenn\.dev", "media"),
    (r"(^|\.)(amazon\.co\.jp|rakuten\.co\.jp|kakaku\.com|itreview\.jp|boxil\.jp|aspic\.or\.jp)$", "portal"),
]


def _norm(s):
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—ー_?？!！]", "", (s or "").lower())


def domain_of(u):
    m = re.match(r"https?://([^/:?#]+)", u or "")
    d = (m.group(1) if m else "").lower()
    d = d[4:] if d.startswith("www.") else d
    # Gemini の出典の転送URL（行き先を追えなかった分）は、どのサイトか分からないので数えない
    return "" if d == "vertexaisearch.cloud.google.com" else d


def _known():
    p = ROOT / "data" / "research" / "source_class.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


KNOWN = None


def kind_of(dom, mine=(), operator=()):
    """出典ドメインの種類。ポータル・公的機関・百科事典・まとめは同業の競合と混ぜない"""
    global KNOWN
    if not dom:
        return ""
    if any(dom == m or dom.endswith("." + m) for m in mine):
        return "self"
    if any(dom == m or dom.endswith("." + m) for m in operator):
        return "operator"
    try:
        import industry_ai_sources as IAS
        c = IAS.rule_class(dom)
    except Exception:
        c = ""
    if not c:
        for pat, k in EXTRA_RULES:
            if re.search(pat, dom):
                c = k
                break
    if not c:
        if KNOWN is None:
            KNOWN = _known()
        c = KNOWN.get(dom, "")
    if not c or c in PEER_FROM_RESEARCH:
        return "peer"
    return c if c in TYPES else "peer"


def site_domains(sid, cfg):
    """自社（その社）のドメインと、運用会社のドメイン。お客様の比較に当社のサイトを競合として出さない"""
    import sites as S
    mine = {cfg["domain"].lower().replace("www.", "")}
    # 自社3サイトどうしは同じ会社なので互いを競合に数えない。お客様の比較には当社のサイトを出さない
    own = {S.load(x)["domain"].lower().replace("www.", "") for x in S.own_ids()}
    return mine, own - mine


def ai_cap(cfg):
    try:
        return int((cfg.get("compete") or {}).get("ai_cap") or AI_CAP)
    except (TypeError, ValueError):
        return AI_CAP


def share(n, d):
    """母数が MIN_N 未満なら割合にしない（None）。表示側は「n/d語」で出す"""
    return round(n / d, 3) if d >= MIN_N else None


def fmt_share(n, d):
    if d == 0:
        return "—"
    s = share(n, d)
    return f"{s * 100:.0f}%（{n}/{d}語）" if s is not None else f"{n}/{d}語（母数{MIN_N}未満のため割合にしません）"


# ---- 語を選ぶ -------------------------------------------------------------

def _brand_rx(sid, cfg):
    pats = []
    try:
        import brand_search
        pats.append(brand_search.BRAND.pattern)
    except Exception:
        pass
    names = [cfg.get("name", "")]
    p = ROOT / "data" / "clients" / sid / "company.json"
    if p.is_file():
        try:
            names.append(json.loads(p.read_text(encoding="utf-8")).get("name", ""))
        except (OSError, ValueError):
            pass
    pats += [re.escape(n) for n in names if n and len(n) >= 2]
    return re.compile("|".join(pats), re.I) if pats else None


def gsc_rows(sid):
    """data/ranks/<site>.json の最新の28日（rank_track が日々残す）。返すのは (行, 期間)"""
    f = ROOT / "data" / "ranks" / f"{sid}.json"
    if not f.is_file():
        return [], ""
    hist = json.loads(f.read_text(encoding="utf-8"))
    if not hist:
        return [], ""
    day = sorted(hist)[-1]
    end = date.fromisoformat(day) - timedelta(days=3)
    return hist[day], f"{end - timedelta(days=28)}〜{end}"


def ledger_words(sid):
    """台帳で優先度Aの公開済みの語。管制塔に届かなければ、公開記事の keyword（狙う語）"""
    out = []
    try:
        import hub_client
        rows = hub_client.all_kw() if hub_client.enabled() else []
    except Exception:
        rows = []
    for r in rows:
        if r.get("site") == sid and str(r.get("status", "")).strip() == "公開済み" \
                and str(r.get("priority", "")).strip() == "A" and r.get("keyword"):
            out.append(str(r["keyword"]))
    if out:
        return out
    import sites as S
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        kw = re.search(r"^keyword:\s*(.+)$", fm, re.M)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if cat and kw and sc and int(sc.group(1)) >= 90 and S.find_category_owner(cat.group(1)) == sid:
            out.append(kw.group(1).strip().strip('"'))
    return out


def keywords(sid, cfg, limit=MAX_KW, prev=None):
    """GSC の表示が多い語と台帳の優先語から最大 limit 語。先月の語はなるべく残す（先月と比べられるように）"""
    import ai_kw_research as AK
    rows, window = gsc_rows(sid)
    brand = _brand_rx(sid, cfg)
    by = {}
    for r in rows:
        kw = str(r.get("kw", ""))
        if len(kw) < 3 or (brand is not None and brand.search(kw)):
            continue
        # 守備範囲の外の語（補助金サイトに出る「meo 対策 大阪」など）は、その社が狙う語ではない
        if (cfg.get("owns") or (cfg.get("kw_seeds") or {}).get("industries")) and not AK.in_territory(kw, cfg):
            continue
        k = _norm(kw)
        if k not in by or r.get("imp", 0) > by[k].get("imp", 0):
            by[k] = r
    gsc = sorted(by.values(), key=lambda r: -r.get("imp", 0))
    led = [w for w in ledger_words(sid) if not (brand is not None and brand.search(w))]
    picked, seen = [], set()

    def add(kw):
        k = _norm(kw)
        if k and k not in seen and len(picked) < limit:
            seen.add(k)
            picked.append(kw)
    cand = {_norm(r["kw"]) for r in gsc} | {_norm(w) for w in led}
    for kw in prev or []:
        if _norm(kw) in cand:
            add(kw)
    n_led = min(len(led), max(limit // 4, 1))
    for r in gsc[:limit - n_led]:
        add(r["kw"])
    for w in led:
        add(w)
    for r in gsc:
        add(r["kw"])
    return picked, by, window


def rank_of(kw, by):
    r = by.get(_norm(kw))
    if not r:
        return None, 0, ""
    return r.get("pos"), r.get("imp", 0), r.get("url", "")


def slug_of(url):
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def slug_for_kw(kw, url):
    """自社でその語に答える記事。GSC の着地ページが記事でなければ、狙う語が同じ記事"""
    s = slug_of(url)
    if s and (ROOT / "articles" / f"{s}.md").is_file():
        return s
    k = _norm(kw)
    for p in (ROOT / "articles").glob("*.md"):
        m = re.search(r"^keyword:\s*(.+)$", p.read_text(encoding="utf-8-sig")[:3000], re.M)
        if m and _norm(m.group(1)) == k:
            return p.stem
    return ""


# ---- AIに聞く（上限つき） ------------------------------------------------------

def load_usage():
    try:
        return json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_usage(u):
    OUT.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps(u, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def engines(cache_only):
    """聞くAI。cache_only は呼ばずに答えのキャッシュだけを読む（古さを問わない。試しと上限超えの回）"""
    import ai_cite_check as AC
    if cache_only:
        def reader(name):
            def f(q):
                for n in (name, name + "-sub"):
                    u = AC.cached(n, q, days=None)
                    if u is not None:
                        return u
                return None
            return f
        return {n: reader(n) for n in ENGINE_NAMES
                if (AC.CACHE_DIR / n).is_dir() or (AC.CACHE_DIR / (n + "-sub")).is_dir()}
    return AC.engines_available()


def need_calls(kws, names):
    """新しく聞くことになる回数（30日以内のキャッシュに無い組）。課金の前に数える"""
    import ai_cite_check as AC
    return sum(1 for q in kws for n in names if AC.cached(n, q) is None)


def ask(kw, eng, mine, operator):
    """エンジンごとの出典。domains はその社と運用会社を除いた全ドメイン"""
    out = {}
    for name, fn in eng.items():
        try:
            urls = fn(kw)
        except Exception as e:
            out[name] = {"error": str(e)[:80]}
            continue
        if urls is None:
            continue
        urls = list(dict.fromkeys(u for u in urls if domain_of(u)))
        doms = list(dict.fromkeys(domain_of(u) for u in urls))
        out[name] = {"answered": bool(doms),
                     "ours": any(kind_of(d, mine) == "self" for d in doms),
                     "domains": [d for d in doms if kind_of(d, mine, operator) not in ("self", "operator")][:15],
                     "urls": [u for u in urls if kind_of(domain_of(u), mine, operator) not in ("self", "operator")][:12]}
    return out


def summarize(items, mine, operator):
    """指標: AIのシェア（出典に自社が出た語の割合）・上位10位の割合、競合上位5社の同じ指標"""
    answered = [x for x in items if x["ai_answered"]]
    ranked = [x for x in items if x["pos"] is not None]
    dn = len(answered)
    hits, kinds = {}, {}
    for x in answered:
        for d in x["ai_domains"]:
            k = kind_of(d, mine, operator)
            kinds.setdefault(k, set()).add(d)
            if k == "peer":
                hits[d] = hits.get(d, 0) + 1
    comp = sorted(((d, n) for d, n in hits.items() if n >= MIN_REPEAT), key=lambda x: (-x[1], x[0]))[:5]
    engines_n = {}
    for x in items:
        for name, r in x["ai"].items():
            if "error" in r:
                continue
            e = engines_n.setdefault(name, {"answered": 0, "ours": 0})
            e["answered"] += bool(r.get("answered"))
            e["ours"] += bool(r.get("ours"))
    own_ai = sum(1 for x in answered if x["ai_ours"])
    top10 = sum(1 for x in ranked if x["pos"] <= 10)
    return {
        "kw_n": len(items),
        "ai": {"answered_n": dn, "ours_n": own_ai, "share": share(own_ai, dn)},
        "search": {"ranked_n": len(ranked), "top10_n": top10, "top10_rate": share(top10, len(ranked))},
        "competitors": [{"domain": d, "type": "peer", "ai_n": n, "ai_share": share(n, dn),
                         "top10_rate": None} for d, n in comp],
        "other_types": {k: sorted(v)[:8] for k, v in kinds.items() if k not in ("peer", "self", "operator", "")},
        "engines": engines_n,
        # 検索上位の顔ぶれは課金APIで取らない（0.3節・課金の決まり）。相手の上位率は出せない
        "search_note": "競合の検索順位は取得していません（SERPを課金APIで取らないため）。自社の順位は Search Console の実測です",
    }


def prev_month(ym):
    y, m = map(int, ym.split("-"))
    return f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"


def months(sid):
    d = OUT / sid
    return sorted(p.stem for p in d.glob("????-??.json")) if d.is_dir() else []


def load_month(sid, ym):
    p = OUT / sid / f"{ym}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def measure_site(sid, cfg, cache_only=False, dry=False, ym=None, eng=None, usage=None):
    ym = ym or f"{date.today():%Y-%m}"
    mine, operator = site_domains(sid, cfg)
    prev = load_month(sid, prev_month(ym))
    kws, by, window = keywords(sid, cfg, MAX_KW, [x["kw"] for x in (prev or {}).get("items", [])])
    if not kws:
        print(f"   {sid}: 語を選べません（Search Console の順位も台帳の語もありません）")
        return None
    eng = eng if eng is not None else engines(cache_only)
    usage = usage if usage is not None else load_usage()
    cap, used = ai_cap(cfg), usage.get(ym, {}).get(sid, 0)
    status, need = "ok", 0
    if not cache_only:
        need = need_calls(kws, list(eng))
        print(f"   {sid}: {len(kws)}語 × AI {len(eng)}つ（{', '.join(eng) or 'なし'}）。新しく聞く {need}回"
              f"（今月 {used}/{cap}回）")
        if dry:
            print(f"COMPETE_EST={sid}:{need}")
            return None
        if used + need > cap:
            print(f"要対応: {cfg['name']} の競合比較は月の上限（AIに新しく聞く {cap}回）を超えるため、"
                  f"AIには聞きませんでした（必要 {need}回・残り {max(cap - used, 0)}回）。"
                  f"キャッシュにある答えだけで出します。上限は sites/{sid}.json の compete.ai_cap")
            eng, status = engines(True), "over_cap"
    elif dry:
        return None
    if not eng and status == "ok":
        status = "no_engine"
    items = []
    for kw in kws:
        pos, imp, url = rank_of(kw, by)
        ai = ask(kw, eng, mine, operator) if eng else {}
        doms = {}
        for r in ai.values():
            for d in r.get("domains") or []:
                doms[d] = doms.get(d, 0) + 1
        items.append({"kw": kw, "pos": pos, "imp": imp, "url": url, "slug": slug_for_kw(kw, url), "ai": ai,
                      "ai_answered": any(r.get("answered") for r in ai.values()),
                      "ai_ours": any(r.get("ours") for r in ai.values()), "ai_domains": doms})
    if status == "ok" and not cache_only:
        usage.setdefault(ym, {})[sid] = used + need
        save_usage(usage)
    rec = {"site": sid, "ym": ym, "measured": date.today().isoformat(),
           "mode": "cache" if cache_only or status == "over_cap" else "live", "status": status,
           "gsc_window": window, "engines": sorted(eng), "summary": summarize(items, mine, operator),
           "items": items}
    if prev:
        rec["diff"] = diff(prev, rec)
    (OUT / sid).mkdir(parents=True, exist_ok=True)
    (OUT / sid / f"{ym}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    s = rec["summary"]
    print(f"   {cfg['name']}: AIのシェア {fmt_share(s['ai']['ours_n'], s['ai']['answered_n'])} ／ "
          f"上位10位 {fmt_share(s['search']['top10_n'], s['search']['ranked_n'])} ／ 競合 "
          + "・".join(f"{c['domain']}({c['ai_n']})" for c in s["competitors"]))
    return rec


def diff(prev, cur):
    """先月から: 指標の差（割合はポイント、母数が足りなければ件数）と、AIの出典から外れた語"""
    p = {x["kw"]: x for x in prev.get("items", [])}
    lost = [x["kw"] for x in cur["items"] if x["ai_answered"] and not x["ai_ours"]
            and p.get(x["kw"], {}).get("ai_ours")]
    won = [x["kw"] for x in cur["items"] if x["ai_ours"] and x["kw"] in p
           and p[x["kw"]].get("ai_answered") and not p[x["kw"]].get("ai_ours")]
    ps, cs = prev.get("summary", {}), cur["summary"]

    def pt(a, b):
        return round((b - a) * 100, 1) if a is not None and b is not None else None
    return {"from": prev.get("ym"), "lost": lost, "won": won,
            "ai_share_pt": pt((ps.get("ai") or {}).get("share"), cs["ai"]["share"]),
            "top10_pt": pt((ps.get("search") or {}).get("top10_rate"), cs["search"]["top10_rate"]),
            "ai_ours_n": [(ps.get("ai") or {}).get("ours_n"), cs["ai"]["ours_n"]]}


# ---- 負けている理由（競合のページと自社の記事の差） --------------------------------

ROBOTS = {}
PRIMARY = re.compile(r"当社調べ|自社調査|独自調査|アンケート|調査結果|回答者|有効回答|n\s*=\s*\d|件のデータ|当院の実績|当社の実績|実績件数")
# 「〜できる」「〜を削減」のような利点の見出しは問いではない。読者が検索で投げる形だけを問いとみなす
Q_HEAD = re.compile(r"[?？]|とは|ですか|いくら|どう[すや]|なぜ|方法|違い|費用|相場|期間|注意点|選び方|必要")
STOP = {"まとめ", "よくある質問", "はじめに", "目次", "関連記事", "この記事", "監修", "注意", "こちら", "お問い合わせ", "会社概要"}


def _get(url, limit=600_000, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode(r.headers.get_content_charset() or "utf-8", "ignore")


def allowed(url):
    """robots.txt を守る。読めない（403・通信エラー）ときは読まない側に倒す"""
    import urllib.robotparser
    m = re.match(r"(https?://[^/]+)", url)
    if not m:
        return False
    base = m.group(1)
    if base not in ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(_get(base + "/robots.txt", 200_000, 15).splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                rp.parse([])
            else:
                rp = None
        except Exception:
            rp = None
        ROBOTS[base] = rp
    rp = ROBOTS[base]
    return bool(rp) and rp.can_fetch(UA, url)


def _text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", html))


def page_features(html):
    """本文はコピーしない。見出し（40字まで）と、数えられる特徴だけを残す"""
    heads = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h)).strip()[:40]
             for h in re.findall(r"(?is)<h[23][^>]*>(.*?)</h[23]>", html)]
    # 章番号（第1章・1-2.・3．）は見出しの中身ではない
    heads = [re.sub(r"^(第\d+章|\d+(?:[-.．]\d+)*[.．、]?)\s*", "", h) for h in heads]
    heads = [h for h in heads if h and h not in STOP][:20]
    mod = (re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
           or re.search(r'article:modified_time"\s+content="(\d{4}-\d{2}-\d{2})', html)
           or re.search(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})', html))
    text = _text(html)
    pm = PRIMARY.search(text)
    return {"heads": heads, "questions": [h for h in heads if Q_HEAD.search(h)][:10],
            "tables": len(re.findall(r"(?i)<table", html)), "modified": mod.group(1) if mod else "",
            "primary": pm.group(0) if pm else "", "chars": len(text)}


def article_features(slug):
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    fm, body = (m.group(1), m.group(2)) if m else ("", t)
    heads = [h.strip() for h in re.findall(r"^#{2,3}\s+(.+)$", body, re.M)]
    mod = re.search(r"^modified:\s*(\d{4}-\d{2}-\d{2})", fm, re.M) or re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", fm, re.M)
    plain = re.sub(r"\s+", "", re.sub(r"<[^>]+>|[#*|`>=\-]", "", body))
    pm = PRIMARY.search(plain)
    return {"heads": heads, "tables": len(re.findall(r"^\|:?-", body, re.M)) + body.count("<table"),
            "modified": mod.group(1) if mod else "", "primary": pm.group(0) if pm else "",
            "chars": len(plain), "body": body}


def _words(s):
    return [w for w in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{2,}", s or "") if w not in STOP]


def missing_questions(their_qs, mine_text, kw):
    """競合が見出しで答えている問いのうち、自社の記事が語として扱っていないもの"""
    hay = _norm(mine_text)
    own = {_norm(w) for w in _words(kw)}
    out = []
    for q in their_qs:
        ws = [w for w in _words(q) if _norm(w) not in own]
        ws = sorted(ws, key=len, reverse=True)[:3]
        if ws and not all(_norm(w) in hay for w in ws):
            out.append(q)
    return out[:5]


def relevant_facts(sid, kw):
    try:
        import facts as F
        _, fs = F.load_for(sid)
    except Exception:
        return []
    toks = [w for w in _words(kw) if len(w) >= 2]
    return [f["claim"] for f in fs if f.get("claim") and any(w in f["claim"] for w in toks)]


DATA_HINT = [
    (r"アンケート|回答者|有効回答|n\s*=", "読者・顧客へのアンケート結果（回答数と実施時期つき）"),
    (r"件のデータ|実績件数|当院の実績|当社の実績", "対応・支援の件数（期間と母数つき）"),
    (r"調査|当社調べ", "自社で集計した調査の数字（集計期間・母数つき）"),
]


def data_wish(sample):
    for pat, wish in DATA_HINT:
        if re.search(pat, sample or ""):
            return wish
    return "自社で集計した実数（期間・母数つき）"


def decide(kw, mine, theirs, facts_rel):
    """差を並べ、打ち手を決める: rewrite（書き直しで埋まる）／needs_data（一次データが無いと勝てない）"""
    diffs = []
    allq = [q for t in theirs for q in t["questions"]]
    mq = missing_questions(list(dict.fromkeys(allq)), " ".join(mine["heads"]) + mine["body"][:30000], kw)
    if mq:
        diffs.append({"type": "questions", "detail": mq})
    if mine["tables"] == 0 and any(t["tables"] for t in theirs):
        diffs.append({"type": "table", "detail": "競合は表を置いている（自社は0）"})
    newest = max((t["modified"] for t in theirs if t["modified"]), default="")
    old = (date.today() - timedelta(days=120)).isoformat()
    if newest and mine["modified"] and newest > mine["modified"] and mine["modified"] < old:
        diffs.append({"type": "fresh", "detail": f"競合の更新 {newest} ／ 自社 {mine['modified']}"})
    prim = [t["primary"] for t in theirs if t["primary"]]
    if prim and not mine["primary"]:
        diffs.append({"type": "primary", "detail": f"競合は自社集計の数字を出している（{prim[0]}）"})
    mx = max((t["chars"] for t in theirs), default=0)
    if mx and mine["chars"] and mx > mine["chars"] * 1.5:
        diffs.append({"type": "length", "detail": f"競合 {mx:,}字 ／ 自社 {mine['chars']:,}字（長さは成果を分けないため参考）"})
    fixable = [d for d in diffs if d["type"] in ("questions", "table", "fresh")]
    if any(d["type"] == "primary" for d in diffs) and not facts_rel and not fixable:
        return diffs, "needs_data", data_wish(prim[0])
    if fixable or (facts_rel and any(d["type"] == "primary" for d in diffs)):
        return diffs, "rewrite", ""
    return diffs, "none", ""


def gaps_site(sid, cfg, pages=PAGES_PER_SITE, fetch=None):
    """先月（最新）の測定から、競合が出典に出て自社が出ない語の差を出す"""
    ms = months(sid)
    if not ms:
        print(f"   {sid}: 測定がありません（--measure が先）")
        return None
    rec = load_month(sid, ms[-1])
    comps = {c["domain"] for c in rec["summary"]["competitors"]}
    mine_d, operator = site_domains(sid, cfg)
    fetch = fetch or _get
    items, read, blocked, per_dom = [], 0, 0, {}
    lose = [x for x in rec["items"] if x["ai_answered"] and not x["ai_ours"]
            and any(kind_of(d, mine_d, operator) == "peer" for d in x["ai_domains"])]
    lose.sort(key=lambda x: (-sum(d in comps for d in x["ai_domains"]), -(x.get("imp") or 0)))
    for x in lose:
        urls = [u for r in x["ai"].values() for u in r.get("urls") or []
                if kind_of(domain_of(u), mine_d, operator) == "peer"]
        urls = sorted(dict.fromkeys(urls), key=lambda u: domain_of(u) not in comps)
        theirs = []
        for u in urls:
            if read >= pages or theirs:
                break
            d = domain_of(u)
            if per_dom.get(d, 0) >= PAGES_PER_DOMAIN:
                continue
            if fetch is _get and not allowed(u):
                blocked += 1
                continue
            try:
                h = fetch(u)
            except Exception:
                continue
            read += 1
            per_dom[d] = per_dom.get(d, 0) + 1
            f = page_features(h)
            f.update(url=u, domain=d)
            theirs.append(f)
        it = {"kw": x["kw"], "slug": x.get("slug", ""), "imp": x.get("imp") or 0, "pos": x.get("pos"),
              "competitors": sorted({domain_of(u) for u in urls})[:5],
              "their_pages": [{k: t[k] for k in ("url", "domain", "heads", "tables", "modified", "primary", "chars")}
                              for t in theirs]}
        if not x.get("slug"):
            it.update(action="new_article", diffs=[], why="この語に答える自社の記事がありません（台帳へ積むかは kw_guard で決める）")
        elif not theirs:
            it.update(action="unread", diffs=[], why="競合のページを読めませんでした（robots・上限・通信）")
        else:
            mine = article_features(x["slug"])
            rel = relevant_facts(sid, x["kw"])
            diffs, action, wish = decide(x["kw"], mine, theirs, rel)
            it.update(action=action, diffs=diffs, facts=rel[:5])
            if wish:
                it["wish"] = wish
        items.append(it)
    out = {"site": sid, "ym": rec["ym"], "generated": date.today().isoformat(), "read": read,
           "robots_blocked": blocked, "items": items}
    (OUT / sid).mkdir(parents=True, exist_ok=True)
    (OUT / sid / "gaps.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    n = {}
    for it in items:
        n[it["action"]] = n.get(it["action"], 0) + 1
    print(f"   {cfg['name']}: 負けている語 {len(items)}（" + "・".join(f"{k} {v}" for k, v in n.items())
          + f"）／ 読んだページ {read}・robotsで読まない {blocked}")
    return out


ENQUEUE_PER_SITE = 3   # 月初に台帳へ積む新しい語の上限（書くのは日次の執筆。積みすぎると他の語が後回しになる）


def enqueue_new(sid, out, budget=ENQUEUE_PER_SITE):
    """自社の記事が無い語を、食い合いの検査（kw_guard）を通ったものだけ台帳へ積む。
    検査と積み方は report_actions.enqueue_gaps と同じ道具を使う（同じ役目を2つ作らない）"""
    import report_actions as RA
    items = [{"kind": "article_new", "site": sid, "finding": it["kw"]}
             for it in (out or {}).get("items", []) if it.get("action") == "new_article"]
    n = RA.enqueue_gaps(items, budget) if items else 0
    if items:
        print(f"   {sid}: 記事の無い語 {len(items)} → 台帳へ積んだ {n}（食い合いの検査を通った分・上限{budget}）")
    return n


def load_gaps(sid):
    try:
        return json.loads((OUT / sid / "gaps.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- 週次の知らせ・月次レポート ---------------------------------------------------

def check(sids=None):
    """AIの出典から外れた語・一次データがあれば勝てる語・上限超えを要対応で出す（印は COMPETE_OK）"""
    import sites as S
    bad = False
    for sid, cfg in S.load_all().items():
        if sids and sid not in sids:
            continue
        ms = months(sid)
        if not ms:
            continue
        cur = load_month(sid, ms[-1]) or {}
        d = cur.get("diff") or {}
        if d.get("lost"):
            bad = True
            print(f"要対応: {cfg['name']} でAIのシェアが下がった語 {len(d['lost'])}語（{d.get('from')}→{cur['ym']}。"
                  f"先月はAIの出典に出ていた）")
            for kw in d["lost"][:6]:
                print(f"  - {kw}")
        if cur.get("status") == "over_cap":
            bad = True
            print(f"要対応: {cfg['name']} の競合比較が月の上限で一部しか測れていません（{cur['ym']}）")
        g = load_gaps(sid) or {}
        wish = [it for it in g.get("items", []) if it.get("action") == "needs_data"]
        if wish:
            bad = True
            print(f"要対応: {cfg['name']} で一次データがあれば勝てる語 {len(wish)}語（書き直しでは埋まらない）")
            for it in wish[:6]:
                print(f"  - {it['kw']}: {it.get('wish', '')}（add_fact で登録すると書き直しに回ります）")
    print("COMPETE_OK=" + ("no" if bad else "yes"))
    return 0


def report_html(sid, client=False):
    """月次レポートの節（2ページ）。測定が無ければ None"""
    import html as H
    ms = months(sid)
    if not ms:
        return None
    cur = load_month(sid, ms[-1])
    s = cur["summary"]
    E = H.escape
    d = cur.get("diff") or {}

    def pt(v):
        return "—" if v is None else f"{v:+.1f}ポイント"
    ai_n, ai_d = s["ai"]["ours_n"], s["ai"]["answered_n"]
    sr_n, sr_d = s["search"]["top10_n"], s["search"]["ranked_n"]
    period = (f"対象: {s['kw_n']}語（Search Console の表示が多い語と優先語）。検索順位は {E(cur.get('gsc_window') or '—')} の28日、"
              f"AIは {E(cur['measured'])} に {E('・'.join(cur.get('engines') or []) or '—')} へ質問"
              + ("（キャッシュの答えを含む）" if cur.get("mode") == "cache" else "") + "。")
    cards = (
        f'<div class="hl-cards" style="margin:8px 0 12px">'
        f'<div class="hl"><div class="k">AIのシェア（出典に自社）</div><div class="v">{E(fmt_share(ai_n, ai_d).split("（")[0])}</div>'
        f'<div class="s">{ai_n}/{ai_d}語 ・先月から {pt(d.get("ai_share_pt"))}</div></div>'
        f'<div class="hl"><div class="k">検索で上位10位に入った語</div><div class="v">{E(fmt_share(sr_n, sr_d).split("（")[0])}</div>'
        f'<div class="s">{sr_n}/{sr_d}語 ・先月から {pt(d.get("top10_pt"))}</div></div></div>')
    rows = [f'<tr><td><b>自社</b></td><td>{E(fmt_share(ai_n, ai_d))}</td><td>{E(fmt_share(sr_n, sr_d))}</td></tr>']
    for c in s["competitors"]:
        rows.append(f'<tr><td>{E(c["domain"])}</td><td>{E(fmt_share(c["ai_n"], ai_d))}</td><td>未取得</td></tr>')
    if not s["competitors"]:
        rows.append(f'<tr><td colspan="3">{MIN_REPEAT}語以上でAIの出典に出た同業のサイトはありませんでした</td></tr>')
    others = "／".join(f"{TYPES.get(k, k)}: {'・'.join(v[:3])}" for k, v in (s.get("other_types") or {}).items())
    page1 = (f'<p style="font-size:9.5pt">同じ語で、AIの回答の出典と検索順位を競合と並べました。{period}'
             f'母数が{MIN_N}語に満たない指標は割合にせず件数で示します。</p>{cards}'
             '<h3>競合上位5社との比較</h3><table><tr><th style="width:40%">サイト</th><th>AIのシェア</th><th>上位10位の割合</th></tr>'
             + "".join(rows) + '</table>'
             f'<p class="note">{E(s.get("search_note", ""))}。競合は「{MIN_REPEAT}語以上でAIの出典に出た同業のサイト」です。'
             'ポータル・公的機関・百科事典・まとめは同業と分けて数えています'
             + (f'（{E(others)}）' if others else "") + '。</p>')
    if d:
        if d.get("lost"):
            page1 += f'<p style="font-size:9.5pt">先月はAIの出典に出ていて今月外れた語: {E("・".join(d["lost"][:8]))}</p>'
        if d.get("won"):
            page1 += f'<p style="font-size:9.5pt">今月新たにAIの出典に出た語: {E("・".join(d["won"][:8]))}</p>'
    else:
        page1 += '<p class="note">今月が最初の測定です。来月から先月との差を示します。</p>'

    g = load_gaps(sid) or {}
    label = {"rewrite": "記事の書き直し（自動・週2本まで）", "needs_data": "一次データのご用意",
             "new_article": "新しい記事（食い合いの検査を通してから）", "unread": "相手のページを読めず保留", "none": "差が見つからず保留"}
    who = "御社にご用意いただきたいもの" if client else "人が用意するもの（自動ではできない）"
    lrows = []
    for it in sorted(g.get("items", []), key=lambda x: -(x.get("imp") or 0))[:8]:
        gap = "・".join({"questions": "答えている問い", "table": "表", "fresh": "更新日", "primary": "一次データ",
                         "length": "文字数"}[x["type"]] for x in it.get("diffs", [])) or "—"
        nxt = label.get(it["action"], it["action"])
        if it["action"] == "needs_data":
            nxt += f"（{it.get('wish', '')}）"
        lrows.append(f'<tr><td>{E(it["kw"])}</td><td>{E("・".join(it.get("competitors", [])[:2]))}</td>'
                     f'<td>{E(gap)}</td><td>{E(nxt)}</td></tr>')
    auto = sum(1 for it in g.get("items", []) if it["action"] == "rewrite")
    data = [it for it in g.get("items", []) if it["action"] == "needs_data"]
    page2 = ('<p style="font-size:9.5pt">競合がAIの出典に出て自社が出ない語について、相手の公開ページと自社の記事を'
             '「答えている問い・表・更新日・一次データ・文字数」で比べました（相手の本文は保存・転載していません）。</p>'
             '<table><tr><th style="width:24%">負けている語</th><th style="width:22%">出典に出た競合</th>'
             '<th style="width:20%">差</th><th>次の打ち手</th></tr>'
             + ("".join(lrows) or '<tr><td colspan="4">差を調べた語はまだありません</td></tr>') + '</table>'
             f'<h3>次の打ち手</h3><p style="font-size:9.5pt"><b>自動で行うもの</b>: 差が書き直しで埋まる{auto}語は、'
             '週次の書き直しで答えている問い・表を足します（数字は登録済みの一次データだけ。28日後に対照群と比べ、'
             '効かなければ元に戻します）。</p>'
             f'<p style="font-size:9.5pt"><b>{who}</b>: '
             + ("・".join(f"「{E(it['kw'])}」の{E(it.get('wish', ''))}" for it in data[:4])
                if data else "今月はありません") + '。AIが出典に選ぶのは、そこにしか無い数字です。</p>')
    return page1, page2


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--gaps", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--cache-only", action="store_true", help="AIを呼ばずにキャッシュの答えだけで出す（課金なし）")
    ap.add_argument("--dry-run", action="store_true", help="何回聞くことになるかだけを出す（課金なし）")
    ap.add_argument("--pages", type=int, default=PAGES_PER_SITE)
    a = ap.parse_args()
    sids = [x for x in S.load_all() if not a.site or x == a.site]
    if a.check:
        return check(sids)
    if a.measure:
        print("■ 競合比較の測定" + ("（キャッシュだけ）" if a.cache_only else "（予定だけ）" if a.dry_run else ""))
        eng = engines(a.cache_only)
        if not eng and not a.cache_only:
            print("   AIの鍵がありません（検索側だけを残します）")
        usage = load_usage()
        for sid in sids:
            try:
                measure_site(sid, S.load(sid), a.cache_only, a.dry_run, eng=eng, usage=usage)
            except Exception as e:
                print(f"   {sid}: 測れませんでした（{type(e).__name__}: {str(e)[:80]}）")
                print("COMPETE_OK=unknown")
    if a.gaps:
        print("■ 負けている語の差")
        for sid in sids:
            try:
                enqueue_new(sid, gaps_site(sid, S.load(sid), a.pages))
            except Exception as e:
                print(f"   {sid}: 差を出せませんでした（{type(e).__name__}: {str(e)[:80]}）")
    if not (a.measure or a.gaps):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
