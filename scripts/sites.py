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

# お客様の社（client: true）の sites/<公開の id>.json に置くのは、社が特定できない3項目だけ（2026-10-10 運用者の指示
# 「会社名・住所…が公開されないように」）。公開の id は社名から推測できない文字列（private_store.new_public_id）。
# 社名・ドメイン・配信先・カテゴリ・戦略の部分は全部、非公開のリポジトリの clients/<社の id>/site_private.json に置き、
# load_all がそこから読む（public_id で公開の id と結ぶ）。公開の印は枠の割り当て（site_order）を、非公開のデータが
# 取れない回も同じにするために残す（門 gates_history_h76・h77 が守る）
PUBLIC_KEYS = ("id", "client", "daily_articles")


def split_public(cfg):
    """サイト設定を (公開してよい項目, 非公開の項目) に分ける"""
    pub = {k: v for k, v in cfg.items() if k in PUBLIC_KEYS}
    priv = {k: v for k, v in cfg.items() if k not in PUBLIC_KEYS and k != "_path"}
    return pub, priv


def _raw(site_id):
    try:
        return json.loads((SITES_DIR / f"{site_id}.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _private_clients():
    """非公開の置き場にあるお客様の社の設定 {公開の id: 設定}"""
    import private_store
    out = {}
    for sid in private_store.known_clients():
        cfg = private_store.site_private(sid)
        if cfg.get("domain"):
            cfg = dict(cfg, id=cfg.get("id") or sid)
            out[cfg.get("public_id") or cfg["id"]] = cfg
    return out


def load_all():
    """全社の設定 {社の id: 設定}。お客様の社は非公開の置き場の設定（社の id で引く）。非公開のデータが取れない回は、
    お客様の社は入らない（公開の印だけでは名前もドメインも無く、工程が動かせない。記事の枠は private_store.require で止まる）"""
    out = {}
    priv = None
    for p in sorted(SITES_DIR.glob("*.json")):
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
        if cfg.get("client") and set(cfg) <= set(PUBLIC_KEYS):
            priv = _private_clients() if priv is None else priv
            full = priv.get(cfg["id"])
            if not full:
                continue
            stub = cfg
            cfg = dict(full, client=True, public_id=stub["id"])
            if "daily_articles" in stub:
                cfg["daily_articles"] = stub["daily_articles"]
        cfg["_path"] = p.as_posix()
        out[cfg["id"]] = cfg
    return out


def resolve(site_id):
    """公開の id（sites/<id>.json のお客様の印の名前）を社の id にする。分からなければそのまま返す"""
    if site_id and _raw(site_id).get("client"):
        for sid, cfg in load_all().items():
            if cfg.get("public_id") == site_id:
                return sid
    return site_id


def public_id(site_id):
    """社の id の公開の名前（コミットの文・ジョブの間の受け渡し・ログに使う）。自社はそのまま"""
    return (load_all().get(site_id) or {}).get("public_id") or site_id


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
    return [sid for sid in load_all() if not is_client(sid)]


def is_client(site_id):
    """受託のクライアントか。sites/<id>.json の "client": true（公開側に残す印）か、data/clients/<id>/ がある社。
    材料を非公開のリポジトリへ移した後は data/clients/<id>/ が CI に無いので、印で決める（無いと自社と判定され、
    お客様の順位・語が public に書かれる）"""
    if not site_id:
        return False
    if _raw(site_id).get("client") or (ROOT / "data" / "clients" / site_id).is_dir():
        return True
    import private_store
    return private_store.client_path(site_id, "site_private.json").is_file()


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
    if is_client(site_id):
        import private_store
        addr = (private_store.read_json(site_id, "company.json", {}) or {}).get("address") or ""
    else:
        try:
            addr = json.loads((ROOT / "data" / "company_profile.json").read_text(encoding="utf-8-sig")).get("address") or ""
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


def operator_leaks(text, cfg=None):
    """本文・題名に残った運用会社の名前と、自社サイトのカテゴリへの内部リンク（お客様のドメインでは404）。

    cfg の operator_ok に書いた語（運用者がその社にだけ許した当社の表記）は、外してから見る。
    お客様の社は「ラクシフトAIは、セブンセンシズ株式会社が提供しています」と書いてよい（2026-10-08 運用者の決定）。
    許すのは書いた語そのものだけで、代表者名・社名の略・AI集客ラボ・当社のドメインは止める"""
    import re
    text = text or ""
    for ok in (cfg or {}).get("operator_ok") or []:
        if ok:
            text = text.replace(ok, "")
    hit = [m for m in OPERATOR_MARKS if m in text]
    cats = {c for sid in own_ids() for c in load(sid).get("categories", {})}
    for path in re.findall(r"""(?:\]\(|href=["'])(/[^)"'\s#?]*)""", text):
        first = path.strip("/").split("/")[0]
        if first in cats:
            hit.append(f"自社サイトへのリンク {path}")
    return hit


def load(site_id):
    all_ = load_all()
    if site_id not in all_:
        site_id = resolve(site_id)          # 公開の id で呼ばれたとき（記事の枠のジョブの間の受け渡し）
    if site_id not in all_:
        if _raw(site_id).get("client"):
            # お客様の社の印はあるが、非公開の設定が読めない（鍵の権限が無い CI など）。工程を止めて要対応で知らせる
            import private_store
            private_store.require_or_exit(site_id, "工程")
        raise SystemExit(f"サイト設定が見つかりません: {site_id}（候補: {', '.join(public_id(s) for s in all_)}）")
    return all_[site_id]


def article_url(cfg, meta):
    """公開後のURLを組み立てる"""
    # WordPress はパーマリンク設定が URL を決めるので、組み立てる前に先方へ聞く。
    # wp_bridge.article_url はこの関数を呼ぶため、循環しない post_link だけを使う
    if cfg.get("type") == "wordpress":
        try:
            import wp_bridge
            link = wp_bridge.post_link(cfg, meta["slug"])
        except Exception:
            link = ""
        if link:
            return link
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
        if is_client(cid):              # お客様の社は名前もドメインもテーマも CI のログに出さない（公開の id だけ）
            lines.append(f"{c.get('public_id') or cid:10s} {'（お客様）':22s} {c.get('type', ''):14s}")
            continue
        lines.append(f"{cid:10s} {c['domain']:22s} {c['type']:14s} {c.get('theme', '')}")
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
