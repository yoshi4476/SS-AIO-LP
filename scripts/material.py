"""記事の題に使える自社の材料（一次情報・体験・事例・お客様の声）があるかを見る。

一次性の採点は「自社の経験や数字が2か所以上・うち1つは母数つき」で80点。材料の無い題で書くと、事実を作らない限り
何度直しても届かない（2026-10-20 お客様の記事が一次性40点のまま、直しが2回とも変更なしで止まった）。
そこで、材料のある題を先に書き（hub_client.next_kw）、材料が無くて止まった記事には「何を教えてほしいか」の依頼を残し、
材料が増えるまで直しに Claude を使わない（quality_loop）。新しい記事を書くこと自体は止めない。

  python scripts/material.py --site <id> --kw "<語>"   # その語に当たる材料の数
  python scripts/material.py --requests                # 残っている材料の依頼（お客様の社は件数だけ）
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OWN_REQUESTS = ROOT / "data" / "material_requests.json"
REQUESTS = "material_requests.json"
# 語の半分近くに出る語（サービス名・業種名）は、材料に出ても「その題の材料」とは言えない。
# 「システム開発 外注 デメリット」は経歴の「システム開発の事業を運営」に当たって材料ありと誤って数えた（2026-10-20）
COMMON_SHARE = 0.3
# 母数つきの数字（何社・何件・何名のうち）。一次性の80点は「自社の数字が2か所以上・うち1つは母数つき」
BASE = re.compile(r"\d[\d,]*\s*(?:社|件|名|人|店|院|枚|棟|組|か所|カ所)|のうち|中\d")
# 題の語どうしの距離（字）の上限。これより離れていれば同じ話とみなさない
NEAR = 40
# 探し方の語。材料の文には出てこないので、題の中身の語として求めない
INTENT = re.compile(r"方法|やり方|とは|違い|比較|おすすめ|コツ|ポイント|事例|例|メリット|デメリット|無料|テンプレート|"
                    r"書き方|選び方|費用|料金|相場|一覧|まとめ|活用|術|20\d\d")
# 材料の依頼で実例を聞かない見出し
SKIP_HEAD = re.compile(r"まとめ|よくある質問|faq|参考|出典|おわりに|関連|目次", re.I)
# 採点者の指摘のうち、足りない数字・実例を名指しした文
MISSING = re.compile(r"(?:件数|割合|数字|実測|実例|具体例|事例).{0,20}(?:無い|ない|ありません|少ない|薄い)")


def lines(site):
    """その社の材料の文（一次情報・登録した体験・ヒアリングシートの事例とお客様の声）"""
    out = []
    try:
        import facts as F
        _, fs = F.load_for(site)
        out += [str(f.get("claim") or "") for f in fs or []]
    except Exception:  # noqa: BLE001  材料が読めない社は材料なしとして扱う
        pass
    try:
        import originality
        out += [str(r.get("text") or "") for r in originality.load_experiences(site)]
    except Exception:  # noqa: BLE001
        pass
    try:
        import private_store as P
        if P.is_client(site):
            brief = P.read_json(site, "brief.json", {}) or {}
            for k in ("cases", "voices"):
                for x in brief.get(k) or []:
                    out.append(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    return [x for x in out if x.strip()]


def fingerprint(site):
    """材料が増えた・変わったかを見る印"""
    return hashlib.sha1("\n".join(sorted(lines(site))).encode("utf-8")).hexdigest()[:12]


def tokens(kw):
    return [t for t in re.split(r"[\s　/・｜|、,]+", str(kw).lower()) if len(t) >= 2]


def _freq(pool):
    pool = [set(tokens(k)) for k in pool or [] if k]
    seen = {}
    for ts in pool:
        for t in ts:
            seen[t] = seen.get(t, 0) + 1
    return seen, len(pool)


def subject(kw, pool=()):
    """その題を他の題と分ける語（語の集まりで一番出てこない語）。サービス名・業種名のように多くの題に出る語は、
    材料に出ても「その題の材料」とは言えない。「aio 外注」は aio だけで材料6件と数えていた（2026-10-20）"""
    ts = tokens(kw)
    seen, n = _freq(pool)
    if not ts or n < 5:
        return ts
    low = min(seen.get(t, 0) for t in ts)
    rare = [t for t in ts if seen.get(t, 0) == low]
    return [t for t in rare if low / n < COMMON_SHARE] or rare


def topic(kw, pool=()):
    """題の中身の語。多くの題に出るサービス名・業種名と、探し方の語（方法・とは・無料…）を除く。除くと空なら残す"""
    ts = tokens(kw)
    seen, n = _freq(pool)
    rare = [t for t in ts if n < 5 or seen.get(t, 0) / n < COMMON_SHARE] or ts
    return [t for t in rare if not INTENT.fullmatch(t)] or rare


def hits(kw, mats, pool=()):
    """その題で一次性に使える材料の文の数。題の中身の語を全部、同じ文（。まで）に含み、母数つきの数字がある文だけを数える。
    語のどれか1つで数えていたので、「請求書 仕訳」は「仕訳の誤りの直し約90件」「請求書の発行代行18社」の片方ずつに
    当たって材料ありと数え、主題の数字が無いまま書いて一次性78点で止まった（2026-10-31）"""
    words = topic(kw, pool)

    def ok(s):
        at = [s.find(t) for t in words]
        # 語どうしが離れた文は、別々の話を並べただけ（「経理代行を担当した33社の内訳は…クリニック4社」は
        # クリニックの経理の材料ではない。2026-10-23 一次性で止まった）
        return min(at) >= 0 and max(at) - min(at) <= NEAR and bool(BASE.search(s))
    return sum(1 for m in mats if any(ok(s) for s in re.split(r"(?<=。)", m.lower())))


def _load_requests(site, path=None):
    import private_store as P
    if P.is_client(site):
        return P.read_json(site, REQUESTS, {}) or {}
    try:
        return json.loads((path or OWN_REQUESTS).read_text(encoding="utf-8")).get(site, {})
    except (OSError, ValueError):
        return {}


def _save_requests(site, data, path=None):
    import private_store as P
    if P.is_client(site):
        P.write_json(site, REQUESTS, data)
        return
    path = path or OWN_REQUESTS
    try:
        allr = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        allr = {}
    allr[site] = data
    path.write_text(json.dumps(allr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def questions(kw, weak=(), heads=()):
    """材料の依頼の質問（5つまで）。主題そのものの数字、採点者が無いと言った数字、見出しごとの実例を名指しで聞く。
    汎用の「実際にあったことを2〜3件」だけでは、周辺の話（仕訳の誤り全般など）が返って主題の数字が届かなかった（2026-10-31）。
    聞くだけで、答えの数字は作らない"""
    qs = [f"「{kw}」そのものについて、当社で数えた数字（期間つき・全体で何件のうち何件か。社名は伏せます）"]
    said = [s.strip() for w in weak or [] for s in re.split(r"(?<=。)", str(w)) if MISSING.search(s)]
    said.sort(key=lambda s: not re.search(r"件数|割合|何件|何社", s))   # 数えられる形で名指しした指摘を先に
    qs += [f"採点者の指摘「{s}」に答えられる、当社で数えた数字か実例（無ければ「無し」で構いません）" for s in said[:2]]
    hs = [h.strip() for h in heads or [] if h.strip() and not SKIP_HEAD.search(h)]
    qs += [f"見出し「{h}」の節に使える実例1件（時期つき。何が起き、どう判断し、どうなったか）" for h in hs[:2]]
    if len(qs) < 3:
        qs += ["そのうちの件数: 全体で何件あり、うまくいった・問題になったのが何件か（母数つきの数字になります）",
               "1件の事例: 何が起き、どう判断し、どうなったか"]
    return qs[:5]


def ask(site, slug, kw, weak=(), path=None, heads=()):
    """材料の依頼を残す（記事ごとに1件。同じ記事は書き直す）。お客様の社は非公開の置き場にだけ書く"""
    data = _load_requests(site, path)
    data[slug] = {
        "keyword": kw,
        "since": (data.get(slug) or {}).get("since") or date.today().isoformat(),
        "questions": questions(kw, weak, heads),
        "scorer": [str(w) for w in (weak or [])][:4],
    }
    _save_requests(site, data, path)


def resolve(site, slug, path=None):
    """材料が届いて記事が通ったら、依頼を消す"""
    data = _load_requests(site, path)
    if data.pop(slug, None) is not None:
        _save_requests(site, data, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--kw", default="")
    ap.add_argument("--requests", action="store_true")
    a = ap.parse_args()
    if a.kw and a.site:
        print(f"MATERIAL_HITS={hits(a.kw, lines(a.site))}")
        return
    if a.requests:
        import private_store as P
        import sites as S
        for sid in sorted(S.load_all()):
            n = len(_load_requests(sid))
            if n:
                print(f"  {S.public_id(sid) if P.is_client(sid) else sid}: 材料の依頼 {n}件")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
