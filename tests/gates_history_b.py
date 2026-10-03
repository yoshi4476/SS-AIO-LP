# -*- coding: utf-8 -*-
"""過去の誤りの棚卸し（動画・記事・データ）から作った門。

各門は「知っている悪い例を捕まえる」「良い例は通す」を確かめてから、いまのファイルに当てる
（CLAUDE.md 0.1: 検出器を試さずに「0件」と言わない）。
ネットワークを使う確認は scripts/history_checks_b.py に置く。
"""
import ast
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

NO_HEAD = "」』）)、。，．！？!?ー…"
NONSPEECH = re.compile(r"\[(?:音楽|拍手|笑い|笑|歓声|Music|Applause|Laughter)\]|♪|♫", re.I)
DELIVERY_TYPES = ("self-static", "nextjs-json", "external-html", "external-md", "wordpress")


def _warn(title, items, n=8):
    if items:
        print(f"  WARN  {title}: {len(items)}件")
        for x in items[:n]:
            print(f"        - {x}")


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ── 1. 動画の字幕 ─────────────────────────────────
def line_issues(lines, width_of=None, max_w=None, max_lines=2):
    """字幕の行の崩れ。行頭の禁則・「その／の」割れ・英数字の途中割れ・行数・幅"""
    ng = []
    if len(lines) > max_lines:
        ng.append(f"{len(lines)}行（{max_lines}行を超えた分は画面に出ない）")
    for i, ln in enumerate(lines):
        if i and ln[:1] in NO_HEAD:
            ng.append(f"行頭が「{ln[0]}」")
        # 「その／まま」「そ／の次」: 連体詞を名詞から離さない
        if i and (re.search(r"(?:^|[^そこあど])[そこあど]の$", lines[i - 1])
                  or (lines[i - 1][-1:] in "そこあど" and ln.startswith("の"))):
            ng.append(f"連体詞で割れた（{lines[i - 1][-3:]}／{ln[:3]}）")
        if i and re.match(r"[A-Za-z0-9]", lines[i - 1][-1:]) and re.match(r"[A-Za-z0-9]", ln[:1]):
            ng.append(f"英数字の途中で割れた（{lines[i - 1][-3:]}／{ln[:3]}）")
        if width_of and max_w and width_of(ln) > max_w:
            ng.append(f"幅 {width_of(ln):.0f}px > {max_w}px（{ln}）")
    return ng


def srt_issues(text):
    """字幕ファイルの崩れ。発話でない字幕（[音楽] など）・空の字幕・時刻の逆行"""
    ng, last = [], -1.0
    for blk in re.split(r"\n\s*\n", text.strip()):
        rows = blk.strip().splitlines()
        if len(rows) < 2:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", rows[1])
        if not m:
            ng.append(f"時刻の行が読めない: {rows[1][:30]}")
            continue
        g = list(map(int, m.groups()))
        s, e = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(rows[2:]).strip()
        if NONSPEECH.search(body):
            ng.append(f"発話でない字幕: {body[:20]}")
        if not body:
            ng.append(f"空の字幕（{rows[1]}）")
        if e <= s or s < last - 0.01:
            ng.append(f"時刻が逆行（{rows[1]}）")
        last = s
    return ng


def _measure():
    from PIL import Image, ImageDraw
    import video_make as VM
    return VM, ImageDraw.Draw(Image.new("RGB", (8, 8)))


def short_layout(text):
    """縦型ショートの字幕（duo_short._subtitle と同じ区切り・同じ幅）で行に分ける"""
    import duo_short as DS
    import duo_video as DV
    VM, d = _measure()
    f = VM.font(52)
    out = []
    for c in DV.chunks(text, limit=30):
        ls = DS._lines(d, VM, c, f, 800, 99)
        # 句読点を前の行にぶら下げる分（1字）は枠の余白に収まる
        out.append((c, ls, line_issues(ls, lambda s: d.textlength(s, font=f), 800 + 56)))
    return out


def duo_layout(text):
    """横型の掛け合い動画の字幕（duo_video._subtitle と同じ区切り・同じ幅）"""
    import duo_video as DV
    VM, d = _measure()
    k = lambda v: round(v * DV.KS)
    f = VM.font(k(48))
    out = []
    for c in DV.chunks(text, limit=44):
        ls = VM.wrap(d, c, f, k(1180))
        out.append((c, ls, line_issues(ls, lambda s: d.textlength(s, font=f), k(1240))))
    return out


