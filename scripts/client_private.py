# -*- coding: utf-8 -*-
"""お客様の社の検索語・順位・AIの出典を、public のリポジトリに置かずに CI の実行をまたいで持ち越す。

このリポジトリは public。お客様の分は .gitignore で外したが（2026-10-07）、CI はジョブごとに作り直すため、
外したファイルは実行のたびに消える。順位の推移・AIの語の優先（next_kw）・引用の実測（ai_cite_check は
data/ranks が無い社を飛ばす）・競合比較の自社順位が、お客様の社だけ空になっていた（2026-10-08 の点検）。

置き場は data/clients/<id>/private/<元の相対パス>（.gitignore）。書いた工程から読む工程へは CI のキャッシュ
（.github/actions/client-private）で渡す。成果物（artifact）には入れない（public のリポジトリでは誰でも落とせる）。

  1. サイトごとの記録（PER_SITE。data/ranks/<id>.json など）は元の場所のまま読み書きする。
     書いた工程の終わりに --pack で置き場へ写し、読む工程の始めに --unpack で元の場所へ戻す
  2. 全社で1ファイルの記録（rank_up.json・ai_citations の月の記録と followup.json・共起語・
     URL検査の記録と再送の間隔）は、お客様の分だけを置き場に分けて書き（save_*）、読むときに合わせる（load_*）

  python scripts/client_private.py --pack [--kinds ai_kw]     # 書いた工程の終わり
  python scripts/client_private.py --unpack [--kinds ai_kw]   # 読む工程の始め（- なら戻さない）
  python scripts/client_private.py --list                     # 置き場にあるもの
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as S  # noqa: E402

# サイトごとの記録（種類 → 置き場の相対パス）。どれもお客様の分は .gitignore 済み。
# 種類は「どのジョブが書くか」で分ける（並行ジョブの書いた分を、別のジョブの古い写しで上書きしないため）
PER_SITE = {
    "ranks": ("data/ranks/{}.json",),                                   # rank_track（毎晩の救済）
    "ai_kw": ("data/ai_kw/{}.json", "docs/ai-kw-{}.md"),                 # ai_kw_research（週次の KW 補充）
    "weekly": ("data/win_patterns/{}.md", "docs/kw-strong-{}.md",        # win_patterns・kw_reorder・
               "docs/country-{}.md", "docs/season-{}.md"),               # country_rank・season（週次）
    "monthly": ("docs/kw-plan-{}.md", "reports/targets-{}.json"),       # kw_plan・monthly_report（月次）
}
CITATIONS = "data/ai_citations"
MONTH = re.compile(r"^\d{4}-\d{2}\.json$")


def clients():
    return [sid for sid in S.load_all() if S.is_client(sid)]


def is_private(sid):
    return bool(sid) and S.is_client(sid)


def private_path(sid, rel):
    return ROOT / "data" / "clients" / sid / "private" / rel


def templates(kinds=None):
    return [t for k, ts in PER_SITE.items() if not kinds or k in kinds for t in ts]


def _copy_all(kinds, to_private):
    n = 0
    for sid in clients():
        for t in templates(kinds):
            rel = t.format(sid)
            src, dst = (ROOT / rel, private_path(sid, rel)) if to_private else (private_path(sid, rel), ROOT / rel)
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                n += 1
    return n


def pack(kinds=None):
    """サイトごとの記録を置き場へ写す（お客様の社だけ）"""
    return _copy_all(kinds, True)


def unpack(kinds=None):
    """置き場の写しを元の場所へ戻す（お客様の社だけ。自社の記録はコミット済みなので触らない）"""
    return _copy_all(kinds, False)


# ── 全社で1ファイルの記録 ───────────────────────────────

def _read(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _dump(o):
    return json.dumps(o, ensure_ascii=False, indent=1) + "\n"


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def url_owner():
    """URL → 社（ドメインで決める）。1回の保存で何百件も引くので、ドメインの表は先に1回だけ作る"""
    doms = {str(c.get("domain") or "").lower().replace("www.", ""): sid for sid, c in S.load_all().items()}

    def owner(url, _value=None):
        m = re.match(r"https?://([^/]+)", str(url or ""))
        return doms.get((m.group(1) if m else "").lower().replace("www.", "")) if m else None
    return owner


def owner_of_url(url):
    return url_owner()(url)


def owner_of_slug(slug):
    p = ROOT / "articles" / f"{slug}.md"
    try:
        m = re.search(r"^category:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", p.read_text(encoding="utf-8-sig"), re.M)
    except OSError:
        return None
    return S.find_category_owner(m.group(1).strip()) if m else None


def load_dict(rel, pub=None):
    """public の rel（{キー: 値}）に、お客様ごとの置き場の rel を重ねたもの。
    pub は public 側の実際の場所（呼び出し側のモジュールの定数。門が一時の場所へ差し替える）"""
    d = dict(_read(Path(pub) if pub else ROOT / rel, {}))
    for sid in clients():
        d.update(_read(private_path(sid, rel), {}))
    return d


def save_dict(rel, d, owner, dump=_dump, pub=None):
    """owner(キー, 値) がお客様の社なら置き場へ、それ以外は public の rel へ書き分ける"""
    own, priv = {}, {}
    for k, v in d.items():
        sid = owner(k, v)
        if is_private(sid):
            priv.setdefault(sid, {})[k] = v
        else:
            own[k] = v
    _write(Path(pub) if pub else ROOT / rel, dump(own))
    for sid in clients():
        p = private_path(sid, rel)
        if sid in priv or p.is_file():
            _write(p, dump(priv.get(sid, {})))


def site_file(sid, rel):
    """1社分のファイルの置き場（お客様の社は置き場、自社は元の場所）"""
    return private_path(sid, rel) if is_private(sid) else ROOT / rel


def find_file(rel):
    """どの社のものか分からないファイル（共起語の <slug>.json など）。お客様の置き場を先に見る"""
    for sid in clients():
        p = private_path(sid, rel)
        if p.is_file():
            return p
    return ROOT / rel


def citation_months():
    """data/ai_citations の月の記録（YYYY-MM.json）の名前を古い順に。
    *.json で拾うと followup.json が最後に来て「最新の月」と取り違える（AIOの推定が空になっていた）"""
    names = {p.name for p in (ROOT / CITATIONS).glob("*.json") if MONTH.match(p.name)}
    for sid in clients():
        names |= {p.name for p in private_path(sid, CITATIONS).glob("*.json") if MONTH.match(p.name)}
    return sorted(names)


def load_citations(name):
    """月の記録（sites・measured.sites）に、お客様の分を合わせたもの"""
    pub = _read(ROOT / CITATIONS / name, {})
    d = dict(pub)
    d["sites"] = dict(pub.get("sites") or {})
    if pub.get("measured") is not None:
        d["measured"] = dict(pub["measured"], sites=dict(pub["measured"].get("sites") or {}))
    for sid in clients():
        part = _read(private_path(sid, f"{CITATIONS}/{name}"), {})
        d["sites"].update(part.get("sites") or {})
        pm = part.get("measured") or {}
        if pm.get("sites"):
            m = d.setdefault("measured", {k: v for k, v in pm.items() if k != "sites"})
            m.setdefault("sites", {}).update(pm["sites"])
    return d


def save_citations(name, d):
    """月の記録を書き分ける（お客様の sites・measured.sites は置き場へ）"""
    def part(src, keep):
        return {s: v for s, v in (src or {}).items() if keep(s)}

    meas = d.get("measured")
    pub = {k: v for k, v in d.items() if k not in ("sites", "measured")}
    pub["sites"] = part(d.get("sites"), lambda s: not is_private(s))
    if meas is not None:
        pub["measured"] = {k: v for k, v in meas.items() if k != "sites"}
        pub["measured"]["sites"] = part(meas.get("sites"), lambda s: not is_private(s))
    _write(ROOT / CITATIONS / name, json.dumps(pub, ensure_ascii=False, indent=2))
    for sid in clients():
        p = private_path(sid, f"{CITATIONS}/{name}")
        mine = {"date": d.get("date"), "sites": part(d.get("sites"), lambda s: s == sid)}
        if meas is not None and sid in (meas.get("sites") or {}):
            mine["measured"] = {k: v for k, v in meas.items() if k != "sites"}
            mine["measured"]["sites"] = {sid: meas["sites"][sid]}
        if mine["sites"] or "measured" in mine or p.is_file():
            _write(p, json.dumps(mine, ensure_ascii=False, indent=2))


def main():
    a = sys.argv[1:]
    kinds = None
    if "--kinds" in a:
        kinds = [k for k in a[a.index("--kinds") + 1].split(",") if k]
        unknown = [k for k in kinds if k not in PER_SITE and k != "-"]
        if unknown:
            raise SystemExit(f"種類が違います: {unknown}（{', '.join(PER_SITE)}）")
    if kinds == ["-"]:
        print("CLIENT_PRIVATE=skip（写す種類なし）")
        return 0
    if "--pack" in a:
        print(f"CLIENT_PRIVATE_PACKED={pack(kinds)}")
    elif "--unpack" in a:
        print(f"CLIENT_PRIVATE_UNPACKED={unpack(kinds)}")
    elif "--list" in a:
        for sid in clients():
            base = ROOT / "data" / "clients" / sid / "private"
            for p in sorted(base.rglob("*")) if base.is_dir() else []:
                if p.is_file():
                    print(f"  {sid}: {p.relative_to(base).as_posix()}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
