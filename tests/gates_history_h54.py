# -*- coding: utf-8 -*-
"""自動化の点検（2026-10-08）で運用者が直すと決めた4つの穴。

  1. 同日救済（予定 21:30）は GitHub の定時の遅れで14回とも日付が変わってから走り（翌1:36〜5:36）、
     「この時刻での期待は0本」と見て、3社とも0本だった 10/2・10/3 まで「救済不要」にしていた
  2. 日次KPIが記事の枠0の中にあり、枠0が月の上限・量産の兆候・取りこぼしで飛ぶと集計も飛んだ（9/28〜10/3）
  3. お客様の検索語・順位・AIの出典を public から外したが、CI の実行ごとに消えて順位の推移・AIの語の優先・
     引用の実測・競合比較の自社順位が空になる。全社で1ファイルの記録はお客様の分ごと public に載る
  4. 週次メールの「要対応」が毎週15種前後並び（盤面の空き・達成率93%・構成の提案30件・数字の信頼性など）、
     本当の異常が埋もれる
"""
import contextlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
JST = timezone(timedelta(hours=9))


@contextlib.contextmanager
def patched(obj, **kw):
    saved = {k: getattr(obj, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(obj, k, v)
        yield obj
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def audit_day(value):
    old = os.environ.get("AUDIT_DAY")
    try:
        if value is None:
            os.environ.pop("AUDIT_DAY", None)
        else:
            os.environ["AUDIT_DAY"] = value
        yield
    finally:
        if old is None:
            os.environ.pop("AUDIT_DAY", None)
        else:
            os.environ["AUDIT_DAY"] = old


def _quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, buf.getvalue()


# ── 1. 同日救済が日付をまたいだ回は前日を数える ───────────────────────

def test_rescue_counts_previous_day_after_midnight():
    import daily_audit as D
    import site_order
    rd = getattr(D, "rescue_day", None)
    check("救済: 数える日を決める関数がある（daily_audit.rescue_day）", callable(rd), True)
    if not callable(rd):
        return
    first = D.first_slot_hour()
    check("救済: 最初の枠の時刻は記事の枠の割り当て（pipeline-multi の cron）から求める",
          first, min(h for s in site_order.order() for h in (D.publish_hours(s) or ())))
    got = [rd(datetime(2026, 10, 8, h, 36, tzinfo=JST)) for h in (1, 3, 5)]
    check("救済: 実際に始まった時刻（翌1:36〜5:36）は前日を数える", got, ["2026-10-07"] * 3)
    check("救済: 予定どおり（21:30）・その日の最初の枠の後に始まった回は当日",
          [rd(datetime(2026, 10, 8, 21, 30, tzinfo=JST)), rd(datetime(2026, 10, 8, first, 7, tzinfo=JST))],
          ["2026-10-08", "2026-10-08"])


def _art(slug, d, makeup=""):
    return {"slug": slug, "date": d, "score": "95", "title": slug, "category": "x", "makeup_for": makeup}


def test_previous_day_shortfall_is_counted_and_written():
    """前日を数える回は、前日の枠はすべて過ぎているので1日の本数を丸ごと求める。
    月の上限・量産の兆候（社ごとの1日の本数）・監修待ちは今までどおり差し引く"""
    import daily_audit as D
    import pace
    day, today = "2026-10-07", "2026-10-08"
    arts = {
        "own-zero": [],                                                     # 前日0本
        "client-one": [],                                                   # 1日1本の社（CONFLUX と同じ）
        "own-cap": [_art(f"c{i}", f"2026-10-{i % 6 + 1:02d}") for i in range(60)],   # 月の上限に達した社
        "own-held": [_art("h1", day), _art("h2", day)],                     # 監修待ちでも書いた本数に入る
        "own-made": [_art("m1", today, makeup=day), _art("m2", day)],        # 前日分を今日書いた1本
    }
    todo = []
    with patched(D, articles_by_site=lambda: arts, today_iso=lambda: today), \
            patched(pace, quota=lambda sid: 1 if sid == "client-one" else 2), audit_day(day):
        _, out = _quiet(D.check_volume, todo)
    want = [f"TODO: own-zero の記事を前日（{day}）の不足分としてあと 2 本作成して公開する"]
    check("救済（前日）: 足りない社だけ書き足す（上限・監修待ち・書き足し済みは数える）",
          [t.split("（date:")[0] for t in todo], want)
    # 1日1本に絞っている社（CONFLUX はオーナーの指示）は書き足さない。書き足すと暦の上で1日2本になる
    check("救済（前日）: 1日の本数を絞っている社は前日の分を書き足さない",
          ("client-one は1日1本に絞っているため" in out, any("client-one" in t for t in todo)), (True, False))
    check("救済（前日）: 公開日は今日のまま書くよう指示する（前日の日付で出さない）",
          all("date: は公開する今日の日付" in t for t in todo), True)
    now, _ = D.split_todo(todo + ["TODO: x を品質基準まで直して score を更新し、再ビルドする"])
    check("救済（前日）: 書き足しの TODO は今日やることの先頭に来る", now[:len(todo)] == todo, True)
    # 前日分として今日書いた記事を、今日の本数に二重に数えない（今日の枠の2本はそのまま書かれる）
    todo2 = []
    with patched(D, articles_by_site=lambda: {"own-made": arts["own-made"]}, today_iso=lambda: today,
                 _due_now=lambda sid, hour=None: 2), patched(pace, quota=lambda sid: 2), audit_day(None):
        _quiet(D.check_volume, todo2)
    check("前日分として今日書いた記事は、今日の本数に数えない", todo2,
          ["TODO: own-made の記事を本日あと 2 本作成して公開する"])


def test_makeup_keeps_the_real_publish_date():
    """前日の不足分として書いた記事の公開日（date:）は公開した今日。検索エンジンに公開日を偽らない。
    どの日の分かは data/makeup.json に残し、本数だけ前日に数える"""
    import daily_audit as D
    head = "---\ntitle: t\ndate: 2026-10-07\nmodified: 2026-10-07\ncategory: aio\nscore: 95\n---\n本文\n"
    with tempfile.TemporaryDirectory() as td:
        arts = Path(td) / "articles"
        arts.mkdir()
        (arts / "new-one.md").write_text(head, encoding="utf-8")
        (arts / "old-one.md").write_text(head, encoding="utf-8")
        with patched(D, ARTICLES=arts, MAKEUP=Path(td) / "makeup.json", today_iso=lambda: "2026-10-08",
                     is_new_article=lambda slug: slug == "new-one"):
            with audit_day("2026-10-07"):
                got = D.stamp_makeup("new-one")
                kept = D.stamp_makeup("old-one")
            with audit_day(None):
                same_day = D.stamp_makeup("new-one")
            text = (arts / "new-one.md").read_text(encoding="utf-8")
            led = json.loads((Path(td) / "makeup.json").read_text(encoding="utf-8"))
            old = (arts / "old-one.md").read_text(encoding="utf-8")
    check("前日分: 公開日は公開する今日・更新日も公開日より前にしない・前日の分として台帳に残す",
          (got, "date: 2026-10-08" in text, "modified: 2026-10-08" in text, led),
          ("2026-10-07", True, True, {"new-one": "2026-10-07"}))
    check("前日分: コミット済みの記事（品質の直し・配信のし直し）と、当日の救済・手元の実行では何もしない",
          (kept, same_day, old == head), (None, None, True))
    src = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    main = src.split("def main():", 1)[1]
    check("publish_flow: 月の上限を数える前（公開日が決まる前）に前日分の記録をする",
          0 < main.find("daily_audit.stamp_makeup(slug)") < main.find("0-3. 月の上限"), True)
    import outcome_watch as OW
    check("結果の見張り: 前日分として翌日に書いた記事は前日の本数に数える",
          "D.counted_day(a) == day.isoformat()" in inspect.getsource(OW.check_articles), True)
    rp = (ROOT / "automation" / "retry_prompt.txt").read_text(encoding="utf-8")
    check("救済の手順: 前日分の TODO の扱い（公開日は今日）を書いてある",
          "の不足分としてあと N 本作成して公開する" in rp and "date: は**今日（公開する日）**" in rp, True)


# ── 2. 日次KPIは同じ日を2回送らない（抜けた日は埋める） ───────────────

def test_daily_kpi_sends_each_day_once():
    import daily_kpi as K
    dts = getattr(K, "days_to_send", None)
    check("日次KPI: 送る日を決める関数がある（daily_kpi.days_to_send）", callable(dts), True)
    if not callable(dts):
        return
    t = date(2026, 10, 8)
    check("日次KPI: 記録が無ければ前日だけ（記事の枠の中で送っていた日を二重に送らない）", dts(set(), t), ["2026-10-07"])
    check("日次KPI: 前日を送り済みなら何も送らない", dts({"2026-10-07"}, t), [])
    check("日次KPI: 取りこぼした日（最後に送った日の翌日から前日まで）を埋める",
          dts({"2026-10-04"}, t), ["2026-10-05", "2026-10-06", "2026-10-07"])
    check("日次KPI: 埋めるのは7日前まで", dts({"2026-09-01"}, t)[0], "2026-10-01")
    posted = []
    with tempfile.TemporaryDirectory() as td:
        sa = Path(td) / "sa.json"
        sa.write_text("{}", encoding="utf-8")
        hc = K.hub_client
        with patched(K, SA=sa, SENT=Path(td) / "kpi_sent.json", collect=lambda d: [{"site": "x", "date": d}]), \
                patched(hc, enabled=lambda: True,
                        _post=lambda body: posted.append(body["rows"][0]["date"]) or {"ok": True, "rows": 1}), \
                patched(sys, argv=["daily_kpi.py", "--send", "--once"]):
            _quiet(K.main)
            _quiet(K.main)          # 同じ日にもう一度（手で流した・定時が2回来た）
    check("日次KPI: 同じ日に2回動いても、管制塔へは1回だけ送る（kpi_log は行を足すだけ）",
          posted, [(date.today() - timedelta(days=1)).isoformat()])


# ── 3. お客様のデータは public に置かず、実行をまたいで持ち越す ─────────────

def _ignored(rel):
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", rel]).returncode == 0


def test_client_private_stays_out_of_public_repo():
    check("お客様の置き場（data/clients/<id>/private/）は public に置かない",
          [_ignored(p) for p in ("data/clients/conflux/private/data/ranks/conflux.json",
                                 "data/clients/client-zz/private/data/rank_up.json")], [True, True])
    check("お客様の翌月の目標（reports/targets-<id>.json）は public に置かない（11/1 の月次がコミットする）",
          [_ignored(p) for p in ("reports/targets-conflux.json", "reports/targets-client-zz.json")], [True, True])
    # 目標値・レポートと、お客様の会社情報は非公開のリポジトリへ移した（2026-10-10 守秘義務・h76）
    check("目標値とお客様の会社情報は公開側に置かない（非公開のリポジトリ）",
          [_ignored(p) for p in ("reports/targets.json", "reports/targets-corporate.json",
                                 "reports/targets-subsidy.json", "data/clients/conflux/company.json")], [True] * 4)
    check("置き場の外の記録はこれまでどおりコミットする",
          [_ignored(p) for p in ("data/makeup.json", "data/findings_seen.json")], [False] * 2)
    check("日次KPIを送った日の記録（キャッシュで持ち越す）はコミットしない", _ignored("data/kpi_sent.json"), True)


def test_client_private_pack_and_split():
    import client_private as CP
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"):
            for rel in ("data/ranks/cx.json", "data/ranks/ai-lab.json", "data/ai_kw/cx.json"):
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text('{"d": 1}', encoding="utf-8")
            n_kw = CP.pack(["ai_kw"])
            n_all = CP.pack()
            priv = base / "data" / "clients" / "cx" / "private"
            files = sorted(p.relative_to(priv).as_posix() for p in priv.rglob("*") if p.is_file())
            check("持ち越し: 写すのはお客様の社のファイルだけ（種類を絞れる）",
                  (n_kw, n_all, files), (1, 2, ["data/ai_kw/cx.json", "data/ranks/cx.json"]))
            (base / "data/ranks/cx.json").unlink()        # 次の実行のランナー（外したファイルは無い）
            (base / "data/ranks/ai-lab.json").write_text('{"d": 2}', encoding="utf-8")
            CP.unpack()
            check("持ち越し: 戻すとお客様のファイルが元の場所に戻り、自社のコミット済みの記録は触らない",
                  ((base / "data/ranks/cx.json").is_file(), (base / "data/ranks/ai-lab.json").read_text(encoding="utf-8")),
                  (True, '{"d": 2}'))
            # 全社で1ファイルの記録
            CP.save_dict("data/rank_up.json", {"a": {"site": "ai-lab"}, "b": {"site": "cx"}}, lambda k, v: v["site"])
            pub = json.loads((base / "data/rank_up.json").read_text(encoding="utf-8"))
            check("全社1ファイル: お客様の分は public の記録に書かず、読むときは合わせる",
                  (sorted(pub), sorted(CP.load_dict("data/rank_up.json"))), (["a"], ["a", "b"]))
            d = {"date": "2026-10-08", "method": "m",
                 "sites": {"ai-lab": {"items": [{"kw": "自社の語"}]}, "cx": {"items": [{"kw": "お客様の語"}]}},
                 "measured": {"engines": ["G"], "sites": {"ai-lab": {"cited": 1}, "cx": {"cited": 0}}}}
            CP.save_citations("2026-10.json", d)
            text = (base / "data/ai_citations/2026-10.json").read_text(encoding="utf-8")
            got = CP.load_citations("2026-10.json")
            check("引用の記録: お客様の語・出典は public の月の記録に載らず、読むときは両方そろう",
                  ("お客様の語" in text, '"cx"' in text, sorted(got["sites"]), sorted(got["measured"]["sites"])),
                  (False, False, ["ai-lab", "cx"], ["ai-lab", "cx"]))
            (base / "data/ai_citations/followup.json").write_text('{"articles": {}}', encoding="utf-8")
            check("引用の記録: 月の記録（YYYY-MM.json）だけを最新の月として読む（followup.json を取り違えない）",
                  CP.citation_months(), ["2026-10.json"])


def test_shared_ledgers_split_client_rows():
    """rank_up.json・引用の月の記録（推定は毎晩・実測は週次/月次）・followup.json・URL検査の記録と再送の間隔"""
    import client_private as CP
    import rank_up as RU
    import ai_followup as AF
    import reindex as RX
    import ai_citation_check as AC
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        with patched(CP, ROOT=base, clients=lambda: ["conflux"], is_private=lambda s: s == "conflux"):
            priv = base / "data" / "clients" / "conflux" / "private"
            with patched(RU, LOG=base / "data" / "rank_up.json"):
                RU.save_log({"s-own": {"site": "ai-lab", "pos": 12}, "s-client": {"site": "conflux", "pos": 15}})
                check("rank_up.json: お客様の記事の順位は public に書かず、読むときは合わせる",
                      (sorted(json.loads(RU.LOG.read_text(encoding="utf-8"))), sorted(RU.load_log())),
                      (["s-own"], ["s-client", "s-own"]))
            with patched(AF, OUT=base / "data" / "ai_citations" / "followup.json"):
                AF.save({"articles": {"a": {"site": "ai-lab"}, "c": {"site": "conflux"}}, "last_run": {"date": "x"}})
                check("followup.json: お客様の記事の分は public に書かず、読むときは合わせる",
                      (sorted(json.loads(AF.OUT.read_text(encoding="utf-8"))["articles"]), sorted(AF.load()["articles"])),
                      (["a"], ["a", "c"]))
            with patched(RX, CACHE=base / "data" / "index_cache.json", SENT=base / "data" / "index_resend.json"):
                urls = {"https://ai.7senses.co.jp/aio/x/": {"verdict": "PASS"},
                        "https://conflux-partners.jp/blog/y/": {"verdict": "NEUTRAL"}}
                RX._save(dict(urls))
                RX._save_sent({u: "2026-10-08" for u in urls})
                check("URL検査の記録・再送の間隔: お客様のURLは public に書かず、読むときは合わせる",
                      (list(json.loads(RX.CACHE.read_text(encoding="utf-8"))), sorted(RX._cache()),
                       list(json.loads(RX.SENT.read_text(encoding="utf-8"))), sorted(RX._sent())),
                      (["https://ai.7senses.co.jp/aio/x/"], sorted(urls), ["https://ai.7senses.co.jp/aio/x/"], sorted(urls)))
            # 毎晩の推定（ai_citation_check）が、週次・月次の実測（measured）を消さない
            month = f"{date.today():%Y-%m}.json"
            CP.save_citations(month, {"date": "x", "sites": {}, "measured": {"engines": ["G"], "sites": {
                "ai-lab": {"cited": 1}, "conflux": {"cited": 0}}}})
            ranks = base / "data" / "ranks"
            ranks.mkdir(parents=True, exist_ok=True)
            row = {"kw": "語", "url": "u", "pos": 3.0, "imp": 50, "clicks": 0, "ctr": 0.0}
            for sid in ("ai-lab", "conflux"):
                (ranks / f"{sid}.json").write_text(json.dumps({"2026-10-07": [row]}), encoding="utf-8")
            fake = type("S", (), {"load_all": staticmethod(lambda: {"ai-lab": {"id": "ai-lab", "name": "A"},
                                                                    "conflux": {"id": "conflux", "name": "C"}})})
            with patched(AC, ROOT=base, RANKS=ranks, OUT=base / "data" / "ai_citations", sites_mod=fake):
                _quiet(AC.main)
            got = CP.load_citations(month)
            pub = (base / "data" / "ai_citations" / month).read_text(encoding="utf-8")
            check("毎晩の推定が実測（measured）を消さず、お客様の分は置き場に分ける",
                  (sorted(got.get("measured", {}).get("sites", {})), sorted(got["sites"]), "conflux" in pub,
                   (priv / "data" / "ai_citations" / month).is_file()),
                  (["ai-lab", "conflux"], ["ai-lab", "conflux"], False, True))
    import cooccur as CO
    import auto_rewrite as AR
    import daily_kpi as DK
    import win_patterns as WP
    check("共起語: お客様の記事の分は置き場へ書き、直す工程は置き場から読む",
          ("CP.site_file(site_id" in inspect.getsource(CO.cover),
           'CP.find_file(f"data/cooccur/{slug}.json")' in inspect.getsource(AR)), (True, True))
    check("引用の月の記録を読む3か所（日次KPI・直し・勝ち型）が、お客様の分を合わせて月の記録だけを読む",
          ["CP.citation_months()" in inspect.getsource(f) for f in (DK.aio_estimate, AR.aio_items, WP.cited_words)],
          [True, True, True])


# ── 4. 週次の通知は、新しく出た・悪化した・期限のあるものだけを要対応にする ───────

def test_weekly_notice_raises_only_new_worse_or_deadline():
    import findings as F
    import notify_slack as N
    comp = getattr(F, "compose", None)
    check("週次の通知: 要対応と情報を組み分ける関数がある（findings.compose）", callable(comp), True)
    if not callable(comp):
        return
    labels = {lab for lab, _, _ in F.CHECKS}
    check("週次の通知: 運用者が挙げた毎週出る項目（盤面の空き・達成率・構成の提案・数字の信頼性）は情報",
          {"盤面の空き（業種×手法）", "こちら側で決まる要因の達成率", "サイト構成の提案", "数字の信頼性"} <= set(F.STEADY), True)
    check("週次の通知: 情報に下げる項目・期限のある項目の名前は、どれも実在の検査",
          sorted((set(F.STEADY) | set(F.DEADLINE)) - labels), [])
    yomi, sns = "動画の読み違い（聞き直して直せなかった読み）", "SNS の鍵の期限（Threads・LinkedIn は60日）"
    rows = [("盤面の空き（業種×手法）", "要対応", ["空いているマス 38 / 薄いマス 19"]),
            (yomi, "要対応", ["要対応: 読み上げで直せなかった読み 37件", "- 「の型」 台本 カタ → 声 ホ"]),
            (sns, "要対応", ["要対応: Threads の鍵が残り5日"]),
            ("AIO基盤（robots・llms.txt・構造化データ）", "問題なし", [])]
    prev = ["要対応: ラッコキーワードのクレジットが尽きました", "要対応: 原稿からページを作れませんでした（Weekly Optimize）"]

    def heads(body):
        top = body[:body.index(next((b for b in body if b.startswith(N.INFO_MARK)), body[-1]))] \
            if any(b.startswith(N.INFO_MARK) for b in body) else body
        return [b for b in top if b.startswith(("要対応", "動かせず"))]

    b1, s1, n1, _ = comp(rows, prev, {}, "2026-10-12")
    check("1週目: 新しく出たもの・期限のあるもの・この回に失われた仕事は要対応、盤面の空きは情報",
          heads(b1), prev + [f"要対応: {yomi}", f"要対応: {sns}"])
    b2, s2, n2, down2 = comp(rows, prev, s1, "2026-10-19")
    check("2週目（先週と同じ）: 期限のある鍵と、この回に失われた仕事だけ要対応",
          heads(b2), [prev[1], f"要対応: {sns}"])
    check("2週目: 続いているものは本文の下の情報に、何週目かを添えてまとめる",
          any(b.startswith(f"情報: {yomi}（2週目") for b in b2), True)
    rows3 = [rows[0], (yomi, "要対応", rows[1][2] + ["- 「じゅう位」 台本 クライ → 声"]), rows[2]]
    b3, s3, _, _ = comp(rows3, prev[:1], s2, "2026-10-26")
    check("3週目（新しい明細）: 悪化した項目は要対応に戻し、新しい明細を先に見せる",
          (f"要対応: {yomi}" in heads(b3), b3[b3.index(f"要対応: {yomi}") + 2].strip()), (True, "- 「じゅう位」 台本 クライ → 声"))
    rows4 = [(yomi, "要対応", ["要対応: 読み上げで直せなかった読み 52件"] + rows3[1][2][1:])]
    b4, _, _, _ = comp(rows4, [], s3, "2026-11-02")
    check("4週目（同じ明細で件数が増えた）: 悪化として要対応", f"要対応: {yomi}" in heads(b4), True)
    calm = ["# 生成: x"] + comp(rows[:1] + rows[3:], [], s1, "2026-10-19")[0]
    check("情報の欄だけの週はメールを送らない（情報の明細の「不足」「失敗」で送らない）",
          (N.worth_sending("🔧 週次最適化: success\n" + "\n".join(calm), True),
           N.worth_sending("🔧 週次最適化: success\n" + "\n".join(b2), True)), (False, True))
    check("要対応の行は「要対応: <検査名>」のまま（前の回の自分の行を持ち越さない carry_over の目印）",
          f"要対応: {sns}" in b2, True)
    src = inspect.getsource(F.main)
    check("判定（judge・*_OK= の印）と終了コード0は変えない",
          ("state = judge(text, rc)" in src, "return 0   # 知らせるのが仕事" in src), (True, True))
    check("前の週の記録は CI の回だけ書く（手元で試した回を比べる相手にしない）",
          'os.environ.get("GITHUB_ACTIONS")' in src and "save_seen(" in src, True)


# ── ワークフロー（ワークフローの変更と同じコミット） ──────────────────────

def _yaml(path):
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _steps(name, job):
    return _yaml(ROOT / ".github" / "workflows" / name)["jobs"][job]["steps"]


def _at(steps, pred):
    return next((i for i, s in enumerate(steps) if pred(s)), None)


def _named(text):
    return lambda s: text in str(s.get("name", ""))


def _ran(text):
    return lambda s: text in str(s.get("run", ""))


def _cp(mode, family="private"):
    def pred(s):
        w = s.get("with") or {}
        return (s.get("uses") == "./.github/actions/client-private" and w.get("mode") == mode
                and (w.get("family") or "private") == family)
    return pred


def test_rescue_workflow_counts_one_day_throughout():
    st = _steps("pipeline.yml", "pipeline")
    day, rescue, again = _at(st, _ran("daily_audit.py --rescue-day")), _at(st, _named("同日救済")), _at(st, _named("救済後の再監査"))
    check("救済: 数える日を最初に1回だけ決め、claude と再監査が同じ日を数える（GITHUB_ENV）",
          (day is not None and rescue is not None and again is not None and day < rescue < again,
           "GITHUB_ENV" in str(st[day].get("run", "")) if day is not None else False,
           str(st[day].get("if", "")) if day is not None else ""),
          (True, True, "steps.mode.outputs.mode == 'rescue'"))


def test_daily_kpi_runs_outside_the_article_slots():
    pm = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("日次KPIは記事の枠（pipeline-multi）から外した（枠0が上限・量産の兆候で飛ぶと集計も飛んだ）",
          "daily_kpi.py" in pm, False)
    p = ROOT / ".github" / "workflows" / "daily-kpi.yml"
    check("日次KPIは独立したワークフロー（daily-kpi.yml）", p.is_file(), True)
    if not p.is_file():
        return
    y = _yaml(p)
    trig = y.get("on") or y.get(True) or {}
    crons = [c["cron"] for c in trig.get("schedule") or []]
    st = y["jobs"]["kpi"]["steps"]
    run = "\n".join(str(s.get("run", "")) for s in st)
    check("日次KPI: 毎日1回・同時に2本動かない・同じ日は2回送らない（--once）",
          (len(crons), (y.get("concurrency") or {}).get("group"), "daily_kpi.py --send --once" in run),
          (1, "daily-kpi", True))
    rest = _at(st, lambda s: (s.get("with") or {}).get("path") == "data/kpi_sent.json" and "restore" in str(s.get("uses")))
    send = _at(st, _ran("daily_kpi.py"))
    save = _at(st, lambda s: (s.get("with") or {}).get("path") == "data/kpi_sent.json" and "save" in str(s.get("uses")))
    check("日次KPI: 送った日の記録を送る前に戻し、送った後に（落ちても）残す",
          (None not in (rest, send, save) and rest < send < save,
           str(st[save].get("if", "")).startswith("always()") if save is not None else False), (True, True))
    m, h = crons[0].split()[:2] if crons else ("", "")
    jst = f"{(int(h) + 9) % 24:02d}:{int(m):02d}" if crons else ""
    row = next((ln for ln in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
                if ln.startswith("| Daily KPI Report")), "")
    check("CLAUDE.md 5章の表の時刻とワークフローの定時が合う", (f"毎日 {jst}" in row, "daily-kpi.yml" in row), (True, True))


def test_client_private_is_carried_between_jobs():
    act = _yaml(ROOT / ".github" / "actions" / "client-private" / "action.yml")
    paths = {str((s.get("with") or {}).get("path")) for s in act["runs"]["steps"] if "actions/cache" in str(s.get("uses"))}
    check("持ち越し: キャッシュは data/clients/*/private の1か所だけ（成果物には入れない）", paths, {"data/clients/*/private"})
    bad = []

    def order(wf, job, before, after, what):
        st = _steps(wf, job)
        a, b = _at(st, before), _at(st, after)
        if a is None or b is None or not a < b:
            bad.append(f"{wf}/{job}: {what}")

    # 読む工程の前に戻す
    order("pipeline-multi.yml", "write", _cp("restore"), _named("執筆ブリーフ"), "書く前に戻す")
    order("pipeline-multi.yml", "write", _cp("restore", "ai-kw"), _named("食い合いゲート（執筆前）"), "次の語の前に AI の語を戻す")
    order("pipeline.yml", "pipeline", _cp("restore"), _named("順位の記録"), "順位を積み足す前に戻す")
    order("weekly-optimize.yml", "optimize", _cp("restore"), _named("順位を上げる"), "直す前に戻す")
    order("weekly-optimize.yml", "optimize", _named("途中までの直しを正本へ保存"), _cp("restore", "ai-kw"), "並行の KW 補充の後に AI の語を受け取る")
    order("weekly-optimize.yml", "optimize", _cp("restore", "ai-kw"), _named("実測（速度"), "共起語・勝ち型の前に AI の語を受け取る")
    order("weekly-optimize.yml", "optimize", _cp("restore", "index"), _named("登録されていないページを拾って再通知"), "再通知の前に URL検査を受け取る")
    order("monthly-report.yml", "report", _cp("restore"), _named("AI引用の実測"), "引用の実測の前に順位を戻す")
    order("monthly-report.yml", "report", _cp("restore"), _named("月次レポート生成"), "レポートの前に目標を戻す")
    order("focus-mode.yml", "focus", _cp("restore"), _named("11〜30位の欠けた問いを足す"), "直す前に戻す")
    order("daily-kpi.yml", "kpi", _cp("restore"), _ran("daily_kpi.py"), "AIO の推定の前に戻す")
    # 書いた工程の後に（落ちても）残す
    order("pipeline.yml", "pipeline", _named("順位の記録"), _cp("save"), "順位を積んだ後に残す")
    order("weekly-optimize.yml", "kw-refill", _named("KWキューの実データ補充"), _cp("save", "ai-kw"), "AI の語を書いた後に残す")
    order("weekly-optimize.yml", "index-inspect", _named("登録されていないページを検査する"), _cp("save", "index"), "URL検査の後に残す")
    order("weekly-optimize.yml", "optimize", _named("登録されていないページを拾って再通知"), _cp("save"), "最後に残す")
    order("monthly-report.yml", "report", _named("目標値の保存をコミット"), _cp("save"), "目標を作った後に残す")
    check("持ち越し: 読む工程の前に戻し、書いた工程の後に残す", bad, [])
    saves = [(wf, job) for wf in ("pipeline.yml", "weekly-optimize.yml", "monthly-report.yml")
             for job, j in _yaml(ROOT / ".github" / "workflows" / wf)["jobs"].items()
             for s in j.get("steps") or [] if (s.get("with") or {}).get("mode") == "save"
             and s.get("uses") == "./.github/actions/client-private" and not str(s.get("if", "")).startswith("always()")]
    check("持ち越し: 残す工程は途中が落ちても動く（always()）", saves, [])
    # 並行ジョブは自分の系統だけに残す（同じ系統だと optimize の古い写しで上書きされる）
    kw = [s for s in _steps("weekly-optimize.yml", "kw-refill") if s.get("uses") == "./.github/actions/client-private"]
    ix = [s for s in _steps("weekly-optimize.yml", "index-inspect") if s.get("uses") == "./.github/actions/client-private"]
    check("持ち越し: 並行ジョブは戻さず、自分の系統（ai-kw・index）にだけ残す",
          ([(s["with"]["mode"], s["with"].get("family")) for s in kw], [(s["with"]["mode"], s["with"].get("family")) for s in ix]),
          ([("save", "ai-kw")], [("save", "index")]))


def test_weekly_remembers_what_it_reported():
    body = next(str(s.get("run")) for s in _steps("weekly-optimize.yml", "optimize") if _ran("scripts/findings.py")(s))
    check("週次: 前の週に出たもの（findings_seen.json）をコミットし、未コミットの変更があっても pull を通す",
          ("data/findings_seen.json" in body, "git pull --rebase --autostash" in body), (True, True))
