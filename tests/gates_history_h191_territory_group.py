# -*- coding: utf-8 -*-
"""担当領域の検査は同じ会社の組の中だけで比べる（2026-11-18）。

担当の語の広い社（システム開発・SEO・DX など）を受けた翌日、本文の語を数える担当領域の検査が、
ほかのお客様の社の記事6本と自社の記事1本を「その社の領域。取り下げてその社へ配信し直す」と知らせた。
別の会社へは記事を移せない。同じ判定を配信の門（publish_flow）も使うので、放っておけば新しい記事も止まった。
台帳の侵食の検査（territory_check）と retire_offterritory も同じ。kw_fit・kw_discover は既に組で比べていた
"""
import sys
from unittest import mock

from test_gates import ROOT, check

sys.path.insert(0, str(ROOT / "scripts"))

CFGS = {"own-a": {"owns": ["集客"]}, "own-b": {"owns": ["補助金"]},
        "cli-x": {"owns": ["システム開発", "集客", "補助金"]}, "cli-y": {"owns": ["給与計算"]}}
GROUPS = {"own-a": ["own-a", "own-b"], "own-b": ["own-a", "own-b"], "cli-x": ["cli-x"], "cli-y": ["cli-y"]}


def _territory(title, body, site):
    import cannibal_check as CC
    import sites
    with mock.patch.object(sites, "load_all", return_value=CFGS), \
            mock.patch.object(sites, "group_of", side_effect=lambda s: GROUPS[s]):
        return CC.article_territory(title, body, site)[0]


def test_territory_compares_within_the_same_company():
    print("\n■ 担当領域（本文）: 別の会社の担当の語が多くても、その社の領域と言わない。同じ会社の組の中では今までどおり知らせる")
    body = "システム開発の外注。" * 30
    check("自社の記事に別の会社（お客様）の語が多い: 報告しない", _territory("システム開発の外注", body, "own-a"), None)
    check("お客様の記事に別のお客様の語が多い: 報告しない", _territory("給与計算", "給与計算の外注。" * 30, "cli-x"), None)
    check("自社の記事に自社のほかのサイトの語が多い: 報告する（悪い例を拾う）",
          _territory("補助金の申請", "補助金の申請。" * 30, "own-a"), "own-b")

    print("\n■ 担当領域（台帳）: 別の会社の担当の語を含む語を、侵食と数えない")
    import cannibal_check as CC
    import hub_client
    import sites
    rows = [{"site": "own-a", "keyword": "給与計算 代行"}, {"site": "own-a", "keyword": "補助金 申請"}]
    with mock.patch.object(sites, "load_all", return_value=CFGS), \
            mock.patch.object(sites, "group_of", side_effect=lambda s: GROUPS[s]), \
            mock.patch.object(hub_client, "enabled", return_value=True), \
            mock.patch.object(hub_client, "all_kw", return_value=rows), \
            mock.patch("builtins.print"):
        bad = CC.territory_check()
    check("台帳: 自社の組の侵食だけを返す", [(b["keyword"], b["owner"]) for b in bad], [("補助金 申請", "own-b")])
