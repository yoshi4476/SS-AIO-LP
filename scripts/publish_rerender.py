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
    arts = kept_articles(cfg, [(m, b, p) for m, b, p in wp_bridge._site_articles(cfg) if m["slug"] in live])
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
            print(f"  × {shown(meta['slug'])}: {str(e)[:80] if shown(meta['slug']) == meta['slug'] else '止まりました'}")
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
        base, scfg, written, counts, hold = DF.stage(cfg), DF.stage_cfg(cfg), [], {}, []
        done = set(DF.load_index(cfg))
        for md in sorted((ROOT / "articles").glob("*.md")):
            if md.stem not in done:
                continue
            meta, body = publish.parse_article(md)
            if held(cfg, meta, body, md, None, counts, hold):     # publish.py が止める記事は送り直さない
                continue
            w, _ = publish.write_external_html(scfg, base, meta, body, md)
            written += w + [publish.stamp_manifest(cfg, base, meta, md)]
        report_held(counts, hold, f"描き直し {len(done) - len(hold)}本（{cfg['type']}）")
        # まとめのページ（比較表・テーマ・エリア・季節・多言語）も、いまの記事の並びで作り直して一緒に届ける
        agg, keep = publish.aggregate_for_files(cfg, base, force=True)
        if DF.deliver_batch(cfg, written + agg, base, a.push, "描き直し"):
            publish.aggregate_files_done(cfg, keep)
        return 0
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
    counts, hold = {}, []
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
        # publish.py が止める記事（入れてはいけない HTML・監修待ちなど）は、描き直しでも送らない
        if held(cfg, meta, body, md, dest, counts, hold):
            continue
        if nextjs:
            publish.write_nextjs_json(cfg, dest, meta, body)
        else:
            publish.write_external_html(cfg, dest, meta, body, md)
        publish.stamp_manifest(cfg, dest, meta, md)
        done.append(meta["slug"])
    report_held(counts, hold, f"描き直し {len(done)}本 / 未公開のため見送り {len(skipped)}本")
    # まとめのページ（比較表・テーマ・エリア・季節・多言語）も、いまの記事の並びで作り直す（同じコミットに入る）
    publish.aggregate_for_git(cfg, dest)
    st = subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True,
                        text=True, encoding="utf-8").stdout
    print(f"配信先で変わるファイル: {len([ln for ln in st.splitlines() if ln.strip()])}")
    if not a.push:
        print("押していません（--push で配信）")
        return 0
    # 変わらない回に commit すると git が「何も無い」で落ち、週次の工程ごと失敗していた
    if not st.strip():
        print("変更が無いので押しません")
        return 0
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
        # 押せなかった回を成功に見せない（rerender_watch が指紋を進めず、次の回にやり直す）
        return 1
    return 0


# ── 送り直す前の門（2026-10-20）。下に置くのは、配信の仕組みの表（data/capabilities.json）がこの道具の行番号を根拠にしているため ──

def shown(slug):
    """CI のログ（public）に出す記事の名前。お客様の記事は slug を出さない"""
    import private_store
    return private_store.shown(slug)


def redeliver_problems(cfg, meta, body, src, dest=None):
    """配信済みの記事を描き直して送り直す前に、publish.main と同じ門のうち記事の中身で決まるものを見る。止める理由の短い名前を返す
    （空なら送ってよい。名前には語・slug を入れない＝CI のログに出せる）。

    この道具は公開基準（gate_ok）しか見ずに全部を送り直していたので、main が止める記事（入れてはいけない HTML・景表法の文・
    衝突マーカー・監修待ち・お客様の記事に出せないもの・非公開のデータが読めない社）まで配信先へ届いた（2026-10-20 の点検）。
    検査そのものは main と同じ関数（legal_claims・gate_ok・editorial_review・operator_leaks・html_safety・pre_problems・
    foreign_links）を呼ぶ。publish.py を書き換えると配信の仕組みの表の根拠の行がずれるので、並びだけをここに写した。
    量産の指紋（scaled_guard）は main でも配信済みの記事には当てないので、ここでも見ない"""
    import json
    import re
    import deliver_files
    import editorial_review
    import html_safety
    import legal_claims
    import publish
    import sites as S
    out = []
    if re.search(r"^(<<<<<<< |>>>>>>> |=======\s*$)", body, re.M):     # publish.main と同じ衝突マーカー
        out.append("衝突マーカー")
    if legal_claims.find(Path(src).read_text(encoding="utf-8")):
        out.append("採択率・申請代行と読める文")
    if not publish.gate_ok(meta):
        out.append("公開基準未達")
    if not editorial_review.reviewed(meta["slug"]):
        out.append("監修待ち")
    if meta.get("category") not in cfg.get("categories", {}):
        out.append("カテゴリがその社に無い")
    if S.is_client(cfg["id"]):
        import private_store
        if not private_store.require(cfg["id"], "配信"):
            return out + ["非公開のデータなし"]
        text = f"{meta.get('title', '')}\n{meta.get('description', '')}\n" \
               f"{json.dumps(meta.get('faq') or [], ensure_ascii=False)}\n{body}"
        ng = [w for w in ((cfg.get("rules") or {}).get("ng_words") or [])
              if w and w in f"{meta.get('title', '')}{meta.get('description', '')}{body}"]
        if S.operator_leaks(text, cfg) or ng:
            out.append("お客様の記事に出せないもの")
        if (cfg.get("rules") or {}).get("review_before_publish") and meta["slug"] not in editorial_review.load():
            out.append("公開前の確認待ち")
    if html_safety.article_problems(meta, body, [cfg.get("domain")], raw=cfg["type"] == "external-md"):
        out.append("入れてはいけない HTML")
    if publish.pre_problems(cfg, meta, body):
        out.append("配信の途中で止まる形")
    files_type = cfg["type"] == "wordpress" or cfg["type"] in deliver_files.TYPES
    if publish.foreign_links(cfg, body, None if files_type else dest):
        out.append("その社に無い場所へのリンク")
    return out


def held(cfg, meta, body, md, dest, counts, slugs):
    """publish.py が止める記事なら True（数を理由ごとに足す）"""
    why = redeliver_problems(cfg, meta, body, md, dest)
    for w in why:
        counts[w] = counts.get(w, 0) + 1
    if why:
        slugs.append(shown(meta["slug"]))
    return bool(why)


def kept_articles(cfg, arts):
    """WordPress の公開済みの記事 [(meta, body, path)] のうち、送り直してよいもの（見送った数を出す）"""
    counts, hold = {}, []
    out = [(m, b, p) for m, b, p in arts if not held(cfg, m, b, p, None, counts, hold)]
    report_held(counts, hold)
    return out


def report_held(counts, slugs, head=""):
    """head（描き直した数の行）と、配信の門で見送った数（お客様の記事は slug を出さない）"""
    if head:
        print(head)
    if not slugs:
        return
    print(f"見送り {len(slugs)}本（publish.py が止める記事は送り直しません）: "
          + "・".join(f"{k} {v}本" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    names = sorted({s for s in slugs if s == s.strip("（）") and not s.startswith("（")})
    if names:
        print("   " + ", ".join(names[:8]) + (" ほか" if len(names) > 8 else ""))


if __name__ == "__main__":
    sys.exit(main())
