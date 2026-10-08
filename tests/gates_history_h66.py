# -*- coding: utf-8 -*-
"""2026-10-08 CONFLUX の対策キーワードをラッコで出した（運用者の依頼）から。

- ヒアリングシートの「狙う語」（メイン5・サブ15・狙わない語11）は brief.json にだけ入り、計画（kw_plan）は
  業種×意図しか見ていなかった。「システム開発 外注」「AI エージェント 導入」が1語も起点にならず、狙わない語も効いていなかった
- 空白を含む owns（「AI エージェント」「Excel 脱却」）が、1語ずつ比べる判定でどの語にも当たらず、
  「aiエージェント 費用」が領域語なしで落ちていた
- CONFLUX の owns の「外注・見積もり・保守」が、他の3サイトの除外語に入り「経理 外注」「seo 外注」を落とし、
  CONFLUX の側では「美容 師 外注 源泉」「高須 クリニック 見積もり」を領域の語として通していた
- 週次の補充（kw_discover）が業種×汎用語（相場・費用）で語を通し、CONFLUX の台帳に「建設業 役員報酬 相場」
  「工務店 値引き 相場」が30本積まれた
- 主題の候補（client_intake.subjects）が狙わない語「AI 導入補助金」の「AI」1語で AI の語を全部消していた
- 計画にページの題（「ai エージェント 導入 開発 運用 トータル ガイド」）と補助金の制度名（「中小企業 ai導入支援」）が入った
- dry-run と見積もりが本番と違う中身で控えを引いていたため、取得済みの問い合わせも課金と数え、
  dry-run では控えの応答を使えず「課金なしで条件を直す」ができなかった
- 一新（--replace）がシートに書いた語（検索数0）まで取り下げるところだった
"""
import contextlib
import json
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


def _conflux():
    import kw_discover as KD
    import kw_plan as P
    S = KD.site_config("conflux")
    S["sheet"], S["sheet_ng"] = P.sheet_terms("conflux")
    return S


def test_kw_plan_uses_the_hearing_sheet_keywords():
    print("\n■ ヒアリングシートの狙う語が計画の起点と条件に入る（CONFLUX）")
    import kw_plan as P
    S = _conflux()
    check("シートのメインKWが起点に入る", {"AI エージェント 導入", "システム開発 外注"} <= set(S["sheet"]), True)
    check("シートのサブKWが起点に入る", "Excel 業務 システム化" in S["sheet"], True)
    check("シートの狙わない語が除外に入る", "AI 導入補助金" in S["sheet_ng"], True)
    cases = {
        "aiエージェント 費用": "",                     # 空白を含む owns が当たる
        "ai エージェント 導入 事例": "",
        "問い合わせ対応 自動化 ai": "",                # owns に無くてもシートの語なら領域
        "excel 業務 システム化 メリット": "",
        "ai 導入 費用 中小企業": "",                   # 「AI 導入補助金」の1語だけでは落とさない
        "ai 導入補助金 2026": "狙わない語",
        "it導入補助金 システム開発": "狙わない語",
        "美容 師 外注 源泉": "領域語なし",             # 頼み方の語は領域の語ではない
        "高須 クリニック 見積もり": "領域語なし",
        "建設業 役員報酬 相場": "領域語なし",
        "システム開発 外注費 勘定科目": "除外語",      # 会計処理の調べ物（sites/conflux.json の ng_terms）
        "システム開発 求人": "見込み客でない",
        # 運用者の判断（2026-10-08）: ページの題と、補助金の制度名（中小企業デジタル化・AI導入支援事業）は入れない
        "ai エージェント 導入 開発 運用 トータル ガイド": "題のような語",
        "中小企業 ai導入支援": "除外語",
        "中小 企業 ai 導入 支援": "除外語",
    }
    for kw, want in cases.items():
        check(f"CONFLUX: {kw}", P.cheap_reject({"kw": kw}, S), want)

    # 業種名は聞ける形にして掛ける。「人材派遣・紹介 システム開発」と打つ人はいない
    check("業種名の「・」以降を外す", P.ind_query("人材派遣・紹介"), "人材派遣")
    check("業種名の括弧を外す", P.ind_query("飲食（多店舗）"), "飲食")
    check("優先業種の加点が「人材派遣」の語にも付く",
          P.score({"kw": "人材派遣 システム開発", "vol": 50, "kd": 10, "subject": "x"}, ["人材派遣・紹介"])
          > P.score({"kw": "人材派遣 システム開発", "vol": 50, "kd": 10, "subject": "x"}, ["製造業"]), True)

    # 業種起点のサイトは core を書く（無いと owns の先頭4語「ai エージェント・業務自動化・ai 自動化・rag」を掛けていた）
    cfg = json.loads((ROOT / "sites" / "conflux.json").read_text(encoding="utf-8"))
    core = cfg.get("kw_seeds", {}).get("core") or []
    owns = {o.lower() for o in cfg.get("owns", [])}
    check("CONFLUX: kw_seeds.core がある", len(core) >= 2, True)
    check("CONFLUX: core は owns の語", [c for c in core if c.lower() not in owns], [])

    # 見積もりにシートの語の問い合わせ（関連語＋サジェスト）が入る。課金の前に数えるため
    T = {"cfg": {"kw_seeds": {"core": ["集客"]}}, "own_terms": ("aio",), "industries": ["人材派遣・紹介"],
         "intents": [], "sheet": ["門の検査用の語 h66"]}
    with _empty_cache():
        # 一括調査は登録のやり直し1回ぶんを足して 15×2（rakko の上限の見積もり。gates_history_h67）
        check("見積もりにシートの語の問い合わせを数える", P.estimate(T), 3 * 1.5 + 2 * 15)
        check("シートの語の問い合わせは予備の枠で見積もる", P.estimate_parts(T).get("reserve"), 3 * 1.5)
        check("業種は聞ける形で問い合わせる", [b["keyword"] for _, b in P.paid_queries(T)][-1], "人材派遣 集客")
    check("シートの語そのものは一括調査に必ず送る",
          P.worth_lookup([{"kw": "x a"}, {"kw": "業務自動化 ai", "src": {"sheet"}}])[0]["kw"], "業務自動化 ai")
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("計画の実行でシートの語を読む", 'S["sheet"], S["sheet_ng"] = sheet_terms(site_id)' in src, True)
    # AI集客ラボは AI への質問の形（長い1語）を狙っている。題の判定に巻き込まない
    check("AIへの質問の形は題とみなさない", P.title_like("大阪でmeoとaioの両方を支援してくれる会社を教えてください。"), False)

    # --replace でも、シートに書いた語は検索数0でも取り下げない（週次補充の関係ない語だけを外す）
    retire, keep = P.split_retire(["建設業 役員報酬 相場", "Excel 業務 システム化"], ["RAG 導入"],
                                  {P.norm("Excel 業務 システム化")})
    check("一新でシートの語は残す", (retire, keep), (["建設業 役員報酬 相場"], ["Excel 業務 システム化"]))
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


