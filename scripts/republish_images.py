# -*- coding: utf-8 -*-
"""配信先で画像が 404 になっている記事だけを描き直し、画像ごと1コミットで押す。

publish.py は1本ごとに配信先を最新へ戻す（ensure_clone）ため、複数本をまとめて
押すにはここで同期を1回だけ行う。中身は publish.py と同じ関数だけを使う。

  python scripts/republish_images.py --site corporate --slugs a,b,c        # 描き直して差分を見る
  python scripts/republish_images.py --site corporate --slugs a,b,c --push
  python scripts/republish_images.py --site subsidy --missing --push       # 本番で eyecatch が 404 の記事を自動で選ぶ
"""
import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def missing_live(cfg, site_id):
    """本番で eyecatch が 404 の公開記事（その社のもの）"""
    import re
    import sites as S
    pre = publish_image_prefix(cfg)
    out = []
    for md in (ROOT / "articles").glob("*.md"):
        head = md.read_text(encoding="utf-8-sig")[:1500]
        cat = re.search(r"^category:\s*(\S+)", head, re.M)
        sc = re.search(r"^score:\s*(\d+)", head, re.M)
        if not cat or S.find_category_owner(cat.group(1)) != site_id or not sc or int(sc.group(1)) < 90:
            continue
        if not re.search(r"^eyecatch:", head, re.M):
            continue
        url = f"https://{cfg['domain']}{pre}/{md.stem}/eyecatch.png"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ss-aio-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = 0
        if code == 404:
            out.append(md.stem)
    return out


def publish_image_prefix(cfg):
    import publish
    return publish.image_prefix(cfg)


def main():
    import publish
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--slugs", default="")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    cfg = S.load(a.site)
    slugs = [s for s in a.slugs.split(",") if s]
    if a.missing:
        slugs += [s for s in missing_live(cfg, a.site) if s not in slugs]
    if not slugs:
        print("対象がありません")
        return 0
    token = publish._push_token()
    dest = publish.ensure_clone(cfg, token)
    done = []
    for slug in slugs:
        md = ROOT / "articles" / f"{slug}.md"
        if not md.is_file():
            print(f"   × 記事がありません: {slug}")
            continue
        meta, body = publish.parse_article(md)
        if cfg["type"] == "nextjs-json":
            publish.write_nextjs_json(cfg, dest, meta, body)
        elif cfg["type"] == "external-html":
            publish.write_external_html(cfg, dest, meta, body, md)
        else:
            print(f"   × 未対応の種別: {cfg['type']}")
            continue
        publish.stamp_manifest(cfg, dest, meta, md)
        done.append(slug)
        print(f"   ○ {slug}")
    st = subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True, text=True, encoding="utf-8").stdout
    print(f"描き直し {len(done)}本 / 配信先で変わるファイル {len([l for l in st.splitlines() if l.strip()])}")
    if not a.push:
        print("押していません（--push で配信）")
        return 0
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(["git", "-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                    "commit", "-q", "-m", f"画像が 404 だった記事{len(done)}本を画像ごと描き直す"], cwd=dest, check=True)
    env = publish.git_auth(token)
    r = subprocess.run(["git", "push", f"https://x-access-token@github.com/{cfg['repo']}.git", f"HEAD:{cfg['branch']}"],
                       cwd=dest, env=env, capture_output=True, text=True)
    print("push:", "OK" if r.returncode == 0 else "NG")
    if r.returncode != 0:
        print(r.stderr[-300:].replace(token or "@@", "***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
