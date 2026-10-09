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
     URL検査の記録と再送の間隔・量産の兆候・本数の効き・狙う語の推移・積んだ語）は、お客様の分だけを
     置き場に分けて書き（save_*）、読むときに合わせる（load_*）
  3. 1行ずつ積む記録（SPLIT_JSONL。介入の台帳・学び）は、お客様の記事・社の行だけを置き場へ書き
     （append_jsonl・save_jsonl）、読むときに合わせる（read_lines）。全社に効く学びは public に残し、
     お客様の名前・ドメインは伏せる（redact）
  4. AIの答え（data/ai_cache）は、お客様の社の質問だけ置き場に置く（ai_cite_check.cache_file の site）
  5. 残すときは、一番新しい写しを重ね直してから、このジョブで変えたファイルだけを戻す（並行のジョブの分を消さない）

  python scripts/client_private.py --pack [--kinds ai_kw]     # 書いた工程の終わり
  python scripts/client_private.py --unpack [--kinds ai_kw]   # 読む工程の始め（- なら戻さない）
  python scripts/client_private.py --mark-before / --mark-after   # キャッシュを戻す前と後（戻した中身を覚える）
  python scripts/client_private.py --stash / --unstash             # 残す前にこのジョブの分を退避し、最新に重ねて戻す
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
    "monthly": ("docs/kw-plan-{}.md", "reports/targets-{}.json"),       # kw_plan（毎日の在庫の見張り）・monthly_report（月次）
    "kw_serp": ("data/kw_serp/{}.json",),                                # kw_plan が取った上位の見出し・共起語・質問（執筆と書き直しが読む）
}
# 自社の社の分も public に置かない種類。ラッコの利用規約は「社内利用の範囲」なので、ラッコで取った上位の見出し・
# 共起語・質問は自社3サイトの分も置き場で持ち越す（2026-10-09 運用者の決定）
ALL_SITES = {"kw_serp"}
OWN = "_own"   # 自社の社の置き場の区画（社の id には無い名前）
CITATIONS = "data/ai_citations"
MONTH = re.compile(r"^\d{4}-\d{2}\.json$")


def clients():
    return [sid for sid in S.load_all() if S.is_client(sid)]


def is_private(sid):
    return bool(sid) and S.is_client(sid)


def private_path(sid, rel):
    # 自社の社は data/clients/_own/private/<id>/。data/clients/<id>/ を作るとその社が「お客様」と判定され
    # （sites.is_client）、置き場の場所を変えると CI のキャッシュの版が変わってお客様の持ち越しが1回分戻らない
    if is_private(sid):
        return ROOT / "data" / "clients" / sid / "private" / rel
    return ROOT / "data" / "clients" / OWN / "private" / sid / rel


def templates(kinds=None):
    return [t for k, ts in PER_SITE.items() if not kinds or k in kinds for t in ts]


def _copy_all(kinds, to_private):
    n = 0
    for kind, ts in PER_SITE.items():
        if kinds and kind not in kinds:
            continue
        for sid, t in ((s, t) for s in (list(S.load_all()) if kind in ALL_SITES else clients()) for t in ts):
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


def site_key(key, _value=None):
    """{社のID: …} の記録（量産の兆候・本数の効き・狙う語の推移・積んだ語）の持ち主"""
    return key


# ── 1行ずつ積む記録（介入の台帳・学び・統合の記録） ─────────────────────
# 介入の台帳の備考には直した記事の順位・表示が、学びの詳細と統合の記録には検索語・表示の数が入る。
# お客様の記事・社の行は置き場へ書き、読むときに合わせる（2026-10-08 の点検で、どれも public に載りうる形だった）
SPLIT_JSONL = ("automation/logs/auto_fix.jsonl", "data/lessons.jsonl", "data/merges.jsonl")


def _split_rel(p):
    """p が public の分け書きの記録（SPLIT_JSONL）ならその相対パス。門の一時ファイルなど、それ以外は None"""
    try:
        rel = Path(p).resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return None
    return rel if rel in SPLIT_JSONL else None


def append_jsonl(p, row, sid=None):
    """1行を積む。持ち主（sid、無ければ row の slug の記事の社）がお客様なら置き場へ、それ以外は p へ"""
    rel = _split_rel(p)
    if rel and sid is None:
        sid = owner_of_slug(str(row.get("slug") or ""))
    target = private_path(sid, rel) if rel and is_private(sid) else Path(p)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_lines(p):
    """p の空でない行。p が分け書きの記録なら、お客様の置き場の行を後ろに足す"""
    rel = _split_rel(p)
    out = []
    for q in [Path(p)] + ([private_path(sid, rel) for sid in clients()] if rel else []):
        try:
            out += [x for x in q.read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            pass
    return out


def save_jsonl(p, rows, owner, scrub=None):
    """rows を書き直す。owner(row) がお客様の社の行はその社の置き場へ、それ以外は p へ（scrub があれば通す）。
    p が分け書きの記録でなければ（門の一時ファイル）全部 p へ"""
    rel = _split_rel(p)
    pub, priv = [], {}
    for r in rows:
        sid = owner(r) if rel else None
        if is_private(sid):
            priv.setdefault(sid, []).append(r)
        else:
            pub.append(scrub(r) if scrub and rel else r)

    def text(rs):
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs)
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(text(pub), encoding="utf-8", newline="\n")
    for sid in clients() if rel else []:
        q = private_path(sid, rel)
        if sid in priv or q.is_file():
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(text(priv.get(sid, [])), encoding="utf-8", newline="\n")


