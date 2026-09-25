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


def _is_published(a):
    """score>=90（公開基準）が付いた記事だけを「公開済み」として数える。

    score未設定の記事はまだPhase 5を通っておらず、publish.pyも配信を拒む
    （score<90はSystemExit）。それを「本日公開」に数えると、本数は満たしたと
    誤表示され、check_liveでは「公開したのに404」という偽の不具合を報告する。
    監修の記録が無い記事（HELD）も公開されていないので同じく数えない。
    """
    try:
        if int(a.get("score") or 0) < 90:
            return False
    except ValueError:
        return False
    global _REVIEWS
    if _REVIEWS is None:
        import editorial_review
        _REVIEWS = editorial_review.load()
    return a.get("slug") in _REVIEWS


_REVIEWS = None      # 監修の記録（1回の実行で1度だけ読む）


# 記事を公開する時刻（JST）。この時刻を過ぎていなければ、まだ無くて当然。
# GitHub Actions の定期実行は数時間ずれることがある。実際、21:30の救済が
# 翌03:07に走り、「本日0本」と見て6本を書こうとしてターン上限で落ちた
PUBLISH_HOURS = {"ai-lab": (8, 15), "corporate": (10, 17), "subsidy": (12, 19)}
GRACE_HOURS = 2      # 公開の時刻から、これだけ過ぎて無ければ不足とみなす


def _due_now(sid):
    """いまの時刻で、何本まで公開されているべきか"""
    import datetime
    jst = (datetime.datetime.now(datetime.timezone.utc)
           + datetime.timedelta(hours=9))
    hours = PUBLISH_HOURS.get(sid)
    if not hours:
        return DAILY_TARGET
    return sum(1 for h in hours if jst.hour >= h + GRACE_HOURS)


def check_volume(todo):
    """当日の公開本数が目標に届いているか（月の上限も見る）"""
    print(f"■ 本数（目標: 1サイト {DAILY_TARGET}本/日・上限 {MONTHLY_CAP}本/月・{today_iso()}）")
    by_site = {sid: [a for a in arts if _is_published(a)]
               for sid, arts in articles_by_site().items()}
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
        due = min(want, _due_now(sid))      # いまの時刻で在るべき本数
        mark = "OK " if n >= due else "不足"
        yet = "" if due >= want else f"（この時刻での期待は{due}本）"
        print(f"  {mark} {sid:10s} 本日 {n}/{want}本  今月 {month}/{MONTHLY_CAP}本"
              f"  （累計 {len(arts)}本）{yet}")
        # 公開の時刻より前に「不足」と言うと、救済が先回りして1日分を
        # まとめて書こうとする。時刻が来たぶんだけを不足として数える
        if n < due:
            todo.append(f"TODO: {sid} の記事を本日あと {due - n} 本作成して公開する")
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


def check_serp_overlap(todo, limit=5):
    """同じ検索語に自社の複数ページが出ていないか（公開後の食い合い）

    書く前の類似度検査では見つからない。似ていない記事どうしでも、
    同じ語で自社ページが並べば検索エンジンは評価先を決められず、どれも上がらない。
    """
    print()
    print("■ 同じ検索語での自社ページの食い合い")
    import cannibal_check
    try:
        hits = cannibal_check.serp_overlap()
    except Exception as e:
        print(f"  GSCから取得できません（{str(e)[:60]}）")
        return
    print(f"  {len(hits)}語")
    for h in hits[:limit]:
        drag = "・".join(f"{x[0]}({x[1]:.0f}位)" for x in h["drag"][:3])
        todo.append(f"TODO: 「{h['kw']}」で自社ページが競合（{h['site']}）。"
                    f"{h['win'][0]}({h['win'][1]:.0f}位)を勝たせ、{drag}から"
                    "その語の見出しを外して内部リンクを集約する")
    if len(hits) > limit:
        print(f"  （上位{limit}語だけTODOに出す。全体は "
              f"python scripts/cannibal_check.py --serp）")


