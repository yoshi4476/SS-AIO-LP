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
    # お客様の社の行は非公開の置き場に分けて書く（client_private.SPLIT_JSONL）。読むときに合わせる
    import client_private as CP
    return [json.loads(l) for l in CP.read_lines(RETRACT)]


def save(rows):
    import client_private as CP
    CP.save_jsonl(RETRACT, rows, owner=lambda r: r.get("site"))


def redirects_file(cfg, dest: Path):
    """_redirects の置き場。Next.js の静的書き出しは public/ 配下、静的サイトは直下（中身は site_files に1か所）"""
    import site_files
    return site_files.redirects_file(cfg, dest)


def apply(row, cfg, dest: Path):
    """配信先の作業コピーから記事を外し、301 を書く。触ったものの一覧を返す"""
    import publish
    import sites as S
    slug, touched = row["slug"], []
    for rel in (f"{cfg.get('content_dir', 'content')}/{slug}.json", f"{cfg.get('content_dir', 'content')}/{slug}.md"):
        f = dest / rel
        if f.is_file():
            f.unlink(); touched.append(rel)
    for d in (dest / publish.page_dir(cfg) / slug, dest / (cfg.get("images_dir") or "images") / slug,
              dest / "images" / "blog" / slug):
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
    # 転送は配信先のホストが読む形で書く（Cloudflare Pages の _redirects・Vercel の vercel.json・Netlify の
    # netlify.toml・Apache の .htaccess）。_redirects だけだと Cloudflare 以外の配信先では転送が効かなかった。
    # FTP・ZIP の社は deliver_files.retract が .htaccess に書く（ここは作業場所の索引を直すだけ）
    import site_files
    if cfg.get("type") not in ("ftp", "zip"):
        rd = site_files.add_redirect(cfg, dest, row["from"], row["to"], f"{row.get('reason', '取り下げ')}（{row['at']}）")
        if rd:
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
    rows = load()
    todo = [r for r in rows if not r.get("done_at") and (not a.site or r["site"] == a.site)]
    print(f"■ 配信先から外す記事: {len(todo)}件")
    if not todo:
        return 0
    by_site = {}
    for r in todo:
        by_site.setdefault(r["site"], []).append(r)
    # 1社の失敗（鍵が無い・相手が落ちている）で、ほかの社の分と済んだ印を失わない。済んだ印は最後に必ず書く
    try:
        for sid, items in by_site.items():
            try:
                _site(sid, items, a.push)
            except (SystemExit, Exception) as e:
                print(f"  [{_label(sid)}] 取り下げを続けられませんでした（次回また試します）: {type(e).__name__}")
    finally:
        save(rows)
    return 0


def _label(sid):
    """CI のログに出す社の名前。お客様の社は公開の id（社の id・ドメインは伏せる語。2.1 節）"""
    import sites as S
    try:
        return S.public_id(sid) if S.is_client(sid) else sid
    except Exception:
        return "（社）"


def _say(sid, r, text, detail=""):
    """1件の結果をログに出す。お客様の社は slug・URL を出さない（その回に取り下げた記事は伏せる語に無いことがある）"""
    import sites as S
    if S.is_client(sid):
        print(f"  [{_label(sid)}] （お客様の記事）: {text}")
    else:
        print(f"  [{sid}] {r['slug']}: {text}{detail}")


def _site(sid, items, do_push):
    import publish
    import sites as S
    cfg = S.load(sid)
    if cfg.get("type") in (None, "self-static"):
        for r in items:
            r["done_at"] = date.today().isoformat(); r["note"] = "自サイト（build.py が処理）"
        return
    if not do_push:
        for r in items:
            _say(sid, r, f"{r.get('reason', '')}", f"（{r['from']} → {r['to']}）")
        return
    # Git を使わない配信先（FTP・ZIP）は相手のサーバーを直接直す
    import deliver_files
    if cfg.get("type") in deliver_files.TYPES:
        if deliver_files.retract(cfg, items, True):
            for r in items:
                r["done_at"] = date.today().isoformat()
            print(f"  [{_label(sid)}] 取り下げ完了（{cfg['type']}・{len(items)}本）")
        return
    # WordPress: 先方の mu-plugin の転送表に301を足してから、記事を下書きに戻す（公開から外す）。
    # 転送元・転送先は台帳の組み立てたURLではなく、WordPress の実際のパーマリンクを使う。
    # 1件の失敗（接続・権限）で残りの件と済んだ印を失わないよう、1件ずつ受け止める
    if cfg.get("type") == "wordpress":
        import wp_bridge
        for r in items:
            try:
                found = publish._wp_call(cfg, f"posts?slug={r['slug']}&status=publish&_fields=id,link")
                found = found if isinstance(found, list) else []
                src = found[0].get("link") if found else r["from"]
                survivor = r.get("survivor") or r["to"].rstrip("/").rsplit("/", 1)[-1]
                dst = wp_bridge.post_link(cfg, survivor) or r["to"]
                n, rej = wp_bridge.add_redirects(cfg, [(src, dst)])
                if not n:
                    _say(sid, r, "転送を受け付けませんでした。次回また試します", f"（{rej}）")
                    continue
                for p in found:
                    publish._wp_call(cfg, f"posts/{p['id']}", {"status": "draft"})
            except (SystemExit, Exception) as e:
                _say(sid, r, f"転送を足せません（橋渡しが無い・古い・接続できない）。次回また試します: {type(e).__name__}")
                continue
            r["done_at"] = date.today().isoformat()
            r["note"] = f"下書きに戻し、{src} → {dst} を301で送る"
            _say(sid, r, "下書きに戻し、301で送りました", f"（{src} → {dst}）")
        # llms.txt から外した記事を消す（静的サイトで llms.txt の行を消すのと同じ）
        if any(r.get("done_at") for r in items):
            try:
                wp_bridge.push_settings(cfg)
            except (SystemExit, Exception):
                pass
        return
    dest = publish.ensure_clone(cfg, publish._push_token())
    for r in items:
        touched = apply(r, cfg, dest)
        _say(sid, r, f"{len(touched)}か所を直しました", f"（{r['from']} → {r['to']}: {', '.join(touched) or '変更なし'}）")
    if push(cfg, dest, f"統合した記事を外して301で送る（{len(items)}本）"):
        for r in items:
            r["done_at"] = date.today().isoformat()
        print(f"  [{_label(sid)}] push完了")
    else:
        print(f"  [{_label(sid)}] pushできませんでした（次回また試します）")


if __name__ == "__main__":
    sys.exit(main())
