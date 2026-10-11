# -*- coding: utf-8 -*-
"""2026-10-11 点検の指摘。学びの台帳（data/lessons.jsonl）は公開側で追跡していて、以後の全社の AI の指示に入る。
全社に効く学びに入ったお客様の記事の題・slug は lessons._scrub が伏せていたが、照らし方が門と違った。

  - 大文字小文字を区別する単純な置き換えだった。門 h77（find_identity）と CI のログの見張り（log_leak_check）は
    大文字小文字を問わないので、大文字の slug が伏せ漏れになり、門が後から見つける形だった
  - 伏せる語が取れない（非公開のデータが無い・例外）と、黙って伏せずに保存していた

決めたこと:
  1. 記事の題・slug は log_leak_check.word_rx（英数の語は前後の境目を見る）、名前・ドメインは門 h77 と同じ部分一致で、
     どちらも大文字小文字を問わずに伏せる（門が数えるものは全部伏せる。別の slug・ふつうの文は伏せない）
  2. 伏せる語が取れない回は、公開の台帳に新しい行・書き換えた行を書かない（書き換えた行は公開の台帳の文のまま）。
     お客様の記事が source の行も書かない。書かなかった件数を出す（文は出さない）
架空の社（client-zz・zz-shoji.example）で確かめる
"""
import contextlib
import inspect
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

STUB = "c0a1b2c3d"
IDENT = {"client-zz": (["架空商事", "zz-shoji.example", "zz-shoji", "https://zz-shoji.example"],
                       ["zz-secret-slug", "架空の記事の題です"], "zz-shoji.example")}
WORDS = ("zz-secret-slug", "架空の記事の題です", "架空商事", "zz-shoji")
BAD = ["ZZ-SECRET-SLUG の題を直したら表示が戻った",
       "お客様の記事zz-secret-slugで、Zz-Secret-Slug と同じ失敗をした",
       "「架空の記事の題です」は 架空商事 の主力の語",
       "https://ZZ-SHOJI.EXAMPLE/blog/zz-secret-slug/ へ配信した",
       "問い合わせは info@Zz-Shoji.Example まで"]
GOOD = ["zz-secret-slugs を書いた（別の記事）",
        "zz-secret-slug-2 と xzz-secret-slug は別の slug",
        "kw_guard を先に回し、AI集客ラボの記事は食い合いを確かめる"]


def _row(i, rule, source="", **kw):
    return dict({"id": f"L{i:04d}", "at": "2026-10-11", "kind": "failure", "phase": "kw", "sites": [], "rule": rule,
                 "detail": rule, "gate": "", "source": source, "status": "active", "hits": 0}, **kw)


def _write(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))


