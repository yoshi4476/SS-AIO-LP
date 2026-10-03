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


def primary():
    """自前でビルドするサイト。無ければ並び順の先頭。

    レポートの出力先や記事の帰属を決めるのに使う。ここにサイトIDを
    直接書くと、別の会社へ移したときに存在しないサイトを指したまま動く。
    """
    all_ = load_all()
    for sid, cfg in all_.items():
        if cfg.get("type") == "self-static":
            return sid
    return next(iter(all_), "")


def own_ids():
    """運用会社が自分で運営しているサイトのID（受託のクライアントは data/clients/<id>/ がある）。
    ('ai-lab', 'corporate', 'subsidy') と直書きすると、移植先では存在しないサイトを回して
    毎朝0のまま空振りした（2026-08-24）。クライアントを混ぜると自社の数字が他社の記事に出る"""
    return [sid for sid in load_all() if not (ROOT / "data" / "clients" / sid).is_dir()]


def load(site_id):
    all_ = load_all()
    if site_id not in all_:
        raise SystemExit(f"サイト設定が見つかりません: {site_id}（候補: {', '.join(all_)}）")
    return all_[site_id]


def article_url(cfg, meta):
    """公開後のURLを組み立てる"""
    prefix = cfg.get("url_prefix")
    url = (f"https://{cfg['domain']}{prefix}/{meta['slug']}/" if prefix
           else f"https://{cfg['domain']}/{meta['category']}/{meta['slug']}/")
    # Next.js の配信先（コーポレート）は末尾スラッシュ無しが正。付けると毎回308の転送が1回挟まる（2026-10-03）
    return url if cfg.get("trailing_slash", True) else url.rstrip("/")


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
