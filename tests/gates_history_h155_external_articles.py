"""h155: 食い合いの検査は、お客様の側で書かれた記事（当社の工程の外の記事）も相手に数える。
当社の原稿だけを見ていたため、お客様の既存の記事の狙う語そのものでも「ぶつかる既存記事はありません」と通り、在庫に積まれていた
（2026-11-03）。配信のたびに取得する配信先のリポジトリから拾い、非公開の置き場に残す"""
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_client_written_articles_block_same_keyword():
    sys.path.insert(0, str(ROOT / "scripts"))
    import external_articles as EA
    import kw_guard as G
    import private_store
    print("\n■ お客様の側で書かれた記事: 当社の原稿に無い記事だけを拾い、同じ語は着手禁止・重なる語は要差別化にする")
    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / "content"
        c.mkdir()
        (c / "zz-own.md").write_text("---\nslug: zz-own\ntitle: ZZ の題\nkeyword: 架空 業務 自動化 進め方\n---\n本文\n", encoding="utf-8")
        (c / "zz-ours.md").write_text("---\ntitle: 当社の題\nkeyword: 架空 当社の語\n---\n本文\n", encoding="utf-8")
        got = EA.scan(c, {"zz-ours"})
        check("当社の原稿に無い slug の記事だけを拾う", [(r["slug"], r["kw"]) for r in got], [("zz-own", "架空 業務 自動化 進め方")])
    rj, ic = private_store.read_json, EA.load.__globals__.get("S")
    import sites as S
    is_client = S.is_client
    try:
        private_store.read_json = lambda sid, name, default=None, root=None: \
            [{"slug": "zz-own", "kw": "架空 業務 自動化 進め方", "title": "ZZ の題"}] if name == EA.NAME else default
        S.is_client = lambda sid: sid == "client-zz"
        code_same = G.judge("架空 業務 自動化 進め方", "client-zz", use_gsc=False)[0]
        code_part = G.judge("架空 業務 自動化", "client-zz", use_gsc=False)[0]
        code_other = G.judge("架空 まったく別の題材", "client-zz", use_gsc=False)[0]
        check("同じ語は着手禁止・範囲が重なる語は要差別化・別の語は通す", (code_same, code_part, code_other), (2, 1, 0))
        check("自社のサイトには足さない", EA.load("ai-lab"), [])
        # 新しく受けた社の初めての配信の前は一覧が無い。無いのを「ぶつからない」と扱わない
        private_store.read_json = lambda sid, name, default=None, root=None: default
        load_all = S.load_all
        S.load_all = lambda *a, **k: {"client-zz": {"id": "client-zz", "content_dir": "content/journal", "repo": "zz/site"}}
        try:
            check("一覧がまだ無い社は「要確認」（照合できていない）", (EA.missing("client-zz"),
                  G.judge("架空 まったく別の題材", "client-zz", use_gsc=False)[0]), (True, 1))
        finally:
            S.load_all = load_all
        check("設定の無い社では止めない", EA.missing("client-unknown"), False)
    finally:
        private_store.read_json, S.is_client = rj, is_client
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    at = src.find("def ensure_clone")
    check("配信先を取得するたびに取り直す（失敗しても配信は止めない）",
          "external_articles.refresh(cfg, dest)" in src[at:at + 3000], True)
