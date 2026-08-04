# -*- coding: utf-8 -*-
"""対象サイトの執筆ブリーフを1画面で出す（記事パイプラインの最初に実行する）

使い方: python scripts/site_brief.py corporate

サイトのテーマ・読者・担当領域・書いてはいけない領域・カテゴリ・次に書くKWをまとめて表示する。
記事を書くAIがサイト設定を探し回らずに済むようにし、担当領域の取り違えを防ぐのが目的。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def local_next_kw(cfg, limit=5):
    """管制塔が使えないときのフォールバック（KW計画ファイルから未執筆を拾う）"""
    import re
    from cannibal_check import load_articles
    plan = ROOT / cfg.get("kw_plan", "")
    if not plan.exists():
        return []
    corpus = [f"{a['slug']} {a['title']} {a['desc']}" for a in load_articles()]
    out = []
    for line in plan.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+)$", line.strip())
        if not m:
            continue
        aim = re.sub(r"（.*?）", "", m.group(1)).strip()
        for kw in m.group(2).split("/"):
            kw = kw.strip()
            if not kw:
                continue
            tokens = [t for t in re.split(r"[\s　]+", kw) if t]
            if any(all(t in doc for t in tokens) for doc in corpus):
                continue
            out.append({"keyword": kw, "aim": aim})
            if len(out) >= limit:
                return out
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/site_brief.py <site_id>\n" + sites_mod.summary())
    cfg = sites_mod.load(sys.argv[1])

    print("=" * 68)
    print(f"■ 対象サイト: {cfg['name']}（{cfg['id']}）")
    print(f"  ドメイン : {cfg['domain']}")
    print(f"  テーマ   : {cfg['theme']}")
    print(f"  読者     : {cfg.get('audience', '（未設定）')}")
    print("=" * 68)

    print("\n■ 書いてはいけない領域（他サイトの担当。主題にしない）")
    for a in cfg.get("avoid", []):
        print(f"  × {a}")

    print("\n■ 使えるカテゴリ（この中から必ず選ぶ）")
    for slug, name in cfg.get("categories", {}).items():
        print(f"  - {slug:14s} {name}")

    # 内部リンクの方針も設定で1か所に持つ。旧テーマの記事へリンクすると導線が逸れる
    pol = cfg.get("link_policy")
    if pol:
        print("\n■ 内部リンクの方針")
        print(f"  {pol}")

    cta = cfg.get("cta")
    if cta:
        print("\n■ 記事のCTA（この行き先で統一する）")
        print(f"  → {cta.get('label', '')}")
        if cta.get("note"):
            print(f"     {cta['note']}")

    print("\n■ 次に書くKW")
    nxt = hub_client.next_kw(cfg["id"])
    if nxt and nxt.get("keyword"):
        print(f"  → 「{nxt['keyword']}」")
        if nxt.get("aim"):
            print(f"     狙い: {nxt['aim']}")
        print(f"     台帳の残り: {nxt.get('remaining', '?')}件 / "
              f"補充要否: {'必要' if nxt.get('need_replenish') else '不要'}")
        print("  ※ 管制塔の台帳から取得（執筆開始時に「執筆中」へ変わります）")
    else:
        cands = local_next_kw(cfg)
        if not cands:
            print("  候補なし。python scripts/kw_discover.py --append でKWを補充すること")
        else:
            print(f"  → 「{cands[0]['keyword']}」（ローカルのKW計画から）")
            print(f"     狙い: {cands[0]['aim']}")
            for c in cands[1:]:
                print(f"     次点: {c['keyword']}")
        print("  ※ 管制塔が未接続のためローカルのKW計画を使用")

    print("\n■ 公開の流れ")
    if cfg["type"] == "self-static":
        print("  articles/<slug>.md に保存 → python scripts/publish_flow.py "
              f"{cfg['id']} <slug>")
    else:
        print(f"  articles/<slug>.md に保存 → python scripts/publish_flow.py {cfg['id']} <slug>")
        print(f"  （{cfg['repo']} の {cfg['branch']} へ配信されます）")
    print()


if __name__ == "__main__":
    main()
