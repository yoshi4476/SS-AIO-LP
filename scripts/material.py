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


def hits(kw, mats, pool=()):
    """その題の材料の文の数（題を分ける語を含む文）"""
    distinct = subject(kw, pool)
    return sum(1 for m in mats if any(t in m.lower() for t in distinct))


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


def ask(site, slug, kw, weak=(), path=None):
    """材料の依頼を残す（記事ごとに1件。同じ記事は書き直す）。お客様の社は非公開の置き場にだけ書く"""
    data = _load_requests(site, path)
    data[slug] = {
        "keyword": kw,
        "since": (data.get(slug) or {}).get("since") or date.today().isoformat(),
        "questions": [
            f"「{kw}」について、実際にあったことを2〜3件（時期つき。社名は伏せます）",
            "そのうちの件数: 全体で何件あり、うまくいった・問題になったのが何件か（母数つきの数字になります）",
            "1件の事例: 何が起き、どう判断し、どうなったか",
        ],
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