def test_shared_request_words_are_not_another_sites_domain():
    print("\n■ 頼み方の語（外注・見積もり・保守）は、どのサイトの領域でも除外語でもない")
    import kw_discover as KD
    import kw_plan as P
    for sid in ("corporate", "ai-lab", "subsidy"):
        S = KD.site_config(sid)
        check(f"{sid}: 外注・見積もり・保守を除外語にしない",
              [t for t in ("外注", "見積もり", "保守") if t in S["ng_terms"]], [])
    check("コーポレート: 経理 外注 費用 を落とさない", P.cheap_reject({"kw": "経理 外注 費用"}, KD.site_config("corporate")), "")
    check("AI集客ラボ: seo 外注 を落とさない", P.cheap_reject({"kw": "seo 外注 費用"}, KD.site_config("ai-lab")), "")
    check("CONFLUX: 頼み方の語を領域の語にしない",
          [t for t in KD.site_config("conflux")["own_terms"] if t in KD.SHARED_TERMS], [])


def test_kw_discover_needs_a_domain_word():
    print("\n■ 週次の補充は、業種名と汎用語（相場・費用）だけの語を積まない")
    import kw_discover as KD
    check("空白の有無を問わず領域の語に当たる", KD.has_term("aiエージェント 費用", ("ai エージェント",)), True)
    check("領域の語が無ければ当たらない", KD.has_term("建設業 役員報酬 相場", KD.site_config("conflux")["own_terms"]), False)
    src = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("業種の経路で汎用語を領域の語として使わない", "domain_terms" in src, False)
    check("採用はすべて担当領域の語で判定する", src.count('has_term(low, S["own_terms"])'), 5)


def test_intake_subjects_exclude_by_phrase():
    print("\n■ 主題の候補は、狙わない語の言葉が全部入ったときだけ捨てる")
    import client_intake as ci
    nl = chr(10)
    got = {"kw.main": "AI エージェント 導入", "kw.sub": "AI 導入補助金 申請" + nl + "生成AI 社内ルール",
           "kw.exclude": "AI 導入補助金" + nl + "M&A", "kw_seeds.intents": "費用", "kw_seeds.industries": "製造業"}
    subs = [x["keyword"] for x in ci.subjects(got)]
    check("AI の語が残る", {"生成AI 社内ルール", "AI エージェント 導入 費用"} <= set(subs), True)
    check("狙わない語そのものは捨てる", [s for s in subs if "補助金" in s], [])


def test_client_kw_plan_stays_out_of_git():
    print("\n■ お客様の計画とラッコの控えは public のリポジトリに入らない")
    for rel in ("docs/kw-plan-conflux.md", "docs/kw-plan-conflux.dry.md",
                "data/rakko_cache/0000.json", "data/rakko_volume.json", "data/rakko_spend.jsonl"):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel])
        check(f"Git に入らない: {rel}", r.returncode, 0)
