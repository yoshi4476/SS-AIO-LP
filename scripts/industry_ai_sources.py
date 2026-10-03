# -*- coding: utf-8 -*-
"""業種別の調査「患者・顧客がAIに聞いたとき、AIは何を出典に答えているか」。

    python scripts/industry_ai_sources.py --industry dental --dry-run   # 質問と見積もりだけ（課金なし）
    python scripts/industry_ai_sources.py --industry dental              # 聞いて集計する（1回だけ回す）
    python scripts/industry_ai_sources.py --industry dental --classify   # 出典の種類分けをやり直す（課金なし）

質問は固定の一覧（ページでも公開する）。4つのAI（ChatGPT・Gemini・Perplexity・Claude）に聞き、
回答の出典URLをサイトの種類（予約・比較ポータル／医院の公式サイト／公的機関・学会…）に分けて数える。
個別の医院名は公開しない（種類ごとの集計だけ）。応答は ai_cite_check の30日キャッシュに残るので、
集計や種類分けを直すときに聞き直さない（課金は1回だけ）。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "research"
CLASS_FILE = OUT / "source_class.json"

CITIES = ["大阪", "東京", "名古屋", "福岡", "札幌", "横浜", "京都", "神戸", "仙台", "広島"]
QUESTIONS = {
    "dental": {
        "name": "歯科",
        "groups": {
            "地域で探す": [f"{c} 歯医者 おすすめ" for c in CITIES] + [f"{c} 歯科 評判 いい" for c in CITIES],
            "費用": [f"{t} 費用 相場" for t in ("インプラント", "歯列矯正", "マウスピース矯正", "ホワイトニング",
                                              "セラミック 詰め物", "入れ歯", "根管治療", "親知らず 抜歯", "歯周病 治療", "小児矯正")]
                    + [f"{t} 保険 適用 されるか" for t in ("インプラント", "歯列矯正", "ホワイトニング", "セラミック",
                                                       "入れ歯", "根管治療", "親知らず 抜歯", "歯周病 治療", "小児矯正", "歯のクリーニング")]
                    + ["歯医者 初診料 いくら", "銀歯 白くする 費用", "インプラント 1本 値段", "部分矯正 費用",
                       "ブリッジ 費用 保険", "被せ物 種類 値段", "矯正 分割払い できる", "歯科 医療費控除 対象", "歯のクリーニング 自費 違い", "歯科 ローン 使える"],
            "治療の選び方": ["インプラント 失敗しない 歯医者の選び方", "矯正歯科 選び方", "ホワイトニング 歯科 エステ 違い",
                         "マウスピース矯正 デメリット", "インプラント 入れ歯 ブリッジ 比較", "セラミック 保険 違い",
                         "親知らず 抜くべきか", "根管治療 専門医 必要か", "歯周病 治るのか", "子供 矯正 何歳から",
                         "審美歯科 とは", "予防歯科 通う頻度", "歯科 セカンドオピニオン", "訪問歯科 とは", "口腔外科 とは 何をする"],
            "症状": ["歯が痛い 夜 どうする", "歯茎から血が出る 原因", "知覚過敏 治し方", "口臭 歯医者 行くべき",
                   "銀歯 取れた どうする", "歯ぎしり マウスピース 歯医者", "顎関節症 何科", "虫歯 放置 どうなる",
                   "歯が欠けた 応急処置", "親知らず 腫れた", "歯がしみる 原因", "歯茎 腫れ 膿", "子供 歯 ぐらぐら",
                   "口内炎 歯医者 行くべきか", "差し歯 取れた", "歯石 取り 頻度", "歯の黄ばみ 原因", "噛むと痛い 歯",
                   "インプラント 痛み 術後", "抜歯後 ドライソケット"],
            "受診のしかた": ["いい歯医者 見分け方", "歯医者 変えたい 途中", "歯医者 予約 取りやすい", "歯医者 土日 診療",
                         "歯医者 怖い 痛くない", "歯医者 初診 何をする", "歯科 自費 保険 違い", "歯医者 口コミ 信用できるか",
                         "歯医者 説明 しない", "歯医者 削りすぎ", "歯医者 何ヶ月ごと 検診", "女性 歯科医師 探し方",
                         "歯科 夜間 救急", "歯医者 治療 長い なぜ", "歯医者 転院 紹介状"],
        },
    },
}

QUESTIONS["clinic"] = {
    "name": "クリニック",
    "text": {"owner": "クリニック", "owner_site": "医院・クリニックの公式サイト", "portal": "予約・比較ポータル",
             "public_label": "公的機関・学会", "public_ex": "官公庁・大学・学会・医師会",
             "find_ex": "「大阪 内科 クリニック おすすめ」", "other_groups": "費用・選び方・症状・受診のしかた",
             "other_short": "費用・症状・受診など", "self_page": "自院の解説ページ",
             "advice": "診療内容・費用・受診の目安を、自院のサイトで分かりやすく説明しておくこと",
             "lp": "medical", "lp_name": "クリニック・歯科医院のSEO・AI検索対策", "asker": "患者"},
    "groups": {
        "地域で探す": [f"{c} 内科 クリニック おすすめ" for c in CITIES] + [f"{c} 皮膚科 評判 いい" for c in CITIES],
        "費用": [f"{t} 費用 相場" for t in ("健康診断", "人間ドック", "シミ取り 美容皮膚科", "ピル 処方", "AGA 治療",
                                          "インフルエンザ 予防接種", "胃カメラ", "大腸カメラ", "睡眠時無呼吸 検査", "禁煙外来")]
                + [f"{t} 保険 適用 されるか" for t in ("ニキビ 治療", "シミ取り", "胃カメラ", "花粉症 注射", "ED 治療",
                                                   "AGA 治療", "漢方 処方", "睡眠外来", "禁煙外来", "ピル")],
        "選び方": ["内科 選び方", "かかりつけ医 選び方", "皮膚科 美容皮膚科 違い", "胃カメラ 鎮静 クリニック 選び方",
                 "オンライン診療 デメリット", "発熱外来 探し方", "心療内科 精神科 違い", "クリニック 病院 違い",
                 "専門医 探し方", "小児科 選び方", "婦人科 選び方", "耳鼻科 子供 選び方", "整形外科 整骨院 違い",
                 "眼科 選び方", "人間ドック 選び方"],
        "症状": ["発熱 何科", "頭痛 続く 何科", "腹痛 何科", "めまい 何科", "動悸 何科", "咳 止まらない 何科",
               "湿疹 かゆい 何科", "腰痛 何科", "不眠 何科", "胃もたれ 続く", "花粉症 何科", "ニキビ 皮膚科 行くべき",
               "じんましん 原因", "喉の痛み 何科", "血圧 高い 何科", "肩こり 頭痛 何科", "目のかゆみ 何科",
               "膀胱炎 何科", "生理痛 ひどい 何科", "子供 発熱 受診 目安", "物忘れ 何科", "しびれ 何科", "耳鳴り 何科",
               "下痢 続く 何科", "動悸 息切れ 原因"],
        "受診のしかた": ["クリニック 予約なし", "クリニック 土日 診療", "夜間 クリニック", "初診 紹介状 必要か",
                     "オンライン診療 やり方", "クリニック 口コミ 信用できるか", "セカンドオピニオン やり方", "診断書 もらい方",
                     "健康診断 再検査 どこで", "予防接種 予約 方法", "医療費控除 対象 クリニック", "待ち時間 短い クリニック",
                     "クリニック 変える 紹介状", "女性医師 探し方", "マイナ保険証 使えるクリニック", "クリニック 電話 予約 取れない",
                     "往診 頼み方", "訪問診療 とは", "かかりつけ医 必要か", "小児科 何歳まで"],
    },
}
QUESTIONS["fudosan"] = {
    "name": "不動産",
    "text": {"owner": "不動産会社", "owner_site": "不動産会社の公式サイト", "portal": "不動産ポータル・比較サイト",
             "public_label": "公的機関・業界団体", "public_ex": "官公庁・自治体・業界団体",
             "find_ex": "「大阪 不動産会社 おすすめ」", "other_groups": "費用・選び方・手続き・物件探し",
             "other_short": "費用・手続き・物件探しなど", "self_page": "自社の解説ページ",
             "advice": "売却・購入・賃貸の費用や手続きを、自社のサイトで分かりやすく説明しておくこと",
             "lp": "fudosan", "lp_name": "不動産会社のSEO・AI検索対策", "asker": "住まいを探す人・売りたい人"},
    "groups": {
        "地域で探す": [f"{c} 不動産会社 おすすめ" for c in CITIES] + [f"{c} 不動産 売却 おすすめ 会社" for c in CITIES],
        "費用": ["仲介手数料 相場", "不動産売却 費用 内訳", "家を売る 税金", "マンション売却 費用", "土地 売却 費用",
               "賃貸 初期費用 相場", "引っ越し 初期費用 平均", "家 査定 費用", "相続 不動産 費用", "住宅ローン 諸費用 目安",
               "中古マンション 購入 諸費用", "固定資産税 計算", "登記 費用 相場", "空き家 売却 費用", "リースバック 相場",
               "不動産 買取 相場", "賃貸 更新料 相場", "管理会社 手数料 相場", "家 解体 費用", "任意売却 費用"],
        "選び方": ["不動産会社 選び方", "仲介 買取 違い", "一括査定 デメリット", "専任媒介 一般媒介 違い",
                 "大手 地元 不動産 違い", "賃貸 不動産屋 選び方", "管理会社 選び方", "売却 時期 いつ", "住み替え 進め方",
                 "中古 新築 どっち", "マンション 戸建て どっち", "賃貸 持ち家 どっち", "リノベーション物件 注意点",
                 "不動産投資 始め方", "相続した家 どうする", "空き家 活用 方法", "土地活用 選び方", "査定額 違う 理由",
                 "不動産屋 信用できる 見分け方", "おとり物件 見分け方"],
        "手続き・トラブル": ["家を売る 流れ", "賃貸 契約 流れ", "住宅購入 流れ", "重要事項説明 ポイント", "売買契約 キャンセル",
                       "敷金 返ってこない", "原状回復 トラブル", "退去費用 高い", "契約不適合責任 とは", "境界 トラブル",
                       "住宅ローン 審査 落ちた", "売れない 家 理由", "内覧 準備", "値下げ タイミング", "相続登記 義務化",
                       "空き家 特例", "3000万円 控除 条件", "住宅ローン控除 条件", "賃貸 審査 落ちる", "保証人 いない 賃貸"],
        "物件・街の探し方": [f"{c} 住みやすい 街" for c in CITIES]
                     + ["ファミリー 住みやすい 街 選び方", "駅近 デメリット", "ハザードマップ 見方", "学区 調べ方",
                        "新築マンション 買い時", "中古戸建て 注意点", "マンション 築年数 目安", "賃貸 狙い目 時期",
                        "ペット可 賃貸 探し方", "一人暮らし 家賃 目安"],
    },
}
QUESTIONS["koumuten"] = {
    "name": "工務店・リフォーム",
    "text": {"owner": "工務店・リフォーム会社", "owner_site": "住宅会社・リフォーム会社の公式サイト",
             "portal": "住宅の比較・資料請求サイト", "public_label": "公的機関・業界団体", "public_ex": "官公庁・自治体・業界団体",
             "find_ex": "「大阪 工務店 おすすめ」", "other_groups": "費用・選び方・進め方・住まいの悩み",
             "other_short": "費用・家づくり・住まいの悩みなど", "self_page": "自社の解説ページ",
             "advice": "費用の考え方・工法・施工事例を、自社のサイトで分かりやすく説明しておくこと",
             "lp": "koumuten", "lp_name": "工務店・リフォーム会社のSEO・AI検索対策", "asker": "家を建てたい人・直したい人"},
    "groups": {
        "地域で探す": [f"{c} 工務店 おすすめ" for c in CITIES] + [f"{c} リフォーム会社 評判" for c in CITIES],
        "費用": ["注文住宅 費用 相場", "工務店 坪単価 相場", "平屋 費用", "二世帯住宅 費用", "外壁塗装 費用 相場",
               "屋根 リフォーム 費用", "キッチン リフォーム 費用", "浴室 リフォーム 費用", "トイレ リフォーム 費用",
               "フルリノベーション 費用", "耐震 リフォーム 費用", "断熱 リフォーム 費用", "建て替え 費用", "外構 費用 相場",
               "太陽光発電 費用", "注文住宅 諸費用", "地盤改良 費用", "木造 解体 費用", "水回り リフォーム 費用", "床 張り替え 費用"],
        "選び方": ["工務店 ハウスメーカー 違い", "工務店 選び方", "リフォーム会社 選び方", "設計事務所 工務店 違い",
                 "相見積もり 注意点", "高気密高断熱 工務店 見分け方", "ZEH とは", "長期優良住宅 メリット", "耐震等級3 必要か",
                 "断熱等級 とは", "木造 鉄骨 どっち", "平屋 二階建て どっち", "建売 注文住宅 違い", "リフォーム 建て替え どっち",
                 "リノベーション リフォーム 違い", "工務店 倒産 リスク", "完成見学会 チェックポイント", "モデルハウス 見るべき点",
                 "工務店 アフターサービス 比較", "住宅 保証 期間"],
        "進め方・トラブル": ["注文住宅 流れ", "家づくり 何から", "土地探し 工務店", "住宅ローン いつ 申し込む", "間取り 失敗",
                       "注文住宅 後悔", "リフォーム トラブル", "追加費用 トラブル 工事", "工期 遅れる", "欠陥住宅 見分け方",
                       "新築 雨漏り", "リフォーム 補助金", "住宅 補助金 2026", "外壁塗装 時期", "リフォーム 契約 注意点",
                       "工事 近所 挨拶", "地鎮祭 必要か", "引き渡し チェック", "新築 定期点検 内容", "リフォーム ローン"],
        "住まいの悩み": ["家 寒い 対策", "結露 対策", "家 カビ 原因", "床 きしむ 原因", "雨漏り 修理 どこに頼む",
                     "シロアリ 対策", "外壁 ひび割れ", "窓 断熱 方法", "家 暑い 対策", "防音 リフォーム", "バリアフリー リフォーム",
                     "収納 増やす リフォーム", "耐震診断 古い家", "給湯器 交換 時期", "屋根 修理 業者 選び方",
                     "空き家 リフォーム", "古民家 リノベーション", "狭小住宅 間取り", "ガレージハウス 費用", "中古住宅 リフォーム 注意点"],
    },
}

QUESTIONS["shigyou"] = {
    "name": "士業",
    "text": {"owner": "士業事務所", "owner_site": "士業事務所の公式サイト", "portal": "比較・紹介サイト",
             "public_label": "公的機関・士業団体", "public_ex": "官公庁・自治体・各士業会",
             "find_ex": "「大阪 税理士 おすすめ」", "other_groups": "費用・選び方・手続き・制度",
             "other_short": "費用・手続き・制度など", "self_page": "事務所の解説ページ",
             "advice": "相談テーマごとの費用・手続き・制度を、事務所のサイトで分かりやすく説明しておくこと",
             "lp": "shigyou", "lp_name": "士業事務所のSEO・AI検索対策", "asker": "相談先を探す人"},
    "groups": {
        "地域で探す": [f"{c} 税理士 おすすめ" for c in CITIES] + [f"{c} 司法書士 相続 評判" for c in CITIES],
        "費用": ["税理士 顧問料 相場", "確定申告 税理士 費用", "記帳代行 費用", "会社設立 司法書士 費用", "相続税申告 税理士 報酬",
               "相続登記 司法書士 費用", "社労士 顧問料 相場", "就業規則 作成 費用", "助成金 申請 社労士 報酬", "行政書士 許可申請 費用",
               "建設業許可 費用", "ビザ申請 行政書士 費用", "弁護士 相談料 相場", "離婚 弁護士 費用", "遺言書 作成 費用",
               "家族信託 費用", "会社 解散 費用", "決算 税理士 費用 相場", "年末調整 代行 費用", "給与計算 代行 費用"],
        "選び方": ["税理士 選び方", "税理士 変える タイミング", "社労士 選び方", "行政書士 選び方", "弁護士 選び方", "司法書士 選び方",
                 "税理士 会計士 違い", "司法書士 行政書士 違い", "社労士 必要か", "顧問税理士 必要か", "相続 誰に相談", "会社設立 誰に頼む",
                 "オンライン 税理士 デメリット", "女性 税理士 探し方", "相続 弁護士 税理士 違い", "労務トラブル 相談先",
                 "許認可 自分で できるか", "記帳代行 税理士 違い", "税理士 紹介サービス 使うべきか", "社労士 顧問 なし 大丈夫か"],
        "手続き・悩み": ["確定申告 やり方", "インボイス 登録 必要か", "電子帳簿保存法 対応", "相続税 申告 期限", "相続放棄 手続き",
                     "遺産分割 揉めた", "会社設立 流れ", "法人成り タイミング", "社会保険 加入 義務", "未払い残業代 請求された",
                     "労働基準監督署 調査", "就業規則 作成 義務", "建設業許可 要件", "古物商許可 取り方", "在留資格 変更 手続き",
                     "税務調査 来た", "延滞税 計算", "資金繰り 相談先", "事業承継 進め方", "小規模 M&A 相談先"],
        "制度・ルール": ["相続税 基礎控除", "贈与税 非課税", "小規模宅地等の特例", "青色申告 メリット", "経費 認められる 範囲",
                     "減価償却 とは", "消費税 免税事業者", "社会保険 扶養 範囲", "育児休業 給付金", "雇用保険 加入条件",
                     "36協定 とは", "最低賃金 2026", "パート 有給 日数", "労災 申請 方法", "遺言 種類", "成年後見 とは",
                     "家族信託 とは", "相続登記 義務化", "補助金 申請 誰に頼む", "役員報酬 決め方"],
    },
}

# 歯科・クリニック・不動産・工務店・士業のほかの業種（research_extra.py が下書きした質問の組）
try:
    import research_extra as _RX
    QUESTIONS.update({k: v for k, v in _RX.load().items() if k not in QUESTIONS})
except Exception:
    pass

CATS = {
    "portal": "予約・比較ポータル",
    "clinic": "医院・クリニックの公式サイト",
    "review": "口コミ・地図",
    "public": "公的機関・学会・業界団体",
    "maker": "メーカー・企業",
    "media": "ニュース・メディア・まとめ記事",
    "video": "動画・SNS",
    "wiki": "百科事典",
    "other": "その他",
}
# 決まったルールで分けられるもの。分けきれない分だけ claude に分けさせる（結果はファイルに残し、人が見直せる）
RULES = [
    # .or.jp を一律に公的機関にしない。医療法人の医院も .or.jp を使う（試しで ohnuki-dental.or.jp を公的機関と誤った）
    (r"(^|\.)go\.jp$|(^|\.)lg\.jp$|(^|\.)ac\.jp$|(^|\.)jda\.or\.jp$|(^|\.)perio\.jp$|(^|\.)kokuhoken\.or\.jp$|"
     r"who\.int$|nih\.gov$", "public"),
    (r"epark|haisha-yoyaku|caloo|byoinnavi|doctorsfile|qlife|scuel|shika-town|ha-channel|minnano-shika|"
     r"dentalbook|shika-navi|denternet|hospita|medicaldoc|fdoc|mrso|ishachoku|okbiz|"
     r"(^|\.)suumo\.jp$|(^|\.)homes\.co\.jp$|(^|\.)athome\.co\.jp$|(^|\.)ieul\.jp$|(^|\.)home4u\.jp$|"
     r"sumai-step|rehome-navi|homepro\.jp|nuri-kae|reform-guide|zeiri4\.com|bengo4\.com", "portal"),
    (r"google\.(com|co\.jp)/maps|maps\.google|maps\.app\.goo\.gl|tabelog|minkou|minkuru", "review"),
    (r"youtube\.com|youtu\.be|tiktok\.com|instagram\.com|x\.com|twitter\.com|facebook\.com|note\.com|ameblo\.jp", "video"),
    (r"wikipedia\.org", "wiki"),
    (r"yahoo\.co\.jp|nikkei\.com|asahi\.com|yomiuri\.co\.jp|mainichi\.jp|nhk\.or\.jp|allabout\.co\.jp|"
     r"diamond\.jp|president\.jp|news\.", "media"),
]


def domain(u):
    try:
        h = urllib.parse.urlparse(u).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def rule_class(d, u=""):
    for pat, c in RULES:
        if re.search(pat, d) or (c in ("review",) and re.search(pat, u)):
            return c
    return ""


def questions(ind):
    return [(g, q) for g, qs in QUESTIONS[ind]["groups"].items() for q in qs]


def estimate(n):
    # 公式の料金（2026-10-02 確認）: OpenAI web_search_preview $25/1k＋gpt-4.1-mini の文字量、
    # Gemini の検索つき回答は月5,000回まで無料、Perplexity fast は約$0.0065/回、Claude はサブスク
    usd = n * (0.025 + 0.002) + n * 0.0065
    return usd


def ask_all(ind, workers=6, sub=False):
    import ai_cite_check as AC
    # sub=True は課金APIを使わない（ChatGPT・Claude はサブスク、Gemini は無料枠）
    eng = AC.subscription_engines() if sub else AC.engines_available()
    qs = questions(ind)
    tasks = [(g, q, name) for g, q in qs for name in eng]
    res = defaultdict(dict)

    def one(t):
        g, q, name = t
        try:
            urls = eng[name](q) or []
            return g, q, name, urls, ""
        except Exception as e:
            return g, q, name, [], str(e)[:160]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (g, q, name, urls, err) in enumerate(ex.map(one, tasks), 1):
            res[q].setdefault("group", g)
            res[q][name] = {"urls": urls, "error": err}
            if i % 20 == 0:
                print(f"  {i}/{len(tasks)}", flush=True)
    return {"industry": ind, "date": date.today().isoformat(), "engines": sorted(eng), "answers": res}


def classify(raw):
    """出典のドメインを種類に分ける。ルール → 前回の結果 → claude（未知の分だけ）"""
    known = json.loads(CLASS_FILE.read_text(encoding="utf-8")) if CLASS_FILE.is_file() else {}
    samples = {}
    for q, by in raw["answers"].items():
        for name, r in by.items():
            if name == "group":
                continue
            for u in r["urls"]:
                d = domain(u)
                if d:
                    samples.setdefault(d, u)
    todo = [d for d in samples if not rule_class(d, samples[d]) and d not in known]
    if todo:
        import auto_rewrite as AR
        lines = "\n".join(f"{d}\t{samples[d][:120]}" for d in todo)
        prompt = ("次のドメイン（タブの後ろは実際に出典になったURLの例）を、サイトの種類に分けてください。\n"
                  "種類は次のキーのどれか1つ: " + ", ".join(f"{k}={v}" for k, v in CATS.items()) + "\n"
                  "医院・クリニック・病院・不動産会社・工務店・リフォーム会社など、事業者が自社について書いているサイトは clinic。複数の事業者を比べる・予約や査定や資料請求を受ける・"
                  "事業者を紹介するサイトは portal。医療法人の医院は .or.jp でも clinic（公的機関ではない）。住宅設備や建材のメーカーは maker。"
                  "学会・医師会・歯科医師会・業界団体・官公庁・自治体・大学だけが public。分からなければ other。\n"
                  "出力は JSON のオブジェクト1つだけ（{\"ドメイン\": \"キー\", ...}）。説明は書かない。\n\n" + lines)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            r = subprocess.run([AR.claude_bin(), "-p", "--model", "claude-sonnet-5-5"], input=prompt, cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        m = re.search(r"\{.*\}", r.stdout or "", re.S)
        got = json.loads(m.group(0)) if m else {}
        for d in todo:
            c = got.get(d, "other")
            known[d] = c if c in CATS else "other"
        OUT.mkdir(parents=True, exist_ok=True)
        CLASS_FILE.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    # 業種ごとの上書き（"<業種>|<ドメイン>"）を先に見る。同じサイトでも業種で種類が変わる
    # （士業グループは士業の調査では士業事務所、不動産の調査では「その他」）
    ind = raw.get("industry", "")
    return lambda d, u="": rule_class(d, u) or known.get(f"{ind}|{d}") or known.get(d, "other")


def summarize(raw, cls):
    """種類ごとの割合（AIごと・質問の種類ごと）。1つの回答で同じドメインは1回だけ数える"""
    by_engine, by_group, total = defaultdict(Counter), defaultdict(Counter), Counter()
    answered, has_clinic, n_src = Counter(), Counter(), Counter()
    portal_dom = Counter()
    for q, by in raw["answers"].items():
        g = by.get("group", "")
        for name, r in by.items():
            if name == "group" or r.get("error"):
                continue
            doms = {}
            for u in r["urls"]:
                d = domain(u)
                if d:
                    doms.setdefault(d, u)
            if not doms:
                continue
            answered[name] += 1
            n_src[name] += len(doms)
            kinds = {d: cls(d, u) for d, u in doms.items()}
            if "clinic" in kinds.values():
                has_clinic[name] += 1
            for d, k in kinds.items():
                by_engine[name][k] += 1
                by_group[g][k] += 1
                total[k] += 1
                if k == "portal":
                    portal_dom[d] += 1
    return {"total": dict(total), "by_engine": {k: dict(v) for k, v in by_engine.items()},
            "by_group": {k: dict(v) for k, v in by_group.items()}, "answered": dict(answered),
            "has_clinic": dict(has_clinic), "sources": dict(n_src), "portal_top": portal_dom.most_common(10)}


def per_answer(raw):
    """もう1つの数え方: 回答ごとに『その種類を1つでも出典にしたか』（出典のある回答だけ）。
    出典の件数で数えると、出典を多く付ける AI（Claude 10件/回答）の重みが大きくなるため、両方を載せる"""
    known = json.loads(CLASS_FILE.read_text(encoding="utf-8")) if CLASS_FILE.is_file() else {}
    ind = raw.get("industry", "")
    cls = lambda d, u="": rule_class(d, u) or known.get(f"{ind}|{d}") or known.get(d, "other")
    ans, hit = Counter(), defaultdict(Counter)
    for q, by in raw["answers"].items():
        g = by.get("group", "")
        for name, r in by.items():
            if name == "group" or not r.get("urls"):
                continue
            kinds = {cls(domain(u), u) for u in r["urls"] if domain(u)}
            for key in ("全体", g):
                ans[key] += 1
                for k in kinds:
                    hit[key][k] += 1
    return {k: {"answers": ans[k], **dict(hit[k])} for k in ans}


TEXT = {"dental": {
    "owner": "医院", "owner_site": "医院・クリニックの公式サイト", "portal": "予約・比較ポータル",
    "public_label": "公的機関・学会", "public_ex": "官公庁・大学・学会・歯科医師会",
    "find_ex": "「大阪 歯医者 おすすめ」", "other_groups": "費用・治療の選び方・症状・受診のしかた",
    "other_short": "費用・治療・症状など", "self_page": "自院の解説ページ",
    "advice": "費用の考え方や治療の選び方を、自院のサイトで分かりやすく説明しておくこと",
    "lp": "medical", "lp_name": "クリニック・歯科医院のSEO・AI検索対策", "asker": "患者"}}


ENGINE_NOTE = {"ChatGPT": "gpt-4.1-mini＋Web検索", "Gemini": "Gemini Flash＋Google検索", "Perplexity": "Agent API（fast）",
               "Claude": "Claude Sonnet＋Web検索"}


# 業種ハブ（data/industries.json の slug）→ 調査。記事・業種ハブ・提案書・調査ページがここを見る
HUB_TO_RESEARCH = {"shika": "dental", "clinic": "clinic", "fudosan": "fudosan", "koumuten": "koumuten",
                   "reform": "koumuten", "shigyou": "shigyou",
                   # research_extra.py で広げた業種（集計が無いうちは headline が None なので案内は出ない）
                   "seikotsuin": "seikotsuin", "biyou": "biyou", "inshokuten": "inshoku", "btob": "saas",
                   "kensetsu": "kensetsu", "shukuhaku": "hotel"}
# 調査 → チェックリスト（checklist_make.py の業種）
RESEARCH_TO_CHECKLIST = {"dental": "dental", "clinic": "clinic", "fudosan": "fudosan", "koumuten": "koumuten",
                         "shigyou": "shigyou"}


# 記事の題名から、調査のどの種類の質問に当たるかを決める（上から順に見る）。
# 当たれば、その種類の質問だけの内訳を記事に出す（業種全体の同じ数字を全記事に出すより、そのページにしか無い中身になる）
GROUP_RX = [
    (r"費用|相場|料金|いくら|価格|坪単価|報酬|見積", ("費用",)),
    (r"地域|近く|おすすめ|評判|MEO|マップ|口コミ|地図", ("地域で探す",)),
    (r"選び方|会社|比較|依頼|外注|コンサル|代行|ライター", ("選び方", "治療の選び方")),
    (r"症状|痛み|治療|インプラント|矯正", ("症状", "治療の選び方")),
    (r"受診|予約|初診|電話|オンライン診療", ("受診のしかた",)),
    (r"制度|ルール|規制|ガイドライン|法|税", ("制度・ルール",)),
    (r"手続き|トラブル|契約|反響|失敗|見学|施工事例|進め方", ("手続き・トラブル", "進め方・トラブル", "手続き・悩み")),
    (r"物件|街|土地|住まい|リフォーム|断熱|間取り", ("物件・街の探し方", "住まいの悩み")),
]


def group_for(ind, title):
    """題名に当たる質問の種類（調査にその種類が無ければ None）"""
    f = OUT / f"{ind}-summary.json"
    if not f.is_file():
        return None
    groups = json.loads(f.read_text(encoding="utf-8")).get("by_group", {})
    for rx, names in GROUP_RX:
        if re.search(rx, title or ""):
            for n in names:
                if n in groups:
                    return n
                # 業種によって種類の名前が「費用・保険」のように変わる
                hit = next((g for g in groups if g.startswith(n.split("・")[0])), None)
                if hit:
                    return hit
    return None


def group_breakdown(ind, group):
    """その種類の質問で、回答のうち各種類のサイトを出典に含んだ割合（多い順）。数は集計ファイルからだけ"""
    s = json.loads((OUT / f"{ind}-summary.json").read_text(encoding="utf-8"))
    pa = s.get("per_answer", {}).get(group)
    if not pa or not pa.get("answers"):
        return None
    n = pa["answers"]
    rows = sorted(((round(pa.get(k, 0) / n * 100, 1), k) for k in CATS if pa.get(k)), reverse=True)
    return {"answers": n, "questions": len(QUESTIONS[ind]["groups"].get(group, [])), "rows": rows}


def _lpu(T):
    """業種別のLPがある業種はそのLP、無い業種は全業種のLP"""
    return f"/lp/{T['lp']}/" if T.get("lp") else "/lp/"


def research_for_title(title):
    """業種のまとめページが無い業種（ジム・動物病院など）は、題名の業種名で調査を選ぶ。
    調査は29業種あるのに、まとめページのある13業種の記事からしかつながっていなかった（2026-10-04）"""
    if not title:
        return None
    try:
        import research_extra as RX
    except Exception:
        return None
    for slug, name, owner, *_ in RX.INDUSTRIES:
        words = {w for w in re.split(r"[・（）()]", f"{name}・{owner}") if len(w) >= 2 and w not in ("業者", "サロン", "お客様")}
        if any(w in title for w in words) and (ROOT / "data" / "research" / f"{slug}-summary.json").is_file():
            return slug
    return None


def research_box(hub_slug, title=""):
    """記事の末尾に置く「この業種の調査」の案内。題名から質問の種類が分かれば、その種類だけの内訳を出す。
    調査が無い業種は空"""
    import html as H
    r = HUB_TO_RESEARCH.get(hub_slug or "") or research_for_title(title)
    hl = headline(r) if r else None
    if not hl:
        return ""
    T = hl["T"]
    cl = RESEARCH_TO_CHECKLIST.get(r, "")
    g = group_for(r, title)
    gb = group_breakdown(r, g) if g else None
    if gb:
        own = next((p for p, k in gb["rows"] if k == "clinic"), 0.0)
        label = lambda k: T["owner_site"] if k == "clinic" else (T["portal"] if k == "portal" else CATS[k])
        bars = "".join(f'<li><span class="rb-l">{H.escape(label(k))}</span><span class="rb-bar"><i style="width:{min(p, 100)}%"></i></span>'
                       f'<span class="rb-v">{p}%</span></li>' for p, k in gb["rows"][:5])
        return ('<aside class="scan-box research-box" aria-label="この業種の調査">'
                f'<p class="sb-kicker">当社の調査・{hl["date"][:4]}年{int(hl["date"][5:7])}月・{H.escape(hl["name"])}の「{H.escape(g)}」の質問</p>'
                f'<p class="sb-head">{H.escape(T.get("asker", "お客様"))}が「{H.escape(g)}」をAIに聞いたとき、回答の{own}%が{H.escape(T["owner_site"])}を出典に含んでいました</p>'
                f'<ul class="rb-bars">{bars}</ul>'
                f'<p class="sb-sub">「{H.escape(g)}」に当たる{gb["questions"]}問を {hl["engines_text"]} に聞き、'
                f'得られた{gb["answers"]}件の回答で、それぞれの種類のサイトを出典に含んだ回答の割合です（1つの回答が複数の種類を含むため、合計は100%になりません）。</p>'
                f'<p><a class="btn btn-primary" href="/research/{r}-ai-sources/" data-cta="article_research_{r}">調査の結果を見る</a> '
                + (f'<a class="btn btn-ghost" href="/download/?ind={cl}" data-cta="article_checklist_{cl}">チェックリスト（PDF）を受け取る</a>' if cl else "")
                + '</p></aside>')
    return ('<aside class="scan-box research-box" aria-label="この業種の調査">'
            f'<p class="sb-kicker">調査レポート・{hl["date"][:4]}年{int(hl["date"][5:7])}月</p>'
            f'<p class="sb-head">{H.escape(T["other_short"])}の質問では、回答の{hl["oa"]}%が{H.escape(T["owner_site"])}を出典にしていました</p>'
            f'<p class="sb-sub">{H.escape(hl["name"])}に関する{hl["questions"]}問を {hl["engines_text"]} に聞き、'
            f'AIが何を出典に答えているかを数えた調査です。</p>'
            f'<p><a class="btn btn-primary" href="/research/{r}-ai-sources/" data-cta="article_research_{r}">調査の結果を見る</a> '
            + (f'<a class="btn btn-ghost" href="/download/?ind={cl}" data-cta="article_checklist_{cl}">チェックリスト（PDF）を受け取る</a>' if cl else "")
            + '</p></aside>')


def headline(ind):
    """調査の要点の数字。調査ページ・業種別LP・提案書はここだけから数字を取る（食い違いを起こさない）。
    集計ファイルが無ければ None"""
    f = OUT / f"{ind}-summary.json"
    if not f.is_file():
        return None
    s = json.loads(f.read_text(encoding="utf-8"))
    if "per_answer" not in s:
        return None
    pa, loc = s["per_answer"], "地域で探す"
    T = {**TEXT["dental"], **QUESTIONS[ind].get("text", {})}
    pct = lambda c, k: round(c.get(k, 0) / max(sum(c.values()), 1) * 100, 1)
    apct = lambda key, k: round(pa[key].get(k, 0) / max(pa[key]["answers"], 1) * 100, 1)
    other = [g for g in s["by_group"] if g != loc]
    lp, lc = pct(s["by_group"][loc], "portal"), pct(s["by_group"][loc], "clinic")
    ap, ac = apct(loc, "portal"), apct(loc, "clinic")
    oc = round(sum(s["by_group"][g].get("clinic", 0) for g in other)
               / max(sum(sum(s["by_group"][g].values()) for g in other), 1) * 100, 1)
    oa = round(sum(pa[g].get("clinic", 0) for g in other) / max(sum(pa[g]["answers"] for g in other), 1) * 100, 1)
    # 「どちらが多い」は2通りの数え方で向きがそろい、件数で5ポイント以上の差があるときだけ言う
    verdict = ("portal" if lp - lc >= 5 and ap > ac else "owner" if lc - lp >= 5 and ac > ap else "even")
    # 実際に回答が取れたAIだけを並べる。固定の文で「4つに聞いた」と書くと、ChatGPT が上限で
    # 0件だった業種でも4つに聞いたことになっていた（2026-10-04）
    got = [e for e in ("ChatGPT", "Gemini", "Claude", "Perplexity") if (s.get("answered") or {}).get(e)]
    return {"ind": ind, "name": s["name"], "date": s["date"], "questions": s["questions"], "T": T,
            "engines_text": "・".join(got), "n_engines": len(got),
            "lp": lp, "lc": lc, "ap": ap, "ac": ac, "oc": oc, "oa": oa, "verdict": verdict,
            "url": f"https://ai.7senses.co.jp/research/{ind}-ai-sources/"}


def hero(ind):
    """調査ページの最初の画面（トップ・業種別LPと同じ lx-hero）。数字は headline() からだけ取る"""
    import html as H
    hl = headline(ind)
    T = hl["T"]
    if hl["verdict"] == "portal":
        first = (f'{hl["lp"]}%', f'{T["owner"]}を探す質問で、出典が{T["portal"]}だった割合（{T["owner_site"]}は{hl["lc"]}%）')
    elif hl["verdict"] == "owner":
        first = (f'{hl["lc"]}%', f'{T["owner"]}を探す質問で、出典が{T["owner_site"]}だった割合（{T["portal"]}は{hl["lp"]}%）')
    else:
        first = (f'{hl["lp"]}%／{hl["lc"]}%', f'{T["owner"]}を探す質問で、出典になった{T["portal"]}と{T["owner_site"]}の割合（ほぼ同じ）')
    y, m = hl["date"][:4], int(hl["date"][5:7])
    return (f'<section class="lx-hero ilp-hero" data-area="メインビジュアル" data-area-id="mv">'
            f'<div class="lx-wrap lx-hero-grid"><div>'
            f'<ul class="lx-kicker"><li>調査レポート</li><li>{y}年{m}月</li></ul>'
            f'<h1 class="lx-h1">{H.escape(hl["name"])}の質問に、<br><em>AIは何を出典に答えるか</em></h1>'
            f'<p class="lx-lead">{H.escape(T["asker"])}が実際に調べそうな{hl["questions"]}問を、{hl["engines_text"]} の{hl["n_engines"]}つに聞き、'
            f'回答の出典になったサイトの種類を数えました。</p>'
            f'<p class="lx-alt">集計データ: <a href="/research/{ind}-ai-sources/data.csv" download>CSVをダウンロード</a>'
            f' ／ <a href="/download/?ind={RESEARCH_TO_CHECKLIST.get(ind, "")}" data-cta="research_hero_checklist_{ind}">チェックリスト（PDF）を受け取る</a>'
            f' ／ {H.escape(T["owner"])}向けの対策: <a href="{_lpu(T)}" data-cta="research_hero_lp_{T["lp"]}">{H.escape(T["lp_name"])}</a></p>'
            f'</div><div class="lx-console ilp-console" aria-label="調査の要点">'
            f'<div class="lx-console-head"><b>要点</b><small>{hl["questions"]}問×4つのAI・{hl["date"]}</small></div>'
            f'<div class="lx-stat"><b>{H.escape(first[0])}</b><span>{H.escape(first[1])}</span></div>'
            f'<div class="lx-stat"><b>{hl["oa"]}%</b><span>{H.escape(T["other_short"])}を調べる質問で、回答が{H.escape(T["owner_site"])}を1つ以上出典にしていた割合</span></div>'
            f'</div></div></section>')


def cta_band(ind):
    """ページ末の帯。その業種の LP と30秒診断へ"""
    hl = headline(ind)
    T = hl["T"]
    return ('<section class="section"><div class="ilp-band" style="max-width:1120px;margin:0 auto">'
            f'<h2>{T["owner"]}のサイトは、AIと検索に読まれていますか？</h2>'
            '<p>URLを入れるだけで、AIのクローラーが入れるか・検索に出る設定か・内容を読み取れるかを30秒で診断します。</p>'
            '<div class="btns">'
            f'<a class="btn btn-primary" href="{_lpu(T)}#scan-start" data-cta="research_band_scan_{ind}">30秒で無料診断する</a>'
            f'<a class="btn btn-ghost" href="/tools/ai-check/" data-cta="research_band_aicheck_{ind}">自社がAIにどう紹介されているか確かめる</a>'
            f'<a class="btn btn-ghost" href="{_lpu(T)}" data-cta="research_band_lp_{ind}">{T["lp_name"]}を見る</a></div></div></section>')


def render(ind):
    """公開ページの中身（HTML）と構造化データ。数字は集計ファイルからだけ取る（手で書かない）"""
    import html as H
    s = json.loads((OUT / f"{ind}-summary.json").read_text(encoding="utf-8"))
    # 公開リポジトリには集計だけを置く（生データには個別の医院のURLが入るため、コミットしない）
    pa = s["per_answer"]
    name = s["name"]
    tot = sum(s["total"].values()) or 1
    pct = lambda c, k: round(c.get(k, 0) / max(sum(c.values()), 1) * 100, 1)
    apct = lambda key, k: round(pa[key].get(k, 0) / max(pa[key]["answers"], 1) * 100, 1)
    loc = "地域で探す"
    T = {**TEXT["dental"], **QUESTIONS[ind].get("text", {})}
    LAB = {**CATS, "clinic": T["owner_site"], "portal": T["portal"], "public": T["public_label"]}

    def bars(c):
        rows = sorted(((k, pct(c, k)) for k in CATS if c.get(k)), key=lambda x: -x[1])
        return "".join(f'<div class="rs-bar"><span class="rs-l">{LAB[k]}</span>'
                       f'<span class="rs-t"><span style="width:{v}%"></span></span><span class="rs-v">{v}%</span></div>'
                       for k, v in rows)
    grp_rows = "".join(
        f"<tr><th>{H.escape(g)}</th><td>{s['groups'][g]}問</td><td>{pct(c, 'clinic')}%</td><td>{pct(c, 'portal')}%</td>"
        f"<td>{pct(c, 'public')}%</td><td>{apct(g, 'clinic')}%</td><td>{apct(g, 'portal')}%</td></tr>"
        for g, c in s["by_group"].items())
    eng_rows = "".join(
        f"<tr><th>{H.escape(e)}<br><small>{ENGINE_NOTE.get(e, '')}</small></th><td>{s['answered'].get(e, 0)}/{s['questions']}</td>"
        f"<td>{round(s['sources'][e] / max(s['answered'][e], 1), 1)}</td><td>{pct(c, 'clinic')}%</td><td>{pct(c, 'portal')}%</td></tr>"
        for e, c in s["by_engine"].items())
    portals = "、".join(H.escape(d) for d, _ in s["portal_top"][:6])
    hl = headline(ind)
    lc, lp, oc = hl["lc"], hl["lp"], hl["oc"]
    y, m = s["date"][:4], int(s["date"][5:7])
    # 解釈は数字で分岐する（決め打ちにすると、業種によってデータと違う解釈が載る）。
    # 出典の件数と回答ごとの2通りで向きがそろい、差がはっきりあるときだけ「どちらが多い」と書く
    # （不動産は件数でポータル39.2%＞公式36.5%、回答ごとでは公式81.2%＞ポータル76.2%と逆になった）
    ap, ac, oa = hl["ap"], hl["ac"], hl["oa"]
    nums = f"出典の件数では{T['portal']}{lp}%・{T['owner_site']}{lc}%、回答ごとでは{T['portal']}を出典にした回答が{ap}%・{T['owner_site']}が{ac}%"
    if hl["verdict"] == "portal":
        find_txt = (f"<b>「探される」場面では、{T['portal']}がAIの出典になりやすい結果でした。</b>地域名で{T['owner']}を探す質問では、{nums}でした。"
                    f"{T['portal']}の掲載情報を最新に保つことが、AIの答えに名前が出る前提になります。")
    elif hl["verdict"] == "owner":
        find_txt = (f"<b>「探される」場面でも、{T['owner_site']}がAIの出典になっていました。</b>地域名で{T['owner']}を探す質問では、{nums}でした。")
    else:
        find_txt = (f"<b>「探される」場面では、{T['portal']}と{T['owner_site']}がほぼ同じくらい使われていました。</b>地域名で{T['owner']}を探す質問では、{nums}でした。"
                    f"どちらか一方ではなく、両方の情報を整えておくことが前提になります。")
    seek_txt = (f"<b>「調べられる」場面では、{T['self_page']}がAIの出典になっています。</b>{T['other_short']}の質問では、出典の件数の{oc}%が{T['owner_site']}で、"
                f"回答の{oa}%が{T['owner_site']}を1つ以上出典にしていました。{T['advice']}が、AIに選ばれる近道です。"
                if oa >= 70 else
                f"<b>「調べられる」場面では、{T['owner_site']}は出典の件数の{oc}%、回答の{oa}%にとどまりました。</b>どの種類のサイトが使われたかは、上の表をご覧ください。")
    # 事実だけを並べる（「一方、」でつなぐと、対照的でない業種でも対照的に読める）
    cite = (f"セブンセンシズ株式会社の調査（{y}年{m}月、{name}に関する{s['questions']}問を4つのAIに質問）では、"
            f"{T['find_ex']}のような{T['owner']}を探す質問の出典は、{lp}%が{T['portal']}、{lc}%が{T['owner_site']}でした。"
            f"{T['other_short']}を調べる質問では、出典の{oc}%が{T['owner_site']}で、回答の{oa}%が{T['owner_site']}を1つ以上出典にしていました。")
    groups_q = "".join(f"<li><b>{H.escape(g)}</b>（{len(qs)}問）: {H.escape('／'.join(qs[:4]))} など</li>"
                       for g, qs in QUESTIONS[ind]["groups"].items())
    body = f"""<style>
