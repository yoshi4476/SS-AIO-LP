# -*- coding: utf-8 -*-
"""上位ページの見出しの並び・共起語・実際の質問（ラッコで取ったもの）を、語ごとに残して執筆と書き直しに渡す。

**なぜ要るか**: ラッコの枠は「見出し・共起語 70／実際の質問 30」が一番大きいのに、どの工程も呼んでおらず、
課金は効きの弱い関連語の大量取得（予備の枠 20）に寄っていた（2026-10-09 の点検）。上位10ページが共通して
扱う観点（見出し）と、上位に必ず出てくる語（共起語）と、読者が実際に聞いている質問は、構成の「共通60〜70%」と
FAQ の材料そのもの。取るのは kw_plan（毎日の在庫の見張りが1か月分を切った社だけ動かす）で、ここは残すのと読むだけ。
ラッコには触らない（通信の口は rakko.call の1か所・課金する工程は kw_plan だけ）。

残すもの（相手の本文は残さない）: 見出しは40字まで・ページごとの見出しの数と文字数・見出しの語の出現数・
共起語と出現サイト数・質問と相対需要。URL・題・説明文は残さない（自社のページかどうかの印だけ）。

置き場: data/kw_serp/<site>.json（{正規化した語: {...}}）。お客様の社の分は .gitignore で外し、
CI のキャッシュ（client_private の kw_serp）で書いた工程から執筆・書き直しへ渡す。

  python scripts/kw_serp.py --brief <site> --kw "<狙う語>"   # 執筆の指示（multi_site_prompt の 5c）
  python scripts/kw_serp.py --rewrite <slug>                   # 書き直しの指示に入る分（auto_rewrite が読む）
  python scripts/kw_serp.py --list <site>                      # 残っている語
出す印: KW_SERP=yes / KW_SERP=none
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DIR = ROOT / "data" / "kw_serp"
HEAD_MAX = 40        # 見出しは40字まで（相手の文を丸ごと残さない）
PAGES_MAX = 10       # 上位10ページの並びまで
HEADS_PER_PAGE = 14  # 1ページの見出しの数の上限（h4 までの長いページで膨らませない）
COOC_MAX = 30
Q_MAX = 15
STALE_DAYS = 60      # これより古い記録は執筆に渡さない（上位の顔ぶれが変わる）
STOP = {"まとめ", "よくある質問", "はじめに", "目次", "関連記事", "この記事", "監修", "注意", "こちら", "おわりに",
        "参考", "記事", "について", "とは", "ポイント", "方法", "解説"}


def norm(kw):
    return re.sub(r"[\s　]+", "", str(kw or "")).lower()


def path(site):
    return DIR / f"{site}.json"


def load(site):
    try:
        d = json.loads(path(site).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(site, d):
    p = path(site)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _own_domains():
    try:
        import sites
        return {str(c.get("domain") or "").lower().replace("www.", "") for c in sites.load_all().values()} - {""}
    except Exception:
        return set()


def _ours(url, own):
    m = re.match(r"https?://([^/]+)", str(url or ""))
    host = (m.group(1) if m else "").lower().replace("www.", "")
    return bool(host) and any(host == d or host.endswith("." + d) for d in own)


def terms(text):
    return {w.lower() for w in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{2,}", str(text or ""))
            if w not in STOP and len(w) <= 12}


def compact_headline(res, own=None):
    """見出しの応答を、並び（40字まで）と数だけにする。相手の URL・題・説明文は残さない"""
    own = _own_domains() if own is None else own
    d = (res or {}).get("data") or {}
    pages, seen = [], Counter()
    for it in (d.get("items") or [])[:PAGES_MAX]:
        m = it.get("metrics") or {}
        heads = [[str(h.get("level") or ""), re.sub(r"\s+", " ", str(h.get("text") or "")).strip()[:HEAD_MAX]]
                 for h in it.get("headlines") or [] if str(h.get("level") or "") in ("h2", "h3") and h.get("text")]
        pages.append({"pos": m.get("position"), "ours": _ours((it.get("page") or {}).get("url"), own),
                      "heads": heads[:HEADS_PER_PAGE], "n_heads": m.get("headlineCount"), "chars": m.get("wordCount")})
        for t in set().union(*[terms(h[1]) for h in heads]) if heads else ():
            seen[t] += 1                                   # 何ページの見出しに出たか（1ページで何度出ても1）
    sm = d.get("summary") or {}
    return {"pages": pages, "avg_heads": sm.get("averageHeadlineCount"), "avg_chars": sm.get("averageWordCount"),
            "head_terms": [[t, n] for t, n in seen.most_common(25) if n >= 2]}


def compact_cooccur(res):
    """[語, 本文に出たサイト数, 見出しに出たサイト数]。見出しに出たサイトが多い順（本文だけの語は「データ」「管理」の
    ような汎用の語が上位20サイト全部に出て、差が付かない。2026-10-09 の確認の呼び出しで19サイト全部が19だった）"""
    out = []
    for it in ((res or {}).get("data") or {}).get("items") or []:
        m = it.get("metrics") or {}
        w = str(it.get("word") or "").strip()
        if len(w) >= 2 and w not in STOP:
            out.append([w, m.get("siteCountTotal") or 0, m.get("siteCountHeading") or 0])
    out.sort(key=lambda x: (-x[2], -x[1]))
    return out[:COOC_MAX]


def compact_questions(rows):
    out = []
    for r in rows or []:
        q = str((r or {}).get("question") or "").strip() if isinstance(r, dict) else str(r)
        if q:
            out.append([q[:80], ((r.get("metrics") or {}) if isinstance(r, dict) else {}).get("relativeDemand")])
    return out[:Q_MAX]


def put(site, kw, why="", **parts):
    """語の記録を足す（取れた部分だけ上書き）。parts: headline / cooccur / questions（compact_* の形）"""
    parts = {k: v for k, v in parts.items() if v}
    if not parts:
        return False
    d = load(site)
    rec = d.get(norm(kw)) or {"kw": kw}
    rec.update(parts)
    rec["at"] = date.today().isoformat()
    if why:
        rec["why"] = why
    d[norm(kw)] = rec
    save(site, d)
    return True


def get(site, kw, stale_days=STALE_DAYS):
    rec = load(site).get(norm(kw))
    if not rec:
        return None
    try:
        if (date.today() - date.fromisoformat(rec.get("at", ""))).days > stale_days:
            return None
    except ValueError:
        return None
    return rec


def _head_lines(rec, pages=5):
    h = rec.get("headline") or {}
    out = []
    if h.get("head_terms"):
        out.append("  上位ページの見出しに共通して出る語（語: 出たページ数）: "
                   + "／".join(f"{t}:{n}" for t, n in h["head_terms"][:15]))
    rows = [p for p in h.get("pages") or [] if not p.get("ours") and p.get("heads")][:pages]
    for p in rows:
        out.append(f"  {p.get('pos')}位の見出しの並び: " + " → ".join(x[1] for x in p["heads"] if x[0] == "h2")[:300])
    if h.get("avg_heads"):
        out.append(f"  上位の平均: 見出し{h.get('avg_heads')}個・{h.get('avg_chars')}字（長さは成果を分けない。参考）")
    return out


def _cooc_line(rec):
    c = rec.get("cooccur") or []
    return ["  上位ページに共通して出る語（共起語・見出しに出たサイト数／本文に出たサイト数）: "
            + "／".join(f"{w}:{h}/{n}" for w, n, h in c[:25])] if c else []


def _q_lines(rec, n=10):
    q = rec.get("questions") or []
    return [f"  ・{x[0]}" for x in q[:n]]


def brief(site, kw):
    """執筆の指示に渡す行。記録が無ければ空"""
    rec = get(site, kw)
    if not rec:
        return []
    out = [f"■ 上位ページの調べ（ラッコ・{rec.get('at')} 時点・狙う語「{rec.get('kw')}」）"]
    hl = _head_lines(rec)
    if hl:
        out.append("【見出しの並び】構成の「共通60〜70%」の参考にする。上位の見出しの文をそのまま写さない（観点だけ使う）")
        out += hl
    cl = _cooc_line(rec)
    if cl:
        out.append("【共起語】主題に含まれる語だけ本文で扱う。語を並べるだけの文は書かない")
        out += cl
    ql = _q_lines(rec)
    if ql:
        out.append("【実際の質問】FAQ の候補。答えは記事の事実（site_brief の一次情報・公的な出典で確かめたこと）だけで書く。"
                   "質問に無い数字・確かめていない数字を答えに足さない。主題の外の質問は使わない")
        out += ql
    return out if len(out) > 1 else []


def article_meta(slug):
    """(社, 狙う語)。記事が無ければ (None, '')"""
    p = ROOT / "articles" / f"{slug}.md"
    try:
        t = p.read_text(encoding="utf-8-sig")
    except OSError:
        return None, ""
    m = re.search(r"^keyword:\s*[\"']?(.+?)[\"']?\s*$", t[:3000], re.M)
    c = re.search(r"^category:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", t[:3000], re.M)
    site = None
    if c:
        try:
            import sites
            site = sites.find_category_owner(c.group(1).strip())
        except Exception:
            site = None
    return site, (m.group(1).strip() if m else "")


def rewrite_brief(slug):
    """書き直しの指示に足す文（auto_rewrite の stuck・compete が読む）。記録が無ければ空"""
    site, kw = article_meta(slug)
    rec = get(site, kw) if site and kw else None
    if not rec:
        return ""
    lines = _head_lines(rec, pages=3) + _cooc_line(rec)
    q = _q_lines(rec, 6)
    if q:
        lines += ["  実際に聞かれている質問（FAQ の候補。答えは記事にある事実だけで書く。数字を足さない）:"] + q
    if not lines:
        return ""
    return ("\n上位ページの調べ（ラッコ・" + str(rec.get("at")) + " 時点・狙う語「" + str(rec.get("kw")) + "」）。"
            "この記事に無い観点のうち、主題に含まれるものだけ節を足す。上位の見出しの文を写さない:\n" + "\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", default="", help="サイトID")
    ap.add_argument("--kw", default="")
    ap.add_argument("--rewrite", default="", help="記事の slug")
    ap.add_argument("--list", default="", help="サイトID")
    a = ap.parse_args()
    if a.list:
        for k, r in sorted(load(a.list).items(), key=lambda x: x[1].get("at", ""), reverse=True):
            print(f"  {r.get('at')}  {r.get('kw')}  [{'見出し' if r.get('headline') else ''}"
                  f"{'・共起語' if r.get('cooccur') else ''}{'・質問' if r.get('questions') else ''}] {r.get('why', '')}")
        return 0
    if a.rewrite:
        s = rewrite_brief(a.rewrite)
        print(s or "  この記事の狙う語の調べはまだありません")
        print("KW_SERP=" + ("yes" if s else "none"))
        return 0
    if not a.brief or not a.kw:
        ap.error("--brief <site> --kw <語> / --rewrite <slug> / --list <site> のどれかを指定してください")
    lines = brief(a.brief, a.kw)
    print("\n".join(lines) if lines else f"  「{a.kw}」の上位ページの調べはまだありません（何もしない。無いものを型にしない）")
    print("KW_SERP=" + ("yes" if lines else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
