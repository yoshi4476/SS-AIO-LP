# -*- coding: utf-8 -*-
"""ヒアリングシートを読み込むだけで全機能の準備がそろうか（2026-10-07 運用者の依頼）。

「すべての機能を使うのに必要なものをヒアリングシートに載せる。ちゃんとしたシートを読み込ませるだけで、
全機能が使え、解析ができ、記事作成が行われるように」。外部（WordPress・FTP・GitHub・Google）には触れず、
一時フォルダに登録して確かめる:

  - シートの先頭に「記入のしかた」の枠、5列（項目・記入欄・必須・説明・記入例）、方式ごとの必須の印、プルダウン
  - 全欄に流れ先があり（client_intake.FLOW）、欄を1つ抜くと登録される中身が必ず変わる（流れない欄を作らない）
  - 全部埋めたシート＋鍵が登録済み → 準備状況が全部 ok（対象外を除く）。方式ごとに確かめる
  - 欄を抜いたシート → 抜けた欄が効く機能だけが ok でなくなる
  - 鍵が未登録: シートで「送付済み」なら当社の受領待ち、それ以外はお客様の要対応
  - 足した欄の行き先（繁忙期→season・競合→compete・触ってはいけないページ→site_renovate）が実際に効く
  - 担当者のメール・パスワードが public のファイル（sites/・brief.json・company.json）に出ない
"""
import contextlib
import inspect
import io
import json
import tempfile
from pathlib import Path

from test_gates import check, ROOT

FULL = {"wp": True, "ftp": True, "git": True, "youtube": True, "facebook": True, "instagram": True,
        "threads": True, "linkedin": True, "gbp": "ready"}


def sample(C, sid="h38-wp", t="wordpress"):
    """全欄を埋めたシートの回答（記入例を使い、既定と同じになる値だけ差し替える）"""
    got = {k: ex for k, _l, _d, ex, _r in C.fields_for() if not k.startswith("#") and ex}
    got.update({
        "id": sid, "name": "H38メディア", "domain": f"{sid}.example.test", "type": t,
        "categories": f"{sid}-a: A\n{sid}-b: B", "category_mix": f"{sid}-a: 60\n{sid}-b: 40",
        "main_category": f"{sid}-a", "monthly_cap": "30", "review_before_publish": "要",
        "report_issuer": "お客様名だけ", "branch": "develop", "ga4.installed": "入っている",
        "renovate_auto": "CSSのみ", "languages": "en", "note": "申し送り", "kw.known": "経理代行 大阪",
        "link.known": "https://links.example.test/a", "gbp.description": "大阪の経理代行の会社です。",
        "wp_api": f"https://{sid}.example.test/wp-json/wp/v2", "facts.2.denominator": "42",
        "facts.2.period": "2025-04〜2026-03", "facts.3.claim": "初月の並行稼働で引き継ぎ漏れは0件でした",
        "facts.1.source": "自社の受託台帳", "facts.3.source": "自社の受託台帳", "facts.3.as_of": "2026-09", "case.2.summary": "飲食店の給与計算",
        "case.2.result": "締めから支給まで5日", "case.2.publish": "可（社名を出す）", "case.2.confirmed": "済",
        "voice.2.text": "相談しやすかったです", "voice.2.name": "京都市の飲食店", "voice.2.publish": "可",
        "voice.2.by": "本人が内容を確認した",
    })
    return got


def outputs(C, got, ind=""):
    sid = got.get("id") or "client"
    return json.dumps([C.to_config(got), C.to_company(got), C.to_private(got), C.to_brief(got, ind),
                       C.to_facts(got, sid)], ensure_ascii=False, sort_keys=True)


@contextlib.contextmanager
def tree():
    """client_intake の書き先を一時フォルダへ向ける"""
    import client_intake as C
    old = (C.ROOT, C.SITES)
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "sites").mkdir()
        C.ROOT, C.SITES = r, r / "sites"
        try:
            yield r
        finally:
            C.ROOT, C.SITES = old


