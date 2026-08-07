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
MONTHLY_CAP = 60       # 1サイトあたりの1か月の上限。31日ある月は2本/日で62本になり
                       # 上限を超える。同一ドメインへ短期に大量投入すると機械的な
                       # 生成と見なされる risk があるため、月単位で頭を打たせる
KW_MIN_DAYS = 8        # 未着手KWがこの日数分を切ったら補充する
KW_WARN_DAYS = 30      # この日数分を切ったら早期警戒（補充の井戸が枯れていないか見る）
                       # 週次補充まで最大7日空くため、4日分では次の補充を待てずに枯れる
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
    """当日の公開本数が目標に届いているか（月の上限も見る）"""
    print(f"■ 本数（目標: 1サイト {DAILY_TARGET}本/日・上限 {MONTHLY_CAP}本/月・{today_iso()}）")
    by_site = articles_by_site()
    ym = today_iso()[:7]
    for sid, arts in by_site.items():
        n = sum(1 for a in arts if a["date"] == today_iso())
        month = sum(1 for a in arts if a["date"][:7] == ym)
        left = MONTHLY_CAP - month
        if left <= 0:
            # 上限に達したら「不足」と言わない。言えば救済が走って超過する
            print(f"  上限 {sid:10s} 今月 {month}/{MONTHLY_CAP}本 — 今月はこれ以上公開しません")
            continue
        want = min(DAILY_TARGET, left)
        mark = "OK " if n >= want else "不足"
        print(f"  {mark} {sid:10s} 本日 {n}/{want}本  今月 {month}/{MONTHLY_CAP}本"
              f"  （累計 {len(arts)}本）")
        if n < want:
            todo.append(f"TODO: {sid} の記事を本日あと {want - n} 本作成して公開する")
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
    print("\n■ 配信先サイトの既存記事との重複")
    import cannibal_check
    for h in cannibal_check.external_dup_check():
        todo.append(f"TODO: {h['mine']['slug']} は {h['site']} の既存記事と重複"
                    f"（類似度{h['score']}・{h['theirs']['url']}）。"
                    "自作側を取り下げて既存記事へ301転送する")


