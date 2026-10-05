# -*- coding: utf-8 -*-
"""配信まわりの取りこぼしの門（2026-10-05）。

YouTube の説明欄は 5,000 バイト（UTF-8）が上限なのに文字数で切っていた／
ZIP 納品で記事の一覧（article-manifest.json）が前の回の記事を落とすおそれ／
WordPress で本文に入れた構造化データの <script> が、unfiltered_html の無い投稿者では消される。
YouTube・先方のサーバー・WordPress には触れない（手元の関数と一時フォルダだけ）。
"""
import inspect

from test_gates import check, ROOT


def test_youtube_description_fits_in_bytes():
    import youtube_upload as Y
    print("\n■ YouTube の説明欄: UTF-8 で 4,900 バイト以下・字の途中で切らない・チャプターを残す")
    chap = "0:00 はじめに\n1:23 費用の目安\n3:45 よくある失敗"
    long_jp = "▼ 記事はこちら\nhttps://example.com/a/\n\n" + "日本語の説明文です。" * 400
    d = Y.fit_description(long_jp + Y.CHAPTER_HEAD + chap + "\n")
    b = d.encode("utf-8")
    check("4,900 バイト以下（文字数ではなくバイト数）", len(b) <= Y.DESC_BYTES, True)
    check("字の途中で割れていない（UTF-8 として読み直せる）", b.decode("utf-8") == d, True)
    check("先頭の記事URLと末尾のチャプターはそのまま残る",
          (d.startswith("▼ 記事はこちら\nhttps://example.com/a/"), d.endswith(Y.CHAPTER_HEAD + chap + "\n")), (True, True))
    check("チャプターの無い説明欄もバイト数で切る", len(Y.fit_description("あ" * 3000).encode("utf-8")) <= Y.DESC_BYTES, True)
    check("収まる説明欄は変えない", Y.fit_description("短い説明\n" + chap), "短い説明\n" + chap)
    src = (ROOT / "scripts" / "youtube_upload.py").read_text(encoding="utf-8")
    check("文字数で切る箇所が残っていない（desc[:4900]）", "desc[:4900]" in src, False)


def test_zip_manifest_keeps_earlier_deliveries():
    import json
    import tempfile
    from pathlib import Path
    import deliver_files as DF
    import publish as P
    print("\n■ ZIP 納品: 記事の一覧（article-manifest.json）が前の回の記事を落とさない")
    cfg = {"id": "h19-zip", "type": "zip", "domain": "h19.example", "name": "h19"}
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        old = (DF.index_path, DF.ROOT, DF.hand_over)
        try:
            DF.index_path = lambda c: r / "delivered.json"
            DF.ROOT = r
            DF.hand_over = lambda c, out: True       # 先方へメールしない
            (r / "delivered.json").write_text(json.dumps(
                {"old-a": {"title": "A", "date": "2026-09-01", "hash": "aaa111"},
                 "old-b": {"title": "B", "date": "2026-09-02"}}, ensure_ascii=False), encoding="utf-8")
            base = r / "work"
            base.mkdir()
            # 先方がまだ上げていない／読めない回: 公開中の一覧が無い
            DF.keep_delivered(cfg, base)
            src = r / "new-c.md"
            src.write_text("本文\n", encoding="utf-8")
            meta = {"slug": "new-c", "title": "C", "date": "2026-10-05"}
            mp = P.stamp_manifest(cfg, base, meta, src)
            man = json.loads(mp.read_text(encoding="utf-8"))
            check("前の回の記事と今回の記事が両方載る（同じ slug は置き換え）",
                  (sorted(man), man["old-a"], man["old-b"], man["new-c"] == P.source_hash(src)),
                  (["new-c", "old-a", "old-b"], "aaa111", "", True))
            # 公開中の一覧が読めた回: 先方の値を優先し、手元の一覧で欠けを補う
            mp.write_text(json.dumps({"old-a": "live999"}), encoding="utf-8")
            DF.keep_delivered(cfg, base)
            man = json.loads(mp.read_text(encoding="utf-8"))
            check("読めた一覧の値は残し、欠けた記事だけ足す", (man["old-a"], sorted(man)),
                  ("live999", ["old-a", "old-b"]))
            mp.write_text("[壊れた", encoding="utf-8")
            DF.keep_delivered(cfg, base)
            check("壊れた一覧でも配信済みの記事で作り直す",
                  sorted(json.loads(mp.read_text(encoding="utf-8"))), ["old-a", "old-b"])
            P.stamp_manifest(cfg, base, meta, src)
            f = base / "blog" / "new-c" / "index.html"
            f.parent.mkdir(parents=True)
            f.write_text("<h1>C</h1>", encoding="utf-8")
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                DF.deliver(cfg, meta, [f, mp], base, push=True)
            idx = json.loads((r / "delivered.json").read_text(encoding="utf-8"))
            check("配信済み一覧に今回の指紋を控える（次の回の一覧を作るため）",
                  idx["new-c"].get("hash"), P.source_hash(src))
        finally:
            DF.index_path, DF.ROOT, DF.hand_over = old
    check("作業場所を用意するたびに配信済みの記事を一覧へ戻す",
          "keep_delivered(cfg, d)" in inspect.getsource(DF.stage), True)
