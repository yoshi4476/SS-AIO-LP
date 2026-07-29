# -*- coding: utf-8 -*-
"""管制塔のKW台帳を、ローカルのKW計画と公開済み記事から初期化・同期する

使い方:
    python scripts/seed_hub.py            # 投入内容を表示するだけ
    python scripts/seed_hub.py --apply    # 管制塔へ投入する

各サイトの kw_plan（sites/*.json で指定）から「**〜**: KW / KW / …」形式の行を読み、
未登録のKWだけを台帳に追加する。既に記事がある分は「公開済み」として記録する。
何度実行しても重複しない（管制塔側で同一サイト・同一KWは無視される）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402
from cannibal_check import load_articles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def plan_keywords(plan_path):
    p = ROOT / plan_path
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+)$", line.strip())
        if not m:
            continue
        group = re.sub(r"（.*?）", "", m.group(1)).strip()
        for kw in m.group(2).split("/"):
            kw = kw.strip()
            if kw:
                out.append({"keyword": kw, "aim": group})
    return out


def published_map(cfg):
    """このサイトで既に公開済みの記事の一覧（KWとの突合用に本文メタを連結して持つ）"""
    if cfg["type"] != "self-static":
        return []  # 他サイトの既存記事はエンジン管理外のため触らない
    return [{"title": a["title"], "slug": a["slug"], "category": a["cat"],
             "text": f"{a['slug']} {a['title']} {a['desc']}"} for a in load_articles()]


def match_published(keyword, pubs):
    """KWの全単語を含む記事があれば公開済みとみなす（Dice類似度より確実）"""
    tokens = [t for t in re.split(r"[\s　]+", keyword) if t]
    for p in pubs:
        if all(tok in p["text"] for tok in tokens):
            return p
    return None


def main():
    apply_ = "--apply" in sys.argv
    if not hub_client.enabled():
        raise SystemExit("HUB_URL が未設定です（.env に設定してください）")

    for site_id, cfg in sites_mod.load_all().items():
        kws = plan_keywords(cfg.get("kw_plan", ""))
        pubs = published_map(cfg)
        # 公開済み記事とタイトルが近いKWは「公開済み」として登録する
        done, todo = [], []
        for k in kws:
            hit = match_published(k["keyword"], pubs)
            (done if hit else todo).append((k, hit))

        print(f"\n■ {cfg['name']}（{site_id}）")
        print(f"   計画KW {len(kws)}件 → 未着手 {len(todo)}件 / 公開済み {len(done)}件")
        for k, _ in todo[:5]:
            print(f"     - {k['keyword']}  ［{k['aim']}］")
        if len(todo) > 5:
            print(f"     …ほか{len(todo) - 5}件")

        if not apply_:
            continue

        if kws:
            r = hub_client.add_kw(site_id, [
                {"keyword": k["keyword"], "aim": k["aim"], "priority": "B"} for k in kws])
            print(f"   台帳へ追加: {r.get('added', 0)}件")
        for k, p in done:
            if not p:
                continue
            url = f"https://{cfg['domain']}/{p['category']}/{p['slug']}/"
            hub_client.publish_log(site=site_id, title=p["title"], keyword=k["keyword"],
                                   category=p["category"], url=url, note="既存記事の同期")
        if done:
            print(f"   公開済みとして記録: {len(done)}件")

    if not apply_:
        print("\n※ 確認モードです。実際に投入するには --apply を付けてください。")
    else:
        print("\n投入完了。python scripts/hub_client.py status で確認できます。")


if __name__ == "__main__":
    main()
