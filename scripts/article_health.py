"""公開済みの記事の「今の調子」を検索の実績で分け、伸びている記事を直しから守る（2026-10-22 運用者
「今までの記事の質が悪いので改善の方向に向かうように。但し伸びているものは変えるとまずい。ちゃんと判断して」）。

材料は rank_track が毎日残すページ単位の28日×2期間（data/ranks/<site>.pages.json）。無い・古いときだけ
語×ページの記録（data/ranks/<site>.json の最新の日とその28日前）で代える（クリックを取りこぼすので守りが弱くなる）。
ここでは Search Console を呼ばない。

分け方（公開35日未満は判定しない。順位が落ち着く前に直すと、効いたのかが分からない）:
  growing  伸びている  表示30回以上で、表示が1.3倍以上 または 平均順位が3以上上がった → 直さない
  read     読まれている クリック3回以上 または 10位以内でクリックあり → 題・構成を変える直しはしない
  falling  落ちている  前の期間に表示30回以上あり、6割を切った → 先に直す（需要はあった）
  weak     表示はあるが弱い 表示10回以上 → 次に直す
  dormant  ほぼ表示なし → 後回し（質を上げても表示は増えにくい。統合・取り下げは retire_stale が受け持つ）
  young    公開35日未満 → 触らない

  python scripts/article_health.py --report     # 社ごとの内訳（お客様の社は件数だけ）
"""
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

YOUNG_DAYS = 35
MIN_IMP = 30
# 読まれている記事に当ててよい直し（足すだけで題・構成を変えない）。伸びている記事には何も当てない
SAFE_FOR_READ = ("aio", "fresh")
# 直す順（小さいほど先）
ORDER = {"falling": 0, "weak": 1, "dormant": 2, "read": 3, "growing": 4, "young": 5}

_CACHE = {}


def _norm(u):
    return u.split("#")[0].split("?")[0].rstrip("/") + "/"


def _pages(site):
    """(今の28日, その前の28日) の {URL: [表示, クリック, 表示で重みづけした順位]}。記録が無ければ ({}, {})。
    ページ単位の記録（rank_track の <site>.pages.json）を先に使う。語×ページの記録はクリックを取りこぼす
    （コーポレートで「読まれている記事」がページ単位の12本に対し0本に見えた）ので、無い・古いときの代わりだけ"""
    if site in _CACHE:
        return _CACHE[site]
    import client_private as CP
    try:
        pg = json.loads(CP.find_file(f"data/ranks/{site}.pages.json").read_text(encoding="utf-8"))
        if pg.get("end", "") >= (date.today() - timedelta(days=13)).isoformat() and pg.get("cur"):
            _CACHE[site] = (pg["cur"], pg.get("prev") or {})
            return _CACHE[site]
    except Exception:  # noqa: BLE001  無ければ語×ページの記録で代える
        pass
    try:
        hist = json.loads(CP.find_file(f"data/ranks/{site}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  記録が無ければ判定しない（守りもしない）
        _CACHE[site] = ({}, {})
        return _CACHE[site]
    days = sorted(hist)
    if not days:
        _CACHE[site] = ({}, {})
        return _CACHE[site]
    last = days[-1]
    want = (date.fromisoformat(last) - timedelta(days=28)).isoformat()
    before = [d for d in days if d <= want]

    def agg(rows):
        out = {}
        for r in rows or []:
            v = out.setdefault(_norm(r.get("url", "")), [0, 0, 0.0])
            imp = int(r.get("imp") or 0)
            if imp:
                v[2] = (v[2] * v[0] + float(r.get("pos") or 0) * imp) / (v[0] + imp)
            v[0] += imp
            v[1] += int(r.get("clicks") or 0)
        return out
    _CACHE[site] = (agg(hist[last]), agg(hist[before[-1]]) if before else {})
    return _CACHE[site]


def classify(cur, prev, age):
    """(表示, クリック, 順位) の今と前、公開からの日数 → 分類"""
    if age < YOUNG_DAYS:
        return "young"
    imp, clk, pos = cur
    pimp, _, ppos = prev
    up = imp >= MIN_IMP and (imp >= pimp * 1.3 or (ppos and pos and pos <= ppos - 3))
    if up:
        return "growing"
    if clk >= 3 or (clk >= 1 and pos and pos <= 10):
        return "read"
    if pimp >= MIN_IMP and imp < pimp * 0.6:
        return "falling"
    if imp >= 10:
        return "weak"
    return "dormant"


def of(slug, site=None, meta=None):
    """記事1本の分類。順位の記録が無い社は None（守らず、順も変えない）"""
    import sites as S
    site = site or _site_of(slug)
    cur, prev = _pages(site)
    if not cur:
        return None
    if meta is None:
        meta = _meta(slug)
    try:
        url = _norm(S.article_url(S.load(site), meta))
    except Exception:  # noqa: BLE001
        return None
    try:
        age = (date.today() - date.fromisoformat(str(meta.get("date"))[:10])).days
    except ValueError:
        age = 999
    return classify(cur.get(url, [0, 0, 0.0]), prev.get(url, [0, 0, 0.0]), age)


def protected(slug, kind=None, site=None):
    """この直し（kind）を当ててはいけない記事か。伸びている記事は何も、読まれている記事は題・構成を変える直しをしない"""
    h = of(slug, site)
    if h == "growing":
        return True
    return h == "read" and kind not in SAFE_FOR_READ


def drop_protected(items, kind=None):
    """書き直しの候補から、守る記事を外す（運用者が --slugs で名指しした記事は呼び出し側が外さない）"""
    keep, held = [], []
    for x in items:
        (held if protected(x["slug"], x.get("kind") or kind, x.get("site")) else keep).append(x)
    if held:
        print(f"  伸びている・読まれている記事 {len(held)}本は直しません（article_health）")
    return keep


def _site_of(slug):
    import daily_audit as D
    for sid, arts in D.articles_by_site().items():
        if any(a["slug"] == slug for a in arts):
            return sid
    return ""


def _meta(slug):
    import quality_loop as Q
    try:
        return Q.meta_of(Q.read(slug))
    except Exception:  # noqa: BLE001
        return {}


def report():
    import daily_audit as D
    import sites as S
    for sid, arts in D.articles_by_site().items():
        pub = [a for a in arts if D._is_published(a, need_review=False) and a.get("quality_state") != "improving"]
        if not pub or not _pages(sid)[0]:
            continue
        c = Counter(of(a["slug"], sid) for a in pub)
        name = S.public_id(sid) if S.is_client(sid) else sid
        print(f"  {name}: " + "・".join(f"{k} {c[k]}本" for k in sorted(c, key=lambda k: ORDER.get(k, 9))))
    print("HEALTH_OK=yes")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        print(__doc__)
