# -*- coding: utf-8 -*-
"""2026-10-10 運用者の指示（守秘義務）の続き。h76 の後も、外部のお客様を受けると次が公開側に出るところだった。

  - sites/<id>.json の name・domain・repo（公開してよい項目に入れていた）と、社名をそのまま使った id
  - articles/ の原稿（公開前・90点未満で止めたものも）と、その図（site/images/<slug>/）・動画の台本（data/duo_*）
  - 全社1ファイルの記録のその社の行（data/videos.json・youtube_connected.json・editorial_reviews.jsonl・
    bing_backfill.json）と、能力の目録（capabilities.json）・コメント・門に書いた社名・ドメイン・記事の slug
  - CI のログ: 公開した記事の slug（「[1] ○ <slug>」）・題・URL、コミットの文の社の id・記事の slug

決めたこと:
  1. 公開側に残すのは社が特定できない印（sites/<公開の id>.json に id・client・daily_articles の3つ）だけ。
     公開の id は社名から推測できない（c と16進8桁）。新しく受けるお客様は社の id も同じ値にする
  2. 社名・ドメイン・配信先・カテゴリ・戦略の部分は非公開のリポジトリの clients/<社の id>/site_private.json。
     sites.load_all がそこから読む。取れない回はお客様の社は入らず、自社3サイトはこれまでどおり動く
  3. 原稿・図・台本は非公開のリポジトリに置き、取得のたびに作業場所へ重ねて置く（.git/info/exclude で公開側の git から
     外す）。commit の直前の見張り（.git/hooks/pre-commit）とジョブの最後（private-data の save）で非公開へ戻す
  4. 全社1ファイルの記録のお客様の行は、非公開のリポジトリ（client_private.REPO_BACKED）に書き、読むときに合わせる
  5. CI のログには、お客様の社の記事の題・slug を出さない（件数か「（お客様の記事）」）。ジョブの間とコミットの文は
     公開の id で渡す。門の出力（test_gates.check）も社の id・名前を公開の id に置き換える
  6. 運用者自身の事業の社も同じ道を毎日通す（外部のお客様より先に、壊れた所が見つかる）。自社サイトのフッターの制作表記
     など、もともと公開している表示は残す（DISPLAY_OK）
"""
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT
from gates_history_h72 import patched, _quiet
from gates_history_h76 import _env, _workflows

sys.path.insert(0, str(ROOT / "scripts"))

# 運用者がもともと公開している表示（自社サイトのフッターの制作表記・無料ツールの開発者）。お客様の社の名前・ドメインが
# 出てよいのはここだけ。記事の題・slug はここでも出てはいけない
DISPLAY_OK = ("site/", "site.config.json", "scripts/subsidy/footer_credit.py", "scripts/tools_catalog.py")
TEXT_EXT = {".py", ".md", ".json", ".jsonl", ".yml", ".yaml", ".txt", ".html", ".xml", ".js", ".css", ".gs", ".csv",
            ".toml", ".ini", ".sh", ".ps1", ".tsx", ".ts", ".mjs", ".svg", ""}
URL = re.compile(r"https?://([^/\s\"'<>)]+)[^\s\"'<>)]*")
# 名前を出してよいか・slug を数えるかで、ログの出し方を替えた道具（お客様の記事の slug を CI のログに出さない）
QUIET_TOOLS = ("build.py", "publish_gap.py", "fix_block_breaks.py", "split_paragraphs.py", "split_sentences.py",
               "anchor_audit.py", "shorten_anchors.py", "cta_fill.py")


def _tracked():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True)
    return [x for x in r.stdout.decode("utf-8", "replace").split("\0") if x]


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _own():
    import sites as S
    ids = [s for s in S.load_all() if not S.is_client(s)]
    return ids, {str(S.load(s).get("domain") or "").lower().replace("www.", "") for s in ids}


# ── 1. 公開側の印は、社が特定できない3項目だけ ─────────────────────────────────

