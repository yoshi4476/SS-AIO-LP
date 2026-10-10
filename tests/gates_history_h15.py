# -*- coding: utf-8 -*-
"""これから作る動画の題・配分・ショートからの導線の門（2026-10-05）。

実測（公開中11本）: ショート5本は1本183〜543回再生、通常の動画6本は0〜1回。
通常の動画は YouTube のサジェストに記事の語が出るテーマだけ作り、題はその検索語を先頭にした問いの形にする。
ショートの説明欄の先頭に、同じ記事の通常の動画を置く。上げ済みの動画の題・説明は変えない。
本物の YouTube・claude・TTS は動かさない（サジェスト・台本・動画作り・アップロードは偽物に差し替える）。
"""
import json
import sys
import types
from datetime import date

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _ledger():
    return json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8"))


def test_long_video_title_uses_youtube_search_term():
    print("\n■ 通常の動画の題（YouTube の検索語・記事に無い数字なし）")
    import yt_demand as YD
    art = YD.article("nougyou-shoki-hiyou-hojokin")
    have = YD._nums(art["text"])
    j = YD.judge("nougyou-shoki-hiyou-hojokin", art=art,
                 fetch=lambda q: ["農業 補助金 2031", "農業 ドローン 補助金", "農業 初期費用"])
    check("サジェストに近い検索語があれば通常の動画を作る", j["decision"], "make")
    check("題は検索語で始まる", j.get("title", "").startswith("農業 初期費用"), True)
    check("題は問いの形", "？" in j.get("title", ""), True)
    check("題に記事に無い数字が無い", YD._nums(j.get("title", "")) <= have, True)
    check("題は YouTube の上限（100字）以内", len(j.get("title", "")) <= 100, True)
    check("記事に無い数字を含む検索語は選ばない", YD.fits("農業 初期費用 2031", art["keyword"], art["text"]), None)
    check("記事に無い数字が入った題は通さない", bool(YD.title_ng("農業 初期費用は2031万円？", "農業 初期費用", art)), True)
    check("英字の手法名（aio）が欠けた語は選ばない（税理士 法人税法）",
          YD.fits("税理士 法人税法", "税理士 法人 aio", "税理士法人のAIO対策"), None)


def test_no_long_video_without_youtube_demand():
    print("\n■ YouTube で検索されないテーマは通常の動画を作らない（本数は増やさない）")
    import yt_demand as YD
    import article_videos as AV
    art = YD.article("nougyou-shoki-hiyou-hojokin")
    check("サジェストが空ならショートだけ（skip）", YD.judge("x", art=art, fetch=lambda q: [])["decision"], "skip")

    def down(q):
        raise OSError("network")
    check("サジェストが取れなければ決めない（unknown）", YD.judge("x", art=art, fetch=down)["decision"], "unknown")
    verdict = {"a": "skip", "b": "unknown", "c": "make", "d": "make"}
    make, skipped = AV.plan_long([{"slug": s, "site": "ai-lab"} for s in "abcd"], 1,
                                 lambda s: {"decision": verdict[s], "reason": ""})
    check("通常の動画の枠は検索語のある記事だけ・枠の本数まで", [r["slug"] for r in make], ["c"])
    check("見送った記事は記録し（unknown は記録しない）", [r["slug"] for r, _ in skipped], ["a"])
    make, skipped = AV.plan_long([{"slug": s, "site": "ai-lab"} for s in "ab"], 1,
                                 lambda s: {"decision": "skip", "reason": ""})
    check("全部見送りなら通常の動画は0本（別の動画で埋めない）", make, [])
    import inspect
    src = inspect.getsource(AV.main)
    check("見送りの記録には date・youtube を付けない（動画を上げた記事として数えない）",
          'ledger.setdefault(r["slug"], {"site": r["site"], "long": j})' in src, True)
    check("ショートの本数は引数のまま（見送った分を足さない）", "shorts(ledger, a.shorts, token, a.public)" in src, True)
    import video_embed as VE
    check("見送りの記録は記事への埋め込み対象にならない（youtube のある記録だけ）",
          'rec.get("youtube")' in inspect.getsource(VE.info), True)
    import outcome_watch as OW
    check("ショートだけの日も「動画が上がった日」に数える", "short" in inspect.getsource(OW.check_video), True)


class _Up:
    def __init__(self):
        self.calls = []

    def __call__(self, out, slug, **k):
        self.calls.append((slug, k))
        return "NEWSHORT"


def _run_shorts(ledger):
    import article_videos as AV
    import duo_short as DS
    import youtube_upload as YT
    saved = (DS.load_script, DS.make, YT.upload)
    up = _Up()
    DS.load_script = lambda slug: {"title": "テストの問い？", "lines": []}
    DS.make = lambda sc, out: 40.0
    YT.upload = up
    try:
        made = AV.shorts(ledger, 1, True, True)
    finally:
        DS.load_script, DS.make, YT.upload = saved
    return made, up


