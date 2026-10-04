# -*- coding: utf-8 -*-
"""業種別の調査を note の下書きと掛け合い動画に回す（2026-10-05）。

見本で「数字が headline 以外から入らない・ChatGPT がそろわない業種は出さない・一律の言い方をしない・
社名とURLが入る」を確かめる。claude・TTS・YouTube は呼ばない。
"""
import json
from datetime import date

from test_gates import check, ROOT


def _summaries():
    out = {}
    for f in sorted((ROOT / "data" / "research").glob("*-summary.json")):
        out[f.name[:-len("-summary.json")]] = json.loads(f.read_text(encoding="utf-8"))
    return out


def test_research_promo_note():
    import research_promo as RP
    print("\n■ 調査の note 下書き（2026-10-05）")
    sums = _summaries()
    inds = RP.industries()
    want = sorted(k for k, s in sums.items()
                  if s.get("per_answer") and (s.get("answered") or {}).get("ChatGPT", 0) * 2 >= s.get("questions", 0) > 0)
    check("出す業種は ChatGPT の回答が質問数の半分以上そろった業種だけ", sorted(inds), want)
    short = [k for k, s in sums.items() if (s.get("answered") or {}).get("ChatGPT", 0) * 2 < s.get("questions", 0)]
    if short:
        check("そろっていない業種は下書きも動画の元も作らない",
              [k for k in short if RP.eligible(k) or RP.source(k)], [])

    bad = []
    for ind in inds:
        hl = RP.headline(ind)
        it = RP.note_item(ind)
        bad += [f"{ind}: {x}" for x in RP.check_item(it, hl)]
    check(f"下書きの数字は headline の値だけ・一律の言い方なし・社名/URL/調査日/質問数/AIあり（{len(inds)}業種）", bad, [])

    if not inds:
        return
    hl = RP.headline(inds[0])
    it = RP.note_item(inds[0])
    have = RP._nums(json.dumps(hl, ensure_ascii=False))
    nb = next(str(k) for k in range(901, 9999) if str(k) not in have)
    forged = json.loads(json.dumps(it))
    forged["posts"]["note"] += f"\n導入した事業者の{nb}社で問い合わせが増えました。"
    check("headline に無い数字を足すと止める（検出器の確認）", any(nb in x for x in RP.check_item(forged, hl)), True)
    nourl = json.loads(json.dumps(it))
    nourl["posts"]["note"] = nourl["posts"]["note"].replace(hl["url"], "")
    check("調査ページのURLが無ければ止める", any(hl["url"] in x for x in RP.check_item(nourl, hl)), True)
    check("note の本文に社名が入る", RP.COMPANY in it["posts"]["note"], True)
    check("「04日」と「4日」は同じ数字に数える（隣を拾わない）", RP._nums("2026-10-04") == RP._nums("2026年10月4日"), True)

    even = dict(hl, verdict="even")
    portal = dict(hl, verdict="portal")
    owner = dict(hl, verdict="owner")
    T = hl["T"]
    check("「業種を問わず」は判定によらず止める", bool(RP.uniform_ng("業種を問わず、出典は同じでした。", portal)), True)
    check("どちらとも言えない業種で「ポータルが中心」は止める", bool(RP.uniform_ng("ポータルが中心です。", even)), True)
    check("公式が多い業種で「ポータルのほうが多い」は止める",
          bool(RP.uniform_ng(f"{T['portal']}のほうが多く使われていました。", owner)), True)
    check("ポータルが多い業種の正しい言い方は通す（隣を拾わない）",
          RP.uniform_ng(f"{T['portal']}のほうが多く使われていました。", portal), [])
    check("出典の割合を並べるだけの文は通す",
          RP.uniform_ng(f"出典の{hl['lp']}%が{T['portal']}、{hl['lc']}%が{T['owner_site']}でした。", even), [])
    # 判定と文の向きがずれていないか（全業種の下書きで）
    for ind in inds:
        h = RP.headline(ind)
        if h["verdict"] != "portal":
            check(f"{ind}: 判定が portal でない業種の下書きに「{h['T']['portal']}のほうが多く」が無い",
                  f"{h['T']['portal']}のほうが多く" in RP.note_text(h), False)


