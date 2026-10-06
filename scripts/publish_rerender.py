# -*- coding: utf-8 -*-
"""配信先の公開済み記事を、いまのテンプレート・設定で全部描き直す（external-html・nextjs-json・ftp・zip・WordPress）。

**なぜ要るか**: テンプレートやサイト設定（CTAの文言・導線）を変えても、
publish_changed は「原稿が変わった記事」しか配信しない。既存の記事は古い
描き方のまま残り、変えた効果が何か月も測れない。

publish.py は1本ごとに配信先を最新へ戻す（ensure_clone）ため、1本ずつ回すと
前の1本が消える。ここでは同期を1回だけ行い、公開済みの記事を全部描き直し、
1つのコミットで押す。中身は publish.py と同じ関数だけを使う。
新しい描き方をここに書かない。

  python scripts/publish_rerender.py --site subsidy          # 描き直して差分の数を見る
  python scripts/publish_rerender.py --site subsidy --push   # 配信先へ commit + push
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def rerender_wordpress(cfg, push):
    """WordPress: 公開済みの記事（先方に公開されている slug）を、いまの描き方で全部送り直す。
    1本ずつ REST で更新するので、同期・コミットは要らない。公開していない記事は触らない（publish の仕事）"""
    import publish
    import wp_bridge
    live = wp_bridge.url_map(cfg)
    arts = [(m, b, p) for m, b, p in wp_bridge._site_articles(cfg) if m["slug"] in live]
    print(f"描き直し {len(arts)}本（WordPress・公開済みのもの）")
    if not push:
        print("送っていません（--push で配信）")
        return 0
    ng = 0
    for meta, body, md in arts:
        try:
            if not publish.write_wordpress(cfg, meta, body, md, push=True):
                ng += 1
        except SystemExit as e:
            ng += 1
            print(f"  × {meta['slug']}: {str(e)[:80]}")
    print(f"送り直し {len(arts) - ng}本 / 失敗 {ng}本")
    # 業種のまとめ・用語集のページと llms.txt も、いまの記事の並びで作り直す
    try:
        for n in wp_bridge.sync_pages(cfg):
            print(n)
        wp_bridge.push_settings(cfg)
    except SystemExit as e:
        print(f"要対応: {cfg['id']} の橋渡しに届きません（{str(e)[:80]}）")
    return 1 if ng else 0


def main():
    import publish
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-sync", action="store_true", help="配信先を最新へ戻さず、手元の状態の上で描く")
    a = ap.parse_args()
    cfg = S.load(a.site)
    import deliver_files as DF
    if cfg["type"] in DF.TYPES:
        # FTP・ZIP は配信済みの一覧（delivered.json）の記事だけを、1回の接続・1つの ZIP で描き直す
        base, scfg, written = DF.stage(cfg), DF.stage_cfg(cfg), []
        done = set(DF.load_index(cfg))
        for md in sorted((ROOT / "articles").glob("*.md")):
            if md.stem not in done:
                continue
            meta, body = publish.parse_article(md)
            if not publish.gate_ok(meta):
                continue
            w, _ = publish.write_external_html(scfg, base, meta, body, md)
            written += w + [publish.stamp_manifest(cfg, base, meta, md)]
        print(f"描き直し {len(done)}本（{cfg['type']}）")
        DF.deliver_batch(cfg, written, base, a.push, "描き直し")
        return
    if cfg["type"] == "wordpress":
        return rerender_wordpress(cfg, a.push)
    # Next.js の社も、本文HTML込みのJSONを描いて置く方式なので、描き方（監修の表示・画像の置き場）を
    # 変えたら描き直しが要る。external-html だけを扱っていたため、変えても既存記事に届かなかった
    if cfg["type"] not in ("external-html", "nextjs-json"):
        raise SystemExit(f"{a.site} は {cfg['type']}。この道具は external-html・nextjs-json・ftp・zip・WordPress を扱います")
    nextjs = cfg["type"] == "nextjs-json"
    token = publish._push_token()
    dest = (publish.WORK / cfg["id"]) if a.no_sync else publish.ensure_clone(cfg, token)
    done, skipped = [], []
    for md in sorted((ROOT / "articles").glob("*.md")):
        try:
            meta, body = publish.parse_article(md)
        except Exception:
            continue
        if S.find_category_owner(meta.get("category", "")) != a.site:
            continue
        if not publish.gate_ok(meta):          # 観点の足切りまで見る（build.py と同じ）
            continue
        page = (dest / cfg["content_dir"] / f"{meta['slug']}.json" if nextjs
                else dest / publish.page_dir(cfg) / meta["slug"] / "index.html")
        if not page.is_file():
            skipped.append(meta["slug"])           # まだ公開していない記事は触らない（publish の仕事）
            continue
        if nextjs:
            publish.write_nextjs_json(cfg, dest, meta, body)
        else:
            publish.write_external_html(cfg, dest, meta, body, md)
        publish.stamp_manifest(cfg, dest, meta, md)
        done.append(meta["slug"])
    print(f"描き直し {len(done)}本 / 未公開のため見送り {len(skipped)}本")
    st = subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True,
                        text=True, encoding="utf-8").stdout
    print(f"配信先で変わるファイル: {len([ln for ln in st.splitlines() if ln.strip()])}")
    if not a.push:
        print("押していません（--push で配信）")
        return
    # 変わらない回に commit すると git が「何も無い」で落ち、週次の工程ごと失敗していた
    if not st.strip():
        print("変更が無いので押しません")
        return
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(["git", "-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                    "commit", "-q", "-m", f"記事{len(done)}本を、いまのテンプレートと設定で描き直す"],
                   cwd=dest, check=True)
    env = publish.git_auth(token)
    auth_url = f"https://x-access-token@github.com/{cfg['repo']}.git"
    r = subprocess.run(["git", "push", auth_url, f"HEAD:{cfg['branch']}"], cwd=dest, env=env,
                       capture_output=True, text=True)
    print("push:", "OK" if r.returncode == 0 else "NG")
    if r.returncode != 0:
        print(r.stderr[-400:].replace(token or "@@", "***"))


if __name__ == "__main__":
    main()
