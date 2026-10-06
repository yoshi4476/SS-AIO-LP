# -*- coding: utf-8 -*-
"""当社の採択率・支援社数と、当社が申請書類を作成・代行すると読める表現の門（2026-10-07）。

運用者の承認（景品表示法・行政書士法の見直し）: 当社は IT導入支援事業者として補助金の申請を支援する立場で、
申請書類の作成代行は行わず、採択を保証しない。当社の採択率・支援社数は根拠（母数・期間）が無いので載せない。
定型文「当社は登録支援事業者として、対象ツールの選定から申請書類の作成、採択後の実績報告まで一貫して支援」が
約80本の原稿に、「のべ50社以上の導入を支援」が材料（first_party_facts.json）から8本に広がっていた。
手書きのページは配信先で直したが、原稿と材料が残っていた。同じ見落としを繰り返さないため、手書きのページを含む
公開物を全部見る。

固定すること:
  - 見つかるべき例（当社が主語・主語を省いた書き手の文・バッジ・注記）を検出器が拾う
  - 止めてはいけない例（士業の代行の説明・代行の相場・支援事業者の役割・打ち消し・選び方の確認項目）を拾わない
  - 原稿と、管制塔の手書きのページ・llms.txt、配信先の手書きのページ（作業コピーがあるときだけ）に該当が無い
  - publish.py と build.py が該当のある原稿を公開しない
  - 材料（一次情報・サイト設定）と執筆の指示に、同じ主張が戻っていない
"""
import inspect
import json

from test_gates import check, ROOT

MUST = [
    ("当社はAI導入補助金の登録支援事業者として、対象ツールの選定から申請書類の作成、採択後の実績報告まで一貫して支援しています。", "daiko"),
    ("対象ツールの選定から申請書類の作成、採択後の実績報告まで一貫して支援しています。", "daiko"),
    ("AI導入補助金の登録支援事業者として、対象ツールの選定から申請書類の作成、採択後の実績報告まで一貫して支援してきた経験から、1業務から任せてください。", "daiko"),
    ("差し戻されやすい箇所を確かめ、事業計画書の作成から実績報告までサポートします。", "daiko"),
    ("対象ツールの確認、交付申請の書類作成、導入後の実績報告まで、手順ごとに一緒に進めます。", "daiko"),
    ("GビズIDの取得から実績報告まで伴走のセブンセンシズが、書類準備から着金まで伴走します。", "daiko"),
    ("当社が申請代行も承ります。", "daiko"),
    ("当社は紹介ではなく、申請書類の作成まで代行します。", "daiko"),
    ("当社はAI導入補助金の登録支援事業者で、2020年3月の創業から2026年9月までに、のべ50社以上の導入を支援しました。", "count"),
    ("2020年3月の創業から2026年9月までに、のべ50社以上の導入を支援してきた経験からも、一般論では差別化になりません。", "count"),
    ("当社は経理BPOの導入支援を10社以上手がけています。", "count"),
    ("当社の採択率は90%です。", "rate"),
    ("私たちが支援した申請の採択率は業界トップ水準です。", "rate"),
    ('<div class="badge"><span>90%+</span><span>採択通過率</span></div>', "rate"),
    ("所要時間は合計1.5〜3時間です。※当社支援実績(2026年7月時点)", "basis"),
]
MUST_NOT = [
    "行政書士は、官公署に提出する書類の作成を代行できます。",
    "IT導入補助金の申請代行・サポート費用の相場|セブンセンシズ株式会社",
    "IT導入支援事業者に申請書類の作成をどこまで手伝ってもらえるかを、契約前に確認しておくと手戻りを防げます。",
    "支援事業者は、事業計画書の作成支援から、交付決定後の実績報告まで一貫して伴走する役割を担います。",
    "相談先には、支援社数・採択通過率を開示しているかを質問してください。",
    "当社は申請書類の作成代行は行っておらず、採択を保証するものではありません。",
    "だからこそ当社は、書類作成の代行ではなく「工程管理」を含めた伴走にこだわります。",
    "当社の採択率・支援社数は書かない(根拠の母数・期間が無いため)",
    "当社はAI導入補助金の登録支援事業者として、対象ツールの選定から、申請に向けた相談・助言、採択後の実績報告まで一貫して支援しています（申請書類はお客様が作成し、当社は内容の確認と助言を行います）。",
    "私たちが申請サポートを行った店舗のオーナーからも、「繁忙期に手続きを進めようとして書類作成が後回しになった」という声を聞いています。",
    "私たちが入力代行の相談を受ける際も、明細書の添付が抜けているケースを見かけます。",
    "当社は2023年1月から2026年8月までに、経理BPOを10社以上へ導入しています。",
    "小規模事業者持続化補助金の個人事業主向け採択率は、第19回で47.2%でした。",
    "当社が2026年10月にChatGPT・Claudeへ聞いたところ、採択率を答えたのは2回答でした（当社調べ）。",
    "自社開発のシステムは補助の対象外です。",
]


