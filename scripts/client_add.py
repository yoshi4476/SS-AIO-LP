# -*- coding: utf-8 -*-
"""クライアントのサイトを1件追加する（受託運用の初期設定）

sites/*.json を手で書くと項目の抜けに気づけず、記事を作り始めてから
「カテゴリが未定義」「担当領域が空でカニバリ検査が効かない」と分かる。
ヒアリングの回答をJSONで渡せば、必要な項目が揃った状態で作られる。

使い方:
    python scripts/client_add.py --template > client.json   # 記入用の雛形を出す
    python scripts/client_add.py client.json                # 内容を確認（書き込まない）
    python scripts/client_add.py client.json --write        # sites/ に追加する
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"

# ヒアリングシートの回答をそのまま入れられる形にしてある
TEMPLATE = {
    "id": "client-name",
    "name": "クライアント名 メディア名",
    "domain": "media.example.co.jp",
    "repo": "owner/repository",
    "branch": "main",
    "type": "external-html",
    "content_dir": "blog",
    "url_prefix": "/blog",
    "ga4_property_id": "",
    "kw_plan": "docs/kw-client-name.md",
    "theme": "何を扱うメディアか（1行）",
    "audience": "誰に向けたものか（1行）",
    "owns": ["自社が扱う語1", "自社が扱う語2"],
    "avoid": ["扱わない領域1（理由も書く）"],
    "categories": {"category-slug": "カテゴリ表示名"},
    "kw_seeds": {"industries": ["業種1", "業種2"], "intents": ["意図1", "意図2"]},
    "cta_title": "記事下CTAの見出し",
    "cta_desc": "記事下CTAの説明文",
    "cta": {"label": "ボタンの文言", "url": "https://example.co.jp/contact",
            "note": "補足（任意）"},
    "x_tags": ["SNS投稿に付けるタグ"],
}

REQUIRED = ["id", "name", "domain", "type", "theme", "audience",
            "owns", "categories", "kw_seeds"]
TYPES = {
    "self-static": "この管制塔リポジトリ内の静的サイト（build.py が公開する）",
    "nextjs-json": "Next.jsサイト。src/content/blog/<slug>.json を書き出す",
    "external-md": "別リポジトリの静的サイト。Markdownをそのまま置く",
    "external-html": "別リポジトリ。HTMLに変換して置く（相手のテンプレートを使う）",
}


def check(cfg):
    """記事を作り始める前に気づきたいことだけを見る"""
    ng, warn = [], []
    for k in REQUIRED:
        v = cfg.get(k)
        if not v:
            ng.append(f"{k} が空です")
    if cfg.get("type") not in TYPES:
        ng.append(f"type が不正です（{' / '.join(TYPES)}）")
    if cfg.get("type") != "self-static" and not cfg.get("repo"):
        ng.append("repo が空です（外部サイトは配信先リポジトリが要ります）")

    ids = {p.stem for p in SITES.glob("*.json")}
    if cfg.get("id") in ids:
        ng.append(f"id「{cfg['id']}」は既にあります")
    # 既存サイトとカテゴリ名がぶつかると、記事がどちらのサイトのものか決まらない
    for p in SITES.glob("*.json"):
        other = json.loads(p.read_text(encoding="utf-8-sig"))
        dup = set(cfg.get("categories", {})) & set(other.get("categories", {}))
        if dup:
            ng.append(f"カテゴリ {sorted(dup)} が {p.stem} と重複しています")
        if cfg.get("domain") == other.get("domain"):
            ng.append(f"ドメインが {p.stem} と同じです")

    seeds = cfg.get("kw_seeds", {})
    n = len(seeds.get("industries", [])) * len(seeds.get("intents", []))
    if n < 100:
        warn.append(f"kw_seeds の組み合わせが{n}通りしかありません"
                    "（業種×意図で200通り以上あるとKWが枯れにくい）")
    if not cfg.get("avoid"):
        warn.append("avoid が空です。他サイトとの territory 検査が効きません")
    if not cfg.get("ga4_property_id"):
        warn.append("ga4_property_id が空です。レポートの流入データが出ません")
    return ng, warn


def main():
    if "--template" in sys.argv:
        print(json.dumps(TEMPLATE, ensure_ascii=False, indent=2))
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/client_add.py <設定JSON> [--write]")
    cfg = json.loads(Path(args[0]).read_text(encoding="utf-8-sig"))

    print(f"■ {cfg.get('name', '（名称なし）')}（{cfg.get('id', '?')}）")
    print(f"    種別: {cfg.get('type')} … {TYPES.get(cfg.get('type'), '不明')}")
    print(f"    公開先: {cfg.get('domain')}{cfg.get('url_prefix', '')}")
    seeds = cfg.get("kw_seeds", {})
    print(f"    KWの起点: 業種{len(seeds.get('industries', []))} × "
          f"意図{len(seeds.get('intents', []))} = "
          f"{len(seeds.get('industries', [])) * len(seeds.get('intents', []))}通り")

    ng, warn = check(cfg)
    for m in ng:
        print(f"    × {m}")
    for m in warn:
        print(f"    ! {m}")
    if ng:
        raise SystemExit("\n  不備があるため追加しません。直してから再実行してください")

    if "--write" not in sys.argv:
        print("\n  確認のみ（--write を付けると sites/ に追加します）")
        return
    out = SITES / f"{cfg['id']}.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  作成: {out.relative_to(ROOT).as_posix()}")
    plan = ROOT / cfg.get("kw_plan", f"docs/kw-{cfg['id']}.md")
    if not plan.exists():
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(f"# {cfg['name']} KW計画\n\n"
                        f"対象: {cfg['audience']}\n\n"
                        "（kw_discover.py が自動補充します）\n", encoding="utf-8")
        print(f"  作成: {plan.relative_to(ROOT).as_posix()}")
    print("\n  次にやること")
    print("    1. python scripts/kw_discover.py --site " + cfg["id"] + " --append")
    print("    2. GA4とSearch Consoleにサービスアカウントを追加")
    print("    3. 配信先リポジトリに書き込めるかを token_check.py で確認")


if __name__ == "__main__":
    main()