def test_hist_video_subtitles():
    """2026-10-03: ショートが字幕なしで上がり YouTube の自動字幕「[音楽]」が出た。
    経理・補助金の動画が「AI集客ラボ」と名乗った。6つと言って5つしか出さなかった。
    2026-09-01/09-24: 字幕の枠はみ出し・行頭の「、」・「その／まま」割れ"""
    import duo_short as DS
    import duo_video as DV
    import youtube_upload as YU
    print("\n■ 動画の字幕・名乗り・数の一致（2026-10-03 ほか）")
    check("duo_short の selftest が通る", _quiet(DS.selftest)[0], 0)
    check("duo_video の selftest が通る", _quiet(DV.selftest)[0], 0)

    # 名乗り: 補助金の記事で「AI集客ラボ」と名乗る台本を止め、正しい名乗りは通す
    import sites as S
    cat = next(iter(S.load("subsidy").get("categories") or {"hojokin": ""}))
    art = {"text": "補助金の申請は3つの書類がそろってからです。", "category": cat}
    br = DV.brand(art)
    check("補助金の記事の名乗りはセブンセンシズ", br["name"], "セブンセンシズ")

    def sc(first_n, last):
        return {"title": "申請はいつから？", "listener_role": "社長",
                "lines": [{"who": "K", "text": "申請はいつから？", "board": {"type": "hook", "title": "問い"}},
                          {"who": "N", "text": first_n}]
                + [{"who": "K", "text": "なるほど。"}, {"who": "N", "text": "書類をそろえてからです。"}] * 3
                + [{"who": "N", "text": last, "board": {"type": "end"}}]}
    good = sc(f"{br['name']}のナナです。書類からです。", f"詳しくは『{br['search']}』で検索してください。")
    bad = sc("AI集客ラボのナナです。書類からです。", "詳しくは『AI集客ラボ』で検索してください。")
    check("正しい名乗りの台本は通る", DS.validate(good, art), [])
    check("別サイトの名乗りを止める", bool([x for x in DS.validate(bad, art) if "ナナです" in x or "AI集客ラボ" in x]), True)

    # 数の一致: 「3つ」と言って3項目出すのは通し、「5つ」と言って3項目なら止める
    pts = {"type": "points", "head": "書類", "items": ["登記", "決算書", "見積書"]}
    ok3 = {"lines": [{"who": "N", "text": "書類は3つです。", "board": pts}]}
    ng5 = {"lines": [{"who": "N", "text": "書類は5つです。", "board": pts}]}
    check("言った数と項目数が合えば通す", DS.count_ng(ok3), [])
    check("言った数より項目が少なければ止める", bool(DS.count_ng(ng5)), True)

    # 字幕ファイルの無い動画を上げない（ネットワークに出る前に止まることを確かめる）
    src = Path(YU.__file__).read_text(encoding="utf-8")
    up = src[src.index("def upload("):]
    i_srt, i_ins = up.find('with_suffix(".srt").is_file()'), up.find("videos().insert")
    check("youtube_upload は insert の前に .srt を確かめる", 0 <= i_srt < i_ins, True)
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "x.mp4").write_bytes(b"")
        old = YU.creds
        YU.creds = lambda: object()
        try:
            YU.upload(tmp / "x.mp4", "no-such-slug")
            refused = False
        except RuntimeError as e:
            refused = "字幕" in str(e)
        except ImportError:
            refused = 0 <= i_srt < i_ins       # googleapiclient の無い環境では順序だけで判定
        finally:
            YU.creds = old
        check("字幕ファイルが無ければ上げない", refused, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ds_src = Path(DS.__file__).read_text(encoding="utf-8")
    check("duo_short はショートの .srt を書く", 'with_suffix(".srt").write_text' in ds_src, True)

    # 字幕ファイルの中身
    bad_srt = "1\n00:00:00,000 --> 00:00:01,000\n[音楽]\n\n2\n00:00:01,000 --> 00:00:02,000\n、5回に\n"
    good_srt = "1\n00:00:00,000 --> 00:00:01,500\n請求書のテンプレートは無料です。\n"
    check("字幕の「[音楽]」を捕まえる", bool(srt_issues(bad_srt)), True)
    check("正しい字幕は通す", srt_issues(good_srt), [])
    bad = []
    for p in sorted((ROOT / "automation" / "video").glob("*.srt")):
        bad += [f"{p.name}: {x}" for x in srt_issues(p.read_text(encoding="utf-8", errors="replace"))]
    _warn("字幕ファイルの崩れ", bad)

    # 行の割れ方
    check("行頭の「、」を捕まえる", bool(line_issues(["請求書は", "、5回に"])), True)
    check("「その／まま」の割れを捕まえる", bool(line_issues(["テンプレ、その", "まま使える？"])), True)
    check("英字の途中割れを捕まえる", bool(line_issues(["Goo", "gleの地図"])), True)
    check("3行目以降の切り捨てを捕まえる", bool(line_issues(["あ", "い", "う"])), True)
    check("正しい割れ方は通す", line_issues(["請求書の", "テンプレートは無料"]), [])
    lay = short_layout("テンプレートをそのまま使えるかどうかは、書類の形式で決まります。")
    check("ショートの字幕は助詞で割れ、2行に収まる", [x for _, _, iss in lay for x in iss], [])
    bad = []
    for d, fn in ((ROOT / "data" / "duo_shorts", short_layout), (ROOT / "data" / "duo_scripts", duo_layout)):
        for p in sorted(d.glob("*.json")):
            try:
                sc_ = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for ln in sc_.get("lines") or []:
                for c, ls, iss in fn(ln.get("text", "")):
                    bad += [f"{d.name}/{p.stem}: {x}（{'／'.join(ls)}）" for x in iss]
    _warn("字幕の行の崩れ（作り直しの対象）", bad)

    # いまの台本が名乗り・数の一致を満たしているか（作り直し中のため知らせるだけ）
    bad = []
    for p in sorted((ROOT / "data" / "duo_shorts").glob("*.json")):
        try:
            sc_ = json.loads(p.read_text(encoding="utf-8"))
            a = DV.article(p.stem)
        except Exception:
            continue
        bad += [f"{p.stem}: {x}" for x in DV.brand_ng(sc_, a) + DS.count_ng(sc_)]
    _warn("ショート台本の名乗り・数の食い違い", bad)


# ── 11. 公開されていない記事を「公開済み」と記録しない ─────
def flow_issues(src):
    """publish_flow: build が止めた記事・配信を確かめられない記事で publish_log を呼ばないか"""
    ng = []
    mn = src[src.index("def main("):src.index("def finish(")]
    st = mn[mn.find('cfg["type"] == "self-static"'):]
    i_build, i_html = st.find("scripts/build.py"), st.find('"index.html").is_file()')
    i_fin = mn.rfind("finish(")
    if not (0 <= i_build < i_html) or mn.find('"index.html").is_file()') > i_fin:
        ng.append("build の後・finish の前に HTML の有無を確かめていない")
    ap = src[src.index("def finish_approved("):src.index("def main(")]
    if not (0 <= ap.find('"index.html").is_file()') < ap.find("finish(site_id")):
        ng.append("--finish の経路で HTML の有無を確かめていない")
    fin = src[src.index("def finish("):]
    i_v, i_log = fin.find("verify_publish.verify"), fin.find("publish_log(")
    if not (0 <= i_v < i_log):
        ng.append("配信先の公開確認の前に publish_log を呼んでいる")
    elif "raise SystemExit" not in fin[i_v:i_log]:
        ng.append("公開を確認できないときに止まらない")
    return ng


def delivery_key_issues(src):
    """配信方式の値（self-static など）を、type 以外のキーで見ていないか"""
    vals = "|".join(re.escape(v) for v in DELIVERY_TYPES)
    ng = []
    pat = (r"""\b\w+(?:\.get\(\s*["'](\w+)["'][^)\n]*\)|\[\s*["'](\w+)["']\s*\])"""
           r"""\s*(?:==|!=|not\s+in|in)\s*[^\n:]{0,40}?["'](?:%s)["']""" % vals)
    for m in re.finditer(pat, src):
        if (m.group(1) or m.group(2)) != "type":
            ng.append(m.group(0)[:70])
    return ng


def test_hist_publish_log_only_live():
    """2026-09-25: build が止めた記事を台帳に『公開済み』と記録。取り下げは配信方式を
    存在しないキー（delivery）で見て、配信先から外さないまま完了扱いにしていた"""
    print("\n■ 公開していない記事を公開済みにしない（2026-09-25）")
    src = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    bad_src = src.replace('if not (ROOT / "site" / cat / slug / "index.html").is_file():', "if False:")
    check("HTML の確認を外した publish_flow を捕まえる", bool(flow_issues(bad_src)), True)
    bad_src = re.sub(r'\n    if cfg\["type"\] == "self-static" and not \(ROOT / "site" / meta\["category"\][^\n]*\n[^\n]*\n', "\n", src)
    check("--finish の経路の HTML の確認を外したものも捕まえる", bad_src != src and bool(flow_issues(bad_src)), True)
    check("いまの publish_flow は HTML と公開を確かめてから記録する", flow_issues(src), [])

    check("存在しないキーで配信方式を見る行を捕まえる",
          bool(delivery_key_issues('if cfg.get("delivery") in (None, "self-static"):')), True)
    check("type で見る行は通す", delivery_key_issues('if cfg.get("type") in (None, "self-static"):'), [])
    check("[] で引く形も捕まえる", bool(delivery_key_issues('if cfg["mode"] == "wordpress":')), True)
    check("同じ行の別のキーを誤って拾わない",
          delivery_key_issues('u = norm(c["domain"]) if c.get("type") == "wordpress" else ""'), [])
    bad = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        bad += [f"{p.name}: {x}" for x in delivery_key_issues(p.read_text(encoding="utf-8", errors="replace"))]
    check("配信方式を type 以外のキーで見ている所が無い", bad, [])

    import sites as S
    types = {sid: (cfg.get("type") or "self-static") for sid, cfg in S.load_all().items()}
    check("全サイトの type が既知の配信方式", sorted(t for t in types.values() if t not in DELIVERY_TYPES), [])
    rows = []
    f = ROOT / "data" / "retractions.jsonl"
    if f.is_file():
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]

    def ret_issues(rs):
        return [f"{r['site']}/{r['slug']}" for r in rs if r.get("done_at")
                and "自サイト" in (r.get("note") or "") and types.get(r["site"], "self-static") != "self-static"]
    fake = [{"site": "subsidy", "slug": "x", "done_at": "2026-09-25", "note": "自サイト（build.py が処理）"}]
    check("外部配信のサイトを『自サイト』で完了にした行を捕まえる", bool(ret_issues(fake)) or "subsidy" not in types, True)
    check("取り下げの台帳に配信先から外さず完了にした行が無い", ret_issues(rows), [])