def test_short_description_leads_to_long_video():
    print("\n■ ショートの説明欄の先頭に、同じ記事の通常の動画")
    import youtube_upload as YT
    led = _ledger()
    slug = next(k for k, v in led.items() if v.get("youtube") and (ROOT / "articles" / f"{k}.md").is_file())
    desc, _, _ = YT.full_description(slug, short=True, lead_long=True)
    lines = desc.splitlines()
    check("1行目が「続きの解説（通常の動画）」", lines[0] if lines else "", "▶ 続きの解説（通常の動画）")
    check("2行目がその記事の通常の動画のURL", lines[1] if len(lines) > 1 else "", f"https://youtu.be/{led[slug]['youtube']}")
    check("続きのURLは1回だけ", desc.count(f"youtu.be/{led[slug]['youtube']}"), 1)
    # 通常の動画がある記事のショートは印を付けて上げる
    made, up = _run_shorts({slug: {"site": "ai-lab", "youtube": led[slug]["youtube"], "date": "2026-10-05"}})
    check("通常の動画がある記事のショートは lead_long で上げる", [k.get("lead_long") for _, k in up.calls], [True])
    # 通常の動画を作らなかった記事は、ショートだけを作る（続きのリンクは付けない）
    other = next(k for k, v in led.items() if k != slug and (ROOT / "articles" / f"{k}.md").is_file())
    lg = {other: {"site": "ai-lab", "long": {"decision": "skip", "date": date.today().isoformat()}}}
    made, up = _run_shorts(lg)
    check("見送った記事もショートの対象", (made, [s for s, _ in up.calls]), (1, [other]))
    check("通常の動画が無いショートは続きのリンクを付けない", [k.get("lead_long") for _, k in up.calls], [False])
    check("通常の動画が無いショートには印を付けない", "desc" in lg[other]["short"], False)
    two = {**{slug: {"site": "ai-lab", "youtube": "X", "date": "2026-10-05"}}, **lg}
    lg[other].pop("short", None)
    made, up = _run_shorts(two)
    check("候補が2本あってもショートは1日1本", made, 1)
    import inspect
    check("関連動画・コメント固定は API で設定できないので作らない（呼び出しが無い）",
          any(w in inspect.getsource(YT) for w in ("commentThreads", "relatedToVideoId")), False)


def test_existing_videos_are_not_rewritten():
    print("\n■ 上げ済みの動画の説明欄・題は、今回の直しで書き換わらない")
    import article_videos as AV
    import youtube_upload as YT
    led = _ledger()
    # 印は毎日の記事動画で増えていく（2026-10-10 に1本目）。この門が見るのは「印の無い上げ済みの動画は書き換えない」
    # なので、台帳の印は lead-long だけであることを確かめたうえで、印を外した形（直しを入れる前の台帳）で確かめる
    check("台帳の印は desc=lead-long だけ（ほかの印で説明欄を書き換えない）",
          sorted({(v.get("short") or {}).get("desc") for v in led.values()} - {None} - {YT.LEAD_LONG}), [])
    for v in led.values():
        if (v.get("short") or {}).get("desc"):
            v["short"] = {k: x for k, x in v["short"].items() if k != "desc"}
    # 「いま YouTube にある説明欄」= 今回の直しを入れる前と同じ組み立て（lead_long なし）
    current = {}
    for slug, v in led.items():
        for vid, short in ((v.get("youtube"), False), ((v.get("short") or {}).get("youtube"), True)):
            if vid:
                d, t, _ = YT.full_description(slug, short=short, chapters=ROOT / "automation" / "video" / f"{slug}.chapters.txt")
                current[vid] = {"title": f"上げ済みの題 {vid}", "description": d, "categoryId": "27", "tags": []}
    # これから上げるショート（印あり）を1本だけ混ぜる
    slug = next(k for k, v in led.items() if v.get("youtube") and v.get("short", {}).get("youtube"))
    fresh = json.loads(json.dumps(led))
    fresh[slug]["short"] = dict(fresh[slug]["short"], youtube="NEWSHORT", desc=YT.LEAD_LONG)
    current["NEWSHORT"] = {"title": "新しいショート #Shorts", "categoryId": "27", "tags": [],
                           "description": current[led[slug]["short"]["youtube"]]["description"]}
    updates = []

    class _Req:
        def __init__(self, v):
            self.v = v

        def execute(self):
            return self.v

    class _Videos:
        def list(self, part, id):
            return _Req({"items": [{"snippet": current[id]}] if id in current else []})

        def update(self, part, body):
            updates.append(body)
            return _Req({})

    class _YT:
        def videos(self):
            return _Videos()

    fake = types.ModuleType("googleapiclient.discovery")
    fake.build = lambda *a, **k: _YT()
    saved_mods = {m: sys.modules.get(m) for m in ("googleapiclient", "googleapiclient.discovery")}
    saved = (YT.creds, AV.load)
    sys.modules["googleapiclient"] = sys.modules.get("googleapiclient") or types.ModuleType("googleapiclient")
    sys.modules["googleapiclient.discovery"] = fake
    YT.creds = lambda site=None: object()
    try:
        AV.load = lambda: led
        YT.update_descriptions()
        check("今ある動画の説明欄は1本も書き換えない", [b["id"] for b in updates], [])
        AV.load = lambda: fresh
        YT.update_descriptions()
        check("印の付いた新しいショートだけが対象", [b["id"] for b in updates], ["NEWSHORT"])
        check("説明欄を直しても題はそのまま", [b["snippet"]["title"] for b in updates], ["新しいショート #Shorts"])
    finally:
        YT.creds, AV.load = saved
        for m, v in saved_mods.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
    import inspect
    src = inspect.getsource(AV.main)
    check("作り直し（redo）の行には新しい題を付けない（題を決めるのは新しい記事の判定だけ）",
          '"redo": True}' in src and "plan_long(candidates(" in src, True)
