# -*- coding: utf-8 -*-
"""業種調査（industry_ai_sources）を、歯科・クリニック・不動産・工務店・士業のほかの業種へ広げる。

質問の組は Claude のサブスク（claude -p）で下書きし、形式と件数を機械で検査して
data/research/extra_questions.json に置く。industry_ai_sources が読み込んで QUESTIONS に足す。
質問は「お客様がAIに聞きそうな検索語」で、事実ではない（数字は聞いた結果からだけ出す）。

    python scripts/research_extra.py --draft            # まだ無い業種の質問を下書きする
    python scripts/research_extra.py --list             # 業種と質問数
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "research" / "extra_questions.json"
PER_GROUP = 10

# (slug, 業種名, 事業者の呼び方, 聞く人, 例の手がかり)
INDUSTRIES = [
    ("seikotsuin", "整骨院・接骨院", "整骨院", "患者", "肩こり・腰痛・交通事故・保険の使い方"),
    ("biyou", "美容室・サロン", "美容室", "お客様", "カット・カラー・縮毛矯正・メンズ・予約"),
    ("inshoku", "飲食店", "飲食店", "お客様", "ランチ・個室・宴会・予約・テイクアウト"),
    ("kaigo", "介護事業所", "介護事業所", "ご家族", "デイサービス・訪問介護・老人ホーム・費用・要介護認定"),
    ("juku", "学習塾・スクール", "学習塾", "保護者", "個別指導・受験・料金・オンライン・英会話"),
    ("hotel", "ホテル・旅館", "宿", "旅行者", "温泉・家族旅行・朝食・アクセス・キャンセル"),
    ("fitness", "フィットネス・ジム", "ジム", "利用者", "パーソナル・24時間・料金・ダイエット・女性専用"),
    ("esthe", "エステ・ネイルサロン", "サロン", "お客様", "脱毛・フェイシャル・ジェルネイル・料金・回数"),
    ("jidousha", "自動車整備・販売", "整備工場・販売店", "車の持ち主", "車検・オイル交換・修理・中古車・費用"),
    ("seizou", "製造業（受託加工）", "製造会社", "発注担当者", "試作・小ロット・金属加工・樹脂成形・見積"),
    ("kensetsu", "建設・設備工事", "工事会社", "発注者", "外構・解体・電気工事・空調・見積"),
    ("unso", "運送・物流", "運送会社", "荷主", "引っ越し・チャーター便・倉庫・配送料金"),
    ("ec", "ネットショップ（EC）", "ショップ", "買い手", "通販・送料・返品・ギフト・口コミ"),
    ("saas", "IT・SaaS", "IT企業", "導入担当者", "勤怠管理・会計ソフト・CRM・比較・料金"),
    ("vet", "動物病院", "動物病院", "飼い主", "夜間救急・ワクチン・去勢・費用・ペット保険"),
    ("hoken", "保険代理店", "保険代理店", "相談者", "生命保険・自動車保険・見直し・無料相談・比較"),
    ("sougi", "葬儀社", "葬儀社", "ご遺族", "家族葬・直葬・費用・互助会・お布施"),
    ("wedding", "結婚式場", "式場", "新郎新婦", "費用・少人数婚・フォトウェディング・見学・持ち込み"),
    ("gaiheki", "外壁塗装・屋根工事", "塗装店", "家の持ち主", "外壁塗装の相場・屋根・塗料・助成金・業者選び"),
    ("fuyouhin", "不用品回収・遺品整理", "回収業者", "依頼者", "不用品回収・遺品整理・料金・粗大ごみ・買取"),
    ("pet", "ペットサロン・ペットホテル", "ペットサロン", "飼い主", "トリミング・ペットホテル・料金・犬種・予約"),
    ("yakkyoku", "薬局", "薬局", "利用者", "処方箋・オンライン服薬指導・営業時間・ジェネリック・在庫"),
    ("shashin", "写真館・フォトスタジオ", "写真館", "お客様", "七五三・成人式・家族写真・料金・データ納品"),
    ("kaji", "家事代行・ハウスクリーニング", "業者", "依頼者", "エアコン掃除・家事代行・料金・定期契約・口コミ"),
]

SCHEMA_NOTE = (
    "次の JSON オブジェクトだけを出力してください（説明は書かない）。\n"
    '{"name": 業種名, "text": {"owner": 事業者の呼び方, "owner_site": "◯◯の公式サイト", "portal": 比較・予約・紹介サイトの呼び方,'
    ' "public_label": 公的機関・業界団体の呼び方, "public_ex": その例を「・」でつないだ文, "find_ex": 地域で探す質問の例を「」で囲んだもの,'
    ' "other_groups": 地域で探す以外の4種類を「・」でつないだ文, "other_short": その短い言い方, "self_page": "自社の解説ページ"のような言い方,'
    ' "advice": この業種の事業者が自社サイトでしておくべきこと（40字前後・断定しすぎない）, "asker": 聞く人},'
    f' "groups": {{"地域で探す": [{PER_GROUP}問], 種類2: [{PER_GROUP}問], 種類3: [{PER_GROUP}問], 種類4: [{PER_GROUP}問], 種類5: [{PER_GROUP}問]}}}}\n'
    "質問は、聞く人が検索窓やAIに打ちそうな短い語の並び（例「大阪 整骨院 おすすめ」「縮毛矯正 料金 相場」）。"
    "「地域で探す」は大阪・東京・名古屋・福岡・札幌・横浜・京都・神戸・仙台・広島を1つずつ使う。"
    "ほかの4種類は、費用・選び方を必ず含め、残り2つはこの業種で聞く人が多い悩みの種類にする。"
    "同じ質問を繰り返さない。実在の店名・社名・商品名・数字は入れない。"
)


def load():
    """QUESTIONS に足す分（ファイルが無ければ空）。lp は業種別のLPが無いので空（全業種のLPへ案内する）"""
    if not FILE.is_file():
        return {}
    d = json.loads(FILE.read_text(encoding="utf-8"))
    out = {}
    for slug, v in d.items():
        t = dict(v["text"])
        t.setdefault("lp", "")
        t.setdefault("lp_name", "SEO・AIO・LLMO対策")
        out[slug] = {"name": v["name"], "text": t, "groups": v["groups"]}
    return out


def _valid(v):
    g = v.get("groups") or {}
    if "地域で探す" not in g or len(g) != 5:
        return "種類が5つでない／地域で探すが無い"
    for k, qs in g.items():
        if len(qs) != PER_GROUP or len(set(qs)) != PER_GROUP:
            return f"{k}が{PER_GROUP}問でない・重複がある"
        if any(re.search(r"\d{2,}", q) and not re.search(r"20\d\d", q) for q in qs):
            return f"{k}に数字が入っている"
    need = {"owner", "owner_site", "portal", "public_label", "public_ex", "find_ex", "other_groups", "other_short",
            "self_page", "advice", "asker"}
    miss = need - set(v.get("text") or {})
    return f"text に {sorted(miss)} が無い" if miss else ""


def draft():
    import auto_rewrite as AR
    cur = json.loads(FILE.read_text(encoding="utf-8")) if FILE.is_file() else {}
    for slug, name, owner, asker, hint in INDUSTRIES:
        if slug in cur:
            continue
        prompt = (f"業種「{name}」（事業者は{owner}、聞く人は{asker}。よく聞かれる話題の例: {hint}）について、"
                  f"お客様がAIや検索で聞きそうな質問の組を作ります。\n" + SCHEMA_NOTE)
        for _ in range(3):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                r = subprocess.run([AR.claude_bin(), "-p", "--model", "claude-sonnet-5-5"], input=prompt, cwd=tmp,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            m = re.search(r"\{.*\}", r.stdout or "", re.S)
            try:
                v = json.loads(m.group(0)) if m else {}
            except Exception:
                v = {}
            why = _valid(v) if v else "JSONが無い"
            if not why:
                v["name"] = name
                cur[slug] = v
                FILE.parent.mkdir(parents=True, exist_ok=True)
                FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"OK {slug} {name}", flush=True)
                break
            print(f"やり直し {slug}: {why}", flush=True)
        else:
            print(f"NG {slug}", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    if "--draft" in sys.argv:
        draft()
    else:
        for k, v in load().items():
            print(k, v["name"], {g: len(q) for g, q in v["groups"].items()})
