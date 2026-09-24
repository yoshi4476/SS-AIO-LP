# -*- coding: utf-8 -*-
"""配信先の公開済み記事を、いまのテンプレート・設定で全部描き直す（external-html 用）。

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


def main():
    import publish
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-sync", action="store_true", help="配信先を最新へ戻さず、手元の状態の上で描く")
    a = ap.parse_args()
    cfg = S.load(a.site)
    if cfg["type"] != "external-html":
        raise SystemExit(f"{a.site} は {cfg['type']}。この道具は external-html だけを扱います")
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
        if (meta.get("score") or 0) < 90:
            continue
        if not (dest / cfg["url_prefix"].strip("/") / meta["slug"] / "index.html").is_file():
            skipped.append(meta["slug"])           # まだ公開していない記事は触らない（publish の仕事）
            continue
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
