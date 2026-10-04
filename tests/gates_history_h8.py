# -*- coding: utf-8 -*-
"""コードレビューで見つかった6件の門（2026-10-05）。

並列の下書きが予算を食い切る・1本の失敗で全部失う／YouTube の鍵の Secret を手元の分だけで上書きする／
IndexNow だけ通ったURLを Google に送った扱いにする／Gemini の予算切れを「引用なし」で確定する／
A/B の出来事を件数の上限で取りこぼす／書き出しのログを閉じない。claude・API・YouTube は呼ばない。
"""
import inspect
import json
import subprocess
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_parallel_drafts_fit_the_budget():
    import auto_rewrite as AR
    import auto_merge as AM
    print("\n■ 並列の下書き（予算と1本ごとの失敗）")
    check("予算なしなら全件を下書きする", AR.draft_quota(10, 2, 0, 30), 10)
    check("予算60分・1本30分なら parallel×2 本だけ", AR.draft_quota(10, 2, 60, 30), 4)
    check("週次の設定（予算40分・3並列）は1回分の3本", AR.draft_quota(10, 3, 40, 30), 3)
    check("予算が1回分に満たなくても parallel 本は書かせる", AR.draft_quota(10, 2, 25, 40), 2)
    check("書き終えた下書きは予算を過ぎても当てる（両方）",
          ["edited is None" in inspect.getsource(AR.main), "not drafts.get(id(p))" in inspect.getsource(AM.main)],
          [True, True])
    check("件数より多くは書かせない", AR.draft_quota(3, 4, 600, 30), 3)

    def fn(x):
        if x == 2:
            raise subprocess.TimeoutExpired("claude", 1)
        return x * 10
    check("1本が TimeoutExpired でも他の本の結果は残る", AR.map_each(fn, [1, 2, 3], 2), [10, None, 30])
    check("auto_rewrite の main は下書きの本数を予算から決める", "draft_quota(" in inspect.getsource(AR.main), True)
    check("auto_merge の main も同じ", "draft_quota(" in inspect.getsource(AM.main), True)
    check("draft_all は1本ずつ例外を受け止める（両方）",
          ["map_each(" in inspect.getsource(f) for f in (AR.draft_all, AM.draft_all)], [True, True])


def test_youtube_secret_not_overwritten_with_partial_tokens():
    import youtube_upload as YU
    print("\n■ YOUTUBE_TOKENS_JSON を手元の鍵だけで置き換えない")
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "sites").mkdir()
        (r / "data" / "clients" / "acme").mkdir(parents=True)
        (r / "data" / "clients" / "beta").mkdir(parents=True)
        (r / "sites" / "acme.json").write_text(json.dumps({"channels": {"youtube": "https://www.youtube.com/@acme"}}), encoding="utf-8")
        (r / "sites" / "beta.json").write_text(json.dumps({"channels": {"youtube": ""}}), encoding="utf-8")
        (r / "data" / "youtube_connected.json").write_text(json.dumps({"sites": ["gamma"]}), encoding="utf-8")
        (r / "youtube-token-beta.json").write_text(json.dumps({"token": "x"}), encoding="utf-8")
        allk, missing = YU.tokens_bundle(r)
        check("チャンネルを書いた社・前に登録した社の鍵が手元に無ければ挙げる", missing, ["acme", "gamma"])
        (r / "youtube-token-acme.json").write_text("{}", encoding="utf-8")
        (r / "youtube-token-gamma.json").write_text("{}", encoding="utf-8")
        allk, missing = YU.tokens_bundle(r)
        check("全社そろえば書き換えてよい", (sorted(allk), missing), (["acme", "beta", "gamma"], []))
    src = inspect.getsource(YU.auth)
    check("auth は欠けがあれば gh secret set の前に止まる",
          src.index("if missing") < src.index('"gh", "secret", "set"'), True)


def test_reindex_records_only_indexing_api_success():
    import reindex as RX
    print("\n■ Indexing API に送れたURLだけを送った扱いにする")
    ok_u, ng_u = "https://ai.example/a/", "https://ai.example/b/"

    class Req:
        def __init__(self, u):
            self.u = u

        def execute(self):
            if self.u == ng_u:
                raise RuntimeError("403")

    class Idx:
        def urlNotifications(self):
            return self

        def publish(self, body):
            return Req(body["url"])

    def no_svc(*a, **k):
        raise RuntimeError("offline")

    saved = {k: getattr(RX, k) for k in ("_sent", "resend_plan", "_indexnow", "SENT", "svc", "time")}
    with tempfile.TemporaryDirectory() as td:
        try:
            RX._sent = lambda: {}
            RX.resend_plan = lambda ng, sent, today, left: ([(ok_u, "x"), (ng_u, "x")], [], [])
            RX._indexnow = lambda urls: set(urls)
            RX.SENT = Path(td) / "sent.json"
            RX.svc = no_svc
            RX.time = type("T", (), {"sleep": staticmethod(lambda s: None)})
            RX._publish(Idx(), "ai.example", [], False)
            got = sorted(json.loads(RX.SENT.read_text(encoding="utf-8")))
        finally:
            for k, v in saved.items():
                setattr(RX, k, v)
    check("IndexNow だけ通ったURLは記録しない（次の週に Google へ送り直す）", got, [ok_u])


def test_ai_followup_none_is_failure():
    import ai_followup as AF
    print("\n■ 聞けなかったAI（None）を「引用なし」にしない")
    a = {"keyword": "テスト語"}
    check("全エンジンが None なら記録しない", AF.measure(a, "ai.example", {"Gemini": lambda q: None}), None)
    r = AF.measure(a, "ai.example", {"Gemini": lambda q: None, "Perplexity": lambda q: []})
    check("None のエンジンは失敗として残す", "error" in r["engines"]["Gemini"], True)
    check("空の出典は「引用なし」として数える", r["engines"]["Perplexity"]["cited"], False)


def test_ab_result_filters_event_names():
    import ab_result as AB
    from google.analytics.data_v1beta.types import Filter
    print("\n■ A/B の出来事を名前の頭で絞って取る")
    exprs = AB.event_filter().or_group.expressions
    check("eventName を ab_impression_ / cta_click_ の BEGINS_WITH で絞る",
          [(e.filter.field_name, e.filter.string_filter.value, e.filter.string_filter.match_type) for e in exprs],
          [("eventName", p, Filter.StringFilter.MatchType.BEGINS_WITH) for p in AB.PREFIXES])
    check("取得に絞り込みを渡している", "dimension_filter=event_filter()" in inspect.getsource(AB.pull), True)
    check("試験の出来事は全部この頭で始まる",
          all(imp.startswith(AB.PREFIXES[0]) and clk.startswith(AB.PREFIXES[1]) for _, imp, clk in AB.tests()), True)


def test_duo_video_closes_encoder_log():
    print("\n■ 書き出しのログを閉じる")
    src = (ROOT / "scripts" / "duo_video.py").read_text(encoding="utf-8")
    check("stderr=open(...) で開きっぱなしにしない", "stderr=open(" in src, False)
    check("with で開いたログを ffmpeg に渡す", 'as elog:' in src and "stderr=elog" in src, True)
