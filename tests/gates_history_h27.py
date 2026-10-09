# -*- coding: utf-8 -*-
"""自社3サイトの決め打ちを残さない（2026-10-06）。

週次・集中モードの直し（link_boost・盤面）が `for s in ai-lab corporate subsidy` で回っていて、
お客様の社（sites/<id>.json。最大20社）を受けても直しが回らなかった。一覧は sites/*.json から作る
（`python scripts/sites.py --ids`）。先方のアカウントの持ち物に触る工程（Bing の送信）や、自社専用の物は
自社だけで正しいので、その箇所は `自社だけ:` で始まるコメントに理由を書いて許す。
"""
import ast
import contextlib
import io
import re

from test_gates import check, ROOT

IDS = ("ai-lab", "corporate", "subsidy")
MARK = "自社だけ:"
LOOKBACK = 8
_ID = {s: re.compile(r"(?<![\w.-])" + re.escape(s) + r"(?![\w.-])") for s in IDS}
_ALT = "(?:" + "|".join(map(re.escape, IDS)) + ")"
_JOINED = re.compile(r"(?<![\w.-])" + _ALT + r"(?:[\s,]+" + _ALT + r"){2,}(?![\w.-])")


def _marked(lines, i):
    return any(MARK in ln for ln in lines[max(0, i - LOOKBACK):i + 1])


def yml_hits(text):
    """ワークフローで3サイトが4行以内に並ぶ箇所（コメント行は数えない）。印のある箇所は除く。行番号（1始まり）"""
    lines = text.split("\n")
    code = ["" if ln.lstrip().startswith("#") else ln for ln in lines]
    out, i = [], 0
    while i < len(code):
        win = "\n".join(code[i:i + 4])
        if any(p.search(code[i]) for p in _ID.values()) and all(p.search(win) for p in _ID.values()):
            if not _marked(lines, i):
                out.append(i + 1)
            i += 4
        else:
            i += 1
    return out