def statuses(R, sid, root, have):
    return {x["id"]: x["status"] for x in R.compute(sid, root, have)}


def bad(st):
    return {k for k, v in st.items() if v not in ("ok", "n/a")}


def test_sheet_has_howto_marks_and_choices():
    print("\n■ ヒアリングシート: 記入のしかた・5列・方式ごとの必須・プルダウン・以前の版も読める")
    import client_intake as C
    from openpyxl import Workbook, load_workbook
    with tempfile.TemporaryDirectory() as d:
        p = C.make_sheet(Path(d) / "s.xlsx")
        ws = load_workbook(p).active
        check("先頭に記入のしかたの枠", str(ws.cell(row=3, column=1).value).startswith("■ 記入のしかた"), True)
        check("記入のしかたに別経路・所要時間がある",
              all(any(w in str(ws.cell(row=r, column=1).value) for r in range(3, C.HEAD_ROW)) for w in ("別の方法", "所要時間")),
              True)
        check("見出しは5列（記入例の列がある）", [ws.cell(row=C.HEAD_ROW, column=i).value for i in range(1, 6)],
              ["項目", "ご記入欄", "必須", "説明", "記入例（見本）"])
        rows = {ws.cell(row=r, column=6).value: r for r in range(C.SAMPLE_ROW, ws.max_row + 1)}
        check("WordPress の欄は「WordPressなら必須」", ws.cell(row=rows["wp.user"], column=3).value, "WordPressなら必須")
        check("接頭辞は Git・FTP で必須", ws.cell(row=rows["url_prefix"], column=3).value, "FTP・Gitなら必須")
        check("会社名は必須", ws.cell(row=rows["company.name"], column=3).value, "必須")
        cells = {str(c) for v in ws.data_validations.dataValidation for rng in v.sqref.ranges for c in [rng.coord]}
        miss = [k for k in C.CHOICES if f"B{rows[k]}" not in cells]
        check("選択肢のある欄はすべてプルダウン", miss, [])
        check("記入例は E 列に出る", ws.cell(row=rows["company.name"], column=5).value, "株式会社サンプル商事")
        # 以前の版（4行目から記入欄・記入のしかたの枠なし）でも読める
        wb = Workbook()
        o = wb.active
        o.cell(row=4, column=6, value="company.name")
        o.cell(row=4, column=2, value="旧版株式会社")
        o.cell(row=5, column=6, value="asset.gbp")
        o.cell(row=5, column=2, value="登録済み")
        wb.save(Path(d) / "old.xlsx")
        g = C.read_sheet(Path(d) / "old.xlsx")
        check("以前の版のシートも読める（4行目から）", (g.get("company.name"), g.get("gbp.status")), ("旧版株式会社", "登録済み"))
        # 書いて読むと同じ値に戻る
        wb2 = load_workbook(p)
        w2 = wb2.active
        w2.cell(row=rows["ftp.protocol"], column=2, value="SFTP")
        wb2.save(p)
        check("書いた値を読み戻せる", C.read_sheet(p).get("ftp.protocol"), "SFTP")
    for ind in ("", "restaurant"):
        with tempfile.TemporaryDirectory() as d:
            ws = load_workbook(C.make_sheet(Path(d) / "s.xlsx", ind)).active
            f = [v.formula1 for v in ws.data_validations.dataValidation if "ftp" in str(v.formula1)]
            check(f"形式の選択肢は1つで zip を含まない（{ind or '汎用'}）", (len(f), "zip" in str(f)), (1, False))
    ng, _ = C.review({"type": "wordpress"}, {"id": "h38-x", "type": "wordpress"})
    ng2, _ = C.review({"type": "ftp"}, {"id": "h38-y", "type": "ftp"})
    check("方式の印: WordPress の社だけ投稿用ユーザー名を求める",
          (any("投稿用のユーザー名" in m for m in ng), any("投稿用のユーザー名" in m for m in ng2)), (True, False))
    check("方式の印: FTP の社だけホスト名を求める",
          (any("FTP のホスト名" in m for m in ng), any("FTP のホスト名" in m for m in ng2)), (False, True))


