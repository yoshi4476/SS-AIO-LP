# -*- coding: utf-8 -*-
"""サイト設定の読み込み（3サイト共通の入口）

sites/*.json を読み、どのサイトへ何を書くかの情報を提供する。
サイトを増やすときは sites/ にJSONを1つ足すだけでよい。

  python scripts/sites.py --ids   # 全社のID（空白区切り）。直しを全社に回すループはこれで回す
  python scripts/sites.py --own   # 自社のIDだけ（先方のアカウントの物に触る工程用）
"""
import json
import re
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


def is_client(site_id):
    """受託のクライアントか（data/clients/<id>/ がある）"""
    return bool(site_id) and (ROOT / "data" / "clients" / site_id).is_dir()


def group_of(site_id):
    """食い合いを見る相手。自社3サイトはドメインをまたいでも自社どうしで食い合うが、
    クライアントは別の会社。混ぜると、お客様の順位で自社の記事が止まり、その逆も起きる"""
    if is_client(site_id):
        return [site_id]
    return own_ids()


def group_key(site_id):
    """group_of の組の名前（管制塔へ渡す）。自社は 'own'、お客様はその社のID"""
    return site_id if is_client(site_id) else "own"


PREF = re.compile(r"(北海道|東京都|(?:京都|大阪)府|[^\s　都道府県0-9０-９]{2,3}県)")


def region_of(site_id):
    """その社の地域。kw_seeds.regions（拠点）、無ければ会社の住所の都道府県。
    KW台帳でお客様どうしが同じ語を持ったとき、地域が違えば両方使ってよいかを運用者が決める材料"""
    cfg = load_all().get(site_id) or {}
    regs = [r for r in (cfg.get("kw_seeds") or {}).get("regions") or [] if r]
    if regs:
        return "・".join(regs)
    p = (ROOT / "data" / "clients" / site_id / "company.json" if is_client(site_id)
         else ROOT / "data" / "company_profile.json")
    try:
        addr = json.loads(p.read_text(encoding="utf-8-sig")).get("address") or ""
    except (OSError, ValueError):
        return ""
    m = PREF.search(addr)
    return m.group(1) if m else ""


def kw_context():
    """KW台帳の重複判定に渡す組と地域（管制塔の GAS と hub_sheets が同じものを見る）"""
    ids = list(load_all())
    return {"groups": {s: group_key(s) for s in ids}, "regions": {s: region_of(s) for s in ids}}


# お客様の記事に出てはいけない運用会社の名前・場所。監修者・著者・実績として混ざると事実と違う記事になる
OPERATOR_MARKS = ("原口 優", "原口優", "セブンセンシズ", "SEVEN SENSES", "Seven Senses", "AI集客ラボ",
                  "G-ran", "7senses.co.jp")


def operator_leaks(text):
    """本文・題名に残った運用会社の名前と、自社サイトのカテゴリへの内部リンク（お客様のドメインでは404）"""
    import re
    hit = [m for m in OPERATOR_MARKS if m in (text or "")]
    cats = {c for sid in own_ids() for c in load(sid).get("categories", {})}
    for path in re.findall(r"""(?:\]\(|href=["'])(/[^)"'\s#?]*)""", text or ""):
        first = path.strip("/").split("/")[0]
        if first in cats:
            hit.append(f"自社サイトへのリンク {path}")
    return hit


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


def ids():
    """全社のID（自社＋お客様。雛形の sample は除く）。ワークフローのループはこれで回す。
    `for s in ai-lab corporate subsidy` と並べると、お客様の社には直しが回らない"""
    return [sid for sid in load_all() if sid != "sample"]


if __name__ == "__main__":
    import sys
    if "--ids" in sys.argv:
        print(" ".join(ids()))
    elif "--own" in sys.argv:
        print(" ".join(s for s in own_ids() if s != "sample"))
    else:
        print(summary())