def py_hits(src):
    """スクリプトで3サイトを並べて対象を決めている箇所: リスト・タプル・集合（argparse の choices を含む）と、
    空白・カンマでつないだ文字列。辞書（サイトごとの値）・docstring・コメントは数えない。行番号"""
    tree = ast.parse(src)
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    lines = src.split("\n")
    out = []
    for n in ast.walk(tree):
        hit = False
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            vals = {e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            hit = set(IDS) <= vals
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            hit = any(set(re.findall(_ALT, m.group(0))) >= set(IDS) for m in _JOINED.finditer(n.value))
        if hit and not _marked(lines, n.lineno - 1):
            out.append(n.lineno)
    return sorted(set(out))


def test_detector_reads_lists_not_neighbors():
    print("\n■ 3サイトの決め打ちの検出器: 並べた一覧は拾い、サイトごとの値・説明・印つきは拾わない")
    check("ワークフローの for ループを拾う", yml_hits("run: |\n  for s in ai-lab corporate subsidy; do\n  done"), [2])
    check("--sites a,b,c の形も拾う", yml_hits("  python x.py --sites ai-lab,corporate,subsidy"), [1])
    check("行をまたぐ並び（キャッシュの除外）も拾う",
          yml_hits("path: |\n  !data/compete/ai-lab\n  !data/compete/corporate\n  !data/compete/subsidy"), [2])
    check("印のコメントがあれば許す",
          yml_hits("# 自社だけ: 先方の Bing の持ち物\nfor s in ai-lab corporate subsidy; do"), [])
    check("コメントの中で名前を挙げるだけなら拾わない", yml_hits("# ai-lab corporate subsidy の3サイト"), [])
    check("sites.py --ids の形は拾わない", yml_hits("for s in $(python scripts/sites.py --ids); do"), [])
    check("python: リストを拾う", py_hits('X = ["ai-lab", "corporate", "subsidy"]\n'), [1])
    check("python: argparse の choices を拾う",
          py_hits('ap.add_argument("--site", choices=["ai-lab", "subsidy", "corporate"])\n'), [1])
    check("python: タプル（行をまたぐ）を拾う", py_hits('for s in (\n    "ai-lab",\n    "corporate",\n    "subsidy"):\n    pass\n'), [1])
    check("python: つないだ文字列を拾う", py_hits('cmd = "--sites ai-lab corporate subsidy"\n'), [1])
    check("python: サイトごとの値の辞書は拾わない（お客様は既定値に落ちる）",
          py_hits('H = {"ai-lab": 1, "corporate": 2, "subsidy": 3}\n'), [])
    check("python: docstring の説明は拾わない", py_hits('def f():\n    """(\'ai-lab\', \'corporate\', \'subsidy\') と書くと"""\n'), [])
    check("python: 印のコメントがあれば許す",
          py_hits('# 自社だけ: 自社のファイル構成\nX = ["ai-lab", "corporate", "subsidy"]\n'), [])
    check("python: 2サイトだけの並びは拾わない", py_hits('X = ["ai-lab", "subsidy"]\n'), [])


def test_no_hardcoded_three_sites_in_workflows_and_scripts():
    print("\n■ ワークフローとスクリプトに3サイトの決め打ちが残っていない（自社だけの箇所は印のコメントつき）")
    bad = []
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        bad += [f"{p.relative_to(ROOT).as_posix()}:{n}" for n in yml_hits(p.read_text(encoding="utf-8"))]
    for p in sorted((ROOT / "scripts").glob("*.py")):
        bad += [f"{p.relative_to(ROOT).as_posix()}:{n}" for n in py_hits(p.read_text(encoding="utf-8-sig"))]
    check("決め打ち（印なし）の箇所", bad, [])


def test_site_lists_come_from_sites_json():
    print("\n■ 全社の一覧は sites/*.json から・集中モードは設定で選ぶ（既定は自社だけ）・Bing は自社だけ")
    import yaml
    import sites as S
    import focus_report as F
    import auto_rewrite as AR
    import bing_webmaster as BW
    # お客様の社は公開の印（sites/<公開の id>.json）から社の id に戻して並ぶ。非公開のデータが無い回は入らない
    want = [S.resolve(p.stem) for p in sorted((ROOT / "sites").glob("*.json")) if p.stem != "sample"]
    check("sites.ids は sites/*.json の全社（sample を除く）", S.ids(), [s for s in want if s in S.load_all()])
    check("集中モード: sites が無ければ自社だけ（今の動き）", F.focus_sites({}), [s for s in S.own_ids() if s != "sample"])
    one = S.ids()[-1]
    check("集中モード: sites に書いた社だけ（無い社は捨てる）", F.focus_sites({"sites": [one, "no-such-site"]}), [one])

    arts = {}
    for p in sorted((ROOT / "articles").glob("*.md")):
        try:
            sid = AR.site_of(p.stem)
        except OSError:
            continue
        arts.setdefault(sid, p.stem)
        if len(arts) >= 2:
            break
    items = [{"slug": s, "kind": "title"} for s in arts.values()]
    first = next(iter(arts))
    check("auto_rewrite --sites: 指定の社の記事だけ残す",
          [x["slug"] for x in AR.only_sites(items, first)], [arts[first]])
    check("auto_rewrite --sites: 空なら絞らない（週次の動きは変えない）", AR.only_sites(items, ""), items)
    check("auto_rewrite --sites: 空白とカンマのどちらでも読む",
          len(AR.only_sites(items, " , ".join(arts))), len(items))

    check("Bing の送り先は自社だけ", sorted(BW.own_cfgs()), sorted(s for s in S.own_ids() if s in S.load_all()))
    saved = (BW.api_key, BW.own_cfgs)
    try:
        BW.api_key = lambda: "dummy-key"
        BW.own_cfgs = lambda: {}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            BW.main(["--site", "client-x"])
        check("Bing: お客様の社を指定されたら送らずに終える", "先方の Bing" in buf.getvalue(), True)
    finally:
        BW.api_key, BW.own_cfgs = saved

    def runs(name):
        y = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
        return "\n".join(str(st.get("run", "")) for job in y["jobs"].values() for st in job.get("steps", []))
    wk, fc = runs("weekly-optimize.yml"), runs("focus-mode.yml")
    check("週次: link_boost と盤面は全社のループ",
          all(x in wk for x in ("for s in $(python scripts/sites.py --ids); do",
                                 'link_boost.py "$s" --write', 'link_boost.py "$s" --rescue --write',
                                 'coverage.py --site "$s"')), True)
    check("集中モード: 内部リンクは focus_report --sites の社", "for s in $(python scripts/focus_report.py --sites); do" in fc, True)
    check("集中モード: 書き直しも同じ社に絞る",
          fc.count('--sites "$(python scripts/focus_report.py --sites)"'), 2)
    check("集中モード: Bing は自社だけ", "for s in $(python scripts/sites.py --own); do" in fc, True)
