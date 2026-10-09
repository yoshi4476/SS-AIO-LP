# -*- coding: utf-8 -*-
"""配信方式 × 機能の表（data/capabilities.json）が、方式と機能を漏れなく覆っていること（2026-10-06）。

運用者の方針: どの納品方式でも、最初の接続が済んだ後は人の手を一切使わずに全機能が動く。
方式ごとに道具が別々に育つと、「Git の社は直せるがレンタルサーバーの社には届かない」が
だれにも気づかれないまま残る（実際、external-md は画像も sitemap も llms.txt も届けていなかった）。
表を機械が持ち、方式や機能を足したときに表へ足し忘れたら、ここで止める。

missing が残っていたら落とす（FAIL_ON）。partial は数を出すだけ。すべて ok / n/a になったら FAIL_ON に partial も足す。

根拠の行（evidence「ファイル:行」）は行番号なので、コードを1行足すだけで別の行を指す。並行作業の結合で
行番号がずれ、引き直したつもりの表に古い判定が混ざった（2026-10-06）。各セルに行の中身（anchor）を持たせ、
根拠の行がその中身と一致することを確かめる。ずれたら python scripts/caps_anchor.py --write で引き直す。
"""
import ast
import json
import re
from collections import Counter

from test_gates import check, ROOT

CAPS = ROOT / "data" / "capabilities.json"
STATUSES = ("ok", "partial", "missing", "n/a")
# 表の状態で門を落とすもの。missing は 2026-10-06 に0になった（業種ハブ・用語集を全方式へ、WordPress の表示速度を
# mu-plugin で）ので、新しく missing を作ったら落とす。partial も無くなったら ("missing", "partial") にする
FAIL_ON = ("missing",)
# build.py・publish.py が読み込むが、機能ではなく道具立てのもの（表に載せない）
PLUMBING = {"md2html": "Markdown→HTML の変換", "sites": "サイト設定の読み込み",
            "private_store": "非公開のデータ（お客様の情報・料金・レポート）の読み書き"}
# 配信方式の値を持つ変数名（他の辞書の "type" と取り違えない）
CFG_NAMES = {"cfg", "c", "_cfg", "conf"}


def load():
    return json.loads(CAPS.read_text(encoding="utf-8"))


def _is_type_of_cfg(node):
    """cfg["type"] / cfg.get("type") / S.load(x).get("type") か"""
    if isinstance(node, ast.Subscript):
        sl = node.slice
        return (isinstance(sl, ast.Constant) and sl.value == "type"
                and isinstance(node.value, ast.Name) and node.value.id in CFG_NAMES)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "type"):
        r = node.func.value
        return ((isinstance(r, ast.Name) and r.id in CFG_NAMES)
                or (isinstance(r, ast.Call) and isinstance(r.func, ast.Attribute) and r.func.attr == "load"))
    return False