def test_public_stub_is_only_an_opaque_mark():
    print("\n■ 守秘義務: 公開側の sites/ に残るお客様の社は、社が特定できない印だけ（2026-10-10）")
    import sites as S
    import private_store as PS
    check("公開してよい項目は id・client・daily_articles の3つ", tuple(S.PUBLIC_KEYS), ("id", "client", "daily_articles"))
    extra, names = [], []
    for p in sorted((ROOT / "sites").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        if not d.get("client"):
            continue
        if not set(d) <= set(S.PUBLIC_KEYS):
            extra.append(f"{p.name}: {sorted(set(d) - set(S.PUBLIC_KEYS))}")
        if not re.fullmatch(r"c[0-9a-f]{8}", p.stem) or d.get("id") != p.stem:
            names.append(p.name)
    check("お客様の社の印に名前・ドメイン・配信先・カテゴリを置かない", extra, [])
    check("印の名前は社名から推測できない公開の id（c と16進8桁）", names, [])
    with tempfile.TemporaryDirectory() as td:
        ids = [PS.new_public_id(td) for _ in range(5)]
        check("新しい公開の id は c と16進8桁で、毎回違う",
              (all(re.fullmatch(r"c[0-9a-f]{8}", x) for x in ids), len(set(ids))), (True, 5))
        import client_intake as C
        cfg = {"id": "sample-shoji", "name": "株式会社サンプル商事", "domain": "sample-shoji.example"}
        with patched(C, SITES=Path(td)):
            pid = C.assign_id(cfg)
        check("新しく受けるお客様の id は、シートに書かれた id や社名から作らない（社の id ＝ 公開の id）",
              (bool(re.fullmatch(r"c[0-9a-f]{8}", pid)), cfg["id"], cfg["public_id"]), (True, pid, pid))
    src = (ROOT / "scripts" / "intake_watch.py").read_text(encoding="utf-8")
    check("置き場に置いたシートの登録も同じ付け方（intake_watch）", "C.assign_id(cfg)" in src, True)


def test_load_all_reads_the_company_from_the_private_store():
    print("\n■ 守秘義務: 社の設定は非公開の置き場から読む。取れない回はお客様の社だけ外れ、自社は動く")
    import sites as S
    import private_store as PS
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        sd, priv = t / "sites", t / "private"
        sd.mkdir()
        (sd / "own-x.json").write_text(json.dumps({"id": "own-x", "domain": "own.example", "categories": {"ox": "O"}}),
                                       encoding="utf-8")
        cz = {"id": "c0a1b2c3d", "public_id": "c0a1b2c3d", "name": "架空の社", "domain": "zz.example", "repo": "o/zz",
              "type": "external-md", "categories": {"zz-blog": "Z"}, "daily_articles": 1}
        # 運用者の事業の社のように、社の id（内部の名前）と公開の id が違う社
        cy = {"id": "yy-own", "public_id": "c1234abcd", "name": "架空の事業", "domain": "yy.example",
              "type": "external-md", "categories": {"yy-blog": "Y"}}
        with _env(SS_PRIVATE_DIR=str(priv)), patched(S, SITES_DIR=sd):
            PS.write_site(dict(cz), sd)
            PS.write_site(dict(cy), sd)
            stubs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sd.glob("c*.json")}
            check("書いた印は3項目まで（名前・ドメイン・配信先・カテゴリは非公開の置き場へ）",
                  {k: sorted(v) for k, v in stubs.items()},
                  {"c0a1b2c3d": ["client", "daily_articles", "id"], "c1234abcd": ["client", "id"]})
            check("社名・ドメインは非公開の置き場の site_private.json にだけある",
                  [PS.site_private("c0a1b2c3d").get("domain"), PS.site_private("yy-own").get("public_id"),
                   "zz.example" in json.dumps(stubs), "架空" in json.dumps(stubs, ensure_ascii=False)],
                  ["zz.example", "c1234abcd", False, False])
            got = S.load_all()
            check("非公開の設定があれば、社の id で全設定が読める（公開の id つき）",
                  sorted((k, v.get("domain"), v.get("client"), v.get("public_id")) for k, v in got.items()),
                  [("c0a1b2c3d", "zz.example", True, "c0a1b2c3d"), ("own-x", "own.example", None, None),
                   ("yy-own", "yy.example", True, "c1234abcd")])
            check("公開の id ⇔ 社の id（ジョブの間は公開の id、工程には社の id）",
                  [S.resolve("c1234abcd"), S.public_id("yy-own"), S.resolve("own-x"), S.public_id("own-x")],
                  ["yy-own", "c1234abcd", "own-x", "own-x"])
            check("どちらの id で聞いてもお客様の社", [S.is_client("c1234abcd"), S.is_client("yy-own"), S.is_client("own-x")],
                  [True, True, False])
        with _env(SS_PRIVATE_DIR=str(t / "none")), patched(S, SITES_DIR=sd):
            check("非公開のデータが取れない回は、お客様の社を入れない（自社は動く）", sorted(S.load_all()), ["own-x"])


