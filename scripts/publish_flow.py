# -*- coding: utf-8 -*-
"""記事1本を公開まで通す（画像生成 → 品質ゲート → 配信 → 管制塔へ記録）

使い方: python scripts/publish_flow.py <site_id> <slug> [--no-push]

サイトごとの違い（静的HTML / Next.js / 別リポジトリ）は publish.py が吸収するため、
パイプラインからは常にこのスクリプトを呼べばよい。
"""
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import md2html  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(args, check=True):
    print(f"$ {' '.join(str(a) for a in args)}")
    r = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", errors="ignore")
    if check and r.returncode != 0:
        raise SystemExit(f"失敗: {' '.join(str(a) for a in args)}")
    return r.returncode


def main():
    if len(sys.argv) < 3:
        raise SystemExit("使い方: python scripts/publish_flow.py <site_id> <slug> [--no-push]")
    site_id, slug = sys.argv[1], sys.argv[2]
    push = "--no-push" not in sys.argv
    cfg = sites_mod.load(site_id)

    src = ROOT / "articles" / f"{slug}.md"
    if not src.exists():
        raise SystemExit(f"記事が見つかりません: {src}")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", src.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        raise SystemExit("フロントマターがありません")
    meta, body = yaml.safe_load(m.group(1)), m.group(2)

    # 0. カテゴリ検証（他サイトのカテゴリが混入するとbuild.pyが黙って除外し、
    #    記事が公開されないまま放置される。ここで即座に落として書き直させる）
    cat = (meta.get("category") or "").strip()
    valid = sites_mod.valid_categories(cfg)
    if cat not in valid:
        owner = sites_mod.find_category_owner(cat)
        hint = f"「{cat}」は {owner} のカテゴリです。" if owner else f"「{cat}」はどのサイトにもありません。"
        raise SystemExit(
            f"categoryが不正です。{hint}\n"
            f"{src} のフロントマター category: を次のどれかに直して再実行すること\n"
            + "\n".join(f"  - {s}  （{sites_mod.category_name(cfg, s)}）" for s in valid))

    # 0-2. 担当領域の検査（カテゴリが正しくても、他サイトの話題を書いていれば止める）
    import cannibal_check
    invader, scores = cannibal_check.article_territory(meta.get("title", ""), body, site_id)
    if invader:
        raise SystemExit(
            f"担当領域を越えています。この記事の主題は {invader}"
            f"（{sites_mod.load(invader)['domain']}）の領域です。\n"
            f"  領域スコア: {scores}\n"
            f"  {cfg['name']} では「{'／'.join(cfg.get('avoid', ['—'])[:2])}」を主題にできません。\n"
            "  対処: この記事を取り下げて別のKWで書き直すか、"
            f"python scripts/publish_flow.py {invader} {slug} で正しいサイトへ配信すること")

    # 0-2-2. カニバリ検査（配信の入口で止める）
    #        領域検査はあったがカニバリ検査が無く、業種名だけ差し替えた同型記事が
    #        繰り返し公開されていた。監査で見つけて後から直す運用では追いつかない。
    _pairs = [x for x in cannibal_check.find_pairs(cannibal_check.load_articles())
              if slug in (x["a"]["slug"], x["b"]["slug"])]
    if _pairs:
        w = _pairs[0]
        other = w["b"] if w["a"]["slug"] == slug else w["a"]
        raise SystemExit(
            f"既存記事と重複しています（類似度 {w['score']}）。\n"
            f"  相手: {other['slug']}「{other['title']}」\n"
            f"  タイトル類似 {w['title_sim']} / H2構成の重なり {w['h2_overlap']}\n"
            "  対処: タイトルとH2を、その業種・対象読者にしか当てはまらない切り口へ変える。\n"
            "        業種名だけを差し替えた構成は、量産の痕跡として評価を下げる")

    # 0-3. 月の上限（監査だけでは止まらない。配信の入口で頭を打たせる）
    #      同一ドメインへ短期に大量投入すると、機械的な生成と見なされる risk がある。
    import daily_audit
    _ym = str(meta.get("date", ""))[:7] or datetime.now().strftime("%Y-%m")
    _n = sum(1 for a in daily_audit.articles_by_site().get(site_id, [])
             if a["date"][:7] == _ym and a["slug"] != slug)
    if _n >= daily_audit.MONTHLY_CAP:
        raise SystemExit(
            f"{site_id} は今月すでに {_n} 本公開しており、上限 "
            f"{daily_audit.MONTHLY_CAP} 本/月に達しています。\n"
            "  来月まで待つか、scripts/daily_audit.py の MONTHLY_CAP を見直してください")

    # 1. 画像（アイキャッチ・図解）
    run([PY, "scripts/make_images.py", slug], check=False)

    # 2. 機械採点18項目（全PASSが公開条件）
    if run([PY, "scripts/score_check.py", slug], check=False) != 0:
        raise SystemExit("機械採点で不合格。指摘を直してから再実行すること")

    score = meta.get("score") or 0
    if score < 90:
        raise SystemExit(f"score={score} のため公開しません（90点以上が必要）")

    # 3. 配信（サイト種別ごとの出口）
    if cfg["type"] == "self-static":
        run([PY, "scripts/build.py"])
        run([PY, "scripts/notify_indexnow.py"], check=False)
        run([PY, "scripts/notify_indexing.py"], check=False)
    else:
        args = [PY, "scripts/publish.py", "--site", site_id, "--slug", slug]
        if push:
            args.append("--push")
        run(args)

    # 4. 本当に公開されたかを確認する。
    #    pushが通ってもビルドが落ちれば記事は出ない。実際、配信先のビルドが停止していたのに
    #    こちらは「push完了」を成功として扱い、記事が消えていることに気づけなかった。
    url = sites_mod.article_url(cfg, meta)
    # 自リポジトリのサイト（ai-lab）は、この後にワークフローがコミット＆デプロイする。
    # ここで公開を確認しにいくと、まだ出ていないため必ず失敗する。
    # 当日中の公開確認は daily_audit の check_live が担当する。
    if push and cfg["type"] != "self-static":
        import verify_publish
        since = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        ok, msgs = verify_publish.verify(site_id, slug, since)
        for m in msgs:
            print(f"  {m}")
        if not ok:
            hub_client.error_log(site_id, "publish",
                                 f"{slug}: 配信したが公開を確認できず / " + " / ".join(msgs))
            raise SystemExit(
                "配信しましたが公開が確認できません。管制塔のエラーログに記録しました。\n"
                "  台帳は『公開済み』にしていません（未公開のまま公開済みと記録しないため）。\n"
                f"  確認: python scripts/verify_publish.py --site {site_id} --slug {slug}")

    # 5. 管制塔へ記録（公開を確認できたものだけを『公開済み』として残す）
    html, _ = md2html.convert(body)
    hub_client.publish_log(
        site=site_id, title=meta["title"], keyword=meta.get("keyword", ""),
        category=meta["category"], score=score, chars=len(md2html.plain_text(html)),
        url=url)

    # 6. SNSへ投稿（認証が無ければ黙ってスキップする。公開そのものは止めない）
    run([PY, "scripts/post_social.py", site_id, slug], check=False)

    print(f"\n公開完了: {url}（score {score}）")


if __name__ == "__main__":
    main()