def type_literals(src):
    """配信方式と比べている文字列（cfg["type"] == "ftp"・in ("ftp", "zip") など）"""
    out = set()
    for n in ast.walk(ast.parse(src)):
        if not (isinstance(n, ast.Compare) and _is_type_of_cfg(n.left)):
            continue
        for comp in n.comparators:
            elts = comp.elts if isinstance(comp, (ast.Tuple, ast.List, ast.Set)) else [comp]
            out |= {e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


def local_imports(src):
    """scripts/ にある自前のモジュールのうち、読み込んでいるもの"""
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            mods.add(n.module.split(".")[0])
    return {m for m in mods if (ROOT / "scripts" / f"{m}.py").is_file() or (ROOT / "scripts" / m).is_dir()}


def cell_problems(caps):
    """表の形の誤り（抜けた組み合わせ・知らない状態・根拠の行が無い・要るものが書かれていない）"""
    bad = []
    methods = list(caps.get("methods") or {})
    for fid, f in (caps.get("features") or {}).items():
        for e in f.get("entry") or []:
            if not (ROOT / e).exists():
                bad.append(f"{fid}: 入口 {e} がありません")
        cells = f.get("cells") or {}
        for m in methods:
            c = cells.get(m)
            if not c:
                bad.append(f"{fid} × {m}: 判定がありません")
                continue
            if c.get("status") not in STATUSES:
                bad.append(f"{fid} × {m}: 状態 {c.get('status')!r} は {STATUSES} のどれでもない")
            ev = str(c.get("evidence") or "")
            mm = re.fullmatch(r"(.+):(\d+)", ev)
            if not mm or not (ROOT / mm.group(1)).is_file():
                bad.append(f"{fid} × {m}: 根拠 {ev!r} が「ファイル:行」になっていないか、ファイルがありません")
            else:
                n = len((ROOT / mm.group(1)).read_text(encoding="utf-8-sig").splitlines())
                if not 1 <= int(mm.group(2)) <= n:
                    bad.append(f"{fid} × {m}: 根拠 {ev} の行がありません（{n}行）")
            if c.get("status") in ("partial", "missing") and not str(c.get("need") or "").strip():
                bad.append(f"{fid} × {m}: {c.get('status')} なのに要るもの（need）が書かれていません")
        extra = set(cells) - set(methods)
        if extra:
            bad.append(f"{fid}: 方式の一覧に無い列 {sorted(extra)}")
    return bad


def test_capability_matrix_covers_every_method_and_feature():
    import client_add
    import client_intake
    import deliver_files
    import site_change
    import sites as S
    print("\n■ 配信方式 × 機能の表（data/capabilities.json）が方式と機能を覆う")
    caps = load()
    methods = set(caps["methods"])

    # 検出器が効くか（効かないまま「抜けなし」と言わない）
    check("検出器: cfg[\"type\"] == と in (…) と S.load(x).get(\"type\") の値を拾う",
          type_literals('if cfg["type"] == "s3": pass\nif c.get("type") in ("a", "b"): pass\n'
                        'if S.load(x).get("type") != "z": pass'), {"s3", "a", "b", "z"})
    check("検出器: 他の辞書の \"type\"（動画の板など）は拾わない",
          type_literals('if bd.get("type") == "cover": pass\nif d["type"] == "table": pass'), set())
    check("検出器: 自前のモジュールの読み込みを拾う（外のライブラリは拾わない）",
          local_imports("import json\nimport sites as S\nfrom publish import gate_ok\n"), {"sites", "publish"})
    bad = cell_problems({"methods": {"ftp": "", "zip": ""}, "features": {
        "x": {"entry": [], "cells": {"ftp": {"status": "partial", "evidence": "scripts/sites.py:1"}}}}})
    check("検出器: 抜けた組み合わせと need の無い partial を拾う", len(bad), 2)

    check("方式の一覧は client_add.TYPES と同じ（シートで選べる方式がすべて表にある）",
          sorted(methods), sorted(client_add.TYPES))
    check("ヒアリングシートも同じ方式の一覧を使う", client_intake.TYPES is client_add.TYPES, True)
    used = set()
    for p in sorted((ROOT / "scripts").rglob("*.py")):
        used |= type_literals(p.read_text(encoding="utf-8-sig"))
    check("コードの分岐から方式を拾えている（空振りで「抜けなし」と言わない）",
          {"ftp", "zip", "wordpress", "nextjs-json"} <= used, True)
    used |= set(deliver_files.TYPES) | set(site_change.GIT_TYPES)
    check("コードが分岐している方式は、すべて表にある", sorted(used - methods), [])
    check("sites/*.json の方式は、すべて表にある",
          sorted({c.get("type") for c in S.load_all().values()} - methods), [])
    check("表の形（全方式×全機能・状態・根拠の行・要るもの）", cell_problems(caps), [])

    entries = {e for f in caps["features"].values() for e in f.get("entry") or []}
    for name in ("build.py", "publish.py"):
        mods = local_imports((ROOT / "scripts" / name).read_text(encoding="utf-8-sig"))
        miss = sorted(m for m in mods - set(PLUMBING)
                      if f"scripts/{m}.py" not in entries and f"scripts/{m}" not in entries)
        check(f"{name} が読み込む機能は、どれかの機能の入口として表にある（足したら表にも足す）", miss, [])

    count = {m: Counter(f["cells"][m]["status"] for f in caps["features"].values()) for m in caps["methods"]}
    print(f"  機能 {len(caps['features'])} × 方式 {len(methods)}")
    for m, c in count.items():
        print(f"  {m:14s} ok {c['ok']:2d} / partial {c['partial']:2d} / missing {c['missing']:2d} / n/a {c['n/a']:2d}")
    print(f"  合計: missing {sum(c['missing'] for c in count.values())} / partial {sum(c['partial'] for c in count.values())}"
          f"（FAIL_ON={FAIL_ON or 'なし。数を記録するだけ'}）")
    failing = sorted(f"{fid} × {m}" for fid, f in caps["features"].items()
                     for m, c in f["cells"].items() if c["status"] in FAIL_ON)
    check(f"表に {FAIL_ON} が残っていない", failing, [])

    # 方式ではなく、ワークフローがサイトIDを直書きして回しているせいで、お客様の社が漏れる工程
    ids = set(S.load_all())
    hard = []
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*for s in ([a-z0-9 -]+); do", line)
            if m and len(set(m.group(1).split()) & ids) >= 2:
                hard.append(f"{p.name}:{i}")
    if hard:
        print(f"  WARN  サイトIDを直書きして回すワークフロー（お客様の社が回らない）: {len(hard)}件  " + " / ".join(hard))


def test_capability_evidence_lines_match_anchors():
    import tempfile
    from pathlib import Path
    import caps_anchor as CA
    print("\n■ 方式×機能の表の根拠の行が、記録した行の中身（anchor）と一致する（ずれたら caps_anchor.py --write）")

    # 検出器が効くか（偽のファイルで、行を足す・同じ中身の行が2つある・行を消す）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = ["def a():", "    return 1", "", "def b():", "    x = 1", "}", "", "def c():", "    y = 2", "}"]
        (root / "f.py").write_text("\n".join(src) + "\n", encoding="utf-8")
        lines = CA.read_lines("f.py", root=root)
        caps = {"features": {"x": {"cells": {"m1": {"evidence": "f.py:4"}, "m2": {"evidence": "f.py:10"}}}}}
        for c in caps["features"]["x"]["cells"].values():
            c.update(CA.make_anchor(lines, int(c["evidence"].split(":")[1])))
        check("検出器: 同じ中身の行（「}」）は直前の行まで記録する",
              caps["features"]["x"]["cells"]["m2"].get("anchor_prev"), ["y = 2"])
        check("検出器: 行が動いていなければ何も言わない", CA.run(caps, root=root), ([], []))
        (root / "f.py").write_text("\n".join(["import os", "", "", ""] + src) + "\n", encoding="utf-8")
        _, todo = CA.run(json.loads(json.dumps(caps)), root=root)
        check("検出器: 上に行が増えたらずれを知らせる", len(todo), 2)
        fixed, todo = CA.run(caps, write=True, root=root)
        check("検出器: --write で中身から引き直す（同じ「}」が2つあっても直前の行で決める）",
              ([c["evidence"] for c in caps["features"]["x"]["cells"].values()], todo), (["f.py:8", "f.py:14"], []))
        (root / "f.py").write_text("\n".join(x for x in src if x != "def b():") + "\n", encoding="utf-8")
        _, todo = CA.run(caps, write=True, root=root)
        check("検出器: 根拠の行が消えたら探し直せない（判定を見直す要対応）", ["見つかりません" in t for t in todo], [True])

    caps = load()
    missing = sorted(f"{fid} × {m}" for fid, f in caps["features"].items() for m, c in f["cells"].items() if not c.get("anchor"))
    check("表の全セルが根拠の行の中身（anchor）を持つ（python scripts/caps_anchor.py --write で付く）", missing, [])
    _, todo = CA.run(caps)
    check("根拠の行が記録した中身と一致する（ずれたら python scripts/caps_anchor.py --write で引き直し、"
          "見つからないセルは判定を見直す）", todo, [])