def markers():
    """お客様の社ごとの名前・ドメイン（public の文から伏せる語）。{社のID: [語…]}"""
    out = {}
    for sid in clients():
        cfg = S.load_all().get(sid) or {}
        names = [sid, str(cfg.get("domain") or "").lower().replace("www.", "")]
        try:
            co = json.loads((ROOT / "data" / "clients" / sid / "company.json").read_text(encoding="utf-8"))
            names += [co.get("name"), co.get("name_en")]
        except (OSError, ValueError):
            pass
        out[sid] = [n for n in dict.fromkeys(names) if n and len(str(n)) >= 3]
    return out


def redact(text):
    """お客様の名前・ドメインを「お客様のサイト」に置き換える（長い語から・大文字小文字を問わない）"""
    words = sorted({w for ws in markers().values() for w in ws}, key=len, reverse=True)
    for w in words:
        text = re.sub(re.escape(w), "お客様のサイト", str(text), flags=re.I)
    return text


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


# ── 持ち越しの保存で、ほかのジョブが同じ間に残した分を消さない ─────────────
# キャッシュは「一番新しい写し」を丸ごと戻す。2つのジョブが同じ写しから始めて別々に残すと、後から残した方が
# 先の方の更新を消していた（月曜と1日・15日に週次と月次が重なると、お客様の更新が1回分失われる。2026-10-08 の点検）。
# 戻すたびに、戻したことで変わったファイルの中身を覚え（mark）、残す前にこのジョブで変えたファイルだけを退避し（stash）、
# 一番新しい写しを重ね直してから戻す（unstash）。1行ずつ積む記録（.jsonl）は両方の行を残す
def _work():
    import os
    import tempfile
    return Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "client-private"


def _hashes():
    import hashlib
    out = {}
    for d in sorted((ROOT / "data" / "clients").glob("*/private")):
        for p in d.rglob("*"):
            if p.is_file():
                out[p.relative_to(ROOT).as_posix()] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def mark_before():
    _write(_work() / "pre.json", json.dumps(_hashes()))
    return len(_read(_work() / "pre.json", {}))


def mark_after():
    """戻したことで現れた・変わったファイルを「戻した時点の中身」として覚える。
    このジョブが先に書いたファイル（戻しても変わらなかったもの）は覚え直さない（このジョブの分として残す）"""
    pre = _read(_work() / "pre.json", {})
    base = _read(_work() / "base.json", {})
    for f, h in _hashes().items():
        if pre.get(f) != h:
            base[f] = h
    _write(_work() / "base.json", json.dumps(base))
    return len(base)


def stash():
    """このジョブで書いた・変えたファイル（覚えた中身と違うもの）を退避する。件数を返す"""
    base = _read(_work() / "base.json", {})
    mine = _work() / "mine"
    shutil.rmtree(mine, ignore_errors=True)
    n = 0
    for f, h in _hashes().items():
        if base.get(f) != h:
            (mine / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, mine / f)
            n += 1
    return n


def merge_jsonl(latest, mine):
    """1行ずつ積む記録を合わせる。id のある行（学び）は同じ id ならこのジョブの行、ほかは同じ行を2回入れない"""
    def key(ln):
        try:
            d = json.loads(ln)
        except ValueError:
            return ("line", ln)
        return ("id", d["id"]) if isinstance(d, dict) and d.get("id") else ("line", ln)
    rows, order = {}, []
    for ln in latest.splitlines() + mine.splitlines():
        if not ln.strip():
            continue
        k = key(ln)
        if k not in rows:
            order.append(k)
        rows[k] = ln
    return "".join(rows[k] + "\n" for k in order)


def unstash():
    """一番新しい写しを戻した後に、このジョブの分を重ねる（.jsonl は merge_jsonl、ほかはこのジョブの中身）"""
    mine = _work() / "mine"
    n = 0
    for p in sorted(mine.rglob("*")) if mine.is_dir() else []:
        if not p.is_file():
            continue
        dst = ROOT / p.relative_to(mine)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".jsonl" and dst.is_file():
            dst.write_text(merge_jsonl(dst.read_text(encoding="utf-8"), p.read_text(encoding="utf-8")),
                           encoding="utf-8", newline="\n")
        else:
            shutil.copy2(p, dst)
        n += 1
    return n


def main():
    a = sys.argv[1:]
    for flag, fn, label in (("--mark-before", mark_before, "MARKED"), ("--mark-after", mark_after, "BASE"),
                            ("--stash", stash, "STASHED"), ("--unstash", unstash, "UNSTASHED")):
        if flag in a:
            print(f"CLIENT_PRIVATE_{label}={fn()}")
            return 0
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