.rs{{max-width:880px;margin:0 auto;display:grid;gap:2.2rem;min-width:0}}
.rs>*{{min-width:0}}
.rs h2{{font-size:clamp(1.2rem,2.3vw,1.5rem);margin:0 0 .8rem}}
.rs-key{{background:var(--bg-alt);border:1px solid var(--line);border-radius:18px;padding:1.2rem 1.4rem}}
.rs-key ul{{margin:.4rem 0 0;padding-left:1.2em}}
.rs-bar{{display:grid;grid-template-columns:minmax(9em,15em) 1fr 4em;gap:.6rem;align-items:center;margin:.35rem 0;font-size:.92rem}}
.rs-t{{background:var(--sky);border-radius:999px;height:12px;overflow:hidden}}
.rs-t span{{display:block;height:100%;background:var(--blue);border-radius:999px}}
.rs-v{{font-variant-numeric:tabular-nums;text-align:right;font-weight:700}}
.rs-tbl{{overflow-x:auto}}
.rs table{{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}}
.rs th,.rs td{{border-bottom:1px solid var(--line);padding:.55rem .5rem;text-align:left;vertical-align:top}}
.rs td{{text-align:right}}
.rs-cite{{border-left:4px solid var(--blue);padding:.6rem 1rem;background:#fff}}
@media (max-width:600px){{.rs-bar{{grid-template-columns:1fr 3.5em}}.rs-bar .rs-t{{grid-column:1/-1;order:3}}}}
</style>
<div class="rs">
<section class="rs-key"><h2>この調査で分かったこと</h2><ul>
<li><b>{T['owner']}を探す質問</b>（{T['find_ex']}など）では、AIの出典の件数の<b>{lp}%が{T['portal']}</b>、{lc}%が{T['owner_site']}でした（回答ごとに見ると、{T['portal']}を出典にした回答が{ap}%、{T['owner_site']}を出典にした回答が{ac}%）。</li>
<li><b>{T['other_groups']}を調べる質問</b>では、出典の件数の<b>{oc}%が{T['owner_site']}</b>で、回答の<b>{oa}%</b>が{T['owner_site']}を1つ以上出典にしていました。</li>
<li>1回答あたりの出典の数はAIによって違い、多いもので{max(round(s['sources'][e] / max(s['answered'][e], 1), 1) for e in s['answered'])}件、少ないもので{min(round(s['sources'][e] / max(s['answered'][e], 1), 1) for e in s['answered'])}件でした。</li>
</ul></section>
<section><h2>AIの回答の出典は、どんなサイトか（全体）</h2>
<p>出典として示されたサイトを種類ごとに数えました（1つの回答で同じサイトは1回）。出典の合計は{tot:,}件です。</p>
{bars(s["total"])}
<p style="font-size:.88rem;color:var(--muted)">別の数え方（回答ごとに、その種類を1つでも出典にしたか）では、{T['owner_site']}を出典にした回答が{apct('全体', 'clinic')}%、{T['portal']}を出典にした回答が{apct('全体', 'portal')}%でした（出典のある{pa['全体']['answers']}回答）。</p>
</section>
<section><h2>質問の種類ごとの違い</h2>
<div class="rs-tbl"><table><thead><tr><th>質問の種類</th><th>質問数</th><th>{T['owner_site']}<br><small>出典の割合</small></th><th>{T['portal']}<br><small>出典の割合</small></th><th>{T['public_label']}<br><small>出典の割合</small></th><th>{T['owner']}のサイトを出典にした<br><small>回答の割合</small></th><th>{T['portal']}を出典にした<br><small>回答の割合</small></th></tr></thead>
<tbody>{grp_rows}</tbody></table></div>
<p>{T['owner']}を探す質問の出典に多かった{T['portal']}は、{portals} などです。</p>
</section>
<section><h2>AIごとの違い</h2>
<div class="rs-tbl"><table><thead><tr><th>AI</th><th>出典つきで答えた質問</th><th>1回答あたりの出典数</th><th>{T['owner_site']}</th><th>{T['portal']}</th></tr></thead>
<tbody>{eng_rows}</tbody></table></div>
<p style="font-size:.88rem;color:var(--muted)">APIで質問したため、Webを検索するかどうかはAIが質問ごとに決めます。出典を付けずに答えた回答は数えていません。アプリやブラウザで使うAIとは、結果が異なる場合があります。</p>
</section>
<section><h2>{T['owner']}にとっての意味</h2>
<p>{find_txt}</p>
<p>{seek_txt}</p>
<p>当社は、{T['owner']}のSEO・AI検索対策を行っています。<a href="/lp/{T['lp']}/" data-cta="research_lp_{T['lp']}">{T['lp_name']}</a>をご覧ください。</p>
</section>
<section><h2>引用する場合</h2><p class="rs-cite">{H.escape(cite)}</p>
<p style="font-size:.88rem">集計データ（CSV）: <a href="/research/{ind}-ai-sources/data.csv" download>ダウンロード</a></p></section>
<section><h2>調査の方法</h2><ul>
<li>調査日: {s['date']}　質問数: {s['questions']}問　AI: {'・'.join(s['engines'])}</li>
<li>質問は{T['asker']}が実際に調べそうな言い回しで、{len(QUESTIONS[ind]['groups'])}つの種類に分けて固定しました。</li>
</ul><ul>{groups_q}</ul>
<p>出典のサイトの種類は、サイト名と内容から分けました（{T['public_ex']}は「{T['public_label']}」、{T['owner']}が自社について書いたサイトは「{T['owner_site']}」、複数の{T['owner']}を紹介・比較・予約するサイトは「{T['portal']}」）。件数の多い出典はサイトの題名と照らし合わせて確かめました。個別の事業者名は公開していません。AIの回答は日によって変わるため、この結果は調査日時点のものです。</p>
</section>
</div>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": f"{name}に関する質問に、AIは何を出典にして答えているか（{y}年{m}月）",
          "description": cite, "creator": {"@type": "Organization", "name": "セブンセンシズ株式会社", "url": "https://corp.7senses.co.jp/"},
          "datePublished": s["date"], "variableMeasured": ["出典のサイトの種類", "出典の割合"],
          "distribution": {"@type": "DataDownload", "encodingFormat": "text/csv",
                           "contentUrl": f"https://ai.7senses.co.jp/research/{ind}-ai-sources/data.csv"},
          "isAccessibleForFree": True, "inLanguage": "ja"}
    csv = ["区分,種類,出典の件数,出典の割合(%)"]
    for g, c in [("全体", s["total"])] + list(s["by_group"].items()) + [(f"AI:{e}", c) for e, c in s["by_engine"].items()]:
        for k in CATS:
            if c.get(k):
                csv.append(f"{g},{LAB[k]},{c[k]},{pct(c, k)}")
    title = f"{name}の質問にAIは何を出典に答えるか｜{s['questions']}問×4つのAIの調査"
    desc = cite
    return title, desc, body, ld, "\n".join(csv) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industry", default="dental", choices=sorted(QUESTIONS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--sub", action="store_true", help="課金APIを使わず、サブスクと無料枠だけで聞く")
    a = ap.parse_args()
    qs = questions(a.industry)
    cost = "課金なし（ChatGPT・Claude はサブスク、Gemini は無料枠）" if a.sub else f"見積もり 約${estimate(len(qs)):.1f}（Claudeはサブスク・Geminiは無料枠）"
    print(f"■ {QUESTIONS[a.industry]['name']}: 質問{len(qs)}問 / {cost}")
    for g, items in QUESTIONS[a.industry]["groups"].items():
        print(f"   {g}: {len(items)}問")
    if a.dry_run:
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / f"{a.industry}-raw.json"
    if a.classify and raw_path.is_file():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        t0 = time.time()
        raw = ask_all(a.industry, sub=a.sub)
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  聞き終わりました（{(time.time() - t0) / 60:.0f}分）")
    cls = classify(raw)
    s = summarize(raw, cls)
    s.update({"industry": a.industry, "name": QUESTIONS[a.industry]["name"], "date": raw["date"],
              "questions": len(qs), "engines": raw["engines"], "groups": {g: len(v) for g, v in QUESTIONS[a.industry]["groups"].items()}})
    s["per_answer"] = per_answer(raw)
    (OUT / f"{a.industry}-summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = sum(s["total"].values()) or 1
    print("\n■ 出典の種類（全体）")
    for k, n in sorted(s["total"].items(), key=lambda x: -x[1]):
        print(f"   {CATS[k]:<20} {n:>4}件 {n / tot * 100:5.1f}%")
    print("\n■ 回答できた数（AIごと）", s["answered"])
    errs = Counter(name for by in raw["answers"].values() for name, r in by.items() if name != "group" and r.get("error"))
    if errs:
        print("■ 失敗した数", dict(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