# ── 2. 公開側で追跡しているファイルに、お客様の社の名前・ドメイン・記事の題と slug が出ない ─────────

def _client_words():
    """{社の id: (名前・ドメインの語, 記事の題・slug の語, ドメイン)}。非公開のデータがある回だけ"""
    import sites as S
    import private_store as PS
    import ci_mask as M
    out = {}
    slugs = PS.client_slugs()
    for sid, cfg in S.load_all().items():
        if not S.is_client(sid):
            continue
        comp = PS.read_json(sid, "company.json", {}) or {}
        mine = sorted(s for s, o in slugs.items() if o == sid)
        art = set(mine)
        for s in mine:
            for d in (ROOT / "articles", PS.base() / "articles"):
                p = d / f"{s}.md"
                if p.is_file():
                    m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", p.read_text(encoding="utf-8-sig")[:3000], re.M)
                    if m:
                        art.add(m.group(1))
                    break
        idw = set(M.identity_words(sid, cfg, comp)) - {cfg.get("public_id")}
        names = {w for w in idw if w not in art and w.lower() not in {a.lower() for a in art}}
        out[sid] = (sorted(names), sorted(art), str(cfg.get("domain") or "").lower().replace("www.", ""))
    return out


def _strip_foreign_urls(text, keep):
    """自社・その社以外のドメインの URL を消す（他社の記事の URL に同じ slug が入っていることがある。調査の生データ）"""
    return URL.sub(lambda m: m.group(0) if m.group(1).lower().replace("www.", "") in keep else " ", text)


