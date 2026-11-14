"""1位を狙う語の台帳を、AI集客ラボだけでなく全部のサイトに広げる（2026-11-15 運用者「AI集客ラボだけではなくすべてラッコして」）。
前は「業種×サービス」の組の語しか拾わず、「経理代行 費用」「AIO対策 会社」のような業種を含まない買い手の語
（コーポレート・補助金では一番大きい語）が台帳に入らなかった。key_queries.general で「業種なし」の組を持てるようにし、
業種は key_queries.industries で kw_seeds.priority と別に決められるようにする"""
import json
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def _cfg(general=True):
    kq = {"max": 40, "per_group": [3, 5], "industries": ["建設業"],
          "industry_terms": {"建設業": ["建設業", "建設会社"]},
          "services": {"経理代行": {"terms": ["経理代行", "経理 外注"], "seed": "経理代行"}},
          "buyer_words": ["費用", "会社", "比較"]}
    if general:
        kq["general"] = "業種なし"
    return {"kw_seeds": {"priority": ["飲食店"]}, "key_queries": kq}


def test_ledger_general_group_and_industry_override():
    import key_queries as K
    print("\n■ 台帳: 業種を含まない買い手の語の組（業種なし）と、台帳だけの業種の指定")
    conf = K.ledger_conf(_cfg())
    check("業種は key_queries.industries を使う（kw_seeds.priority より優先）＋業種なし",
          [i for i, _w in conf["industries"]], ["建設業", "業種なし"])
    check("業種を含まない語は「業種なし」の組に入る", K.group_of("経理代行 費用", conf), ("業種なし", "経理代行"))
    check("業種を含む語はその業種の組に入る（業種なしにしない）", K.group_of("建設業 経理代行 会社", conf), ("建設業", "経理代行"))
    check("general の無い社は今までどおり業種なしの組を作らない",
          K.group_of("経理代行 費用", K.ledger_conf(_cfg(general=False))), None)
    rows = K.build_ledger(_cfg(), {}, ["経理代行 料金"], {}, {}, today="2026-11-15")
    qs = {r["q"]: (r["ind"], r["svc"]) for r in rows}
    check("業種なしの組の組み合わせの語に業種名を入れない（「業種なし 経理代行 費用」にしない）",
          ("経理代行 費用" in qs, any(q.startswith("業種なし") for q in qs)), (True, False))
    check("候補の語（台帳のシート）も業種なしの組に入る", qs.get("経理代行 料金"), ("業種なし", "経理代行"))

    # 補助金の制度名「AI導入補助金」の「導入」が買い手の語に当たり、「飲食店 AI導入補助金で落ちる理由」が台帳に入った
    # （2026-11-15 運用者「買い手に響くキーワードで」）。サイトごとに判定から外す語（buyer_ignore）を持つ
    sub = {"kw_seeds": {}, "key_queries": {
        "max": 30, "per_group": [3, 5], "industries": ["飲食店"], "general": "業種なし",
        "services": {"AI導入補助金": {"terms": ["ai導入補助金"], "seed": "AI導入補助金"}},
        "buyer_words": ["申請代行", "相談"], "buyer_ignore": ["導入"]}}
    cands = ["飲食店 AI導入補助金で落ちる理由", "AI導入補助金 対象要件", "飲食店 AI導入補助金 申請代行", "AI導入補助金 相談"]
    got = [r["q"] for r in K.build_ledger(sub, {}, cands, {}, {}, today="2026-11-15")]
    check("買い手でない語（落ちる理由・対象要件）は、制度名の「導入」があっても入れない",
          [q for q in cands[:2] if q in got], [])
    check("依頼先を探す語（申請代行）と、設定した買い手の語（相談）は入れる", [q for q in cands[2:] if q in got], cands[2:])

    # 他社の名前・別の業種・地域を絞った語が GSC から入った（「meo対策 集客イノベーション」「家事代行 seo」「広島市中区 meo対策」）
    ex = dict(sub, key_queries=dict(sub["key_queries"], exclude=["家事代行", "市"]))
    got = [r["q"] for r in K.build_ledger(ex, {}, ["家事代行 AI導入補助金 申請代行", "大阪市 AI導入補助金 申請代行"],
                                          {}, {}, today="2026-11-15")]
    check("外す語（key_queries.exclude）を含む候補は台帳に入れない", got and [q for q in got if "家事代行" in q or "市 " in q], [])

    sites = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "sites").glob("*.json")}
    # 対象は AI集客ラボ・コーポレート・コンフレックス（非公開の置き場の設定）。補助金は対象外（2026-11-15 運用者「補助金はいらない」）
    check("補助金のサイトには台帳を作らない", bool((sites["subsidy"].get("key_queries") or {}).get("services")), False)
    for sid in ("ai-lab", "corporate"):
        kq = sites[sid].get("key_queries") or {}
        check(f"{sid}: 台帳の設定（サービス・業種なしの組・買い手の語）がある",
              bool(kq.get("services") and kq.get("general") and kq.get("buyer_words")), True)