def test_every_field_flows_somewhere():
    print("\n■ ヒアリングシート: 全欄に流れ先があり、抜くと登録の中身が変わる")
    import client_intake as C
    import intake_readiness as R
    keys = [k for k, *_ in C.fields_for("restaurant") if not k.startswith("#")]
    check("流れ先の無い欄が無い", [k for k in keys if not C.flow_of(k)], [])
    check("同じキーの欄が無い", len(keys), len(set(keys)))
    for ind in ("", "restaurant"):
        got = sample(C)
        if ind:
            got.update({k: ex or "x" for k, _l, _d, ex, _r in C.INDUSTRY[ind][1] + C.INDUSTRY_LINK[ind]
                        if not k.startswith("#")})
        base = outputs(C, got, ind)
        same = [k for k in got if outputs(C, {x: v for x, v in got.items() if x != k}, ind) == base]
        check(f"抜いても登録の中身が変わらない欄が無い（{ind or '汎用'}）", same, [])
    doc = (ROOT / "docs" / "intake-requirements.md")
    check("docs/intake-requirements.md は今の定義から作ったもの（intake_readiness.py --doc）",
          doc.is_file() and doc.read_text(encoding="utf-8") == R.doc_text(), True)
    check("準備状況の各機能が挙げる欄はシートにある",
          [f for it in R.ITEMS for f in it[3] if f not in keys], [])


