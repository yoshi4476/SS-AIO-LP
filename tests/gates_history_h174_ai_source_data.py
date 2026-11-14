"""AIに聞いた答えの記録（data/compete/<自社>/<年月>.json）から、一次データを2つ作る（2026-11-15 運用者「一次情報も作成して」）。
作った数字や体験は使えない。当社が実際にAIに聞いた答えを数えたものだけを、母数と測った日つきで出す。
  ai-shutten-no-shurui … AIの回答の出典URLの種類の内訳
  juni-to-ai-inyou     … 検索の順位の帯ごとに、自社のページが出典に入った回答の割合
お客様の社の記録は数えない（その社の数字を運用会社の一次データにしない）"""
from test_gates import check


def _rec(site, items):
    return {"site": site, "measured": "2026-11-01", "items": items}


def _item(pos, answers):
    """answers: [(エンジン, [URL...], 自社が入ったか)]"""
    return {"kw": "x", "pos": pos, "ai": {e: {"answered": True, "ours": ours, "urls": urls, "domains": []}
                                          for e, urls, ours in answers}}


def test_ai_source_datasets():
    import data_auto as DA
    import data_auto_more as DM
    print("\n■ 一次データ: AIに聞いた答えから、出典の種類と、順位ごとの出典入りの割合を作る")
    mine = {"ai.7senses.co.jp", "corp.7senses.co.jp", "lp.7senses.co.jp"}
    peer = [f"https://peer{i}.co.jp/a" for i in range(3)]
    ours = ["https://ai.7senses.co.jp/aio/x/"]
    gov = ["https://www.meti.go.jp/x"]
    # 60回答 × 出典5件 = 300件。10位以内の30回答のうち12回答で自社が入り、11位以下の30回答では3回答
    items = ([_item(5.0, [("Gemini", peer + ours + gov, True)])] * 12
             + [_item(5.0, [("Gemini", peer + gov + ["https://youtube.com/w"], False)])] * 18
             + [_item(25.0, [("Claude", peer + ours + gov, True)])] * 3
             + [_item(25.0, [("Claude", peer + gov + ["https://note.com/a"], False)])] * 27)
    recs = [_rec("ai-lab", items), _rec("cc0000000", items)]
    is_client = {"ai-lab": False, "cc0000000": True}.get

    ds = DM.ai_source_types(recs=recs, is_client=is_client, mine=mine)
    check("出典の種類: お客様の社の記録を数えない（母数は自社の300件だけ）", ds and ds["n"], 300)
    rows = {r["label"]: r for r in (ds or {}).get("rows", [])}
    check("出典の種類: 自社のページを分けて数える（15件）", rows.get("自社（セブンセンシズのサイト）", {}).get("num"), 15)
    check("出典の種類: 公的機関を分けて数える（60件）", rows.get("公的機関・学会・業界団体", {}).get("num"), 60)
    check("出典の種類: 割合は件数÷母数（%・小数1桁）", rows.get("公的機関・学会・業界団体", {}).get("value"), 20.0)
    check("出典の種類: 母数が下限に届かなければ作らない",
          DM.ai_source_types(recs=[_rec("ai-lab", items[:10])], is_client=is_client, mine=mine), None)

    check("順位と出典入り: 回答が下限（100）に届かなければ作らない", DM.ai_cite_by_rank(recs=recs, is_client=is_client), None)
    dr = DM.ai_cite_by_rank(recs=recs, is_client=is_client, min_n=50)
    rr = {r["label"]: r for r in (dr or {}).get("rows", [])}
    check("順位と出典入り: 10位以内は30回答中12回答（40%）", (rr.get("検索10位以内", {}).get("num"),
                                                rr.get("検索10位以内", {}).get("den"),
                                                rr.get("検索10位以内", {}).get("value")), (12, 30, 40.0))
    check("順位と出典入り: 11位以下は30回答中3回答（10%）", (rr.get("検索11位以下", {}).get("num"),
                                                rr.get("検索11位以下", {}).get("value")), (3, 10.0))
    # 10位以内は12回答、11位以下は8回答（3＋5）。8回答の帯は割合にしない
    few = DM.ai_cite_by_rank(recs=[_rec("ai-lab", items[:12] + items[30:33] + items[33:38])],
                             is_client=is_client, min_n=5)
    check("順位と出典入り: 母数が10未満の帯は割合にしない", [r["label"] for r in (few or {}).get("rows", [])],
          ["検索10位以内"])
    check("どちらも data_auto の切り口に入っている",
          {"AIの回答の出典の種類", "検索順位とAIの出典入り"} <= {n for n, _ in DA.BUILDERS}, True)
