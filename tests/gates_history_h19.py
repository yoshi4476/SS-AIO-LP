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