def check_growth(todo):
    """表示・クリックが前の期間より落ちていないか

    落ちたその日に気づかないと、原因が重なって特定できなくなる。
    合計だけ見ても何を直せばいいか分からないので、消えた語と
    順位が下がった語に分解して出す。
    """
    print()
    print("■ 表示・クリックの推移（直近28日 vs その前）")
    import growth_guard
    try:
        alerts = growth_guard.main()
    except Exception as e:
        print(f"  GSCから取得できません（{str(e)[:60]}）")
        return
    for sid, di, lost, worse, pages in alerts or []:
        todo.append(f"TODO: {sid} の表示が前の期間より{abs(di) * 100:.0f}%落ちた。"
                    f"消えた語{lost}語・順位が下がった語{worse}語。"
                    f"まず {pages[0] if pages else '該当ページ'} が200を返すか確認する")


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
    # 失敗を握りつぶすと在庫0件と区別がつかない。実際、通信が一瞬切れただけで
    # 「全サイト在庫0」と出て、補充が必要だと誤解する状態になっていた。
    try:
        rows = hub_client.all_kw(strict=True)
    except Exception as err:
        print(f"  ?   管制塔から取得できず判定できません（{str(err)[:60]}）")
        return
    per = {}
    for k in rows:
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
        # ばらつきの数字だけだと、どのくらい偏っているかが伝わらない。
        # 実測で312本（92%）が5,000字台の1帯に固まっていたが、
        # 「ばらつき8%」という表示からはその状態が読み取れなかった
        import collections as _c
        band = _c.Counter((n // 1000) * 1000 for n in lens)
        top, n_top = band.most_common(1)[0]
        share = n_top / len(lens)
        print(f"  {'OK ' if share < 0.5 else '注意'} 最も多い帯 "
              f"{top:,}〜{top + 999:,}字 に {n_top}本（{share:.0%}）")
        if not ok or share >= 0.5:
            todo.append(f"TODO: 記事の長さが{top:,}字台に{share:.0%}集中している"
                        "（frontmatter の depth を quick/standard/deep で使い分けること。"
                        "手順や定義だけの語は quick で短く終える）")

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


def check_brand(todo):
    """指名検索の伸び。AIO型メディアの主指標。

    クリック率で測ると、AIO・SEO・MEOのような「検索結果で答えが済む」主題は
    構造上かならず低く出る。実測でAI集客ラボは順位相応のクリックの15%しか
    取れていなかったが、指名検索は28日で11→38表示（+245%）に伸びていた。
    引用でブランドを知った人が社名で検索し直す動きは、こちらに出る。
    """
    print("\n■ 指名検索（主指標）")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import brand_search as B
        d = B.collect(28)
    except Exception as e:
        print(f"  （取得できません: {str(e)[:40]}）")
        return
    ti = sum(v["cur"]["imp"] for v in d.values())
    pi = sum(v["prev"]["imp"] for v in d.values())
    tc = sum(v["cur"]["clicks"] for v in d.values())
    print(f"  {'OK ' if ti >= pi else '注意'} 合計 {pi}表示 → {ti}表示"
          f"（{B.growth(pi, ti)}）/ クリック{tc}回")
    for sid, v in d.items():
        mark = "OK " if v["cur"]["imp"] >= v["prev"]["imp"] else "注意"
        print(f"     {mark} {v['name'][:18]:<20} {v['prev']['imp']:>4} → "
              f"{v['cur']['imp']:<4} {B.growth(v['prev']['imp'], v['cur']['imp'])}")
    if ti < pi:
        todo.append("TODO: 指名検索が前期より減っている"
                    "（python scripts/brand_search.py --list で語を確認する）")


def check_unseen(todo):
    """公開したのに、検索にまったく出ていないページを拾う。

    書いて配信したところで満足すると、載っていないページが溜まる。
    実測で、公開30日以上たっても28日間まったく表示されないページが19件あった。
    コーポレートは sitemap の40%が表示ゼロだった。

    30日を境にするのは、それ未満なら「まだ評価が定まっていない」だけで、
    手を当てても意味がないため（CLAUDE.md 8.2 の基準に合わせる）。
    """
    import re as _re
    from datetime import date as _date, timedelta as _td
    print("\n■ 検索に出ていないページ")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import gsc_detail as _G
        sc = _G.client()
    except Exception as e:
        print(f"  （GSCに接続できないため確認できません: {str(e)[:40]}）")
        return
    end = _date.today() - _td(days=3)
    start = end - _td(days=27)
    # 記事はカテゴリで所属サイトが決まる。全サイトで全記事を照合すると
    # 1本を3回数えてしまうので、持ち主のサイトだけを見る
    mine = {}
    for p_ in (ROOT / "articles").glob("*.md"):
        t_ = p_.read_text(encoding="utf-8", errors="replace")
        d_ = _re.search(r"^date:\s*([0-9-]+)", t_, _re.M)
        c_ = _re.search(r"^category:\s*(.+)$", t_, _re.M)
        if not (d_ and c_):
            continue
        # 公開していない記事（score 90 未満・未採点）は検索に出なくて当然。数えると
        # 「公開したのに出ていない」と誤って報告し、無駄な再通知を促す
        s_ = _re.search(r"^score:\s*(\d+)", t_, _re.M)
        if not s_ or int(s_.group(1)) < 90:
            continue
        owner = sites_mod.find_category_owner(c_.group(1).strip())
        if owner:
            mine.setdefault(owner, []).append((p_.stem, d_.group(1), c_.group(1).strip()))

    total = 0
    for sid, cfg in sites_mod.load_all().items():
        rows = mine.get(sid, [])
        if not rows:
            continue
        try:
            seen = {r["keys"][0].rstrip("/") for r in
                    _G.q(sc, cfg["domain"], str(start), str(end), ["page"], 25000,
                         raise_errors=True)}
        except Exception as e:
            # 取れなかったのを「表示ゼロ」と数えると、全記事が未登録に見える
            print(f"  （{cfg['name'][:18]}: GSCから取得できず確かめられません: {str(e)[:40]}）")
            continue
        old = []
        for slug, dt, cat in rows:
            try:
                days = (_date.today() - _date.fromisoformat(dt)).days
            except ValueError:
                continue
            if days < 30:
                continue          # 評価が定まる前に手を当てても意味がない
            # サイトごとにURLの形が違う。どれかに当たれば「出ている」とみなす
            cands = {f"https://{cfg['domain']}/{cat}/{slug}",
                     f"https://{cfg['domain']}/blog/{slug}"}
            if not (cands & seen):
                old.append((days, slug))
        if old:
            total += len(old)
            old.sort(reverse=True)
            print(f"  注意 {cfg['name'][:18]}: 公開30日以上で表示ゼロ {len(old)}件"
                  f"（最長{old[0][0]}日）")
            for d_, s_ in old[:3]:
                print(f"         {d_}日 {s_[:44]}")
    if total:
        todo.append(f"TODO: 公開30日以上たっても検索に出ないページが{total}件ある"
                    "（python scripts/reindex.py で登録状況を確認して再通知する）")
    else:
        print("  OK  公開30日以上のページは、すべて検索に出ています")


def check_deploy(todo):
    """本番が手元のビルドと一致しているか。

    ワークフローが成功していてもデプロイだけ落ちることがある。
    実際、wrangler の依存の公開遅れでデプロイが3回とも失敗し、
    記事はコミット済みなのに本番が数日古いままだった。
    """
    print("\n■ 本番への反映")
    r = subprocess.run([PY, "scripts/deploy_check.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (r.stdout or "")
    for line in out.splitlines():
        if line.strip() and "DEPLOY_OK" not in line:
            print(f"  {line.strip()}")
    if "DEPLOY_OK=no" in out:
        todo.append("TODO: 本番が手元のビルドより古い。Deployワークフローを実行して反映する"
                    "（python scripts/deploy_check.py で差分を確認）")


# 同日救済が1回の実行で片づけるもの。ここに入らない指摘は「知らせるだけ」に回す。
# 全部を今日やらせると、記事1本目に着手する前にターン上限へ達する
# （実際、300ターン使って5本の記事が1本も書けずに落ちた）
TODAY = ("の記事を本日あと", "を品質基準まで直して", "の領域。", "の既存記事と重複",
         "がサイトで見られない", "のKWを補充する", "のKW補充が0件")

# 1回の実行で扱う上限。記事の作成がいちばん重く、他を積むと本数が埋まらない
MAX_TODAY = 8


def split_todo(todo):
    """「今日やること」と「知らせるだけ」に分ける。

    本数の不足を先頭に置く。ここが埋まらないと、翌日以降の積み上がりが
    遅れ続ける。カニバリの解消は1件が重く、週次の担当にする。
    """
    now = [t for t in todo if any(k in t for k in TODAY)]
    later = [t for t in todo if t not in now]
    now.sort(key=lambda t: 0 if "の記事を本日あと" in t else 1)
    return now[:MAX_TODAY], now[MAX_TODAY:] + later


def main():
    fix_kw = "--fix-kw" in sys.argv
    todo = []
    print(f"===== 日次監査 {today_iso()} =====\n")
    by_site = check_volume(todo)
    check_live(todo, by_site)
    check_blocked(todo)
    check_territory(todo)
    check_external_dup(todo)
    check_serp_overlap(todo)
    check_readability(todo)
    check_supply(todo, fix=fix_kw)
    check_scaled_risk(todo)
    check_tokens(todo)
    check_brand(todo)
    check_unseen(todo)
    check_deploy(todo)

    print("\n===== 結果 =====")
    if not todo:
        print("AUDIT_OK=yes（本日の運用は計画どおりです）")
        return
    now, later = split_todo(todo)
    print("AUDIT_OK=no" if now else "AUDIT_OK=yes（今日やることはありません）")
    for t in now:
        print(t)
    if later:
        print("\n--- 以下は今日やらないこと（週次で扱う / 知らせるだけ） ---")
        for t in later:
            print(t.replace("TODO:", "NOTE:", 1))


if __name__ == "__main__":
    main()
