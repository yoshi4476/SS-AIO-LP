# -*- coding: utf-8 -*-
"""監修の記録。**監修したと表示する記事は、監修した記録がある記事だけにする。**

記事には「監修: 代表取締役 原口 優」と出し、構造化データの editor にも入れている。
記録が無いまま表示すると、確認していない記事にも監修が付いて見える。
大量に公開するサイトほど、表示と実態の食い違いは信頼の問題として見られる
（Google のスパムポリシー「大量生成コンテンツの悪用」は品質の実態を見る）。

記録の無い新しい記事は build.py と publish.py が公開しない（HELD・監修待ち）。
公開済みを後から外すことはしない。

    python scripts/editorial_review.py --pending                 # 監修待ちの一覧（週次の findings が呼ぶ）
    python scripts/editorial_review.py --notify                  # 通知に足す分だけ（日次の記事CIが findings.txt へ）
    python scripts/editorial_review.py --approve slug1 slug2     # 確認した記事を記録する
    python scripts/editorial_review.py --approve-all-pending     # 監修待ちを全部記録する（全部読んだとき）
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "editorial_reviews.jsonl"
REVIEWER = "原口 優"
JST = timezone(timedelta(hours=9))


def load():
    out = {}
    if LEDGER.is_file():
        for ln in LEDGER.read_text(encoding="utf-8-sig").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("slug"):
                out[r["slug"]] = r
    return out


# 承認の記録を公開の条件にするか。監修者が全記事を確認しているため、毎日の承認操作は求めない
# （2026-09-26 運用者の判断）。承認制に戻すときはここを True にするだけで、
# build・publish・配信・日次監査・リンク補充のすべてが記録を見る形に戻る
REQUIRED = False


_SITE = {}


def _head(slug):
    try:
        return (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")[:3000]
    except OSError:
        return ""


def site_of(slug):
    """記事のサイト（カテゴリの持ち主）。build・配信が記事ごとに何度も聞くので覚えておく"""
    if slug not in _SITE:
        m = re.search(r"^category:\s*(\S+)", _head(slug), re.M)
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import sites
            _SITE[slug] = sites.find_category_owner(m.group(1)) if m else None
        except SystemExit:
            _SITE[slug] = None
    return _SITE[slug]


def client_requires(site_id):
    """公開前の確認を「要」にしたお客様か（sites/<id>.json の rules.review_before_publish）"""
    if not site_id:
        return False
    import sites
    return sites.is_client(site_id) and bool(((sites.load_all().get(site_id) or {}).get("rules") or {})
                                             .get("review_before_publish"))


def needs_review(slug):
    """その記事に確認の記録が要るか。全体の REQUIRED か、公開前の確認を「要」にしたお客様の記事"""
    return REQUIRED or client_requires(site_of(slug))


def reviewed(slug, recs=None):
    if not needs_review(slug):
        return True
    return slug in (recs if recs is not None else load())


def record(slugs, by=REVIEWER, note=""):
    have = load()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    new = [s for s in slugs if s not in have]
    if not new:
        return 0
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as f:
        for s in new:
            f.write(json.dumps({"slug": s, "by": by, "at": now, **({"note": note} if note else {})},
                               ensure_ascii=False) + "\n")
    return len(new)


def reviewer_for(slug):
    """その記事の監修者。お客様のサイトの記事なら、サイト設定の review_by（その社のサイトが出す監修の表示と同じ並び。
    CONFLUX は「YW（CONFLUX PARTNERS）・セブンセンシズ株式会社」）、無ければ company.json の監修者"""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import sites
        t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")[:3000]
        m = re.search(r"^category:\s*(\S+)", t, re.M)
        sid = sites.find_category_owner(m.group(1)) if m else None
        if sid and sites.is_client(sid):
            names = [n for n in (sites.load_all().get(sid) or {}).get("review_by") or [] if n]
            if names:
                return "・".join(names)
            import private_store
            c = private_store.read_json(sid, "company.json", {}) or {}
            return (c.get("supervisor") or {}).get("name") or f"{sid} の監修者"
    except (OSError, ValueError):
        pass
    return REVIEWER


def _score(path):
    m = re.search(r"^score:\s*([0-9.]+)", path.read_text(encoding="utf-8-sig")[:3000], re.M)
    return float(m.group(1)) if m else 0.0


def _delivered(site_id):
    """配信済みの一覧（ftp・zip の delivered.json）。確認を「要」に変える前に出した記事を待ちに数えない"""
    try:
        return set(json.loads((ROOT / "data" / "clients" / site_id / "delivered.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def pending():
    """公開の基準（90点）を満たしたのに監修の記録が無い記事（全体の REQUIRED と、確認を「要」にしたお客様の記事）"""
    recs = load()
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.stem in recs or not needs_review(p.stem) or _score(p) < 90:
            continue
        sid = site_of(p.stem)
        if not REQUIRED and p.stem in _delivered(sid):
            continue
        out.append(p.stem)
    return out


def _repo_url():
    """原稿を開くURLの土台（CI は GITHUB_REPOSITORY、手元は origin）"""
    import os
    import subprocess
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        try:
            u = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
            m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", u)
            repo = m.group(1) if m else ""
        except (OSError, subprocess.SubprocessError):
            repo = ""
    branch = os.environ.get("GITHUB_REF_NAME", "") or "master"
    return f"https://github.com/{repo}/blob/{branch}/articles/" if repo else ""


def held_by_site(today=None):
    """確認を「要」にしたお客様の、確認待ちの記事を社ごとに。{site: [{slug, title, days, draft, url}]}"""
    import sites
    today = today or datetime.now(JST).date()
    base = _repo_url()
    out = {}
    for slug in pending():
        sid = site_of(slug)
        if not client_requires(sid):
            continue
        head = _head(slug)
        t = re.search(r"^title:\s*(.+)$", head, re.M)
        d = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", head, re.M)
        days = (today - datetime.strptime(d.group(1), "%Y-%m-%d").date()).days if d else None
        cfg = sites.load(sid)
        m = re.search(r"^category:\s*(\S+)", head, re.M)
        out.setdefault(sid, []).append({
            "slug": slug, "title": (t.group(1).strip().strip("'\"") if t else slug), "days": days,
            "draft": f"{base}{slug}.md" if base else f"articles/{slug}.md",
            "url": sites.article_url(cfg, {"slug": slug, "category": m.group(1) if m else ""})})
    return out


APPROVE_HOW = ("承認: 原稿を読んで問題が無ければ、GitHub の Actions →「監修の記録」（approve-review.yml）を開き、"
               "slug を空白区切りで入れて実行（または python scripts/editorial_review.py --approve <slug>）。"
               "記録すると配信と公開の後の手順まで進みます")


def notify_lines(held=None):
    """findings.txt に足す本文（日次の記事CIがメールで届ける）。社ごとに1行の要対応と明細"""
    held = held_by_site() if held is None else held
    if not held:
        return []
    import sites
    lines = []
    for sid, items in sorted(held.items()):
        name = (sites.load_all().get(sid) or {}).get("name") or sid
        longest = max((i["days"] or 0) for i in items)
        lines.append(f"要対応: 公開前の確認待ち — {name}（{sid}）{len(items)}本（最長{longest}日待ち）")
        for i in items[:10]:
            wait = "" if i["days"] is None else f" {i['days']}日待ち"
            lines.append(f"   - {i['slug']}「{i['title']}」{wait} 原稿: {i['draft']} / 公開予定: {i['url']}")
        if len(items) > 10:
            lines.append(f"   …ほか{len(items) - 10}本（python scripts/editorial_review.py --pending）")
    lines.append("   " + APPROVE_HOW)
    return lines


def main():
    a = sys.argv[1:]
    if "--approve" in a:
        slugs = [x for x in a[a.index("--approve") + 1:] if not x.startswith("--")]
        miss = [s for s in slugs if not (ROOT / "articles" / f"{s}.md").is_file()]
        if miss:
            raise SystemExit("原稿が見つかりません: " + ", ".join(miss))
        # お客様の記事の監修者はお客様ご本人。当社の代表の名前で記録しない
        by = {s: reviewer_for(s) for s in slugs}
        n = sum(record([s], by=by[s]) for s in slugs)
        print(f"  記録しました: {n}本（監修: {' / '.join(sorted(set(by.values())))}）")
        return 0
    if "--approve-all-pending" in a:
        # お客様の記事が混ざる（公開前の確認を「要」にした社）。監修者は記事ごとに決める
        p = pending()
        n = sum(record([s], by=reviewer_for(s)) for s in p)
        print(f"  記録しました: {n}本（監修: {' / '.join(sorted({reviewer_for(s) for s in p})) or REVIEWER}）")
        return 0
    held = held_by_site()
    mine = [s for s in pending() if not client_requires(site_of(s))]
    own_line = (f"要対応: 監修待ちが{len(mine)}本あります。確認したら "
                "python scripts/editorial_review.py --approve <slug> で記録すると公開されます") if mine else ""
    if "--notify" in a:
        # 日次の記事CIが findings.txt に足す分だけを出す（メールの本文になる）。
        # 枠は1日40回走るので、--site でその枠の社の分だけにする（全社分だと同じ一覧が日に40通届く）
        only = a[a.index("--site") + 1] if "--site" in a and a.index("--site") + 1 < len(a) else ""
        if only:
            import sites
            held = {k: v for k, v in held.items() if k == only}
            if only not in sites.own_ids():
                own_line = ""
        if own_line:
            print(own_line + "（GitHub の Actions →「監修の記録」から slug を入れて実行）")
        for ln in notify_lines(held):
            print(ln)
        return 0
    print(f"■ 監修待ち: {len(mine)}本（記録の無い記事は公開されません）")
    for s in mine[:30]:
        print(f"  - {s}")
    if own_line:
        print(own_line)
    for ln in notify_lines(held):
        # 週次の findings は「  - 」で始まる行を明細として拾う
        print(ln.replace("   - ", "  - ", 1) if ln.startswith("   - ") else ln)
    print("REVIEW_OK=" + ("no" if mine or held else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
