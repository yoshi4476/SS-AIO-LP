# -*- coding: utf-8 -*-
"""サイト設定の読み込み（3サイト共通の入口）

sites/*.json を読み、どのサイトへ何を書くかの情報を提供する。
サイトを増やすときは sites/ にJSONを1つ足すだけでよい。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES_DIR = ROOT / "sites"


def load_all():
    out = {}
    for p in sorted(SITES_DIR.glob("*.json")):
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
        cfg["_path"] = p.as_posix()
        out[cfg["id"]] = cfg
    return out


def load(site_id):
    all_ = load_all()
    if site_id not in all_:
        raise SystemExit(f"サイト設定が見つかりません: {site_id}（候補: {', '.join(all_)}）")
    return all_[site_id]


def article_url(cfg, meta):
    """公開後のURLを組み立てる"""
    prefix = cfg.get("url_prefix")
    if prefix:
        return f"https://{cfg['domain']}{prefix}/{meta['slug']}/"
    return f"https://{cfg['domain']}/{meta['category']}/{meta['slug']}/"


def category_name(cfg, slug):
    return cfg.get("categories", {}).get(slug, slug)


def valid_categories(cfg):
    return list(cfg.get("categories", {}).keys())


def find_category_owner(slug):
    """そのカテゴリを持つサイトを返す（他サイトのカテゴリ混入を指摘するため）"""
    for cid, cfg in load_all().items():
        if slug in cfg.get("categories", {}):
            return cid
    return None


def summary():
    lines = []
    for cid, c in load_all().items():
        lines.append(f"{cid:10s} {c['domain']:22s} {c['type']:14s} {c['theme']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