# ── 20. 動画の画素の縦横比・音と映像の長さ ─────────────
def probe_issues(path, max_gap=0.1):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,sample_aspect_ratio,duration",
                        "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        return [f"読めない（{(r.stderr or '').strip()[:50]}）"]
    st = json.loads(r.stdout or "{}").get("streams") or []
    v = [s for s in st if s.get("codec_type") == "video"]
    a = [s for s in st if s.get("codec_type") == "audio"]
    ng = []
    if not v:
        return ["映像が無い"]
    sar = v[0].get("sample_aspect_ratio") or "N/A"
    if sar not in ("1:1", "N/A", "0:1"):
        ng.append(f"画素の縦横比 {sar}（1:1 でない）")
    if int(v[0].get("width", 1)) % 2 or int(v[0].get("height", 1)) % 2:
        ng.append(f"幅・高さが奇数 {v[0].get('width')}x{v[0].get('height')}")
    if a and v[0].get("duration") and a[0].get("duration"):
        gap = abs(float(v[0]["duration"]) - float(a[0]["duration"]))
        if gap > max_gap:
            ng.append(f"音と映像の長さが {gap:.2f}秒ずれる")
    return ng


def test_hist_video_container():
    """2026-09-03/09-24: scale=1740:-2 の端数で画素の縦横比が 1304:1305 になり、途中で再生が止まった"""
    print("\n■ 動画の画素の縦横比・長さ（2026-09-03 / 09-24）")
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        print("  WARN  ffmpeg/ffprobe が無いため飛ばします")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        def mk(name, vf, vdur, adur):
            p = tmp / name
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=320x240:d={vdur}",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(max(vdur, adur)),
                            "-filter_complex", f"[0:v]{vf}[v];[1:a]atrim=0:{adur}[a]", "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(p)], check=True)
            return p
        bad = mk("bad.mp4", "setsar=sar=1304/1305:max=2000", 0.5, 0.5)
        lag = mk("lag.mp4", "setsar=1", 0.5, 1.2)
        good = mk("good.mp4", "setsar=1", 0.5, 0.5)
        check("SAR 1304:1305 の動画を捕まえる", any("縦横比" in x for x in probe_issues(bad)), True)
        check("音と映像の長さのずれを捕まえる", any("ずれ" in x for x in probe_issues(lag)), True)
        check("正しい動画は通す", probe_issues(good), [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 書き出しの大きさが偶数か（端数の拡大縮小をしない）
    import duo_video as DV
    import duo_short as DS
    import video_make as VM
    check("書き出しの幅・高さが偶数", [n for n, v in (("duo_video.OW", DV.OW), ("duo_video.OH", DV.OH),
                                                     ("duo_short.W", DS.W), ("duo_short.H", DS.H),
                                                     ("video_make.W", VM.W), ("video_make.H", VM.H)) if v % 2], [])
    vids = sorted((ROOT / "automation" / "video").glob("*.mp4"))
    issues, busy = [], []
    for p in vids:
        if time.time() - p.stat().st_mtime < 900:
            busy.append(p.name)           # 書き出し中かもしれない
            continue
        issues += [f"{p.name}: {x}" for x in probe_issues(p)]
    for p in sorted((ROOT / "site" / "videos").glob("*.mp4")):
        issues += [f"site/videos/{p.name}: {x}" for x in probe_issues(p, max_gap=0.5)]
    if busy:
        print(f"  （書き出し中の可能性があるため飛ばした: {', '.join(busy)}）")
    _warn("動画の規格の崩れ（上げる前に作り直す）", issues)


# ── 21. 動画の説明欄・台本のURL ───────────────────
URL_RE = re.compile(r"https?://[^\s\"'<>)）」』、。]+")


def url_issues(url, domain=None, slug=None):
    ng = []
    m = re.match(r"^https://([^/]+)(/.*)$", url)
    if not m:
        return [f"URLの形が不正: {url}"]
    if domain and m.group(1) != domain:
        ng.append(f"別サイトのドメイン: {url}（{domain} のはず）")
    path = re.split(r"[?#]", m.group(2))[0]
    # 末尾スラッシュ無しが正のサイト（sites/*.json の trailing_slash: false。コーポレートの Next.js）
    import sites as S
    no_slash = m.group(1) in {c["domain"] for c in S.load_all().values() if c.get("trailing_slash") is False}
    if "//" in path or not (path.endswith("/") or no_slash):
        ng.append(f"パスが不正: {url}")
    if slug and path != "/" and not re.fullmatch(rf"(?:/[a-z0-9-]+)+/{re.escape(slug)}/" + ("?" if no_slash else ""), path):
        ng.append(f"記事のパスになっていない: {url}")
    return ng


def test_hist_video_urls():
    """2026-09-23〜28: url_prefix の連結で /blogai-hojokin-…、他サイトの記事で ai.7senses.co.jp の
    存在しないURLを読み上げ、一次データの非公開中に /data/ へ誘導して404"""
    import social_post as SP
    import sites as S
    import youtube_upload as YU
    print("\n■ 動画の説明欄・台本のURL（2026-09-23〜28）")
    check("連結で壊れたURLを捕まえる",
          bool(url_issues("https://lp.7senses.co.jp/blogai-hojokin-toha/", "lp.7senses.co.jp", "ai-hojokin-toha")), True)
    check("別サイトのドメインを捕まえる",
          bool(url_issues("https://ai.7senses.co.jp/blog/ai-hojokin-toha/", "lp.7senses.co.jp", "ai-hojokin-toha")), True)
    check("正しい記事URLは通す",
          url_issues("https://lp.7senses.co.jp/blog/ai-hojokin-toha/", "lp.7senses.co.jp", "ai-hojokin-toha"), [])

    slugs = set(json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8")))
    slugs |= {p.stem for d in ("duo_scripts", "duo_shorts") for p in (ROOT / "data" / d).glob("*.json")}
    bad, n = [], 0
    for slug in sorted(slugs):
        a = SP.article(slug)
        if not a:
            continue
        sid, cfg = SP.site_of(a["category"])
        if not sid:
            bad.append(f"{slug}: カテゴリ {a['category']} の持ち主のサイトが無い")
            continue
        desc = _quiet(YU.describe, slug)[0][0]
        want = S.article_url(cfg, {"slug": slug, "category": a["category"]})
        urls = URL_RE.findall(desc)
        n += 1
        if want not in urls:
            bad.append(f"{slug}: 説明欄に記事URL {want} が無い")
        for u in urls:
            bad += [f"{slug}: {x}" for x in url_issues(u, cfg["domain"])]
    check(f"動画の説明欄のURLが記事の正しいURL（{n}本）", bad, [])

    # 一次データの動画: 非公開の間は /data/ へ送らない
    import data_intake
    ds = sorted((ROOT / "data" / "datasets").glob("*.json"))
    ds = [p.stem for p in ds if not SP.article(p.stem)]
    if ds:
        old = data_intake.PUBLIC
        try:
            data_intake.PUBLIC = False
            off = _quiet(YU.describe, ds[0])[0][0]
            data_intake.PUBLIC = True
            on = _quiet(YU.describe, ds[0])[0][0]
        finally:
            data_intake.PUBLIC = old
        check("非公開の間は説明欄で /data/ へ送らない", "/data/" in off, False)
        check("公開すれば /data/ を案内する（検出器の確認）", "/data/" in on, True)

    # 台本・字幕・章立てに書かれたURL
    owner = {}
    for sid, cfg in S.load_all().items():
        owner[sid] = cfg["domain"]
    bad = []
    files = [p for d in ("duo_scripts", "duo_shorts") for p in (ROOT / "data" / d).glob("*.json")]
    files += list((ROOT / "automation" / "video").glob("*.srt")) + list((ROOT / "automation" / "video").glob("*.chapters.txt"))
    for p in files:
        slug = p.name.split(".")[0]
        a = SP.article(slug)
        dom = SP.site_of(a["category"])[1].get("domain") if a else None
        for u in URL_RE.findall(p.read_text(encoding="utf-8", errors="replace")):
            bad += [f"{p.name}: {x}" for x in url_issues(u.rstrip(".,"), dom)]
            if "/data/" in u and not data_intake.PUBLIC:
                bad.append(f"{p.name}: 非公開の一次データへ送っている {u}")
    check("台本・字幕に壊れたURL・別サイトのURLが無い", bad, [])


# ── 22. 「人」の読み替え ──────────────────────────
def test_hist_yomi_hito():
    """2026-09-27: 「人」を「ひと」と読ませる置換が熟語に効き「医療法ひとの」。
    聞き直し側にも同じ読み替えを通していて、誤りを見逃した"""
    import video_make as V
    import yomi_guard as Y
    print("\n■ 「人」の読み替え（2026-09-27）")
    check("医療法人の → 変えない", "ひと" in V.read_text("医療法人の事業承継です。"), False)
    check("税理士法人は → 変えない", "ひと" in V.read_text("税理士法人は決算を見ます。"), False)
    check("個人の・本人が → 変えない", "ひと" in V.read_text("個人の方と本人が来ます。"), False)
    check("8億人が → 変えない", "ひと" in V.read_text("8億人が使います。"), False)
    check("判断は人、 → ひと", "ひと" in V.read_text("判断は人、作業は機械です。"), True)
    check("人が → ひと", "ひと" in V.read_text("人が決めます。"), True)
    # 聞き取った側に台本の読み替えを通さない（両側が同じく化けると誤りが消える）
    check("聞き取り側は「人」を読み替えない", "人" in Y.spoken_form("人が決めます", heard=True), True)
    learned = []
    for w in ("医療法人の", "税理士法人は", "社会福祉法人が", "個人の", "本人が"):
        if "ひと" in Y.apply_dict(w):
            learned.append(w)
    check("覚えた読みが熟語の「人」を「ひと」にしない", learned, [])


# ── 23. 一次データの単位 ─────────────────────────
def unit_issues(ds, page):
    """単位が % でない値を % で出していないか・値と単位の組が元データどおりか"""
    import data_intake as DI
    text = re.sub(r"<[^>]+>", " ", page)
    unit = str(ds.get("unit") or "").strip()
    ng = []
    for r in ds.get("rows") or []:
        v = r.get("value")
        if v is None:
            continue
        if unit in ("%", "％"):
            continue          # 割合のデータは実数（分子・分母）の表で出すので、値の字面は一致しない
        s = DI._fmt(v, "")
        if re.search(rf"(?<![\d.,]){re.escape(s)}\s*[%％]", text):
            ng.append(f"{r.get('label')}: {s}{unit} を % で出している")
        if DI._fmt(v, unit) not in text:
            ng.append(f"{r.get('label')}: 「{DI._fmt(v, unit)}」がページに無い")
    return ng


def test_hist_dataset_units():
    """2026-09-25: 一次データのページで「36セッション」を「36%」、「中央値5本」を「5%」と表示（10ページ作り直し）"""
    import data_intake as DI
    print("\n■ 一次データの単位（2026-09-25）")
    base = {"slug": "t", "title": "テスト", "description": "説明", "n": 120, "n_unit": "セッション",
            "period": "2026-06〜2026-08", "published": "2026-09-01", "start": "2026-06", "end": "2026-08", "method": "集計",
            "sentence": "一文", "modified": "2026-09-25", "categories": [], "den_label": "記事数", "num_label": "該当"}
    sess = dict(base, unit="セッション", rows=[{"label": "A", "value": 36.0, "num": 36, "den": 36},
                                                {"label": "B", "value": 5.0, "num": 5, "den": 5}])
    check("% で出したページを捕まえる", bool(unit_issues(sess, "<td>A</td><td>36%</td><td>B</td><td>5セッション</td>")), True)
    check("単位どおりのページは通す", unit_issues(sess, "<td>A</td><td>36セッション</td><td>B</td><td>5セッション</td>"), [])
    check("分子・分母を持つセッションのデータでも % の表にしない", DI.has_counts(sess), False)
    check("セッションのデータを描いても % にならない", unit_issues(sess, DI.page_html(sess)), [])
    old = DI.has_counts
    try:
        DI.has_counts = lambda ds: all("den" in r for r in ds["rows"]) and len(ds["rows"]) > 0   # 2026-09-25 以前の判定
        check("以前の判定で描いたページを捕まえる（検出器の確認）", bool(unit_issues(sess, DI.page_html(sess))), True)
    finally:
        DI.has_counts = old
    bad = []
    for p in sorted((ROOT / "data" / "datasets").glob("*.json")):
        ds = json.loads(p.read_text(encoding="utf-8"))
        try:
            page = DI.page_html(ds)
        except Exception as e:
            bad.append(f"{p.stem}: 描けない（{type(e).__name__}: {str(e)[:40]}）")
            continue
        bad += [f"{p.stem}: {x}" for x in unit_issues(ds, page)]
        out = ROOT / "site" / "data" / p.stem / "index.html"
        if out.is_file():
            bad += [f"site/data/{p.stem}: {x}" for x in unit_issues(ds, out.read_text(encoding="utf-8"))]
    check("一次データの全ページで値と単位が元データどおり", bad, [])


# ── 30. 内部リンクの数え方 ───────────────────────
def test_hist_link_counting():
    """2026-08-17/08-19/09-15: 相対パスだけを数えて絶対URLの内部リンクを見落とし、
    41本をリンク不足・コーポレートを常に0本と誤判定"""
    import sites as S
    print("\n■ 内部リンクの数え方（相対・絶対・末尾スラッシュ無し）（2026-08-17 ほか）")
    cfg = S.load("corporate")
    dom, pre = cfg["domain"], (cfg.get("url_prefix") or "/blog").rstrip("/")
    t = "x-target"
    forms = {"rel": f"[あ]({pre}/{t}/)", "abs": f"[あ](https://{dom}{pre}/{t}/)", "noslash": f"[あ]({pre}/{t})"}
    texts = {f"s-{k}": f"---\ntitle: a\n---\n本文。{v}\n" for k, v in forms.items()}
    texts[t] = "---\ntitle: t\n---\n本文。\n"
    arts = {s: {"body": b, "slug": s} for s, b in texts.items()}
    got = {}
    import auto_improve, priority_boost, rank_up, guarantee, rank_rescue, validate_rules, auto_review, link_boost
    for name, fn in (("auto_improve.inbound", lambda: auto_improve.inbound(t, texts)),
                     ("priority_boost.inbound", lambda: priority_boost.inbound(t, texts)),
                     ("rank_up.inbound", lambda: rank_up.inbound(t, texts)),
                     ("guarantee.inbound_counts", lambda: guarantee.inbound_counts(arts)[t]),
                     ("rank_rescue.inbound_counts", lambda: rank_rescue.inbound_counts(arts)[t]),
                     ("validate_rules.inbound", lambda: validate_rules.inbound(arts)[t])):
        got[name] = fn()
    tmp = Path(tempfile.mkdtemp())
    try:
        for s, b in texts.items():
            (tmp / f"{s}.md").write_text(b, encoding="utf-8")
        got["auto_review.inbound_count"] = auto_review.inbound_count(sorted(tmp.glob("*.md")))[t]
        old = link_boost.ARTICLES
        link_boost.ARTICLES = tmp
        try:
            got["link_boost.inbound"] = link_boost.inbound({s: {} for s in texts})[t]
        finally:
            link_boost.ARTICLES = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check("3つの書き方をすべて1本ずつ数える", {k: v for k, v in got.items() if v != 3}, {})
    # 検出器の確認: 相対しか数えない数え方は、この入力で3にならない
    rel_only = sum(1 for b in texts.values() if re.search(rf"\]\((/[^)]+/{t}/)\)", b))
    check("相対だけの数え方はここで落ちる（検出器の確認）", rel_only != 3, True)

    import score_check as SC
    body = " ".join(forms.values())
    check("score_check は1記事の中の3つの書き方を同じ1本と数える", len(SC.internal_links(body)), 1)
    check("score_check は別の記事を別に数える", len(SC.internal_links(body + f" [い]({pre}/y-other/)")), 2)


# ── 31. 生成AIレポートのページの鍵 ─────────────────
def test_hist_genai_page_key():
    """2026-10-01: 生成AIレポートの取り込みでページを末尾slugだけで鍵にし、
    別カテゴリの同名ページ（/aio/towa/ と /meo/towa/）が1行に潰れた"""
    import genai_import as GI
    print("\n■ 生成AIレポートのページの鍵（2026-10-01）")
    tabs = [("p.csv", ["上位のページ", "表示回数"],
             [["https://ai.7senses.co.jp/aio/towa/", "10"], ["https://ai.7senses.co.jp/meo/towa/", "7"],
              ["https://ai.7senses.co.jp/aio/towa", "3"]])]
    pages = GI.page_table(tabs)
    check("別カテゴリの同名ページは2ページのまま", sorted(pages), ["/aio/towa/", "/meo/towa/"])
    check("末尾スラッシュ違いは同じページに合算", pages.get("/aio/towa/"), 13)
    slug_key = {}
    for k, v in pages.items():
        slug_key[k.rstrip("/").split("/")[-1]] = slug_key.get(k.rstrip("/").split("/")[-1], 0) + v
    check("slugだけで鍵にすると潰れる（検出器の確認）", len(slug_key) < len(pages), True)
    tmp = Path(tempfile.mkdtemp())
    old = GI.STORE
    try:
        GI.STORE = tmp / "g.json"
        csv = tmp / "x.csv"
        csv.write_text("上位のページ,表示回数\nhttps://ai.7senses.co.jp/aio/towa/,10\nhttps://ai.7senses.co.jp/meo/towa/,7\n",
                       encoding="utf-8")
        ok, _ = GI.ingest(csv, write=True, site="ai-lab", month="2026-09")
        st = json.loads(GI.STORE.read_text(encoding="utf-8")) if ok else {}
        check("取り込み後も2ページとして残る", sorted(((st.get("2026-09") or {}).get("ai-lab") or {}).get("pages", {})),
              ["/aio/towa/", "/meo/towa/"])
    finally:
        GI.STORE = old
        shutil.rmtree(tmp, ignore_errors=True)
    f = ROOT / "data" / "genai_impressions.json"
    if f.is_file():
        bad = [f"{ym}/{sid}: {k}" for ym, by in json.loads(f.read_text(encoding="utf-8")).items() if isinstance(by, dict)
               for sid, v in by.items() if isinstance(v, dict) for k in (v.get("pages") or {})
               if not (k.startswith("/") and k.endswith("/"))]
        check("記録済みのページの鍵がすべてパス（slugだけの鍵が無い）", bad, [])


# ── 45. 壊れた原稿・brief.json 1本で全体を止めない ──────────
def build_guard_issues(src):
    """build.main の記事の読み込みが try で守られ、止めた記事を飛ばして続けるか"""
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    ng = []
    for loop in ast.walk(main):
        if not isinstance(loop, ast.For) or "glob" not in ast.unparse(loop.iter):
            continue
        for node in ast.walk(loop):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "parse_article":
                guarded = any(isinstance(t, ast.Try) and any(node is x for x in ast.walk(t))
                              and any(isinstance(x, ast.Continue) for h in t.handlers for x in ast.walk(h))
                              for t in ast.walk(loop))
                if not guarded:
                    ng.append(f"{node.lineno}行目: parse_article が try/continue で守られていない")
    return ng


def test_hist_broken_inputs_do_not_stop_all():
    """2026-09-15/09-25: 壊れた原稿・brief.json 1本でビルド・site_brief 全体が落ちた"""
    import build
    import site_brief
    print("\n■ 壊れた原稿・brief.json で全体を止めない（2026-09-15 / 09-25）")
    tmp = Path(tempfile.mkdtemp())
    try:
        cases = {"unclosed": "---\ntitle: a\nslug: a\n\n本文だけ\n",
                 "yaml": "---\ntitle: [a\nslug: a\n---\n本文\n",
                 "empty": "---\n\n---\n本文\n",
                 "scalar": "---\nただの文字\n---\n本文\n"}
        bad = []
        for name, t in cases.items():
            p = tmp / f"{name}.md"
            p.write_text(t, encoding="utf-8")
            try:
                build.parse_article(p)
                bad.append(f"{name}: 壊れた原稿を通した")
            except Exception:
                pass
            except BaseException as e:      # SystemExit などは except Exception で拾えずビルドが止まる
                bad.append(f"{name}: {type(e).__name__} で抜けた")
        check("壊れた原稿は Exception（拾える形）で止める", bad, [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    bad_src = src.replace("        try:\n            meta = parse_article(p)[0]\n        except Exception as e:",
                          "        if True:\n            meta = parse_article(p)[0]\n        if False:")
    check("守りを外した build を捕まえる", bool(build_guard_issues(bad_src)) or bad_src == src, True)
    check("build.main は記事ごとに読み込みを守る", build_guard_issues(src), [])

    tmp = Path(tempfile.mkdtemp())
    old = site_brief.ROOT
    try:
        site_brief.ROOT = tmp
        d = tmp / "data" / "clients" / "x"
        d.mkdir(parents=True)
        briefs = {"壊れたJSON": "{ \"target\": ",
                  "配列": "[1, 2]",
                  "欄の型違い": json.dumps({"target": "文字列", "keyword": ["a"], "service": None}),
                  "主題の欠け": json.dumps({"subjects": [{"keyword": "a"}, "文字列"]}),
                  "業種の型違い": json.dumps({"industry_detail": {"飲食": "文字列"}, "author": 3})}
        bad = []
        for name, t in briefs.items():
            (d / "brief.json").write_text(t, encoding="utf-8")
            try:
                _quiet(site_brief.show_brief, "x")
            except Exception as e:
                bad.append(f"{name}: {type(e).__name__}: {str(e)[:40]}")
        check("壊れた brief.json でも site_brief が最後まで進む", bad, [])
        (d / "brief.json").write_text(json.dumps({"target": {"persona": "院長"}}), encoding="utf-8")
        out = _quiet(site_brief.show_brief, "x")[1]
        check("正しい brief.json は中身を出す（検出器の確認）", "院長" in out, True)
    finally:
        site_brief.ROOT = old
        shutil.rmtree(tmp, ignore_errors=True)
