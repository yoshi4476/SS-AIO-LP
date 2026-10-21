# -*- coding: utf-8 -*-
"""Phase 5 機械採点（LLM採点の前に走らせる決定的チェック）

数えられる項目はLLMに採点させず、このスクリプトが白黒つける。
全PASSになってから3観点（一次性・抽出性・決定支援）の採点に進むこと。基準は scripts/rubric.py。

使い方: python scripts/score_check.py <slug>
終了コード: 0=全PASS / 1=FAILあり
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _link_patterns():
    """全サイト（sites/*.json）のカテゴリ・ドメインから内部リンク判定パターンを組み立てる。

    新しいサイト（例: corporate）の1本目の記事は自サイトに公開済み記事がまだ無いため、
    姉妹サイト（同じ会社の別サイト）への絶対URLリンクも内部リンクとして扱う。
    """
    cats, domains, prefixes = set(), set(), set()
    for cfg in sites_mod.load_all().values():
        cats.update(cfg.get("categories", {}).keys())
        domains.add(cfg["domain"])
        if cfg.get("url_prefix"):
            prefixes.add(cfg["url_prefix"].strip("/"))
    cat_pat = "|".join(re.escape(c) for c in sorted(cats))
    domain_pat = "|".join(re.escape(d) for d in sorted(domains))
    # url_prefix型サイト（corporate/subsidy）の実URLは /blog/{slug}/ のようにカテゴリを含まないため、
    # カテゴリパスとprefixパスの両方を内部リンクとして認識する（前者だけだと自サイトへのリンクが
    # 一切カウントされず、姉妹サイトへのリンクしか通らないという誤検出になる）。
    prefix_pat = "|".join(re.escape(p) for p in sorted(prefixes))
    path_pat = "|".join(p for p in (cat_pat, prefix_pat) if p)
    internal_re = re.compile(
        rf"\]\((?:https?://(?:{domain_pat}))?(/(?:{path_pat})/[^)]+)\)")
    return internal_re, domains


def internal_links(body):
    """内部リンク先の集合。相対・絶対URL・末尾スラッシュ無し・#付きは同じ1本"""
    return {u.split("#")[0].rstrip("/") for u in _link_patterns()[0].findall(body)}


DECOR_YEAR = re.compile(r"【[^】]*20\d{2}[^】]*】|20\d{2}年?最新")
DECOR_YEAR_FROM = "2026-10-05"


# 年を表す数字（2026年・2023-01・2026/09・単独の2026）。一次情報の目印に数えない
_YEAR = re.compile(r"(?:19|20)\d\d")
# 件数・金額などの単位。年の形の数字でも、これが続けば件数（「2034件」）として目印に残す
_UNIT = tuple("件社店本人名回個円万億%％倍字語秒台枚")


def fact_tokens(claim, strict=False):
    """一次情報（first_party_facts.json の claim）のうち、本文にあれば「その事実を使った」とみなす目印。

    3桁以上の数字をそのまま目印にしていたため、claim の期間（2023年5月〜2026年9月）の年が、鮮度の表記
    （「2026年10月時点」）を持つどの記事にも当たり、一次情報の検査が全記事で通っていた（2026-10-20）。
    年の形の数字は単位が続くときだけ残す。社名・立場の語は従来どおり。

    strict（FACTS_FROM 以降の記事の判定）: 区切りの無い3桁の数字（「100」「196」）は、claim で単位が続くときだけ
    「数字＋単位」（「196本」「100%」）を目印にする。数字だけでは「100万円」「150字」のような別の話に当たる"""
    toks = []
    for m in re.finditer(r"[0-9][0-9,]{2,}", claim):
        num = m.group(0).rstrip(",")
        unit = claim[m.end():m.end() + 1]
        if _YEAR.fullmatch(num) and not unit.startswith(_UNIT):
            continue
        if strict and re.fullmatch(r"[0-9]{3}", num):
            if not (unit and unit in _UNIT):
                continue
            num += unit
        toks.append(num)
    if strict:
        # 「」で括った名前（サービス名・その社の言い回し）。お客様の事実は年数・社数のような小さな数字が多く、
        # 数字だけでは1つも目印が作れなかった（2026-10-20 にお客様の社の4件で0個）
        toks += [q for q in re.findall(r"「([^「」\n]{4,40})」", claim)]
    toks += re.findall(r"G-ran|セブンセンシズ|大阪市東成区", claim)
    toks += [t for t in ("登録支援事業者", "当社は自社サイト", "自社メディア",
                         "支援の現場", "申請の現場", "導入支援", "支援する現場",
                         "会計ソフト", "受発注ソフト") if t in claim]
    return toks


# この日以降の記事は、一次情報をその社が使ってよい事実（facts.load_for）だけで確かめる（2026-10-20 の点検）。
# 全社の事実の、社名・所在地まで目印にしていたため、お客様の記事は当社の実績で、自社の記事は社名だけで通っていた。
# 公開済みの記事は今の判定のまま（DECOR_YEAR_FROM と同じく、決まりを入れた後の記事だけを止める）
FACTS_FROM = "2026-10-21"


def site_fact_marks(sid, cfg=None):
    """その社の記事で「一次情報を使った」とみなす目印 {事実の id: [目印]}。

    お客様の社は非公開の facts.json だけ、自社は自分のサイトに許した事実だけ（facts.load_for）。
    当社の名前・所在地（sites.OPERATOR_MARKS）とその社に許した当社の表記（operator_ok）は、事実ではなく名前なので
    目印にしない（数字の目印は残す）"""
    if not sid:
        return {}
    import facts
    _, got = facts.load_for(sid)
    names = [m for m in (*sites_mod.OPERATOR_MARKS, *((cfg or {}).get("operator_ok") or [])) if m]
    out = {}
    for f in got:
        toks = [t for t in fact_tokens(str(f.get("claim") or ""), strict=True)
                if re.search(r"[0-9]", t) or not any(n in t or t in n for n in names)]
        out[str(f.get("id") or "")] = toks
    return out


def _has(tok, body):
    return tok in body or tok.replace("%", "％") in body


# 抽出性: AI 検索は段落の単位で切り出す。前を読まないと何の話か分からない書き出しは引用されない（別工程の採点の
# 指摘「『4つのうち、最初に…』は前の表を見ないと4つが何か分からない」2026-10-20）
LONE = re.compile(r"^(?:\*\*)?(?:これ|それ|あれ|この|その|あの|こう|そう|こちら|そちら|ここ|そこ|上記|前述|後述|同様に|"
                  r"[0-9０-９一二三四五六七八九十]+つ(?:のうち|とも|目)|起きるのは|理由は|答えは|結論は|ポイントは)")
# 決定支援: 「◯◯なら A」の分かれ目・やらない判断・今日の一歩（採点の基準 rubric の 80〜100点の条件）
BRANCH = re.compile(r"(?:なら|場合は|ときは|会社は|方は)[、]?[^。\n]{0,40}?"
                    r"(?:向いて|選んで|選ぶ|選びます|任せ|依頼|頼|始め|優先|使って|使います|検討して|外注|内製|整えて|進めて|"
                    r"ください|しましょう|ほうが|方が|がよい|が早い|が先)")
SKIP = re.compile(r"(?:向かない|向いていない|向きません|見送|見合わせ|やめ(?:た|る)(?:方|ほう)|不要です|必要ありません|"
                  r"しなくてよい|任せない|頼まない|やらない|待った(?:方|ほう)|急がな|まだ早い|後回し|避けて|しない(?:方|ほう)が)")
STEP = re.compile(r"(?:今日|まず|最初に|手始めに|今週)[^。\n]{0,40}?(?:してください|しましょう|ください|確かめ|決め|書き出|用意|"
                  r"集め|開いて|見直)")


# 本文の途中で前を指す語（採点の指摘: 「前者」「どちら」「両方ともはいなら」「この20日」）
POINT = re.compile(r"^(?:\*\*)?(?:これ|それ|この|その|上記|前述|両方|どちら|前者|後者)|前者|後者")
# 採点で何度も「前の段落を読まないと分からない」と名指しされた言い方（2026-10-21 の CI の記録:「以下は、この不動産会社の…」
# 「4つ目の状況に近く」「両方ともはいなら」「ここを取り違えると」「上の図のとおり」）。段落の書き出しと文の中で拾う
# 「上の表」「上の図」は拾わない。優先の決まり（「上の表で2つ以上に当てはまるときは…を先に」）が表を指す文を求めるので、
# 両方の検査が食い違い、別の工程の採点で90点の記事を配信の前に止めた（2026-10-21 bpo-jimu-wakekata）
POINT_MORE = re.compile(r"^(?:\*\*)?(?:以下は|ここ[をがは]|そこ[をがは])")   # 「そこで」「ここで」は接続なので拾わない
POINT_ANY = re.compile(r"前者|後者|[0-9０-９一二三四五六]つ目の(?:状況|条件|場合|問い|型)|両方とも")
# 採点の観点の検査（score_check では警告。auto_rewrite・agent_guard・publish_flow もこの一覧で止めない）
SOFT = ("前の文を読まないと分からない文が無い", "仮の計算例がある", "決定支援:", "抽出の単位", "H2直下の1文が単体で通じる")
HYPO = re.compile(r"(?:仮に|例えば|たとえば)[^。\n]{0,80}?\d")


def pointing_sentences(body, limit=6):
    """前の文を読まないと分からない文（段落の書き出し、または「前者」「後者」を含む文）。直しの指示に名指しする"""
    out = []
    for h, sec in _core_sections(body):
        for para in re.split(r"\n\s*\n", sec):
            para = re.sub(r"<[^>]+>", "", para).strip()
            if not para or para.startswith(("|", "#", "!", "-", "<")):
                continue
            for i, sent in enumerate(re.split(r"(?<=。)", para)):
                sent = sent.strip()
                if sent and (i == 0 and (POINT.match(sent) or POINT_MORE.match(sent)) or POINT_ANY.search(sent)):
                    out.append(sent[:60])
    return out[:limit]


def _core_sections(body):
    """FAQ・まとめを除く H2 の節（見出し, 本文）"""
    parts = re.split(r"^## (.+)$", body, flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)
            if not re.search(r"よくある質問|FAQ", parts[i]) and not parts[i].startswith("まとめ")]


def extract_issues(body):
    """抽出性の単位（冒頭200字・各H2直下の1文・FAQ の答え）のうち、単体で切り出すと何の話か分からない書き出し。
    採点の基準（rubric の抽出性100点）が名指しする単位を全部見る（2026-10-21。見出し直下だけを見ていた）"""
    out = []
    lead = next((x.strip() for x in body.splitlines() if x.strip() and not x.lstrip().startswith(("<", "#", "!", "|"))), "")
    if LONE.match(lead) or POINT.match(lead):
        out.append("冒頭")
    for h, sec in _core_sections(body):
        first = next((x.strip() for x in sec.splitlines() if x.strip() and not x.lstrip().startswith(("<!--", "!["))), "")
        if LONE.match(re.sub(r"^<[^>]+>", "", first)):
            out.append(h[:30])
    for q, a_ in re.findall(r"<summary>(.*?)</summary>\s*<p[^>]*>(.*?)</p>", body, re.S):
        if LONE.match(re.sub(r"<[^>]+>", "", a_).strip()) or POINT.match(re.sub(r"<[^>]+>", "", a_).strip()):
            out.append("FAQ: " + re.sub(r"<[^>]+>", "", q)[:24])
    return out


SCOPE = re.compile(r"含み|含む|含め|のうち|集計|時点|期間|に限|だけで|ではありません")
FAQ_NUM = re.compile(r"\d[\d,.]*\s*(?:件|社|店舗|%|か月|位)")


def faq_scope_issues(body):
    """FAQ の答えに数字があるのに、本文で同じ数字に付けた条件（母数・期間・「わずかな上昇も含む」）が答えから落ちているもの。
    採点で「答えが単独で出ると実際より強く読める」と何度も減点された（2026-10-21）"""
    out = []
    main = re.split(r"^## .*(?:よくある質問|FAQ).*$", body, maxsplit=1, flags=re.M)[0]
    paras = [re.sub(r"<[^>]+>", "", p) for p in re.split(r"\n\s*\n", main)]
    for q, a_ in re.findall(r"<summary>(.*?)</summary>\s*<p[^>]*>(.*?)</p>", body, re.S):
        a = re.sub(r"<[^>]+>", "", a_)
        if SCOPE.search(a):
            continue
        for n in dict.fromkeys(m.group(0).replace(" ", "") for m in FAQ_NUM.finditer(a)):
            if any(n in p.replace(" ", "") and SCOPE.search(p) for p in paras):
                out.append(f"{re.sub(r'<[^>]+>', '', q)[:24]}（{n}）")
                break
    return out


# 採点の決定支援で85〜90点に止まった記事の指摘（2026-10-21 の CI）: 費用の幅が広すぎる・条件が重なったときの優先が無い・
# 業者の選び方を別の記事に任せている。外注・サービスを選ぶ題（OUTSOURCE）では相場の額と業者に聞く質問を求める
OUTSOURCE = re.compile(r"外注|代行|依頼|業者|会社選び|選び方|サービス|コンサル|費用|相場|頼む|任せ|代理店")
PRIORITY = re.compile(r"(?:複数|2つ以上|二つ以上|いくつか|両方|重なる|重なった)[^。\n]{0,25}?(?:当てはま|該当|重な)[^。\n]{0,40}?"
                      r"(?:先に|優先|から始め|を選)|優先(?:順位|順|する)")
PRICE = re.compile(r"相場[^。\n]{0,40}?\d[\d,.]*\s*(?:〜\s*\d[\d,.]*\s*)?万円|\d[\d,.]*\s*万円[^。\n]{0,30}?相場")
ASK = re.compile(r"(?:業者|依頼先|外注先|会社|代理店|担当者|コンサル)(?:に|へ)[^。\n]{0,12}?(?:聞く|聞き|聞いて|確認する|確かめる|尋ね)"
                 r"|(?:聞く|確認する|確かめる)(?:べき)?(?:質問|項目)")


def decision_issues(body, topic=""):
    """決定支援で足りないもの（空なら足りている）。topic は題と狙う語（外注・サービスを選ぶ題かを見る）"""
    text = re.sub(r"<[^>]+>", "", body)
    out = []
    if len(BRANCH.findall(text)) < 2:
        out.append("「◯◯なら A」の条件の分かれ目が2つ未満")
    if not SKIP.search(text):
        out.append("やらない判断（向かない・見送る条件）が無い")
    if not STEP.search(text):
        out.append("今日できる一歩（まず◯◯してください）が無い")
    if not PRIORITY.search(text):
        out.append("条件が重なったときの優先（「2つ以上に当てはまるなら◯◯を先に」）が無い")
    if OUTSOURCE.search(topic):
        if not PRICE.search(text):
            out.append("費用の目安が無い（一次情報の「相場」の額を、相場として書く）")
        if not ASK.search(text):
            out.append("業者に聞く質問のひな形が無い（別の記事に任せず、聞く質問を3つほど記事の中に置く）")
    return out


def run(slug, path=None):
    """1本を採点して checks を返す。CLI からも、全体の集計からも使う。path は原稿の場所（既定は articles/<slug>.md）"""
    p = Path(path) if path else ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"articles/{slug}.md が見つかりません")
    text = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise SystemExit(f"articles/{slug}.md にフロントマターがありません")
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    # コードブロック内はH2・文言カウントの対象外（プロンプト例の ## 等を誤検出しない）
    body_nc = re.sub(r"```.*?```", "", body, flags=re.S)

    # 読者が読む文字だけを数える。build.py と同じ数え方にそろえる。
    # 見出しの # や表の | まで数えていたため、採点は5,251字で通ったのに
    # ビルドは4,922字で警告する、という食い違いが起きていた。
    # その結果、24本が基準の直下（4,844〜4,998字）に並んだ。
    try:
        import md2html
        plain = re.sub(r"\s|<[^>]+>", "", md2html.convert(body)[0])
    except Exception:
        plain = re.sub(r"\s|<[^>]+>", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body))
    checks = []

    def add(name, ok, detail, warn=False):
        # warn=True は「直したいが公開は止めない」項目。
        # 読みやすさは基準を厳しくすると毎回落ちて記事が出なくなるため、
        # 公開はさせたうえで日次監査に拾わせ、あとから直す方針にする。
        checks.append((name, ok, detail, warn))

    # --- 量・装飾 ---
    # 全記事が5,000〜6,000字に収まると、それ自体が量産の指紋になる（実測で50本が680字幅に集中）。
    # 検索意図で必要な深さは変わるため、下限は意図別に持ち、上限は設けない。
    # depth: quick=手順や定義の確認（3,000字〜）/ standard=比較検討（5,000字〜）/ deep=網羅（8,000字〜）
    _depth = (meta.get("depth") or "standard").strip()
    _min = {"quick": 3000, "standard": 5000, "deep": 8000}.get(_depth, 5000)
    add(f"本文{_min:,}字以上（depth: {_depth}）", len(plain) >= _min,
        f"{len(plain):,}字")
    markers = len(re.findall(r"\*\*[^*]+\*\*", body)) + len(re.findall(r"==[^=]+==", body))
    add("強調12〜18箇所（最低8）", markers >= 8, f"{markers}箇所" + ("（推奨帯外）" if not 12 <= markers <= 18 else ""))

    # --- AIO構造 ---
    first_para = next((ln for ln in body.splitlines() if ln.strip() and not ln.startswith(("<", "#"))), "")
    add("冒頭が断言型（**で開始・80字以上）", first_para.startswith("**") and len(first_para) >= 80,
        f"{len(first_para)}字")
    add("対象読者の限定文言", 'class="target-reader"' in body, "target-reader div")
    add("鮮度表記（◯年◯月時点）", bool(re.search(r"\d{4}年\d{1,2}月時点", body)), "")
    add("定義ブロック", 'class="definition-box"' in body, "definition-box div")
    add("比較テーブルあり", bool(re.search(r"^\|.+\|\s*$", body, re.M)), "")
    add("失敗例・注意点セクション", bool(re.search(r"caution-box|失敗|NG|注意点", body)), "")

    # --- H2構造 ---
    h2s = re.findall(r"^## (.+)$", body_nc, re.M)
    core_h2 = [h for h in h2s if "よくある質問" not in h and not h.startswith("まとめ")]
    add("H2が6〜12個（FAQ・まとめ除く）", 6 <= len(core_h2) <= 12, f"{len(core_h2)}個")
    bad_lead = []
    lines = body_nc.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and "よくある質問" not in ln:
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            # 記号+空白のリスト/表のみを検出（**太字**始まりの1文結論を誤検出しない）
            if nxt.startswith(("| ", "|-", "- ", "* ", "<figure", "<div", "```", "#", "1. ")):
                bad_lead.append(ln[3:])
    add("全H2直下がリード文（表・リスト直置きなし）", not bad_lead, "、".join(bad_lead[:3]))
    lone = extract_issues(body_nc)
    add("抽出の単位（冒頭・H2直下の1文・FAQ の答え）が単体で通じる（「これ」「その」「◯つのうち」「起きるのは」で始めない）", not lone,
        "、".join(lone[:3]))
    miss = decision_issues(body_nc, f"{meta.get('title') or ''} {meta.get('keyword') or ''}")
    add("決定支援: 条件の分かれ目2つ以上・やらない判断・今日できる一歩・重なったときの優先がある（外注・サービスの題は相場の額と業者に聞く質問も）", not miss, "、".join(miss))
    pointing = pointing_sentences(body_nc)
    add("前の文を読まないと分からない文が無い（「前者」「後者」「どちら」「両方」「以下は」「◯つ目の状況」「ここを」で前を指さない）",
        not pointing, "、".join(pointing[:2]))
    scope = faq_scope_issues(body_nc)
    # warn=True を付け忘れて FAIL になり、89点の記事の直しを丸ごと捨てた（2026-10-21 の CI）。公開も直しも止めない警告
    add("［警告］FAQ の答えの数字に、本文と同じ条件（母数・期間・含むもの）を書く", not scope, "、".join(scope[:2]), warn=True)
    add("仮の計算例がある（「仮に◯◯なら」で読者が自分の数字を当てはめられる）",
        bool(HYPO.search(re.sub(r"<[^>]+>", "", body_nc))), "")

    # --- タイトル ---
    # 飾りの年号（【2026年最新】【2026年】）は自社GSCの実測でクリック率が負けた型（title_patterns）。
    # 「2024年問題」「2026年の変更点」のように中身として要る年は止めない。
    # 既存の32本は auto_rewrite がタイトルを直すときに外す（一斉に変えると順位の揺れが読めない）。
    # ここでは決まりを入れた日以降の記事だけを止める
    if str(meta.get("date", "")) >= DECOR_YEAR_FROM:
        deco = DECOR_YEAR.search(str(meta.get("title", "")))
        add("タイトルに飾りの年号を入れない", not deco, deco.group(0) if deco else "")

    # 字数は build.py の quality_checks（15〜45字）と同じ数え方。build.py は警告で、採点では見ていなかったので
    # 範囲外の題も採点を通って配信まで進んだ（2026-10-20 の点検。入れた時点で範囲外は0本）
    tl = len(str(meta.get("title") or ""))
    add("タイトル15〜45字", 15 <= tl <= 45, f"{tl}字")

    # --- 説明文 ---
    # 60字で通していたら Bing Webmaster Tools に「短すぎる」と54ページ指摘された（2026-10-05）。
    # 日本語は1字の情報量が多く、Google の表示も120字前後で切れるので100〜150字を目標、160字を上限にする
    import desc_fill as DF
    dl = len(str(meta.get("description") or ""))
    add(f"説明文{DF.MIN}〜{DF.GATE_MAX}字（目標{DF.MIN}〜{DF.MAX}字）", DF.MIN <= dl <= DF.GATE_MAX, f"{dl}字")

    # --- FAQ ---
    faq = meta.get("faq") or []
    add("FAQ 5問以上", len(faq) >= 5, f"{len(faq)}問")
    bad_a = [f["q"][:12] for f in faq if not 30 <= len(f["a"]) <= 75]
    add("FAQ回答が40〜60字目安（許容30〜75）", not bad_a, "、".join(bad_a[:3]))
    body_faq = body.count("<details>")
    add("本文FAQとfrontmatter数が一致", body_faq == len(faq), f"本文{body_faq} / meta{len(faq)}")

    # --- リンク ---
    own_domains = _link_patterns()[1]
    internal = internal_links(body)
    add("内部リンク3本以上", len(internal) >= 3, f"{len(internal)}本")
    external = set(re.findall(r'href="(https?://[^"]+)"', body))
    external = {u for u in external if not any(d in u for d in own_domains) and "x.com" not in u}
    add("外部権威リンク（出典）2本以上", len(external) >= 2, f"{len(external)}本")

    # --- 読みやすさ ---
    # CLAUDE.md の「段落3行 or 150字以内」「1文50字以下」は規定だけあって検査がなく、
    # 300字を超える段落がそのまま公開されていた。画面では改行のない壁のような塊に見える。
    paras = [p.strip() for p in re.split(r"\n\s*\n", body_nc)
             if p.strip() and not p.strip().startswith(("#", "-", "*", "|", "<", ">", "```", "1."))]
    # HTMLタグとURLは読者が読む文字ではないので、数える前に落とす。
    # 落とさないと <a href="…長いURL…"> が1文としてカウントされ、誤検出になる
    def _plain(p):
        p = re.sub(r"<[^>]+>", "", p)                       # タグを除去
        p = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", p)      # Markdownリンクは表示文だけ残す
        return re.sub(r"[*_=`]", "", p)

    # 表・箇条書き・コードは「文」ではない。1行ずつ読むものなので、
    # 塊のまま1文として数えると長文の誤検出になる（191字の表が挙がった）
    def _is_prose(p):
        s = p.strip()
        return not (s.startswith(("|", "-", "*", ">", "#", "```"))
                    or "|:--" in s)

    # 段落の途中に番号リストが混ざると、塊ごと1文として数えられる（実測306字）。
    # 段落の先頭だけを見る _is_prose では拾えないため、行単位でも落とす
    def _drop_list_lines(p):
        keep = [ln for ln in p.split("\n")
                if not re.match(r"\s*(?:[0-9０-９]+[.．、)）]|[-*+]\s|\||>)", ln)]
        return "\n".join(keep).strip()

    plain_paras = [x for x in (_plain(_drop_list_lines(p))
                               for p in paras if _is_prose(p)) if x]
    # 基準は「読者が壁に感じる塊」を潰すことに絞る。完璧な短文化を求めると
    # 毎回落ちて公開が止まるため、実害の大きい超過だけを不合格にする。
    long_paras = [p for p in plain_paras if len(p) > 200]
    # どこを直せばよいか分かるよう、該当箇所の冒頭を示す（指摘が抽象的だと直せない）
    add("［警告］段落が200字以内（規定150字＋余裕）", not long_paras,
        (f"{len(long_paras)}箇所が超過（最長{max((len(p) for p in long_paras), default=0)}字）"
         + f" 例:「{long_paras[0][:32]}…」" if long_paras
         else f"最長{max((len(p) for p in plain_paras), default=0)}字"), warn=True)

    sentences = [s.strip() for p in plain_paras for s in re.split(r"(?<=[。！？])", p) if s.strip()]
    long_sents = [s for s in sentences if len(s) > 70]
    runaway = [s for s in sentences if len(s) > 100]   # 100字超は一息で読めない
    limit = max(4, int(len(sentences) * 0.12))   # 4文までは許容する
    worst = max(sentences, key=len) if sentences else ""
    add("［警告］長文が1割強以内・100字超はゼロ（規定50字）", len(long_sents) <= limit and not runaway,
        f"70字超{len(long_sents)}/{len(sentences)}文（上限{limit}）"
        + (f"・100字超{len(runaway)}文" if runaway else "")
        + (f" 例:「{worst[:32]}…」({len(worst)}字)" if len(long_sents) > limit or runaway else ""),
        warn=True)

    # --- 一次情報（量産の唯一の防波堤）---
    # 月180本の規模では、外部統計の引き写しだけの記事はスケーラブルコンテンツ濫用と
    # 判定されうる。「自社でしか出せない事実」が入っているかを機械で担保する。
    import json as _json
    _fp = ROOT / "data" / "first_party_facts.json"
    own_hit = []
    try:
        _fsid = sites_mod.find_category_owner(str(meta.get("category") or "")) if meta.get("category") else None
    except SystemExit:
        _fsid = None
    if str(meta.get("date", "")) >= FACTS_FROM:
        for fid, toks in site_fact_marks(_fsid, sites_mod.load_all().get(_fsid) if _fsid else None).items():
            if any(_has(t, body) for t in toks):
                own_hit.append(fid)
    elif _fp.is_file():
        for f in _json.loads(_fp.read_text(encoding="utf-8")).get("facts", []):
            # 主張そのものの一致ではなく、固有の数値・名称が本文にあるかで見る
            # 数値・社名だけを見ていたため、「登録支援事業者として支援している」のような
            # 立場の記述を一次情報と認めていなかった。自社しか書けない表現も拾う。
            for tok in fact_tokens(f["claim"]):
                if tok in body:
                    own_hit.append(f["id"])
                    break
    add("自社の一次情報が1つ以上ある", bool(own_hit), "、".join(sorted(set(own_hit))) or "自社実績・自社実測が本文にありません")

    # --- 人間味 ---
    first_person = len(re.findall(r"私たち|私も|私は|私が|当社|弊社", body_nc))
    add("一人称の体験・観察2箇所以上", first_person >= 2, f"{first_person}箇所")
    # オリジナルとして認められるか（originality.py）。出どころの無い体験談の決まり文句は止める
    # （作り話になりうるうえ、同じ文句が多くの記事に並ぶと量産の指紋になる。2026-10-19 に164本で見つかった）
    import originality
    try:
        _sid = sites_mod.find_category_owner(str(meta.get("category") or "")) if meta.get("category") else None
    except SystemExit:
        _sid = None
    stock = originality.stock_phrases(body, _sid)
    add("出どころの無い体験談の決まり文句ゼロ（体験は data/experiences.json の登録から書く）", not stock,
        "、".join(f"「{w}」" for _, w in stock[:3]) or "なし")
    gain = originality.info_gain(_sid, meta.get("keyword"), core_h2)
    if gain is None:
        add("検索上位の見出しに無い節が2つ以上", False, "上位の見出しのデータが無いため確かめていません", warn=True)
    else:
        add("検索上位の見出しに無い節が2つ以上", gain[0] >= originality.MIN_NOVEL,
            f"{gain[0]}/{gain[1]}節（上位{gain[2]}ページと比べた）")
    koreni = body_nc.count("これにより")
    add("「これにより」ゼロ", koreni == 0, f"{koreni}回")
    juyou = body_nc.count("重要です")
    add("「重要です」3回以下", juyou <= 3, f"{juyou}回")

    # お客様の「使ってはいけない表現」（ヒアリングシート → sites/<id>.json の rules.ng_words）。
    # 配信の門（publish.py）だけで止めていたため、採点も承認も通った記事が配信で静かに止まり、
    # 未配信のまま残った（2026-10-09 お客様の社「必ず」）。書く段で見つけて直させる
    try:
        sid = sites_mod.find_category_owner(str(meta.get("category") or ""))
        site_cfg = sites_mod.load_all().get(sid) or {}
        ng = (site_cfg.get("rules") or {}).get("ng_words") or []
    except SystemExit:
        site_cfg, ng = {}, []
    hay = f"{meta.get('title', '')}{meta.get('description', '')}{body}"
    hit = [w for w in ng if w and w in hay]
    add("お客様の使えない表現（rules.ng_words）が無い", not hit, "、".join(hit) or "なし")

    # 入れてはいけない HTML（ld+json 以外の script・on 属性・iframe・外部への form・javascript: の URL・自動の転送）。
    # 外の文章（字幕・上位の見出し）の指示に従った AI が入れうる。build.py・publish.py と同じ判定（html_safety）を書く段で当てる
    import html_safety
    danger = html_safety.article_problems(meta, body, [site_cfg.get("domain")], raw=site_cfg.get("type") == "external-md")
    add("入れてはいけない HTML が無い（script・on 属性・iframe・外部への form・javascript:）", not danger,
        html_safety.describe(danger, sample=not site_cfg.get("client")) if danger else "なし")

    # 採点の観点の検査（前を指す文・決定支援・抽出の単位・仮の計算例）は警告にする。別の工程の採点が同じ観点を見ており、
    # 書く段階で止めると二重に止まった（2026-10-21 運用者「かなりではなく少し厳しいに」）。直しの指示には名指しで渡る
    return [(n, ok, d, w or n.startswith(SOFT)) for n, ok, d, w in checks]


def main():
    checks = run(sys.argv[1])
    # 警告（warn=True）は公開を止めない。記事が出ないほうが損失が大きいため
    fails = [c for c in checks if not c[1] and not c[3]]
    warns = [c for c in checks if not c[1] and c[3]]
    for name, ok, detail, warn in checks:
        mark = "PASS" if ok else ("WARN" if warn else "FAIL")
        print(f"{mark} | {name}" + (f" | {detail}" if detail else ""))
    hard = [c for c in checks if not c[3]]
    print(f"\n機械採点: {len(hard) - len(fails)}/{len(hard)} PASS"
          + (f" / 警告{len(warns)}件（公開は可能。日次監査で順次直します）" if warns else "")
          + ("" if not fails else " → FAILを修正してからLLM採点に進むこと"))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