def find_identity(files, words, own_domains, read=None):
    """files（公開側の相対パス）のうち、お客様の社の名前・ドメイン・記事の題と slug が出るもの [(path, 種類)]。
    語そのものは返さない（この門の出力も CI のログ）"""
    read = read or (lambda f: (ROOT / f).read_text(encoding="utf-8"))
    hits = []
    pats = {}
    for sid, (names, arts, dom) in words.items():
        n_rx = [re.compile(re.escape(w), re.I) for w in names if len(w) >= 4]
        a_rx = [re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", re.I) for w in arts if len(w) >= 4]
        pats[sid] = (n_rx, a_rx, own_domains | {dom})
    for f in files:
        if Path(f).suffix.lower() not in TEXT_EXT or f.startswith("private/"):
            continue
        try:
            t = read(f)
        except (OSError, UnicodeDecodeError):
            continue
        display = f.startswith(DISPLAY_OK[0]) or f in DISPLAY_OK
        for sid, (n_rx, a_rx, keep) in pats.items():
            if not display and any(rx.search(t) for rx in n_rx):
                hits.append((f, "社の名前・ドメイン"))
            body = _strip_foreign_urls(t, keep)
            if any(rx.search(body) for rx in a_rx):
                hits.append((f, "記事の題・slug"))
    return hits


def test_client_identity_is_not_in_public_tracked_files():
    print("\n■ 守秘義務: 公開側で追跡しているファイルに、お客様の社の名前・ドメイン・記事の題と slug が出ない")
    import sites as S
    own, doms = _own()
    # 検出器が働くか（架空の社で）
    words = {"zz": (["架空商事", "zz-shoji.example"], ["zz-secret-slug", "架空の記事の題です"], "zz-shoji.example")}
    texts = {"a.py": "# 架空商事 の設定", "b.json": '{"u": "https://zz-shoji.example/blog/zz-secret-slug"}',
             "c.json": '{"u": "https://other.example/media/zz-secret-slug/"}', "d.md": "zz-secret-slugs と別の語",
             "site/x.html": "<a href='https://zz-shoji.example/'>架空商事</a>", "site/y.html": "架空の記事の題です",
             "e.txt": "zz-secret-slug を書き直した"}
    got = find_identity(list(texts), words, doms, read=texts.get)
    check("検出器: 名前・ドメイン・slug・題を拾い、他社の URL の中の同じ綴りと表示の場所の名前は拾わない",
          sorted({f for f, _ in got}), ["a.py", "b.json", "e.txt", "site/y.html"])
    # 非公開のデータが無くても確かめられること: 追跡している原稿は自社のカテゴリだけ
    cats = {c for s in own for c in (S.load(s).get("categories") or {})}
    stray = []
    for f in _tracked():
        if re.fullmatch(r"articles/[^/_][^/]*\.md", f):
            m = re.search(r"^category:\s*[\"']?([\w-]+)", (ROOT / f).read_text(encoding="utf-8-sig")[:3000], re.M)
            if not m or m.group(1) not in cats:
                stray.append(f)
    check("公開側で追跡している原稿は自社3サイトのカテゴリだけ（お客様の原稿は非公開のリポジトリ）", stray, [])
    words = _client_words()
    if not words:
        print("  WARN  非公開のデータ（private/）が無いため、お客様の社の名前・題の照合は飛ばします")
        return
    check("照合する語がある（社ごとに名前・ドメインと記事の題・slug）",
          all(n and dom for n, _, dom in words.values()), True)
    hits = find_identity(_tracked(), words, doms)
    check("公開側の追跡ファイルに出ない（ファイルと種類。語そのものは出さない）", sorted(set(hits)), [])


# ── 3. 全社1ファイルの記録のお客様の行は、非公開のリポジトリ ─────────────────────

def test_shared_records_keep_client_rows_in_private_repo():
    print("\n■ 守秘義務: 動画・接続・監修・Bing の記録のお客様の行は、非公開のリポジトリ（キャッシュではなく git）")
    import client_private as CP
    import private_store as PS
    check("非公開のリポジトリに置く記録",
          set(CP.REPO_BACKED) >= {"data/editorial_reviews.jsonl", "data/videos.json", "data/youtube_connected.json",
                                  "data/bing_backfill.json"}, True)
    with tempfile.TemporaryDirectory() as td:
        base, priv = Path(td) / "pub", Path(td) / "priv"
        (base / "data").mkdir(parents=True)
        doms = {"ai.7senses.co.jp": "ai-lab", "zz.example": "client-zz"}
        owner = lambda: (lambda u, _v=None: doms.get(str(u).split("/")[2]) if str(u).count("/") >= 2 else None)  # noqa: E731
        slug_owner = {"own-a": "ai-lab", "zz-a": "client-zz"}.get
        with _env(SS_PRIVATE_DIR=str(priv)), \
                patched(CP, ROOT=base, clients=lambda: ["client-zz"], is_private=lambda s: s == "client-zz",
                        url_owner=owner, owner_of_slug=slug_owner):
            zz = PS.client_dir("client-zz") / "data"
            CP.save_videos({"own-a": {"site": "ai-lab", "id": "v1"}, "zz-a": {"site": "client-zz", "id": "v2"}})
            CP.save_connected(["ai-lab", "client-zz"])
            CP.save_backfill({"connect": {"ai-lab": "2026-10-01", "client-zz": "2026-10-02"},
                              "sent": {"https://ai.7senses.co.jp/aio/x/": "d", "https://zz.example/blog/y/": "d"}})
            rel = "data/editorial_reviews.jsonl"
            (base / rel).write_text("", encoding="utf-8")
            CP.append_jsonl(base / rel, {"slug": "own-a", "by": "A"})
            CP.append_jsonl(base / rel, {"slug": "zz-a", "by": "Z"})
            pub = {n: (base / "data" / n).read_text(encoding="utf-8") for n in
                   ("videos.json", "youtube_connected.json", "bing_backfill.json", "editorial_reviews.jsonl")}
            check("公開側の記録にお客様の社の行・URL が無い",
                  {n: ("zz" in t) for n, t in pub.items()}, {n: False for n in pub})
            check("お客様の行は非公開のリポジトリの clients/<社>/data/ に書く",
                  [(zz / n).is_file() for n in ("videos.json", "youtube_connected.json", "bing_backfill.json",
                                                "editorial_reviews.jsonl")], [True] * 4)
            check("読むときは両方を合わせる",
                  (sorted(CP.load_videos()), CP.load_connected(), sorted(CP.load_backfill()["connect"]),
                   sorted(CP.load_backfill()["sent"]), [json.loads(x)["slug"] for x in CP.read_lines(base / rel)]),
                  (["own-a", "zz-a"], ["ai-lab", "client-zz"], ["ai-lab", "client-zz"],
                   ["https://ai.7senses.co.jp/aio/x/", "https://zz.example/blog/y/"], ["own-a", "zz-a"]))
    # 公開側の本物の記録（非公開のデータが無くても確かめられる）
    own, odoms = _own()
    v = json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8"))
    c = json.loads((ROOT / "data" / "youtube_connected.json").read_text(encoding="utf-8"))
    b = json.loads((ROOT / "data" / "bing_backfill.json").read_text(encoding="utf-8"))
    check("公開側の動画の台帳・接続・Bing の記録は自社3サイトの行だけ",
          (sorted({r.get("site") for r in v.values() if isinstance(r, dict) and r.get("site")} - set(own)),
           sorted(set(c.get("sites") or []) - set(own)), sorted(set(b.get("connect") or {}) - set(own)),
           sorted({u.split("/")[2].lower().replace("www.", "") for u in (b.get("sent") or {})} - odoms)),
          ([], [], [], []))


# ── 4. 原稿・図・台本は重ねて置き、公開側の commit に入れない ─────────────────────

def test_overlay_keeps_client_files_out_of_public_commits():
    print("\n■ 守秘義務: お客様の原稿・図・台本は作業場所へ重ねて置き、公開側の commit に入れない（見張りで戻す）")
    import sites as S
    import private_store as PS
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        pub, priv = t / "pub", t / "priv"
        for d in (pub, priv):
            d.mkdir()
            _git(d, "init", "-q")
            _git(d, "config", "user.email", "gate@example.invalid")
            _git(d, "config", "user.name", "gate")
            _git(d, "config", "commit.gpgsign", "false")
        (pub / "sites").mkdir()
        (pub / "articles").mkdir()
        (pub / "sites" / "own-x.json").write_text(json.dumps({"id": "own-x", "domain": "own.example",
                                                              "categories": {"ox": "O"}}), encoding="utf-8")
        (pub / "articles" / "own-a.md").write_text("---\ntitle: 自社\ncategory: ox\n---\n本文\n", encoding="utf-8")
        _git(pub, "add", "-A")
        _git(pub, "commit", "-q", "-m", "init")
        pushed = []
        with _env(SS_PRIVATE_DIR=str(priv)), patched(S, SITES_DIR=pub / "sites", ROOT=pub), \
                patched(PS, ROOT=pub, push=lambda m, tries=3: pushed.append(m) or True, _CLIENT_SLUGS=None):
            PS.write_site({"id": "c0a1b2c3d", "public_id": "c0a1b2c3d", "name": "架空の社", "domain": "zz.example",
                           "type": "external-md", "categories": {"zz-blog": "Z"}}, pub / "sites")
            for rel, body in (("articles/zz-a.md", "---\ntitle: 架空の題\ncategory: zz-blog\n---\n本文\n"),
                              ("site/images/zz-a/eyecatch.png", "png"), ("data/duo_scripts/zz-a.json", "{}")):
                (priv / rel).parent.mkdir(parents=True, exist_ok=True)
                (priv / rel).write_text(body, encoding="utf-8")
            _git(priv, "add", "-A")
            _git(priv, "commit", "-q", "-m", "init")
            n = PS.overlay_in()
            st = _git(pub, "status", "--porcelain", "--untracked-files=all").stdout
            check("重ねて置く: 原稿・図・台本が作業場所にあり、公開側の git には見えない",
                  (n, (pub / "articles" / "zz-a.md").is_file(), (pub / "data/duo_scripts/zz-a.json").is_file(),
                   "zz-a" in st), (3, True, True, False))
            check("重ねて置いた記事はお客様の記事として数える（ログでは件数か「（お客様の記事）」）",
                  (sorted(PS.client_slugs()), PS.shown("zz-a"), PS.shown("own-a")),
                  (["zz-a"], "（お客様の記事）", "own-a"))
            # この回に書いた新しい原稿（重ねて置いた一覧に無い）と、無理に足した既存の原稿
            (pub / "articles" / "zz-b.md").write_text("---\ntitle: 新しい題\ncategory: zz-blog\n---\n本文\n",
                                                      encoding="utf-8")
            _git(pub, "add", "-A")
            _git(pub, "add", "-f", "articles/zz-a.md")
            staged = _git(pub, "diff", "--cached", "--name-only").stdout.split()
            check("（見張りの前）git add -A と -f でお客様の原稿が入ってしまう", sorted(x for x in staged if "zz-" in x),
                  ["articles/zz-a.md", "articles/zz-b.md"])
            check("新しく書いたお客様の原稿だけを「この回に足した記事」と数える（配信の確認の材料）",
                  PS.client_changes(added_only=True), ["articles/zz-b.md"])
            rc = PS.pre_commit()
            staged = _git(pub, "diff", "--cached", "--name-only").stdout.split()
            check("見張り（pre-commit）: お客様の原稿を commit から外し、非公開の置き場へ戻して残す",
                  (rc, [x for x in staged if "zz-" in x], (priv / "articles" / "zz-b.md").is_file(), len(pushed)),
                  (0, [], True, 1))
            st = _git(pub, "status", "--porcelain", "--untracked-files=all").stdout
            check("戻した後も、公開側の git にはお客様の原稿が見えない", "zz-" in st, False)
            check("公開側に残るのは印と自社の原稿だけ",
                  sorted(x for x in _git(pub, "status", "--porcelain").stdout.split() if x.endswith((".json", ".md"))),
                  ["sites/c0a1b2c3d.json"])
            PS.install_hook()
            hook = (pub / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
            check("見張りの hook は private_store.py --pre-commit を呼ぶ（無い作業場所では何もしない）",
                  ("scripts/private_store.py --pre-commit" in hook, "[ -f scripts/private_store.py ] || exit 0" in hook),
                  (True, True))


# ── 5. CI のログ: 記事の題・slug は出さず、件数で出す ────────────────────────────

def test_ci_logs_count_client_articles_instead_of_naming_them():
    print("\n■ 守秘義務: CI のログに、お客様の社の記事の題・slug・社の id を出さない（件数・公開の id で出す）")
    import private_store as PS
    bad = [n for n in QUIET_TOOLS
           if not re.search(r"PS\.shown\(|PS\.client_slug\(|client_skip",
                            (ROOT / "scripts" / n).read_text(encoding="utf-8"))]
    check("記事の slug を1本ずつ出す道具は、お客様の記事を伏せるか件数にする", bad, [])
    src = (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8")
    check("配信できた記事は published_now.txt（社 slug）に書き、ワークフローはログの「○ slug」を拾わない",
          ("published_now.txt" in src, "PS.shown(s)" in src), (True, True))
    wf = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml")}
    pm, ar = wf["pipeline-multi.yml"], wf["approve-review.yml"]
    check("ログの「○ slug」を拾う処理が残っていない", [n for n, t in wf.items() if "] ○ " in t], [])
    check("警告に slug をそのまま出さない（--shown を通す）",
          [n for n, t in wf.items() if re.search(r"::warning::\$slug\b", t)], [])
    check("コミットの文に社の id・記事の slug を入れない（公開の id・本数）",
          (re.findall(r"git commit[^\n]*steps\.site\.outputs\.id", pm), "監修の記録: ${n}本" in ar,
           "監修の記録: $SLUGS" in ar), ([], True, False))
    check("記事の枠: 選ぶジョブは公開の id で渡し、書くジョブで社の id に戻す",
          ('--resolve "$s"' in pm, '--public-id "$s"' in pm, '--resolve "$pub"' in pm, 'echo "id=$real"' in pm,
           'echo "pub=$pub"' in pm, 'daily_audit.py --cap-reached "$real"' in pm, 'pace.py --slot "$real"' in pm),
          (True,) * 7)
    check("お客様の社の回は、本番の確認・公開ページの検査・監修待ち・リンクの結果を印か件数だけ出す",
          ("grep -E '^VERIFY_'" in pm, "grep -E '^LIVE_CHECK='" in pm, "監修待ちの知らせ: $(grep -c ." in pm,
           "--only=\"$slug\" > /dev/null" in pm), (True,) * 4)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "private_store.py"), "--resolve", "ai-lab"],
                       capture_output=True, text=True, encoding="utf-8")
    r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "private_store.py"), "--shown", "ai-lab-x"],
                        capture_output=True, text=True, encoding="utf-8")
    check("入口: --resolve / --shown は自社の id・slug をそのまま返す", (r.stdout.strip(), r2.stdout.strip()),
          ("ai-lab", "ai-lab-x"))
    import test_gates as T
    with patched(T, _HIDE=[("zz-secret-slug", "c0a1b2c3d"), ("zz-own", "c0a1b2c3d")]):
        check("門の出力も社の id・slug を公開の id に置き換える（境目のある語だけ）",
              T.hide("zz-own の zz-secret-slug と zz-owner"), "c0a1b2c3d の c0a1b2c3d と zz-owner")
    tg = (ROOT / "tests" / "test_gates.py").read_text(encoding="utf-8")
    check("非公開の門の見出し（print）も置き換えて出す", "m.print = _hidden_print" in tg, True)
    words = _client_words()
    if not words:
        print("  WARN  非公開のデータ（private/）が無いため、伏せる語の照合は飛ばします")
        return
    import ci_mask as M
    masked = {w for ws in M.words().values() for w in ws}
    # 語そのものは出さない（この門の出力も CI のログ）。足りない数だけ
    missing = sum(1 for n, a, _ in words.values() for w in list(n) + list(a) if w not in masked)
    check("CI で伏せる語（::add-mask::）に、社の id・名前・ドメインと全記事の題・slug が入る（足りない語の数）", missing, 0)


