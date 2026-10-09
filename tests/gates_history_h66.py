# -*- coding: utf-8 -*-
"""2026-10-08 お客様の社の対策キーワードをラッコで出した（運用者の依頼）から。

- ヒアリングシートの「狙う語」（メイン・サブ・狙わない語）は brief.json にだけ入り、計画（kw_plan）は
  業種×意図しか見ていなかった。シートの語が1語も起点にならず、狙わない語も効いていなかった
- 空白を含む owns が、1語ずつ比べる判定でどの語にも当たらず、領域語なしで落ちていた
- お客様の owns（頼み方の語）が他の3サイトの除外語に入り、自社の語を落としていた
- 週次の補充（kw_discover）が業種×汎用語（相場・費用）で語を通し、台帳に関係ない語が30本積まれた
- 主題の候補（client_intake.subjects）が狙わない語の1語で、関係する語まで全部消していた
- 計画にページの題（6語以上）と補助金の制度名が入った
- dry-run と見積もりが本番と違う中身で控えを引いていたため、取得済みの問い合わせも課金と数え、
  dry-run では控えの応答を使えず「課金なしで条件を直す」ができなかった
- 一新（--replace）がシートに書いた語（検索数0）まで取り下げるところだった

お客様の社の狙う語・除外語に依る門は、非公開のリポジトリの tests/gates_client_*.py にある（public に預かった語を
書かない。2026-10-10 運用者の指示・gates_history_h76）。ここに残すのは、架空の語で確かめられる仕組みの門だけ。
"""
import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def _empty_cache():
    """ラッコの控えの置き場を空の一時フォルダに替える（手元の控えに左右されない・本物の控えに書かない）"""
    import rakko
    saved = rakko.CACHE_DIR
    rakko.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        yield
    finally:
        rakko.CACHE_DIR = saved


def test_kw_plan_uses_the_hearing_sheet_keywords():
    print("\n■ ヒアリングシートの狙う語が計画の起点と条件に入る（仕組み。お客様の語は非公開の門）")
    import kw_plan as P
    # 業種名は聞ける形にして掛ける。「介護・福祉 システム開発」と打つ人はいない
    check("業種名の「・」以降を外す", P.ind_query("介護・福祉"), "介護")
    check("業種名の括弧を外す", P.ind_query("小売（多店舗）"), "小売")
    check("優先業種の加点が「介護」の語にも付く",
          P.score({"kw": "介護 業務 改善", "vol": 50, "kd": 10, "subject": "x"}, ["介護・福祉"])
          > P.score({"kw": "介護 業務 改善", "vol": 50, "kd": 10, "subject": "x"}, ["製造業"]), True)

    # 見積もりにシートの語の問い合わせ（関連語＋サジェスト）が入る。課金の前に数えるため
    T = {"cfg": {"kw_seeds": {"core": ["集客"]}}, "own_terms": ("aio",), "industries": ["介護・福祉"],
         "intents": [], "sheet": ["門の検査用の語 h66"]}
    with _empty_cache():
        # 一括調査は登録のやり直し1回ぶんを足して 15×2（rakko の上限の見積もり。gates_history_h67）
        check("見積もりにシートの語の問い合わせを数える", P.estimate(T), 3 * 1.5 + 2 * 15)
        check("シートの語の問い合わせは予備の枠で見積もる", P.estimate_parts(T).get("reserve"), 3 * 1.5)
        check("業種は聞ける形で問い合わせる", [b["keyword"] for _, b in P.paid_queries(T)][-1], "介護 集客")
    check("シートの語そのものは一括調査に必ず送る",
          P.worth_lookup([{"kw": "x a"}, {"kw": "門の検査用 シート", "src": {"sheet"}}])[0]["kw"], "門の検査用 シート")
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("計画の実行でシートの語を読む", 'S["sheet"], S["sheet_ng"] = sheet_terms(site_id)' in src, True)
    check("シートの語は非公開の置き場の brief.json から読む", 'private_store.read_json(site_id, "brief.json"' in src, True)
    check("6語以上はページの題とみなす", P.title_like("門 検査 用 の 長い 題 ガイド"), True)
    # AI集客ラボは AI への質問の形（長い1語）を狙っている。題の判定に巻き込まない
    check("AIへの質問の形は題とみなさない", P.title_like("大阪でmeoとaioの両方を支援してくれる会社を教えてください。"), False)

    # --replace でも、シートに書いた語は検索数0でも取り下げない（週次補充の関係ない語だけを外す）
    retire, keep = P.split_retire(["門 業種 汎用 相場", "門 シート の 語"], ["門 残す 語"], {P.norm("門 シート の 語")})
    check("一新でシートの語は残す", (retire, keep), (["門 業種 汎用 相場"], ["門 シート の 語"]))
    check("一新にシートの語を渡す", 'replace_ledger(site_id, picked, retire_old=granted, sheet=S["sheet"])' in src, True)


def test_dry_run_reads_the_same_cache_as_the_paid_call():
    print("\n■ dry-run と見積もりは、本番と同じ中身で控えを引く（取得済みを課金と数えない・控えだけで組み直せる）")
    import kw_plan as P
    import rakko
    T = {"cfg": {"kw_seeds": {"core": ["門の検査用 h66"]}}, "own_terms": ("aio",), "industries": ["クリニック"], "intents": []}
    with _empty_cache():
        check("見積もりの問い合わせはサジェストと同じ中身", P.paid_queries(T)[0],
              (rakko.SUGGEST, rakko.suggest_body("クリニック 門の検査用 h66")))
        # 控えにある問い合わせは見積もりに数えない（本番と同じ鍵で引けている）
        rakko._cache_put(rakko.SUGGEST, rakko.suggest_body("クリニック 門の検査用 h66"), "POST",
                         {"result": True, "data": {"items": []}})
        check("控えにある問い合わせは課金と数えない", P.paid_queries(T), [])
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("kw_plan に問い合わせの中身を手で書かない", '"modes": ["google", "youtube"], "limit": 100}' in src, False)


def test_kw_discover_needs_a_domain_word():
    print("\n■ 週次の補充は、業種名と汎用語（相場・費用）だけの語を積まない")
    src = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("業種の経路で汎用語を領域の語として使わない", "domain_terms" in src, False)


def test_intake_subjects_exclude_by_phrase():
    print("\n■ 主題の候補は、狙わない語の言葉が全部入ったときだけ捨てる")
    import client_intake as ci
    nl = chr(10)
    got = {"kw.main": "門AI 検査 導入", "kw.sub": "門AI 補助金 申請" + nl + "生成門AI 社内ルール",
           "kw.exclude": "門AI 補助金" + nl + "M&A", "kw_seeds.intents": "費用", "kw_seeds.industries": "製造業"}
    subs = [x["keyword"] for x in ci.subjects(got)]
    check("狙わない語の1語では消さない", {"生成門AI 社内ルール", "門AI 検査 導入 費用"} <= set(subs), True)
    check("狙わない語そのものは捨てる", [s for s in subs if "補助金" in s], [])


def test_client_kw_plan_stays_out_of_git():
    print("\n■ お客様の計画とラッコの控えは public のリポジトリに入らない")
    for rel in ("docs/kw-plan-conflux.md", "docs/kw-plan-conflux.dry.md",
                "data/rakko_cache/0000.json", "data/rakko_volume.json", "data/rakko_spend.jsonl"):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel])
        check(f"Git に入らない: {rel}", r.returncode, 0)