def _read(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


@contextlib.contextmanager
def _world(base, stubs, ident=None, client_slugs=(), markers=None):
    """一時の場所に公開の台帳・sites/・空の非公開の置き場を置く。ident を渡せば伏せる語が取れる回、渡さなければ
    本物の ci_mask が一時の sites/ から語を作る（非公開のデータが無いので、お客様の印があれば取れない回）"""
    import ci_mask
    import client_private as CP
    import lessons as L
    import private_store as PS
    import sites as S
    src = base / "data" / "lessons.jsonl"
    sd = base / "sites"
    sd.mkdir(parents=True, exist_ok=True)
    for sid, cfg in stubs.items():
        (sd / f"{sid}.json").write_bytes(json.dumps(cfg).encode("utf-8"))
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": str(base / "private-none")}))
        st.enter_context(mock.patch.object(S, "SITES_DIR", sd))
        st.enter_context(mock.patch.object(CP, "ROOT", base))
        st.enter_context(mock.patch.object(L, "SRC", src))
        st.enter_context(mock.patch.object(L, "PUBLIC", src, create=True))
        st.enter_context(mock.patch.object(L, "HELD", [], create=True))
        st.enter_context(mock.patch.object(PS, "_CLIENT_SLUGS", set(client_slugs)))
        if ident is not None:
            # 非公開のデータが読めた回と同じ: 印の社の設定が読め、伏せる語が取れる
            st.enter_context(mock.patch.object(ci_mask, "identity_terms", lambda: ident))
            st.enter_context(mock.patch.object(S, "load_all", lambda: {
                "client-zz": {"id": "client-zz", "public_id": STUB, "client": True, "domain": "zz-shoji.example"}}))
            st.enter_context(mock.patch.object(CP, "markers", lambda: markers or {}))
        yield L, src


def test_lessons_scrub_hides_what_the_gates_find():
    print("\n■ 守秘義務: 学びの台帳の伏せ方は門と同じ（大文字小文字を問わない・語の境目を見る）。2026-10-11")
    import log_leak_check as LL
    import gates_history_h77 as G
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        rows = [_row(i, t) for i, t in enumerate(BAD + GOOD, 1)] + [_row(99, "ふつうの文", source="ZZ-SECRET-SLUG")]
        with _world(base, {STUB: {"id": STUB, "client": True}}, ident=IDENT, client_slugs=["zz-secret-slug"],
                    markers={"client-zz": ["zz-shoji.example", "架空商事"]}) as (L, src):
            L.save(rows)
            text = src.read_text(encoding="utf-8")
            got = {r["id"]: r for r in _read(src)}
    bad_ids = [f"L{i:04d}" for i in range(1, len(BAD) + 1)] + ["L0099"]
    good_ids = [f"L{i:04d}" for i in range(len(BAD) + 1, len(BAD) + len(GOOD) + 1)]
    check("悪い例: 大文字の slug・日本語に続く slug・題・URL の中のドメイン・社名を伏せる（伏せ漏れの行）",
          [i for i in bad_ids if any(w in json.dumps(got.get(i), ensure_ascii=False).lower() for w in WORDS)], [])
    check("お客様の記事が source の行は「お客様の記事」", got.get("L0099", {}).get("source"), "お客様の記事")
    check("良い例: 別の slug（後ろに文字・前に英字）・自社の語・ふつうの文は伏せない（変わった行）",
          [i for i in good_ids if got.get(i, {}).get("rule") != rows[int(i[1:]) - 1]["rule"]], [])
    raw = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    check("検出器の前提: 伏せる前の行は、門 h77 が名前と題・slug の両方で見つける",
          sorted({k for _f, k in G.find_identity(["data/lessons.jsonl"], IDENT, set(), read=lambda f: raw)}),
          ["社の名前・ドメイン", "記事の題・slug"])
    check("伏せた後の台帳は、門 h77 にも CI のログの見張りにも引っかからない",
          (G.find_identity(["data/lessons.jsonl"], IDENT, set(), read=lambda f: text),
           LL.scan(text, LL.patterns(IDENT))), ([], {}))
    pats = LL.patterns(IDENT)
    check("伏せる行 ＝ CI のログの見張りが数える行（同じ照らし方）",
          [t for t, i in zip(BAD + GOOD, bad_ids[:-1] + good_ids)
           if bool(LL.scan(t, pats)) != (got.get(i, {}).get("rule") != t)], [])
    import lessons as L
    check("照らす部品を二重に書かない（記事の題・slug は log_leak_check.word_rx を共有）",
          ("word_rx(" in inspect.getsource(LL.patterns), "LL.word_rx" in inspect.getsource(L)), (True, True))


def test_lessons_hold_rows_when_terms_are_missing():
    print("\n■ 守秘義務: 伏せる語が取れない回は、公開の台帳に新しい行・書き換えた行を書かず、件数を出す")
    import ci_mask
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        disk = [_row(1, "自社の決まり: kw_guard を先に回す"), _row(2, "別の決まり"),
                _row(3, "前から公開の台帳にある行", source="zz-secret-slug")]
        _write(base / "data" / "lessons.jsonl", disk)
        # お客様の印はあるが、非公開のデータが無い（CI で取れなかった回と同じ）
        stubs = {"own-x": {"id": "own-x", "domain": "own.example"}, STUB: {"id": STUB, "client": True}}
        with _world(base, stubs, client_slugs=["zz-secret-slug"]) as (L, src):
            rows = L.load()
            rows[0]["hits"] = 1                                       # 読まれた回数だけが変わった行
            rows[1]["rule"] = "ZZ-SECRET-SLUG の題を直した"            # 文を書き換えた行
            rows.append(_row(4, "新しい決まり Zz-Secret-Slug"))         # 新しい行
            rows.append(_row(5, "ふつうの文", source="zz-secret-slug"))  # お客様の記事が source の新しい行
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                held = L.save(rows)
            kept = _read(src)
            text = src.read_text(encoding="utf-8")
            again = L.add("failure", "kw", "新しい決まり Zz-Secret-Slug")[1]
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["lessons.py", "--add", "--rule", "ZZ-SECRET-SLUG の別の決まり"]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                L.main()
            after_main = src.read_text(encoding="utf-8")
        check("書くのは公開の台帳の文のままの行だけ（書き換えた行は元の文・読まれた回数は残す）",
              [(r["id"], r["rule"], r["hits"]) for r in kept],
              [("L0001", "自社の決まり: kw_guard を先に回す", 1), ("L0002", "別の決まり", 0)])
        check("保存しなかった件数を返し、件数だけを出す（文・slug は出さない）",
              (held, "4件を保存しませんでした" in err.getvalue(), "zz-secret" in err.getvalue().lower()),
              (4, True, False))
        check("公開の台帳にお客様の slug が残らない", "zz-secret-slug" in text.lower(), False)
        check("同じ実行の中で、保存しなかった学びを二重に積まない", again, False)
        check("--add で保存しなかったときは、文を出さずに知らせる（台帳は変えない）",
              ("保存しませんでした" in out.getvalue(), "zz-secret" in out.getvalue().lower(), after_main == text),
              (True, False, True))
        # 語が取れない判定は最後に確かめる（上の振る舞いの検査を先に記録する）
        with _world(base, stubs) as (L, src):
            terms = L._terms()
            with mock.patch.object(ci_mask, "identity_terms", side_effect=RuntimeError("壊れた")):
                broken = L._terms()
    check("非公開のデータが無い・例外のときは「語が取れない」（黙って伏せずに保存しない）", (terms, broken), (None, None))
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write(base / "data" / "lessons.jsonl", [_row(1, "自社の決まり")])
        # お客様の社が無い（伏せる語が無いのは正しい）回は、これまでどおり新しい学びを書く
        with _world(base, {"own-x": {"id": "own-x", "domain": "own.example"}}) as (L, src):
            terms = L._terms()
            held = L.save(L.load() + [_row(2, "自社だけの新しい決まり")])
            ids = [r["id"] for r in _read(src)]
    check("良い例: お客様の社が無い回は伏せる語が無いだけで、新しい学びを書く", (terms, held, ids),
          ((None, {}), 0, ["L0001", "L0002"]))
