# -*- coding: utf-8 -*-
"""統合で消した記事を、配信先（別リポジトリ）からも外し、301で送る。

auto_merge は手元の articles/ から記事を外すが、コーポレート・補助金の記事は
別リポジトリに配信済みで、そこに残ったままだと2本が出続ける（統合の意味が無い）。
data/retractions.jsonl に auto_merge が積み、ここが配信先を直して push する。

  python scripts/retract.py --pending           # 何をするか見る
  python scripts/retract.py --pending --push    # 配信先を直して push する
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
RETRACT = ROOT / "data" / "retractions.jsonl"


def load():
    if not RETRACT.is_file():
        return []
    return [json.loads(l) for l in RETRACT.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(rows):
    RETRACT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                       encoding="utf-8", newline="\n")


def redirects_file(cfg, dest: Path):
    """_redirects の置き場。Next.js の静的書き出しは public/ 配下、静的サイトは直下"""
    import publish
    f = publish._public_file(dest, "_redirects")
    if f:
        return f
    return dest / ("public" if (cfg.get("images_dir") or "").startswith("public/") else "") / "_redirects"


def apply(row, cfg, dest: Path):
    """配信先の作業コピーから記事を外し、301 を書く。触ったものの一覧を返す"""
    import publish
    import sites as S
    slug, touched = row["slug"], []
    for rel in (f"{cfg.get('content_dir', 'content')}/{slug}.json", f"{cfg.get('content_dir', 'content')}/{slug}.md"):
        f = dest / rel
        if f.is_file():
            f.unlink(); touched.append(rel)
    for d in (dest / "blog" / slug, dest / (cfg.get("images_dir") or "images") / slug, dest / "images" / "blog" / slug):
        if d.is_dir():
            shutil.rmtree(d); touched.append(str(d.relative_to(dest)))
    mp = publish.manifest_path(cfg, dest)
    if mp.is_file():
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        if slug in data:
            del data[slug]
            mp.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
            touched.append("article-manifest.json")
    url = f"https://{cfg['domain']}{row['from']}"
    sm = publish._public_file(dest, "sitemap.xml")
    if sm:
        t = sm.read_text(encoding="utf-8")
        u = re.sub(rf"\s*<url>\s*<loc>{re.escape(url)}</loc>.*?</url>", "", t, flags=re.S)
        if u != t:
            sm.write_text(u, encoding="utf-8", newline="\n"); touched.append("sitemap.xml")
    lt = publish._public_file(dest, "llms.txt")
    if lt:
        keep = [x for x in lt.read_text(encoding="utf-8").splitlines() if row["from"] not in x]
        if len(keep) != len(lt.read_text(encoding="utf-8").splitlines()):
            lt.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n"); touched.append("llms.txt")
    rd = redirects_file(cfg, dest)
    line = f"{row['from']} {row['to']} 301"
    cur = rd.read_text(encoding="utf-8") if rd.is_file() else "# Cloudflare Pages のリダイレクト定義\n"
    if line not in cur:
        rd.parent.mkdir(parents=True, exist_ok=True)
        rd.write_text(cur.rstrip("\n") + f"\n# {row.get('reason', '取り下げ')}（{row['at']}）\n{line}\n",
                      encoding="utf-8", newline="\n")
        touched.append(str(rd.relative_to(dest)))
    del S
    return touched


def push(cfg, dest: Path, msg):
    import publish
    token = publish._push_token()
    env = publish.git_auth(token)
    publish.run(["git", "config", "user.name", "AIO Pipeline Bot"], cwd=dest)
    publish.run(["git", "config", "user.email", "noreply@7senses.co.jp"], cwd=dest)
    publish.run(["git", "add", "-A"], cwd=dest)
    if not publish.run(["git", "status", "--porcelain"], cwd=dest):
        return True
    publish.run(["git", "commit", "-q", "-m", msg], cwd=dest)
    u = f"https://x-access-token@github.com/{cfg['repo']}.git"
    if publish.try_run(["git", "push", u, f"HEAD:{cfg['branch']}"], cwd=dest, env=env):
        return True
    # origin はトークン付きのURLで作ったクローン。認証を渡さないと fetch が必ず落ち、取り込み直しが効かない
    if (publish.try_run(["git", "fetch", "origin"], cwd=dest, env=env)
            and publish.try_run(["git", "rebase", f"origin/{cfg['branch']}"], cwd=dest)):
        return publish.try_run(["git", "push", u, f"HEAD:{cfg['branch']}"], cwd=dest, env=env)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", action="store_true", help="未処理の取り下げを対象にする")
    ap.add_argument("--site", default="")
    ap.add_argument("--push", action="store_true", help="配信先を直して push する")
    a = ap.parse_args()
    import publish
    import sites as S
    rows = load()
    todo = [r for r in rows if not r.get("done_at") and (not a.site or r["site"] == a.site)]
    print(f"■ 配信先から外す記事: {len(todo)}件")
    if not todo:
        return 0
    by_site = {}
    for r in todo:
        by_site.setdefault(r["site"], []).append(r)
    for sid, items in by_site.items():
        cfg = S.load(sid)
        if cfg.get("type") in (None, "self-static"):
            for r in items:
                r["done_at"] = date.today().isoformat(); r["note"] = "自サイト（build.py が処理）"
            continue
        if not a.push:
            for r in items:
                print(f"  [{sid}] {r['from']} → {r['to']}（{r.get('reason', '')}）")
            continue
        dest = publish.ensure_clone(cfg, publish._push_token())
        for r in items:
            touched = apply(r, cfg, dest)
            print(f"  [{sid}] {r['from']} → {r['to']}: {', '.join(touched) or '変更なし'}")
        if push(cfg, dest, f"統合した記事を外して301で送る（{len(items)}本）"):
            for r in items:
                r["done_at"] = date.today().isoformat()
            print(f"  [{sid}] push完了")
        else:
            print(f"  [{sid}] pushできませんでした（次回また試します）")
    save(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
