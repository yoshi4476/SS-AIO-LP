# -*- coding: utf-8 -*-
"""その日の運用が計画どおりかを機械判定する（3サイト共通・救済処理の入力になる）

使い方:
    python scripts/daily_audit.py            # 監査結果を表示
    python scripts/daily_audit.py --fix-kw   # KW残数が不足しているサイトを自動補充

判定するのは次の4点。いずれもLLMの目視ではなく数値で決める。
  1. 本数   — サイトごとに当日 DAILY_TARGET 本が公開されているか
  2. 品質   — build.py がBLOCKEDにしている記事がないか
  3. 領域   — 公開済み記事の本文が他サイトの担当領域を主題にしていないか
  4. 供給   — KW台帳の未着手が数日分を切っていないか

出力の最後に AUDIT_OK=yes/no と、直すべき項目を TODO: 行で並べる。
救済ワークフローはこの TODO: 行だけを読めばよい。
"""
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
DAILY_TARGET = 2       # 1サイトあたりの1日の公開本数
KW_MIN_DAYS = 4        # 未着手KWがこの日数分を切ったら補充する
PY = sys.executable


def today_iso():
    return date.today().isoformat()


def articles_by_site():
    """articles/*.md を category から担当サイト別に振り分ける"""
    cat2site = {c: sid for sid, cfg in sites_mod.load_all().items()
                for c in cfg.get("categories", {})}
    out = {sid: [] for sid in sites_mod.load_all()}
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue

        def fv(k):
            mm = re.search(rf"^{k}:\s*(.+?)\s*$", m.group(1), re.M)
            return mm.group(1).strip().strip('"') if mm else ""

        site = cat2site.get(fv("category"))
        if site:
            out[site].append({"slug": p.stem, "date": fv("date"), "score": fv("score"),
                              "title": fv("title"), "category": fv("category")})
    return out


def check_volume(todo):
    """当日の公開本数が目標に届いているか"""
    print(f"■ 本数（目標: 1サイト {DAILY_TARGET}本/日・{today_iso()}）")
    by_site = articles_by_site()
    for sid, arts in by_site.items():
        n = sum(1 for a in arts if a["date"] == today_iso())
        mark = "OK " if n >= DAILY_TARGET else "不足"
        print(f"  {mark} {sid:10s} 本日 {n}/{DAILY_TARGET}本  （累計 {len(arts)}本）")
        if n < DAILY_TARGET:
            todo.append(f"TODO: {sid} の記事を本日あと {DAILY_TARGET - n} 本作成して公開する")
    return by_site


def check_live(todo, by_site):
    """当日の記事が実際にHTTP 200で見られるか。

    articles/ にファイルがあることと、サイトで公開されていることは別。
    実際、補助金サイトへは納品先の取り違えで記事が届かないまま
    「公開済み」と数えていた期間があった。URLを叩いて確かめる。
    """
    import urllib.error
    import urllib.request
    print("\n■ 公開の実地確認（当日分のURLを実際に開く）")
    cfgs = sites_mod.load_all()
    checked = 0
    for sid, arts in by_site.items():
        for a in arts:
            if a["date"] != today_iso():
                continue
            meta = {"slug": a["slug"], "category": a.get("category", "")}
            url = sites_mod.article_url(cfgs[sid], meta)
            checked += 1
            try:
                r = urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=25)
                code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception:
                code = 0
            mark = "OK " if code == 200 else "未公開"
            print(f"  {mark} [{code or '接続不可'}] {url}")
            if code != 200:
                todo.append(f"TODO: {a['slug']} がサイトで見られない（{url}）。"
                            f"python scripts/publish.py --site {sid} --slug {a['slug']} --push "
                            "で配信し直す")
    if not checked:
        print("  （当日の記事がないため確認対象なし）")


def check_blocked(todo):
    """build.py が公開不可としている記事"""
    print("\n■ 品質ゲート（build.py）")
    r = subprocess.run([PY, "scripts/build.py"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="ignore")
    blocked = [ln for ln in (r.stdout or "").splitlines() if "BLOCKED(公開不可)" in ln]
    if not blocked:
        print("  OK  BLOCKEDなし")
        return
    for ln in blocked:
        print(f"  不合格 {ln.strip()}")
        slug = ln.split(":")[1].strip() if ":" in ln else "?"
        todo.append(f"TODO: {slug} を品質基準まで直して score を更新し、再ビルドする")


def check_territory(todo):
    """公開済み記事の主題が担当領域から外れていないか"""
    print("\n■ 担当領域（本文ベース）")
    import cannibal_check
    bad = cannibal_check.written_territory_check()
    for slug, site, invader, _ in bad:
        todo.append(f"TODO: {slug} は {invader} の領域。{site} から取り下げて"
                    f"{invader} へ配信し直し、旧URLを site/_redirects で301転送する")


def check_external_dup(todo):
    """配信先サイトに元からある記事との重複（移管前の記事は台帳にないため見落としやすい）"""
    print("
■ 配信先サイトの既存記事との重複")
    import cannibal_check
    for h in cannibal_check.external_dup_check():
        todo.append(f"TODO: {h['mine']['slug']} は {h['site']} の既存記事と重複"
                    f"（類似度{h['score']}・{h['theirs']['url']}）。"
                    "自作側を取り下げて既存記事へ301転送する")


def check_supply(todo, fix=False):
    """KW台帳の残数。2本/日だと供給が律速になるため、日次で見る"""
    print("\n■ KW供給（管制塔の台帳）")
    import hub_client
    if not hub_client.enabled():
        print("  ?   管制塔が未接続のため判定できません（HUB_URL未設定）")
        return
    per = {}
    for k in hub_client.all_kw():
        if (k.get("status") or "").strip() == "未着手":
            per[k.get("site") or "?"] = per.get(k.get("site") or "?", 0) + 1
    need = DAILY_TARGET * KW_MIN_DAYS
    for sid in sites_mod.load_all():
        n = per.get(sid, 0)
        days = n / DAILY_TARGET
        mark = "OK " if n >= need else "不足"
        print(f"  {mark} {sid:10s} 未着手 {n:3d}件（{days:.1f}日分）")
        if n < need:
            if fix:
                print(f"      → {sid} のKWを自動補充します")
                subprocess.run([PY, "scripts/kw_discover.py", "--site", sid, "--append"],
                               cwd=ROOT, text=True, encoding="utf-8", errors="ignore")
            else:
                todo.append(f"TODO: {sid} のKWを補充する"
                            f"（python scripts/kw_discover.py --site {sid} --append）")


def main():
    fix_kw = "--fix-kw" in sys.argv
    todo = []
    print(f"===== 日次監査 {today_iso()} =====\n")
    by_site = check_volume(todo)
    check_live(todo, by_site)
    check_blocked(todo)
    check_territory(todo)
    check_external_dup(todo)
    check_supply(todo, fix=fix_kw)

    print("\n===== 結果 =====")
    if not todo:
        print("AUDIT_OK=yes（本日の運用は計画どおりです）")
        return
    print("AUDIT_OK=no")
    for t in todo:
        print(t)


if __name__ == "__main__":
    main()
