# -*- coding: utf-8 -*-
"""カニバリゼーション（検索意図の重複）を機械検出する

使い方: python scripts/cannibal_check.py

タイトル・説明文・H2見出しの文字バイグラム類似度で、既存記事どうしの重複を検出する。
形態素解析ライブラリなしで日本語の意図重複を判定するため、文字2-gramのDice係数を使う。
KW選定時の重複回避（kw_status.py）からも本モジュールの関数を利用する。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WARN = 0.50   # これ以上で「要確認」
STRONG = 0.62  # これ以上で「統合を検討」
_NOISE = re.compile(r"[\s　【】\[\]（）()「」『』・、。,.!?！？|｜:：/／〜~\-—+*#\"']")


def bigrams(text):
    t = _NOISE.sub("", str(text)).lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def dice(a, b):
    """2つの文字列の文字バイグラムDice係数（0〜1。1が完全一致）"""
    x, y = bigrams(a), bigrams(b)
    if not x or not y:
        return 0.0
    return 2 * len(x & y) / (len(x) + len(y))


def load_articles():
    arts = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.groups()

        def fv(k):
            mm = re.search(rf"^{k}:\s*(.+?)\s*$", fm, re.M)
            return mm.group(1).strip('"') if mm else ""

        arts.append({
            "slug": p.stem, "title": fv("title"), "desc": fv("description"),
            "cat": fv("category"),
            "h2": [h.strip() for h in re.findall(r"^##\s+(.+?)\s*$", body, re.M)],
        })
    return arts


def h2_overlap(a, b):
    """H2見出しの重なり率（構成レベルの重複度）"""
    if not a["h2"] or not b["h2"]:
        return 0.0
    hits = sum(1 for x in a["h2"] if any(dice(x, y) >= 0.6 for y in b["h2"]))
    return hits / min(len(a["h2"]), len(b["h2"]))


def find_pairs(arts):
    pairs = []
    for i in range(len(arts)):
        for j in range(i + 1, len(arts)):
            a, b = arts[i], arts[j]
            ttl = dice(a["title"], b["title"])
            dsc = dice(a["desc"], b["desc"])
            ov = h2_overlap(a, b)
            score = max(ttl, (ttl + dsc) / 2, ov * 0.9)
            if score >= WARN:
                pairs.append({"a": a, "b": b, "score": round(score, 2),
                              "title_sim": round(ttl, 2), "h2_overlap": round(ov, 2)})
    return sorted(pairs, key=lambda p: -p["score"])


def cross_site_check():
    """全サイト横断の重複検査。

    同じ会社が運営する複数サイトが同じ検索意図を狙うと、Googleがどちらも評価しにくくなる。
    管制塔のKW台帳（3サイト分）を突き合わせ、サイトをまたいだ重複だけを抽出する。
    """
    import hub_client
    if not hub_client.enabled():
        print("CROSS_CANNIBAL=skip （HUB_URL未設定のため横断検査を行いません）")
        return []
    kws = [k for k in hub_client.all_kw() if k.get("status") != "対象外"]
    if not kws:
        print("CROSS_CANNIBAL=no （台帳にKWがありません）")
        return []

    # 公開済み記事のタイトルも突合対象に加える（台帳に載る前の記事を拾うため）。
    # articles/ は3サイト共通の置き場なので、所属はcategoryから判定する。
    # ここを ai-lab 固定にすると、他サイト向け記事が自サイトの重複として誤検出される。
    import sites as sites_mod
    for a in load_articles():
        kws.append({"site": sites_mod.find_category_owner(a["cat"]) or "ai-lab",
                    "keyword": a["title"], "status": "公開済み", "url": "", "_from": "article"})

    # 別リポジトリのサイトは移管前から独自に記事を持っており、台帳に載っていない。
    # 実際に公開されている記事のタイトルも突合対象に入れないと、同テーマを重ねて書いてしまう。
    try:
        import external_index
        for sid, title, url in external_index.all_titles():
            kws.append({"site": sid, "keyword": title, "status": "公開済み",
                        "url": url, "_from": "external"})
    except Exception as e:
        print(f"（外部サイトの記事一覧を取得できずスキップ: {e}）")

    hits = []
    for i in range(len(kws)):
        for j in range(i + 1, len(kws)):
            a, b = kws[i], kws[j]
            if a.get("site") == b.get("site"):
                continue  # 同一サイト内は通常のカニバリ検査が担当する
            s = dice(a.get("keyword", ""), b.get("keyword", ""))
            if s >= WARN:
                hits.append({"score": round(s, 2), "a": a, "b": b})
    hits.sort(key=lambda h: -h["score"])

    print(f"CROSS_CANNIBAL_CHECK: {len(kws)}件のKW・記事を横断検査 / 重複疑い {len(hits)}組")
    if not hits:
        print("CROSS_CANNIBAL=no")
        return []
    print("CROSS_CANNIBAL=yes")
    for h in hits[:15]:
        a, b = h["a"], h["b"]
        print(f"\n[{h['score']}] {a['site']} ×  {b['site']}")
        print(f"  A: {a['keyword']}（{a.get('status', '-')}）")
        print(f"  B: {b['keyword']}（{b.get('status', '-')}）")
        # 公開済み側を残し、未着手側を取り下げるのが原則（既に評価を得ている方を守る）
        done = a if a.get("status") == "公開済み" else (b if b.get("status") == "公開済み" else None)
        if done:
            other = b if done is a else a
            print(f"  → 推奨: {other['site']} の「{other['keyword']}」を取り下げるか、"
                  f"読者と切り口を変える（{done['site']} が先に公開済み）")
        else:
            print("  → 推奨: どちらのサイトで扱うかを sites/*.json の担当領域に沿って決め、"
                  "片方を台帳から削除する")
    return hits


def article_territory(title, body, site_id):
    """書き上がった記事の主題が、どのサイトの担当領域かを判定する。

    カテゴリ検査だけでは「自サイトの正しいカテゴリのまま、他サイトの話題を書く」
    ケースを止められない（例: category=ai-marketing のまま補助金の記事を書く）。
    本文中に出てくる各サイトの所有語を数え、他サイトが主題なら報告する。

    戻り値: (侵食先のサイトID or None, サイト別スコア)
    """
    import sites as sites_mod
    cfgs = sites_mod.load_all()
    # タイトルは記事の主題を表すため重みを3倍にする
    scores = {sid: sum(3 * title.count(t) + body.count(t) for t in cfg.get("owns", []))
              for sid, cfg in cfgs.items()}
    own = scores.get(site_id, 0)
    best = max(scores, key=lambda k: scores[k])
    # 比率と実数の両方で明確に上回る場合だけ侵食とみなす（語数の少ない記事の誤検出を防ぐ）
    if best != site_id and scores[best] > max(own * 1.4, own + 20):
        return best, scores
    return None, scores


def territory_check():
    """担当領域の侵食を検査する。

    サイトごとに「この語を含むテーマは自分の担当」という owns を sites/*.json に定義してある。
    あるサイトの台帳に、他サイトが所有する語を含むKWが入っていたら領域侵食として報告する。
    類似度では拾えない「そもそも扱うべきでないテーマ」を確実に検出するための検査。
    """
    import hub_client
    import sites as sites_mod
    cfgs = sites_mod.load_all()
    owns = {sid: c.get("owns", []) for sid, c in cfgs.items()}
    if not hub_client.enabled():
        print("TERRITORY_CHECK=skip （HUB_URL未設定）")
        return []

    bad = []
    for k in hub_client.all_kw():
        site, kw = k.get("site"), k.get("keyword", "")
        if site not in owns or k.get("status") == "対象外":
            continue  # 取り下げ済みのKWは書かれないため検査対象から外す
        low = kw.lower()
        # 自サイトの所有語を含むなら、他サイトの語が混ざっていても自サイトのテーマとみなす
        if any(t.lower() in low for t in owns[site]):
            continue
        for other, terms in owns.items():
            if other == site:
                continue
            hit = next((t for t in terms if t.lower() in low), None)
            if hit:
                bad.append({"site": site, "keyword": kw, "status": k.get("status", ""),
                            "owner": other, "term": hit})
                break

    print(f"TERRITORY_CHECK: 侵食 {len(bad)}件")
    if not bad:
        print("TERRITORY_OK=yes")
        return []
    print("TERRITORY_OK=no")
    for b in bad:
        print(f"  [{b['site']}] {b['keyword']}（{b['status']}）"
              f" ← 「{b['term']}」は {b['owner']} の担当領域")
    print(f"\n→ 対処: 上記KWを {b['site']} の台帳から取り下げるか、担当サイトへ移す。"
          "\n  そのまま書くと同じ会社のサイトどうしで検索評価を奪い合う。")
    return bad


def external_dup_check():
    """自分が書いた記事と、同じサイトに元からある記事の重複を検査する。

    cross_site_check は「サイトをまたいだ」重複しか見ず、find_pairs は articles/ の中しか見ない。
    別リポジトリのサイト（コーポレート・補助金）は移管前からの記事を持つため、
    この2つの隙間に「同じサイトの既存記事と重複した新記事」が落ちる。
    """
    import sites as sites_mod
    cat2site = {c: sid for sid, cfg in sites_mod.load_all().items()
                for c in cfg.get("categories", {})}
    try:
        import external_index
        ext = external_index.load().get("sites", {})
    except Exception as e:
        print(f"EXTERNAL_DUP_CHECK=skip （外部サイトの記事一覧を取得できません: {e}）")
        return []

    hits = []
    for a in load_articles():
        site = cat2site.get(a["cat"])
        if not site or site not in ext:
            continue
        for e in ext[site]:
            if e["slug"] == a["slug"]:
                continue
            s = dice(a["title"], e["title"])
            if s >= WARN:
                hits.append({"score": round(s, 2), "site": site, "mine": a, "theirs": e})
    hits.sort(key=lambda h: -h["score"])

    print(f"EXTERNAL_DUP_CHECK: {len(load_articles())}記事 × 既存記事を突合 / 重複疑い {len(hits)}組")
    if not hits:
        print("EXTERNAL_DUP=no")
        return []
    print("EXTERNAL_DUP=yes")
    for h in hits[:10]:
        print(f"\n  [{h['score']}] {h['site']} の既存記事と重複")
        print(f"    自作: {h['mine']['title']}（{h['mine']['slug']}）")
        print(f"    既存: {h['theirs']['title']}")
        print(f"          {h['theirs']['url']}")
        print("    → 対処: 既存記事が先にあるため自作側を取り下げ、既存記事へ301で転送する")
    return hits


def written_territory_check():
    """公開済み記事の本文を検査し、他サイトの領域を主題にしているものを報告する。

    KW台帳の検査（territory_check）は「これから書くKW」しか見ない。
    書き上がった記事が結果的に他サイトの話題になっているケースは、本文で確認するしかない。
    """
    import sites as sites_mod
    cat2site = {c: sid for sid, cfg in sites_mod.load_all().items()
                for c in cfg.get("categories", {})}
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        title = (re.search(r"^title:\s*(.+?)\s*$", m.group(1), re.M) or [None, ""])[1]
        cat = (re.search(r"^category:\s*(.+?)\s*$", m.group(1), re.M) or [None, ""])[1]
        site = cat2site.get(cat.strip())
        if not site:
            continue
        invader, scores = article_territory(title.strip('"'), m.group(2), site)
        if invader:
            bad.append((p.stem, site, invader, scores))

    print(f"WRITTEN_TERRITORY_CHECK: {len(list((ROOT / 'articles').glob('*.md')))}記事の本文を検査 "
          f"/ 領域外 {len(bad)}件")
    if not bad:
        print("WRITTEN_TERRITORY_OK=yes")
        return []
    print("WRITTEN_TERRITORY_OK=no")
    for slug, site, invader, scores in bad:
        print(f"\n  {slug}: {site} に置かれているが、主題は {invader} の領域")
        print(f"    領域スコア {scores}")
        print(f"    → 対処: 記事を取り下げるか、{invader} へ配信し直して旧URLを301で転送する")
    return bad


def main():
    if "--cross" in sys.argv:
        cross_site_check()
        print()
        territory_check()
        print()
        written_territory_check()
        print()
        external_dup_check()
        return

    arts = load_articles()
    pairs = find_pairs(arts)
    print(f"CANNIBAL_CHECK: {len(arts)}記事を検査 / 重複疑い {len(pairs)}組")
    if not pairs:
        print("CANNIBAL_FOUND=no")
        return
    print("CANNIBAL_FOUND=yes")
    for p in pairs:
        action = "統合を検討（低品質側を削除し301相当の内部リンク集約）" if p["score"] >= STRONG \
            else "差別化（H1・メタ・冒頭結論の切り口を分ける／片方を対象読者で限定する）"
        print(f"\n[{p['score']}] {p['a']['slug']}  ×  {p['b']['slug']}")
        print(f"  A: {p['a']['title']}")
        print(f"  B: {p['b']['title']}")
        print(f"  タイトル類似 {p['title_sim']} / H2構成の重なり {p['h2_overlap']}")
        print(f"  → 推奨対処: {action}")
    sys.exit(0)


if __name__ == "__main__":
    main()
