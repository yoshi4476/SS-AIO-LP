# -*- coding: utf-8 -*-
"""機能ごとの準備状況: ヒアリングシートで受けた内容と、別経路で受け取る鍵の登録の有無から、
お客様の社の各機能が動く状態かを出す（運用者の依頼 2026-10-07「シートを読み込むだけで全機能が動く」）。

onboard_check.py は本番のサイトを読んで「先方の作り次第」の項目を確かめる。こちらは本番を読まず、
登録した設定（sites/<id>.json と非公開の置き場 private/clients/<id>/。private_store）と鍵の有無だけで判定する（重ねて見ない）。

  python scripts/intake_readiness.py --site <id>   # 1社（data/clients/<id>/readiness.json に残す。public に置かない）
  python scripts/intake_readiness.py --all         # お客様の全社（週次 findings・ヒアリングの登録直後）
  python scripts/intake_readiness.py --doc         # docs/intake-requirements.md を作り直す

状態:
  ok        動く。鍵の要る機能は「別経路で受領済み」= 鍵が管制塔に登録されている（Secret・.env・手元の鍵ファイル）
  要対応    お客様にお願いすること（シートの欄・権限の追加・鍵の送付）
  受領待ち  当社の作業（受け取った鍵の登録・許可の手続き）。シートの「別経路でお送りする鍵」が「送付済み」のとき
  任意      無くても動くが、効きが落ちる（通知には載せない）
  対象外    その社では使わない機能

鍵の中身は読まない・出さない（あるかだけ）。担当者の名前・メールは出力にも readiness.json にも書かない。
印（CLAUDE.md 8.7）: 要対応・受領待ちがあれば「要対応: <社> <機能>: <何が要るか>（<誰が>）」と READINESS_OK=no、
無ければ yes、お客様の社が無ければ unset。終了コードは常に0。
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

GIT = ("external-md", "external-html", "nextjs-json")
LABEL = {"ok": "ok", "todo": "要対応", "wait": "受領待ち", "optional": "任意", "n/a": "対象外"}
SOCIAL = {"facebook": ("Facebook", "FB_PAGE_TOKEN"), "instagram": ("Instagram", "IG_USER_ID"),
          "threads": ("Threads", "THREADS_TOKEN"), "linkedin": ("LinkedIn", "LINKEDIN_TOKEN")}


def _json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def load(site_id, root=ROOT):
    # お客様から預かった内容は非公開の置き場（private_store）。サイト設定は公開側の項目に戦略の部分を重ねる
    import private_store as PS
    cfg = {**PS.site_private(site_id, root=root), **(_json(root / "sites" / f"{site_id}.json") or {"id": site_id})}
    facts = PS.read_json(site_id, "facts.json", {}, root=root) or {}
    return {"cfg": cfg, "company": PS.read_json(site_id, "company.json", {}, root=root) or {},
            "brief": PS.read_json(site_id, "brief.json", {}, root=root) or {},
            "facts": facts.get("facts", []) if isinstance(facts, dict) else [],
            # private.json が無いとき（非公開のデータを取れない回）は、それを見る判定を飛ばす（鍵の登録で判定する）
            "private": PS.read_json(site_id, "private.json", None, root=root)}


def connections(cfg, root=ROOT):
    """別経路で受け取る鍵が登録されているか（中身は見ない）。{名前: bool}、gbp だけ "ready" / "token" / ""。"""
    sid = cfg["id"]
    have = {}
    try:
        import wp_bridge
        have["wp"] = cfg.get("type") == "wordpress" and wp_bridge._has_auth(cfg)
    except Exception:
        have["wp"] = False
    try:
        import deliver_files
        deliver_files.credentials(cfg)
        have["ftp"] = True
    except (SystemExit, Exception):
        have["ftp"] = False
    try:
        import publish
        have["git"] = bool(publish._push_token())
    except Exception:
        have["git"] = bool(os.environ.get("SITE_PUSH_TOKEN"))
    import client_private as CP           # お客様の社の id は非公開のリポジトリに書く
    yt = CP.load_connected(root / "data" / "youtube_connected.json")
    have["youtube"] = (root / f"youtube-token-{sid}.json").is_file() or sid in yt
    raw = os.environ.get("SOCIAL_TOKENS_JSON") or ""
    if not raw and (root / "social-tokens.json").is_file():
        raw = (root / "social-tokens.json").read_text(encoding="utf-8-sig")
    try:
        ent = (json.loads(raw or "{}").get(sid) or {})
    except ValueError:
        ent = {}
    for k, (_, field) in SOCIAL.items():
        have[k] = bool(ent.get(field))
    tok = (root / f"gbp-token-{sid}.json").is_file()
    have["gbp"] = "ready" if tok and (cfg.get("gbp") or {}).get("location") else ("token" if tok else "")
    return have


# ---------------------------------------------------------------- 機能ごとの判定

def _key(ctx, name, what):
    """鍵: 登録済みなら ok。シートで「送付済み」なら当社の登録待ち、それ以外はお客様に送付をお願いする"""
    if ctx["have"].get(name):
        return "ok", "", ""
    if ctx["ob"].get("keys_sent") == "送付済み":
        return "wait", f"{what}の登録（別経路で受け取ったものを管制塔へ。client_intake.py --creds {ctx['cfg']['id']} が形を出す）", "当社"
    return "todo", f"{what}を別経路で送付", "お客様"


def _first(*results):
    """最初に ok でなかったもの。全部 ok なら ok"""
    for r in results:
        if r and r[0] != "ok":
            return r
    return "ok", "", ""


def c_publish(ctx):
    cfg, ob, priv, t = ctx["cfg"], ctx["ob"], ctx["private"], ctx["cfg"].get("type")
    if t == "wordpress":
        if not ctx["have"].get("wp") and priv is not None and not (priv.get("wp") or {}).get("user"):
            return "todo", "WordPress の投稿用ユーザー名（権限は編集者）をシートに", "お客様"
        return _key(ctx, "wp", "WordPress のアプリケーションパスワード")
    if t == "ftp":
        f = (priv or {}).get("ftp") or {}
        if not ctx["have"].get("ftp") and priv is not None and not (f.get("host") and f.get("root")):
            return "todo", "FTP のホスト名・ユーザー名・公開フォルダをシートに", "お客様"
        return _key(ctx, "ftp", "FTP のパスワード")
    if t in GIT:
        return _first(("todo", "配信先リポジトリ（owner/repo）をシートに", "お客様") if not cfg.get("repo") else None,
                      ("todo", "GitHub で当社のアカウントを Write で招待", "お客様") if not ob.get("git_invited") else None,
                      ("wait", "配信用トークン（SITE_PUSH_TOKEN）の登録", "当社") if not ctx["have"].get("git") else None)
    if t == "self-static":
        # DNS が本番に向いたかは onboard_check が本番で確かめる（ここではシートの答えだけを見る）
        if not ob.get("dns_access") or (priv is not None and not (priv.get("dns") or {}).get("provider")):
            return "todo", "DNS の管理会社と、設定をどちらが行うか", "お客様"
        return "ok", "", ""
    return "todo", f"サイトの形式（{t}）を新規受付のある方式に", "お客様"


def c_quality(ctx):
    if ctx["cfg"].get("type") != "wordpress":
        return "ok", "", ""
    how = ctx["ob"].get("wp_plugin", "")
    if how == "御社で置く":
        return "ok", "", ""           # 置けたかは wp_bridge.py --check・onboard_check が本番で確かめる
    if how == "当社が置く":
        if not ctx["ob"].get("ftp_ok") and not ctx["have"].get("ftp"):
            return "todo", "FTP の接続情報（品質の検査のプラグインを置くため）", "お客様"
        return _key(ctx, "ftp", "FTP のパスワード")
    return "todo", "品質の検査のプラグイン（mu-plugin）の置き方（当社が置く／御社で置く）", "お客様"


def c_writing(ctx):
    hard = [f for f in ctx["facts"] if f.get("verifiable")]
    b, sup = ctx["brief"], (ctx["company"].get("supervisor") or {})
    return _first(("todo", "一次情報（その会社にしか出せない数値）を1つ以上", "お客様") if not hard else None,
                  ("todo", "よく聞かれる質問（FAQ）", "お客様") if not (b.get("customer") or {}).get("faq") else None,
                  ("todo", "記事の書き手（著者名・肩書き）", "お客様") if not (b.get("author") or {}).get("name") else None,
                  ("todo", "監修者の掲載の同意（可）", "お客様") if not sup.get("display") else None)


def c_supervisor_contact(ctx):
    priv = ctx["private"]
    if priv is not None and not priv.get("supervisor_contact"):
        return "todo", "監修者の確認のご連絡先（メール）", "お客様"
    return "ok", "", ""


def c_measure(ctx):
    cfg, ob = ctx["cfg"], ctx["ob"]
    tag = None
    if cfg.get("type") in ("wordpress", "ftp") and not cfg.get("ga4_measurement_id") and not ob.get("ga4_installed"):
        tag = ("todo", "GA4 の測定ID（G-）。サイトに GA4 が入っていれば「入っている」に", "お客様")
    return _first(("todo", "GA4 のプロパティID", "お客様") if not cfg.get("ga4_property_id") else None,
                  ("todo", "GA4 に当社を閲覧者で追加", "お客様") if not ob.get("ga4_viewer") else None, tag)


def c_gsc(ctx):
    cfg, ob = ctx["cfg"], ctx["ob"]
    if not cfg.get("gsc_owner"):
        return "todo", "Search Console に当社のサービスアカウントをオーナーで追加", "お客様"
    if ob.get("gsc_property") in ("ドメインだけ", "まだ無い"):
        # オーナーでもプロパティの形が違えば読めない。search_connect は見ていないので、こちらで知らせる
        return "todo", f"Search Console に https://{cfg.get('domain')}/ のURLプレフィックスのプロパティを追加", "お客様", ""
    return "ok", "", ""


def c_indexing(ctx):
    return ("ok", "", "") if ctx["cfg"].get("gsc_owner") else ("todo", "Search Console のオーナー（上と同じ）", "お客様")


def c_bing(ctx):
    return ("ok", "", "") if ctx["cfg"].get("bing_consent") else \
        ("optional", "Bing への登録の同意（可にすると Bing・ChatGPT の検索へすぐ届きます。IndexNow は同意なしでも届きます）", "お客様")


def c_report(ctx):
    priv = ctx["private"]
    if (priv or {}).get("report_to") or ctx["company"].get("email") or priv is None:
        return "ok", "", ""
    return "todo", "レポートの送付先", "お客様"


def c_compete(ctx):
    if (ctx["cfg"].get("compete") or {}).get("rivals"):
        return "ok", "", ""
    return "optional", "競合のサイト（無ければ、AIの出典に2語以上で出た同業から自動で選びます）", "お客様"


def c_season(ctx):
    if (ctx["cfg"].get("season") or {}).get("peaks"):
        return "ok", "", ""
    return "optional", "繁忙期（無ければ、1年分の検索データがそろってから自動で判定します）", "お客様"


def c_youtube(ctx):
    ch = ctx["cfg"].get("channels") or {}
    if not str(ch.get("video", "")).startswith("要"):
        return "n/a", "", ""
    if ctx["have"].get("youtube"):
        return "ok", "", ""
    if str(ch.get("admin_added", "")).startswith("済"):
        return "wait", f"YouTube の許可の手続き（python scripts/youtube_upload.py --auth --site {ctx['cfg']['id']}）", "当社"
    return "todo", "YouTube チャンネルに当社を管理者で追加", "お客様"


def c_social(ctx):
    ch = ctx["cfg"].get("channels") or {}
    want = [k for k in SOCIAL if ch.get(k)]
    if not want:
        return "n/a", "", ""
    miss = [SOCIAL[k][0] for k in want if not ctx["have"].get(k)]
    if not miss:
        return "ok", "", ""
    if str(ch.get("admin_added", "")).startswith("済"):
        return "wait", f"{'・'.join(miss)} の接続（python scripts/social_connect.py --site {ctx['cfg']['id']}）", "当社"
    return "todo", f"{'・'.join(miss)} に当社を管理者で追加", "お客様"


def c_gbp(ctx):
    ob, have = ctx["ob"], ctx["have"].get("gbp")
    st = ob.get("gbp_status", "")
    if st != "登録済み":
        return ("optional", "Googleビジネスプロフィールの登録（店舗がある業種は地図の検索に効きます）", "お客様") \
            if st == "未登録" else ("n/a", "", "")
    if have == "ready":
        return "ok", "", ""
    if have == "token":
        return "wait", f"店舗を選んで sites/{ctx['cfg']['id']}.json の gbp.location に書く（gbp.py --check）", "当社"
    if ob.get("gbp_invite"):
        return "wait", f"許可の手続き（python scripts/gbp.py --auth --site {ctx['cfg']['id']}）", "当社"
    return "todo", "Googleビジネスプロフィールに当社を管理者で追加", "お客様"


def c_i18n(ctx):
    return ("ok", "", "") if ctx["cfg"].get("languages") else ("n/a", "", "")


def c_renovate(ctx):
    cfg, ob, t = ctx["cfg"], ctx["ob"], ctx["cfg"].get("type")
    if not ob.get("renovate"):
        return "n/a", "", ""
    if t == "wordpress":
        return _first(_key(ctx, "wp", "WordPress のアプリケーションパスワード"),
                      ("todo", "管理者のアプリケーションパスワード（追加CSS・メニューの変更）", "お客様")
                      if not ob.get("wp_admin_key") else None)
    if t == "ftp":
        return _key(ctx, "ftp", "FTP のパスワード")
    if t in GIT:
        return c_publish(ctx)
    return "n/a", "", ""


def c_speed(ctx):
    if ctx["cfg"].get("type") != "wordpress":
        return "n/a", "", ""
    if ctx["have"].get("ftp"):
        return "ok", "", ""
    if ctx["ob"].get("ftp_ok"):
        return _key(ctx, "ftp", "FTP のパスワード")
    return "optional", "FTP の接続情報（テーマに直書きのフォント・計測タグを直すため。無ければ測って知らせるだけ）", "お客様"


# (id, 機能, 表の機能 caps, シートの欄, 別経路で受け取るもの, 無いとどうなるか, 判定, 同じ内容を知らせる別の検査)
ITEMS = [
    ("publish", "記事の配信（新記事・書き直し・まとめのページ・統合の転送）",
     ["publish_new", "rewrite_redeliver", "bulk_rerender", "merge_redirect", "body_images", "verify_publish",
      "sitemap", "llms_txt", "industry_hub", "glossary", "compare", "topics", "area", "season_feature", "live_check"],
     ["type", "domain", "url_prefix", "wp.admin_url", "wp.user", "repo", "branch", "content_dir", "images_dir",
      "pages_dir", "git.invited", "ftp.host", "ftp.protocol", "ftp.user", "ftp.root", "dns.provider", "dns.access",
      "keys.sent"],
     "WordPress: アプリケーションパスワード（WP_CREDENTIALS_JSON）／FTP: パスワード（FTP_CREDENTIALS_JSON）／"
     "Git: 当社の配信用トークン（SITE_PUSH_TOKEN）／新規構築: DNS のログイン情報（当社が行う場合）",
     "記事が1本も届かない", c_publish, ""),
    ("quality_gate", "品質ゲート（WordPress 側で90点未満を公開させない）", ["quality_gate"],
     ["wp.plugin", "wp.ftp"], "当社が置く場合は FTP のパスワード",
     "管理画面から公開された記事を止められない（管制塔からは90点未満を送らない）", c_quality, ""),
    ("writing", "記事の中身（一次情報・FAQ・著者・監修の表示）", ["ld_author_person", "ld_faqpage", "ld_blogposting"],
     ["facts.1.claim", "customer.faq", "author.name", "supervisor.consent"], "",
     "どこにでもある記事になり、AI検索に引用されない。監修の表示が出せない", c_writing, ""),
    ("supervisor", "監修の確認依頼（editorial_review）", ["quality_gate"], ["supervisor.contact", "supervisor.review"], "",
     "公開前の確認が「要」の社は、確認依頼が届かず記事が止まったままになる", c_supervisor_contact, ""),
    ("measurement", "計測（GA4・CTA・フォーム・入口）", ["measurement"],
     ["ga4_property_id", "ga4.viewer", "ga4.installed", "ga4_measurement_id"], "",
     "月次レポートに流入・問い合わせの数字が出ない。導線の効きが測れない", c_measure, ""),
    ("search_console", "検索の実績（順位・検索語: 月次レポート・競合比較・効果判定・季節）",
     ["monthly_report", "compete", "effect_ab", "internal_links"], ["gsc_owner", "gsc.property"], "",
     "順位と検索語が取れず、レポート・書き直しの判定・押し上げが動かない", c_gsc, "search_connect"),
    ("indexing_api", "Indexing API（Google への即時通知）", ["indexing_api"], ["gsc_owner"], "",
     "新しい記事を Google へすぐ知らせられない（サイトマップで後から拾われる）", c_indexing, "search_connect"),
    ("bing", "Bing（Webmaster API）", ["bing"], ["bing_consent"], "",
     "Bing・ChatGPT の検索へは IndexNow の通知だけになる", c_bing, ""),
    ("monthly_report", "月次レポートの宛先と名義", ["monthly_report"], ["report_to", "report_issuer", "company.email"], "",
     "レポートの宛先が決まらない", c_report, ""),
    ("compete", "競合比較の相手", ["compete"], ["compete.sites"], "",
     "AIの出典から自動で選ぶ（挙げた競合が比較に出ないことがある）", c_compete, ""),
    ("season", "季節の前出し", ["season_feature"], ["season.peaks"], "",
     "1年分の検索データがそろうまで、繁忙期の前に記事を前へ出せない", c_season, ""),
    ("youtube", "YouTube への動画の投稿", ["video_social", "video_embed"],
     ["channels.youtube", "channels.video", "channels.admin_added"], "先方の Google アカウントでの許可（1回・当社が手続き）",
     "動画を作らない（当社のチャンネルには上げない）", c_youtube, ""),
    ("social", "SNS への投稿（Facebook・Instagram・Threads・LinkedIn）", ["video_social"],
     ["channels.facebook", "channels.instagram", "channels.threads", "channels.linkedin", "channels.admin_added",
      "channels.tags"], "先方のアカウントでの許可（1回・当社が手続き）", "その社の SNS には投稿しない", c_social, ""),
    ("gbp", "Googleビジネスプロフィール（説明文・属性・口コミの返信案）", [],
     ["gbp.status", "gbp.invite", "gbp.description"], "先方の Google アカウントでの許可（1回・当社が手続き）",
     "地図の説明文・属性を揃えられない。口コミの件数を知らせられない", c_gbp, ""),
    ("i18n", "多言語の要約ページ", ["i18n"], ["languages"], "", "作らない（既定）", c_i18n, ""),
    ("site_renovate", "指示でのサイト改修", ["site_change", "site_renovate"],
     ["renovate.want", "renovate_auto", "renovate.protect", "renovate.wish", "wp.admin_key", "wp.ftp", "git.invited"],
     "WordPress: 管理者のアプリケーションパスワード／FTP: パスワード／Git: 招待",
     "サイトの改修を管制塔から行えない（記事の配信だけになる）", c_renovate, ""),
    ("speed_fix", "表示速度の直し（WordPress のテーマ）", ["speed_fix"], ["wp.ftp", "ftp.host"], "FTP のパスワード",
     "テーマに直書きのフォント・計測タグは測って知らせるだけになる", c_speed, ""),
]


def compute(site_id, root=ROOT, have=None):
    """[{id, label, status, need, who}]（対象外も含む）"""
    ctx = load(site_id, root)
    ctx["ob"] = ctx["cfg"].get("onboarding") or {}
    ctx["have"] = connections(ctx["cfg"], root) if have is None else have
    out = []
    for iid, label, _caps, _fields, _keys, _without, fn, dup in ITEMS:
        r = fn(ctx)
        st, need, who = r[:3]
        out.append({"id": iid, "label": label, "status": st, "need": need, "who": who,
                    "dup": r[3] if len(r) > 3 else dup})
    return out


def save(site_id, items, root=ROOT):
    p = root / "data" / "clients" / site_id / "readiness.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"site": site_id, "made": date.today().isoformat(),
                             "items": [{k: v for k, v in x.items() if k != "dup"} for x in items]},
                            ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return p


def todo_lines(name, items):
    """通知（findings）へ載せる行。任意・対象外は載せない。別の検査が同じことを知らせるものも載せない"""
    return [f"要対応: {name} {x['label'].split('（')[0]}: {x['need']}（{x['who']}）"
            for x in items if x["status"] in ("todo", "wait") and not x["dup"]]


def show(site_id, items, cfg=None):
    cfg = cfg or {}
    print(f"■ 準備状況: {cfg.get('name') or site_id}（{site_id}・{cfg.get('type', '?')}）")
    for x in items:
        tail = f": {x['need']}（{x['who']}）" if x["need"] else ""
        dup = f"  ※ {x['dup']}.py --check も同じことを知らせます" if x["dup"] and x["status"] != "ok" else ""
        print(f"   {LABEL[x['status']]:<6} {x['label']}{tail}{dup}")


def check_site(site_id, root=ROOT, have=None, write=True):
    """1社を判定して表示し、通知へ載せる行を返す"""
    items = compute(site_id, root, have)
    cfg = load(site_id, root)["cfg"]
    show(site_id, items, cfg)
    if write and _is_client(site_id, root):
        save(site_id, items, root)
    return todo_lines(cfg.get("name") or site_id, items)


def _is_client(site_id, root=ROOT):
    import private_store as PS
    return ((root / "data" / "clients" / site_id).is_dir() or PS.client_dir(site_id, root).is_dir()
            or bool((_json(root / "sites" / f"{site_id}.json") or {}).get("client")))


def clients(root=ROOT):
    if root == ROOT:                     # お客様の社は非公開の置き場の社の id（公開側の印の名前ではない）
        import sites as S
        return sorted(s for s in S.load_all() if S.is_client(s))
    return sorted(p.stem for p in (root / "sites").glob("*.json") if _is_client(p.stem, root))


# ---------------------------------------------------------------- 文書

def doc_text():
    """docs/intake-requirements.md（機能ごとに、何をもらえば動くか・シートのどの欄か・無いとどうなるか）"""
    import client_intake as C
    labels = {k: lab for k, lab, *_ in C.fields_for("restaurant")}
    caps = _json(ROOT / "data" / "capabilities.json") or {"features": {}}
    used = {c for it in ITEMS for c in it[2]}
    out = ["# ヒアリングシートで受けるもの（機能ごと）", "",
           "> `python scripts/intake_readiness.py --doc` で作り直す（手で直さない）。"
           "欄の定義は `scripts/client_intake.py`、判定は `scripts/intake_readiness.py`。",
           "> シートを `intake/` に置く（または `client_intake.py <シート> --apply`）と、最後に下の機能ごとの準備状況が出て、"
           "`data/clients/<id>/readiness.json`（public に置かない）に残る。要対応は週次の通知（findings）にも載る。", "",
           "## 機能ごとに要るもの", "",
           "| 機能 | シートの欄 | 別経路で受け取るもの | 無いとどうなるか |", "|:--|:--|:--|:--|"]
    for _id, label, _caps, fields, keys, without, _fn, _dup in ITEMS:
        f = "・".join(f"{labels.get(k, k)}（`{k}`）" for k in fields)
        out.append(f"| {label} | {f} | {keys or '—'} | {without} |")
    feats = caps.get("features", {})
    # お客様の方式（self-static 以外）のセルが全部「対象外」の機能は、運用会社自身のページ（お客様のサイトに置かない）
    own_only = {k for k, v in feats.items()
                if all(c.get("status") == "n/a" for m, c in v.get("cells", {}).items() if m != "self-static")}
    rest = [v["label"] for k, v in feats.items() if k not in used and k not in own_only]
    out += ["", "## シートの欄が要らない機能", "",
            "配信の接続（上の「記事の配信」）が済めば、欄を追加でもらわずに動く: " + "・".join(rest) + "。", "",
            "お客様のサイトには置かない（運用会社自身のページ）: "
            + "・".join(feats[k]["label"] for k in feats if k in own_only) + "。", "",
            "## 欄ごとの流れ先", "",
            "シートの全欄が、どこかの設定か準備状況へ流れる（流れない欄は作らない。門 `tests/gates_history_h38.py` が"
            "欄を1つずつ抜いて、出力が変わることを確かめる）。", "",
            "| 章 | 欄 | キー | 流れ先 |", "|:--|:--|:--|:--|"]
    chapter = ""
    for key, label, _d, _e, _r in C.fields_for("restaurant"):
        if key.startswith("#"):
            chapter = label
            continue
        out.append(f"| {chapter} | {label} | `{key}` | {C.flow_of(key)} |")
    out += ["", "## 状態の意味", "",
            "| 状態 | 意味 |", "|:--|:--|",
            "| ok | 動く。鍵の要る機能は「別経路で受領済み」＝鍵が管制塔に登録されている（Secret・.env・手元の鍵ファイル。中身は見ない） |",
            "| 要対応 | お客様にお願いすること（シートの欄・権限の追加・鍵の送付） |",
            "| 受領待ち | 当社の作業（シートの「別経路でお送りする鍵」が「送付済み」で、まだ登録していない鍵・許可の手続き） |",
            "| 任意 | 無くても動くが効きが落ちる（通知には載せない） |",
            "| 対象外 | その社では使わない |", ""]
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--doc" in argv:
        p = ROOT / "docs" / "intake-requirements.md"
        p.write_text(doc_text(), encoding="utf-8", newline="\n")
        print(f"{p.relative_to(ROOT).as_posix()} を作り直しました")
        return 0
    if "--site" in argv:
        ids = [argv[argv.index("--site") + 1]]
    elif "--all" in argv:
        ids = clients()
    else:
        print(__doc__)
        return 0
    if not ids:
        print("READINESS_OK=unset（お客様の社がありません）")
        return 0
    bad = []
    for sid in ids:
        bad += check_site(sid)
    for line in dict.fromkeys(bad):
        print(line)
    print("READINESS_OK=" + ("no" if bad else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
