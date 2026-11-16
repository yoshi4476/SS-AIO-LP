# -*- coding: utf-8 -*-
"""本数: 書く曜日（publish_weekdays）を決めた社は、その曜日（日本時間）だけ書き、ほかの曜日は書かない（2026-11-17）。
運用者が新しいお客様の社を「最初の3か月は週3本・監修を通した記事だけ」と決めたが、1日0〜2本の刻みしか無く、
週2〜3本を表せなかった。あわせて、本数の設定に4を入れても2本に切り詰められていたのに、4本と報告していた"""
from datetime import datetime, timedelta, timezone

from test_gates import check

JST = timezone(timedelta(hours=9))


class _Clock:
    """pace の datetime の差し替え。now(tz) だけを決めた時刻で返す"""
    at = None

    @classmethod
    def now(cls, tz=None):
        return cls.at.astimezone(tz) if tz else cls.at


def _run(site, at, fn):
    import pace
    keep = (pace._site, pace.datetime, pace.signal_quota)
    pace._site, pace.datetime, pace.signal_quota = (lambda sid: site), _Clock, (lambda sid: 2)
    _Clock.at = at
    try:
        return fn(pace)
    finally:
        pace._site, pace.datetime, pace.signal_quota = keep


def test_weekdays_limit_the_days():
    print("\n■ 本数: 書く曜日を決めた社は、その曜日だけ書く")
    site = {"daily_articles": 1, "publish_weekdays": [0, 2, 4]}
    mon = datetime(2026, 11, 16, 10, 0, tzinfo=JST)
    tue = datetime(2026, 11, 17, 10, 0, tzinfo=JST)
    check("月曜（書く曜日）は1本・火曜（書かない曜日）は0本",
          (_run(site, mon, lambda p: p.quota("x")), _run(site, tue, lambda p: p.quota("x"))), (1, 0))
    check("書かない曜日の枠は skip で、理由に曜日の設定を出す",
          _run(site, tue, lambda p: p.slot("x", 0)),
          ("skip", "今日は書く曜日ではありません（運用者の設定 publish_weekdays）"))
    utc_sun = datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc)   # 日本時間では月曜1時
    check("曜日は日本時間で決める（UTC の日曜16時＝日本の月曜は書く）", _run(site, utc_sun, lambda p: p.quota("x")), 1)
    check("語の計画の1か月分は、書く曜日の割合で数える（30日×3/7≒13本。書かない曜日でも0にしない）",
          (_run(site, mon, lambda p: p.month_quota("x", 30)), _run(site, tue, lambda p: p.month_quota("x", 30))), (13, 13))


def test_without_weekdays_is_unchanged():
    print("\n■ 本数: 書く曜日の設定が無い社は、今までどおり毎日")
    tue = datetime(2026, 11, 17, 10, 0, tzinfo=JST)
    check("良い例: 設定の無い社は毎日2本（既定）・1か月60本",
          _run({}, tue, lambda p: (p.quota("x"), p.month_quota("x", 30))), (2, 60))
    check("悪い例の名残: daily_articles に4を入れても2本まで（上限を超える値は切り詰める）",
          _run({"daily_articles": 4}, tue, lambda p: p.quota("x")), 2)
    check("壊れた値（文字・範囲外）は無視して毎日", _run({"publish_weekdays": "月水金"}, tue, lambda p: p.quota("x")), 2)


def test_stub_carries_weekdays():
    print("\n■ 本数: 公開の印にも書く曜日を写す（非公開の置き場を読む前の日次の枠が読む）")
    import tempfile
    from pathlib import Path

    import private_store as PS
    with tempfile.TemporaryDirectory() as d:
        keep = PS.site_private
        PS.site_private = lambda sid, root=None: {}
        try:
            PS.write_site({"id": "zz-test", "public_id": "c00000000", "daily_articles": 1,
                           "publish_weekdays": [0, 2, 4]}, Path(d) / "sites", root=Path(d))
        finally:
            PS.site_private = keep
        import json
        stub = json.loads((Path(d) / "sites" / "c00000000.json").read_text(encoding="utf-8"))
    check("公開の印に daily_articles と publish_weekdays がある",
          (stub.get("daily_articles"), stub.get("publish_weekdays")), (1, [0, 2, 4]))
    import sites
    check("書く曜日のある印も、公開の印として読む（公開してよい項目だけ）。一覧に無いと社の設定として読まれ、"
          "社の id で引いた本数が毎日2本に戻った", set(stub) <= set(sites.PUBLIC_KEYS), True)