# ── 6. ジョブの最後に、この回の分を非公開のリポジトリへ残す ─────────────────────

def test_jobs_save_client_files_at_the_end():
    print("\n■ 守秘義務: 非公開のデータを取ったジョブは、最後に always で非公開のリポジトリへ残す（save）")
    missing = []
    for name, y in _workflows().items():
        for job, j in (y.get("jobs") or {}).items():
            steps = j.get("steps") or []
            pd = [i for i, s in enumerate(steps) if s.get("uses") == "./.github/actions/private-data"]
            if not pd:
                continue
            last = steps[-1]
            if not (last.get("uses") == "./.github/actions/private-data"
                    and (last.get("with") or {}).get("mode") == "save" and "always()" in str(last.get("if", ""))):
                missing.append(f"{name}/{job}")
    check("取得した全ジョブの最後の工程が save（if: always()）", missing, [])
    act = (ROOT / ".github" / "actions" / "private-data" / "action.yml").read_text(encoding="utf-8")
    check("private-data の save は private_store.py --push（fetch と伏せは fetch のときだけ）",
          ("inputs.mode == 'save'" in act, "private_store.py --push" in act, act.count("inputs.mode == 'fetch'")),
          (True, True, 2))
    ps = (ROOT / "scripts" / "private_store.py").read_text(encoding="utf-8")
    check("取得の後に重ねて置き、見張りを入れる。送る前に作業場所の分を戻す",
          ("overlay_in()" in ps.split("def _after_fetch")[1][:400], "install_hook()" in ps.split("def _after_fetch")[1][:400],
           "overlay_out(unstage=False)" in ps.split("def push")[1][:600]), (True, True, True))