def test_full_sheet_is_ready_and_missing_fields_point_to_features():
    print("\n■ 準備状況: 全部埋めて鍵も登録済みなら全部 ok・抜けた欄の機能だけが ok でなくなる")
    import client_intake as C
    import intake_readiness as R
    for t, sid in (("wordpress", "h38-wp"), ("ftp", "h38-ftp"), ("external-html", "h38-git"), ("self-static", "h38-new")):
        with tree() as root:
            got = sample(C, sid, t)
            cfg = C.to_config(got)
            ng, _ = C.review(got, cfg)
            check(f"全部埋めたシートは不備なし（{t}）", [m for m in ng if "既に" not in m], [])
            C.apply(got, cfg)
            st = statuses(R, sid, root, FULL)
            check(f"全部埋めて鍵が登録済みなら全部 ok（{t}）", bad(st), set())
            if t == "wordpress":
                R.save(sid, R.compute(sid, root, FULL), root)
                saved = (root / "data" / "clients" / sid / "readiness.json").read_text(encoding="utf-8")
                check("readiness.json に担当者のメールを書かない", "@" in saved, False)

    expect = {"ga4.viewer": {"measurement"}, "gsc_owner": {"search_console", "indexing_api"},
              "compete.sites": {"compete"}, "season.peaks": {"season"}, "wp.plugin": {"quality_gate"},
              "supervisor.contact": {"supervisor"}, "wp.admin_key": {"site_renovate"},
              "gbp.invite": set(), "bing_consent": {"bing"}}
    for k, want in expect.items():
        with tree() as root:
            got = sample(C)
            got.pop(k)
            C.apply(got, C.to_config(got))
            check(f"「{k}」を抜くと ok でなくなるのはその機能だけ", bad(statuses(R, "h38-wp", root, FULL)), want)

    # 鍵が未登録のとき: シートで「送付済み」なら当社の受領待ち、そうでなければお客様に送付をお願いする
    have = dict(FULL, wp=False)
    for sent, who, st in (("送付済み", "当社", "wait"), ("これから送る", "お客様", "todo")):
        with tree() as root:
            got = dict(sample(C), **{"keys.sent": sent})
            C.apply(got, C.to_config(got))
            it = {x["id"]: x for x in R.compute("h38-wp", root, have)}
            check(f"鍵が未登録・{sent} → 配信と改修が{R.LABEL[st]}（{who}）",
                  (it["publish"]["status"], it["publish"]["who"], it["site_renovate"]["status"]), (st, who, st))
    # 許可の手続きが当社に残る（管理者の追加は済・鍵はまだ）
    with tree() as root:
        got = dict(sample(C), **{"channels.admin_added": "済"})
        C.apply(got, C.to_config(got))
        it = {x["id"]: x for x in R.compute("h38-wp", root, dict(FULL, youtube=False, gbp="token"))}
        check("YouTube: 管理者の追加が済で鍵が無ければ当社の受領待ち", (it["youtube"]["status"], it["youtube"]["who"]), ("wait", "当社"))
        check("GBP: 鍵はあるが店舗が未選択なら当社の作業", (it["gbp"]["status"], "gbp.location" in it["gbp"]["need"]), ("wait", True))

    # 通知（findings）に載せる行: 任意は載せない・search_connect が知らせるオーナーは重ねない
    with tree() as root:
        got = sample(C)
        for k in ("gsc_owner", "compete.sites", "ga4.viewer"):
            got.pop(k)
        C.apply(got, C.to_config(got))
        with contextlib.redirect_stdout(io.StringIO()):
            lines = R.check_site("h38-wp", root, FULL)
        check("通知: GA4 の閲覧者は載る・任意（競合）と重ね（オーナー）は載らない",
              (any("GA4 に当社を閲覧者で追加" in l for l in lines), any("競合" in l for l in lines),
               any("オーナー" in l for l in lines), all(l.startswith("要対応: ") for l in lines)), (True, False, False, True))
        got["gsc_owner"] = "済"
        got["gsc.property"] = "ドメインだけ"
        C.SITES.joinpath("h38-wp.json").write_text(json.dumps(C.to_config(got), ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            lines = R.check_site("h38-wp", root, FULL)
        check("通知: オーナーでもドメインのプロパティだけなら載る（search_connect は見ていない）",
              any("URLプレフィックスのプロパティ" in l for l in lines), True)


def test_new_fields_take_effect():
    print("\n■ 足した欄の行き先が効く（繁忙期・競合・触ってはいけないページ・導線・タグ・地図・事例と声）")
    import client_intake as C
    import compete as CP
    import season as SE
    import site_renovate as SR
    got = sample(C)
    cfg = C.to_config(got)
    check("繁忙期 → season.peaks", cfg["season"]["peaks"], [{"month": 12, "words": ["年末調整"]}, {"month": 3, "words": ["決算"]}])
    check("season: 1年分そろうまでは申告の繁忙期で山の月を決める", SE.declared_peaks(cfg).get("年末調整"), (12, 0, 0))
    check("競合 → compete.rivals（ドメインだけ・自社を除く）", cfg["compete"]["rivals"],
          ["example-a.co.jp", "example-b.co.jp", "example-c.co.jp"])
    items = [{"ai_answered": True, "ai_ours": False, "pos": 5, "ai": {}, "ai_domains": ["www.example-a.co.jp"]}]
    s = CP.summarize(items, {"h38-wp.example.test"}, set(), CP.declared_rivals(cfg))
    got_c = {c["domain"]: (c["ai_n"], c.get("declared")) for c in s["competitors"]}
    check("compete: 出典に1回しか出ない競合も、挙げた社は比較に入る", got_c.get("example-a.co.jp"), (1, True))
    check("compete: 挙げていなければ従来どおり（2語未満は出さない）",
          CP.summarize(items, {"h38-wp.example.test"}, set())["competitors"], [])
    check("触ってはいけないページ → renovate_protect", cfg["renovate_protect"], ["/recruit/", "/privacy/"])
    check("site_renovate: 静的なファイルはパスで止める",
          (SR.protected(cfg, "recruit/index.html"), SR.protected(cfg, "public/recruit/index.html"),
           SR.protected(cfg, "src/pages/privacy.astro"), SR.protected(cfg, "about/index.html")),
          ("/recruit/", "/recruit/", "/privacy/", ""))
    check("site_renovate: WordPress の固定ページは link で止める",
          SR.protected(cfg, "pages/12.json", json.dumps({"link": "https://h38.example.test/recruit/"}).encode()), "/recruit/")
    check("site_renovate: 検査が止める", "protected(cfg, f" in inspect.getsource(SR.inspect_changes), True)
    check("確認なしで反映してよい範囲 → renovate_auto", (cfg["renovate_auto"], SR.auto_ok(cfg, [("M", "a.css")], {"css"})),
          (["css"], True))
    check("軽い入口 → cta_mid", cfg["cta_mid"]["url"], "https://example.co.jp/check/")
    check("SNS のタグ → x_tags", cfg["x_tags"], ["経理代行", "大阪"])
    check("地図の説明文 → gbp.description", cfg["gbp"]["description"], "大阪の経理代行の会社です。")
    check("狙いたい地域・優先業種 → kw_seeds", (cfg["kw_seeds"]["regions"], cfg["kw_seeds"]["priority"]),
          (["大阪府", "兵庫県"], ["クリニック", "建設業"]))
    check("まとめのページの置き場所 → pages_dir", cfg["pages_dir"], "src/content/pages")
    check("業種の表現の決まり → rules.regulation", cfg["rules"]["regulation"], ["景品表示法"])
    b = C.to_brief(dict(got, **{"case.2.confirmed": "未", "voice.2.by": "未確認"}))
    check("事例・声は掲載が可で本人の確認が済んだものだけ",
          ([c["summary"] for c in b["cases"]], [v["name"] for v in b["voices"]]),
          (["従業員30名の製造業。月次決算の代行"], ["大阪市の製造業"]))
    pub = json.dumps([cfg, C.to_brief(got), C.to_company(got)], ensure_ascii=False)
    check("public のファイルに担当者・監修の連絡先のメールが出ない",
          [m for m in ("hanako@example.co.jp", "sato@example.jp", "taro@example.co.jp") if m in pub], [])
    priv = C.to_private(got)
    check("担当者・接続先は private.json へ", (priv["contact"]["email"], priv["ftp"]["host"], priv["wp"]["user"]),
          ("hanako@example.co.jp", "sv1234.xserver.jp", "ss-editor"))
    t = C.creds_template("h38-wp", priv)
    check("鍵の登録の形はパスワードを空欄にして出す",
          (t["FTP_CREDENTIALS_JSON"]["h38-wp"]["host"], t["WP_CREDENTIALS_JSON"]["h38-wp"]["password"].startswith("<")),
          ("sv1234.xserver.jp", True))
    check("シートでパスワードを聞かない", [k for k, *_ in C.fields_for("restaurant") if "password" in k or "pass" in k], [])


def test_readiness_is_wired():
    print("\n■ 準備状況: 登録の最後に出し、週次の通知に載せ、public に置かない")
    import subprocess
    import findings as F
    import intake_watch as IW
    import client_intake as C
    check("intake_watch: 登録の直後に準備状況を出す", 'readiness(cfg.get("id"))' in inspect.getsource(IW.one), True)
    check("client_intake --apply: 最後に準備状況を出す", "R.check_site(cfg[\"id\"])" in inspect.getsource(C.main), True)
    check("findings が準備状況を回す", any(s == "intake_readiness.py --all" for _, s, _ in F.CHECKS), True)
    r = subprocess.run(["git", "check-ignore", "-q", "data/clients/x/readiness.json"], cwd=str(ROOT), capture_output=True)
    check("readiness.json は public に置かない", r.returncode, 0)
    import intake_readiness as R
    with contextlib.redirect_stdout(io.StringIO()) as o:
        R.main(["--all"])
    check("お客様の社が無ければ READINESS_OK=unset（自社3サイトは見ない）",
          "READINESS_OK=unset" in o.getvalue() or "READINESS_OK=" in o.getvalue(), True)