def test_legal_claims_detector_and_all_public_pages():
    import legal_claims as LC
    got = [(s[:30], sorted({k for k, _ in LC.find(s)})) for s, _ in MUST]
    want = [(s[:30], [k]) for s, k in MUST]
    check("表示の門: 当社の採択率・支援社数・作成代行・注記を見つける（見つかるはずの例）", got, want)
    check("表示の門: 一般の説明・打ち消し・選び方の確認項目は止めない（似た別のもの）",
          [s[:30] for s in MUST_NOT if LC.find(s)], [])

    hits = LC.scan()
    check("表示の門: 原稿・手書きのページ・llms.txt・配信先の作業コピーに当社の採択率・支援社数・作成代行が無い"
          "（python scripts/legal_claims.py）",
          [f"{p.name}: {k}: {s[:50]}" for p, k, s in hits], [])
    tg = {p.relative_to(ROOT).as_posix() for p in LC.targets() if ROOT in p.parents}
    check("表示の門: 手書きのページ（トップ・LP・ラボ・ツール・llms.txt）も検査の対象",
          all(x in tg for x in ("site/index.html", "site/lp/index.html", "site/llms.txt"))
          and any(x.startswith("site/lab/") for x in tg) and any(x.startswith("site/tools/") for x in tg), True)

    import publish
    check("表示の門: publish.py は該当のある原稿を配信しない", "legal_claims.find(" in inspect.getsource(publish.main), True)
    check("表示の門: build.py は該当のある原稿を公開しない（BLOCKED）",
          "legal_claims.find(" in (ROOT / "scripts" / "build.py").read_text(encoding="utf-8"), True)

    facts = json.loads((ROOT / "data" / "first_party_facts.json").read_text(encoding="utf-8"))
    claims = " ".join(f.get("claim", "") for f in facts["facts"])
    check("材料: 一次情報に当社の作成代行・支援社数の主張が無い", LC.find(claims), [])
    sub = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    check("材料: 補助金サイトの記事下の案内が作成代行と読めない",
          (LC.find(sub["cta_desc"]), "申請書類の準備まで" in sub["cta_desc"]), ([], False))
    prompt = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    import auto_rewrite as AR
    check("執筆の指示: 当社の採択率・支援社数と作成代行を書かない決まりがある（記事・書き直し）",
          ("支援社数" in prompt and "legal_claims.py" in prompt, "申請を代行" in AR.PROMPT), (True, True))


def test_legal_claims_catches_subsidy_rebate():
    import legal_claims as LC
    print("\n■ 補助金の還元（採択・交付を条件にした値引き）を見つけ、注意喚起の文は止めない")
    bad = ["開発費550万円−補助金350万円−採択者割引=実質約80万円", "ご契約者様は会員価格で大幅割引",
           "補助金でシステムを導入し、割引になった分でマップ集客まで頼めました", "補助金の一部をキャッシュバックします"]
    ok = ["採択を条件にした割引や特典の提示は、補助金の規程上で問題になります", "2店舗目以降は店舗数に応じた割引を設計します"]
    check("還元の表現は見つける", [bool([k for k, _ in LC.find(x) if k == "rebate"]) for x in bad], [True] * len(bad))
    check("注意喚起や補助金と関係の無い割引は止めない", [bool([k for k, _ in LC.find(x) if k == "rebate"]) for x in ok], [False] * len(ok))
