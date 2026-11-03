"""h154: お客様名義の月次レポートの検査も、運用者がその社にだけ許した当社の表記（operator_ok）を外して見る。
記事には載せてよい「セブンセンシズ株式会社」が記事の一覧に出て、お客様の社の月次が発行されなかった（2026-11-01）"""
import sys

from test_gates import check, ROOT


def test_issuer_leaks_honours_operator_ok():
    sys.path.insert(0, str(ROOT / "scripts"))
    import monthly_report as M
    print("\n■ お客様名義のレポート: 許した表記は通し、それ以外の当社の名前・ドメインは止める")
    iss, cfg = M.issuer, M.site_cfg
    try:
        M.issuer = lambda: {"operator": False}
        M.site_cfg = lambda: {"operator_ok": ["ZZ運用株式会社"]}
        import sites as S
        marks = S.OPERATOR_MARKS
        S.OPERATOR_MARKS = ("ZZ運用", "zz-ops.example")
        try:
            check("許した表記そのものは通す", M.issuer_leaks("<p>ZZ運用株式会社が提供しています</p>"), [])
            check("略した名前・ドメインは止める",
                  M.issuer_leaks("<p>ZZ運用の実績。zz-ops.example</p>"), ["ZZ運用", "zz-ops.example"])
            M.site_cfg = lambda: {}
            check("許していない社では止める", M.issuer_leaks("<p>ZZ運用株式会社</p>"), ["ZZ運用"])
        finally:
            S.OPERATOR_MARKS = marks
    finally:
        M.issuer, M.site_cfg = iss, cfg