def check_readability(todo, limit=3):
    """公開済み記事の読みやすさ（段落・文の長さ）を検査する。

    規定はあったが検査がなく、300字近い段落がそのまま公開されていた。
    全件を一度に直すと夜間の実行が終わらないため、悪い方から少しずつ直す。
    """
    print("\n■ 読みやすさ（段落・文の長さ）")
    bad = []
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        r = subprocess.run([PY, "scripts/score_check.py", p.stem], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        fails = [l for l in (r.stdout or "").splitlines()
                 if l.startswith("FAIL") and ("段落" in l or "1文" in l)]
        if fails:
            bad.append((p.stem, fails))
    print(f"  {len(bad)}本に超過あり（1晩に最大{limit}本ずつ直す）")
    for slug, fails in bad[:limit]:
        detail = " / ".join(f.split("|", 2)[-1].strip() for f in fails)
        print(f"  要修正 {slug}: {detail}")
        todo.append(f"TODO: {slug} の段落と文を短く分ける（{detail}）。"
                    "本文の意味は変えず、区切りだけを直すこと")


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
        # サジェスト由来の候補は有限で、掘り尽くすと補充が0件になる。
        # 8日分を切ってから気づいても手が打てないため、30日分の時点で知らせる。
        if need <= n < DAILY_TARGET * KW_WARN_DAYS:
            todo.append(f"TODO: {sid} のKW在庫が残り{days:.0f}日分"
                        f"（kw_seeds を広げるか、GSCの実データ取得を有効にすること）")
        if n < need:
            if fix:
                print(f"      → {sid} のKWを自動補充します")
                r = subprocess.run([PY, "scripts/kw_discover.py", "--site", sid, "--append"],
                                   cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="ignore")
                out = (r.stdout or "") + (r.returncode and (r.stderr or "") or "")
                m = re.search(r"管制塔の台帳へ (\d+)件を追加しました", out)
                added = int(m.group(1)) if m else 0
                print(f"      補充結果: {added}件を台帳へ追加")
                # 0件のまま放置すると在庫が静かに枯れる。実際に補助金サイトで起きた。
                # 監査を不合格にして、通知とエラーログに必ず乗せる。
                if added == 0:
                    todo.append(f"TODO: {sid} のKW補充が0件だった"
                                f"（sites/{sid}.json の kw_seeds を広げるか、"
                                "台帳・サジェストの取得を確認する）")
                    for line in out.splitlines():
                        if "警告" in line or "中止" in line:
                            print(f"      {line}")
            else:
                todo.append(f"TODO: {sid} のKWを補充する"
                            f"（python scripts/kw_discover.py --site {sid} --append）")


def check_scaled_risk(todo):
    """量産と見なされる兆候を見る（新規記事だけを積み続けていないか）

    スケーラブルコンテンツ濫用の判定は本数ではなく「1本ずつに独自の価値があるか」。
    実運用のサイトは、新規と同時に既存記事の改善が動く。新規しか動いていない状態は
    その逆の signal になるため、順位データからリライト候補を出して手当てを促す。
    """
    import json
    import statistics
    print("\n■ 量産リスクの兆候")

    # 1) 文字数の均一さ。全記事が同じ長さだと機械生成の指紋になる
    lens = []
    for p_ in (ROOT / "articles").glob("*.md"):
        t = p_.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if m:
            lens.append(len(re.sub(r"\s|<[^>]+>", "", m.group(2))))
    if len(lens) >= 10:
        cv = statistics.pstdev(lens) / statistics.mean(lens)
        ok = cv >= 0.15   # ばらつきが15%未満なら不自然
        print(f"  {'OK ' if ok else '注意'} 文字数のばらつき {cv:.0%}"
              f"（{min(lens):,}〜{max(lens):,}字）")
        if not ok:
            todo.append("TODO: 記事の文字数が均一すぎる"
                        "（frontmatter の depth を quick/standard/deep で使い分けること）")

    # 2) リライトの実施状況。新規だけが積み上がる状態を検知する
    rd = ROOT / "data" / "ranks"
    cand = 0
    for cfg in sites_mod.load_all().values():
        f = rd / f"{cfg['id']}.json"
        if not f.is_file():
            continue
        hist = json.loads(f.read_text(encoding="utf-8"))
        if hist:
            cand += len([r for r in hist[sorted(hist)[-1]] if 11 <= r["pos"] <= 30])
    if cand:
        print(f"  ―   リライト候補 {cand}件（11〜30位）")
        todo.append(f"TODO: リライト候補が{cand}件ある。新規記事と並行して"
                    "上位の数本を改善する（python scripts/rank_track.py で一覧）")
    else:
        print("  ―   リライト候補なし（順位データが未取得か、該当なし）")


def check_tokens(todo):
    """SNSトークンの期限。切れてから気づくと、その間の配信が丸ごと落ちる"""
    import json
    print("\n■ SNSトークンの期限")
    f = ROOT / "data" / "token_state.json"
    if not f.is_file():
        print("  ―   記録なし（期限のあるトークンは未設定）")
        return
    from datetime import datetime, timezone
    for key, v in json.loads(f.read_text(encoding="utf-8")).items():
        exp = v.get("expires_at")
        if not exp:
            continue
        left = (datetime.fromisoformat(exp) - datetime.now(timezone.utc)).days
        mark = "OK " if left > 14 else "注意"
        print(f"  {mark} {key:22s} 残り{left}日")
        if left <= 14:
            todo.append(f"TODO: {key} の期限が残り{left}日"
                        "（python scripts/refresh_tokens.py で更新する）")


def main():
    fix_kw = "--fix-kw" in sys.argv
    todo = []
    print(f"===== 日次監査 {today_iso()} =====\n")
    by_site = check_volume(todo)
    check_live(todo, by_site)
    check_blocked(todo)
    check_territory(todo)
    check_external_dup(todo)
    check_readability(todo)
    check_supply(todo, fix=fix_kw)
    check_scaled_risk(todo)
    check_tokens(todo)

    print("\n===== 結果 =====")
    if not todo:
        print("AUDIT_OK=yes（本日の運用は計画どおりです）")
        return
    print("AUDIT_OK=no")
    for t in todo:
        print(t)


if __name__ == "__main__":
    main()
