# -*- coding: utf-8 -*-
"""本文のサイト間リンクに上限を設ける（2026-11-15 運用者の承認）

同じ会社が運営するサイトどうし（AI集客ラボ・コーポレート・補助金・お客様の社）が、記事の本文で
機械的にリンクし合うと、リンクの操作（Google のリンクスパムのポリシー）と見なされることがある。
今は少ないが、増えても気づけなかったため、新しい記事を公開の前に止め、既にある分は週次で知らせる。

  1. 1記事の本文に、他のサイトへのリンクは MAX_PER_ARTICLE 本まで
  2. 各サイトで、他のサイトへリンクする記事は全記事の MAX_SHARE まで

数えるのは記事の本文（原稿）のリンクだけ。ヘッダー・フッター・横の案内・著者欄はサイト共通の部品で、
記事ごとに AI が足すものではないので数えない（部品のリンクは運用者が画面を見て決める。リンクを減らさない決まり）。
止めるのは新しい記事だけ。公開済みのリンクは消さない（取れている評価まで失う）。

    python scripts/cross_links.py              # 各サイトの状態（週次・findings が呼ぶ）
    python scripts/cross_links.py <slug>       # 1本を公開してよいか
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
sys.path.insert(0, str(ROOT / "scripts"))

MAX_PER_ARTICLE = 1
MAX_SHARE = 0.20
URL = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _host(h):
    h = h.lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def domains():
    """{ドメイン: 社の id}。全サイト（お客様の社を含む）"""
    import sites as S
    return {_host(cfg["domain"]): sid for sid, cfg in S.load_all().items() if cfg.get("domain")}


def owner(meta):
    import sites as S
    return S.find_category_owner(str(meta.get("category") or ""))


def name(slug, sid=None):
    """ログに出す記事の名前。お客様の社の記事は slug を出さない（CI のログは public。守秘）"""
    import sites as S
    if sid is None:
        try:
            import client_private as CP
            sid = CP.owner_of_slug(slug)
        except Exception:
            sid = None
    if sid and S.is_client(sid):
        import hashlib
        return f"{S.public_id(sid)} の記事（{hashlib.sha1(slug.encode()).hexdigest()[:6]}）"
    return slug


def load(path):
    try:
        t = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    return (meta, m.group(2)) if isinstance(meta, dict) else None


def cross(body, own, doms):
    """本文のうち、他のサイトへのリンク（同じ社の id のドメインは数えない）の行き先の社の id の一覧"""
    out = []
    for h in URL.findall(body or ""):
        sid = doms.get(_host(h))
        if sid and sid != own:
            out.append(sid)
    return out


def corpus():
    """公開の対象になる全記事 {slug: (社の id, 他サイトへのリンクの数)}。公開の下限は rubric と同じ"""
    import rubric
    doms = domains()
    out = {}
    for p in sorted(ARTICLES.glob("*.md")):
        a = load(p)
        if not a:
            continue
        meta, body = a
        try:
            sc = float(meta.get("score") or 0)
        except (TypeError, ValueError):
            sc = 0
        if sc < rubric.PASS_TOTAL:
            continue
        sid = owner(meta)
        out[p.stem] = (sid, len(cross(body, sid, doms)))
    return out


def room(site_id, arts=None):
    """そのサイトの新しい記事が、他のサイトへのリンクを1本持ってよいか（持つと上限を超えるなら False）"""
    arts = arts if arts is not None else corpus()
    same = [n for sid, n in arts.values() if sid == site_id]
    return (sum(1 for n in same if n) + 1) / (len(same) + 1) <= MAX_SHARE


def check(slug, arts=None):
    """1本を公開してよいか。止める理由のリストを返す（空なら通す）"""
    a = load(ARTICLES / f"{slug}.md")
    if not a:
        return []
    meta, body = a
    sid = owner(meta)
    n = len(cross(body, sid, domains()))
    if not n:
        return []
    issues = []
    if n > MAX_PER_ARTICLE:
        issues.append(f"サイト間リンク: 本文に他のサイトへのリンクが{n}本（上限{MAX_PER_ARTICLE}本。"
                      "同じ会社のサイトどうしで機械的にリンクし合わない。読者に要る1本だけ残す）")
    arts = arts if arts is not None else corpus()
    same = {s: v for s, v in arts.items() if v[0] == sid and s != slug}
    linked = sum(1 for _sid, k in same.values() if k) + 1
    total = len(same) + 1
    if linked / total > MAX_SHARE:
        issues.append(f"サイト間リンク: 他のサイトへリンクする記事が、このサイトの{linked}/{total}本"
                      f"（{linked / total:.0%}・上限{MAX_SHARE:.0%}）になる。この記事の本文からは外す")
    return issues


def report():
    import sites as S
    arts = corpus()
    by = defaultdict(list)
    for slug, (sid, n) in arts.items():
        by[sid].append((slug, n))
    print(f"■ 本文のサイト間リンク（公開対象 {len(arts)}本。1記事{MAX_PER_ARTICLE}本・各サイト{MAX_SHARE:.0%}まで）\n")
    notes = []
    for sid in sorted(by, key=lambda x: str(x)):
        rows = by[sid]
        linked = [r for r in rows if r[1]]
        over = [r for r in rows if r[1] > MAX_PER_ARTICLE]
        share = len(linked) / len(rows)
        label = S.public_id(sid) if sid else "（所属不明）"
        print(f"  {label}: 他サイトへリンクする記事 {len(linked)}/{len(rows)}本（{share:.0%}）"
              f"・{MAX_PER_ARTICLE}本を超える記事 {len(over)}本")
        for slug, n in sorted(over, key=lambda r: -r[1])[:5]:
            print(f"    {n}本: {name(slug, sid)}")
        if share > MAX_SHARE:
            notes.append(f"参考: {label} は他サイトへリンクする記事が{share:.0%}（上限{MAX_SHARE:.0%}）。"
                         "新しい記事は公開前の門で止める")
        if over:
            notes.append(f"参考: {label} に、本文で他サイトへ{MAX_PER_ARTICLE}本を超えてリンクする記事が{len(over)}本。"
                         "公開済みのリンクは消さず、新しい記事は公開前の門で止める")
    print()
    for n in notes:
        print(n)
    # 公開済みは消さない・新しい記事は門で止めるので、人の手は要らない。参考として出すだけ
    print("CROSSLINK_OK=yes")
    return 0


def main(argv):
    if argv:
        bad = check(argv[0])
        for b in bad:
            print("要対応: " + b)
        print("CROSSLINK_OK=" + ("no" if bad else "yes"))
        return 1 if bad else 0
    return report()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