def test_research_promo_video():
    import duo_video as DV
    import research_promo as RP
    import youtube_upload as YU
    print("\n■ 調査の掛け合い動画（2026-10-05）")
    inds = RP.industries()
    if not inds:
        return
    ind = inds[0]
    art = DV.article(RP.PREFIX + ind)
    hl = RP.headline(ind)
    check("動画の元の文章は headline の要点を含む", all(x in art["text"] for x in RP.facts(hl)), True)
    check("調査ページの「4つのAI」を台本の根拠にしない", "4つのAI" in art["text"] and hl["n_engines"] != 4, False)
    have = set(DV._nums(art["text"]))
    nb = next(str(k) for k in range(901, 9999) if str(k) not in have)
    lines = ([{"who": "K", "text": "はじめまして。", "board": {"type": "cover"}},
              {"who": "N", "text": f"{RP.COMPANY}の調査です。"}]
             + [{"who": "N", "text": f"質問は{hl['questions']}問です。"}] * 33
             + [{"who": "N", "text": "詳しくは調査ページにまとめています。", "board": {"type": "end"}}])
    good = {"listener_role": "経営者", "lines": lines}
    check("社名を名乗る正しい台本は通す（別サイトの名前と取り違えない）", DV.validate(good, art), [])
    forged = json.loads(json.dumps(good))
    forged["lines"][5]["text"] = f"導入した{nb}社で成果が出ました。"
    check("調査に無い数字の台本は捨てる（記事と同じ強さ）", any(nb in x for x in DV.validate(forged, art)), True)
    tone = json.loads(json.dumps(good))
    tone["lines"][6]["text"] = "業種を問わず、ポータルが中心です。"
    check("一律の言い方の台本は捨てる", any("一律" in x for x in DV.validate(tone, art)), True)
    check("調査の台本は調査用の指示で書かせる", "--- 調査 ---" in DV.RESEARCH_PROMPT and "一律" in DV.RESEARCH_PROMPT, True)

    desc, title, _ = YU.describe(RP.PREFIX + ind)
    check("説明欄の先頭に調査ページのURL", desc.splitlines()[1] == hl["url"], True)
    check("説明欄と題に社名", RP.COMPANY in desc and RP.COMPANY in title, True)
    check("説明欄の数字は headline の値だけ", RP.number_ng(desc, hl), [])
    check("上げ先はAI集客ラボのチャンネル（クライアントの鍵に落とさない）", YU.site_of(RP.PREFIX + ind), "ai-lab")


def test_research_video_slot():
    import article_videos as AV
    import research_promo as RP
    print("\n■ 調査の動画は記事動画の枠と置き換える（2026-10-05）")
    inds = RP.industries()
    if not inds:
        return
    today = date(2026, 10, 5)
    check("今週まだ無ければ1本出す", AV.research_due({}, 1, today) in inds, True)
    recent = {RP.PREFIX + inds[0]: {"date": "2026-10-01", "kind": "research"}}
    check("今週もう上げていれば出さない（週1本まで）", AV.research_due(recent, 1, today), None)
    old = {RP.PREFIX + inds[0]: {"date": "2026-09-20", "kind": "research"}}
    nxt = AV.research_due(old, 1, today)
    check("翌週は別の業種（1業種1回）", nxt != inds[0] and (nxt in inds or len(inds) == 1), True)
    check("--research 0 なら出さない", AV.research_due({}, 0, today), None)
    import inspect
    src = inspect.getsource(AV.main)
    check("記事動画の本数を増やさず置き換える（rows[:limit - 1] + 調査）", "rows[:a.limit - 1]" in src, True)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が note の下書きを積む（止めない）", "research_promo.py --note" in wf and "research_promo.py --note --limit 2 || true" in wf, True)
    dv = (ROOT / ".github" / "workflows" / "daily-video.yml").read_text(encoding="utf-8")
    check("日次の動画が調査を週1本混ぜる", "--research 1" in dv, True)
