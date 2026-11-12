# -*- coding: utf-8 -*-
"""手で書いた固定ページ（トップ・よくある質問・サービス・会社概要）の数字を、本番から取って台帳と照らす（月初の monthly-report.yml）。

記事の数字は facts.py・add_fact・legal_claims などの門で確かめているが、固定ページは対象外だった。補助金LPのトップの
よくある質問に、公募要領に無い「売上が法人3,300万円・個人事業主3,900万円以上」「決算2期」が残っていた（2026-11-12 に手で直した）。

照らす台帳（既にあるものを読む。固定ページにしか無い外部の統計と例だけ fixed_page_facts.json）:
  制度   .claude/skills/subsidy-advisor/references/program-status.md の表（直した誤りを書いた括弧の中は数えない）
  終了   tests/test_gates.py の RETIRED_PROGRAMS と自社の sites/<id>.json の ng_terms
  実績   data/first_party_facts.json・data/public_facts.json・data/voices.json（お客様の声）・
         data/datasets/*.json（公開している一次データ）。
         お客様の社は非公開の clients/<id>/facts.json と company.json だけ
         （運用会社の実績でお客様の数字を通さない）
  調査   当社の調査の集計から、ページを作る関数（industry_ai_sources・subsidy/research）で毎回計算した値。
         調査は作り直すたびに数字が変わるので、台帳に書き写さない。書き方（小数の桁）まで同じものだけ通す
  外部・例  data/fixed_page_facts.json（一次情報で確かめた外部の統計と、モデルケース。words がページにあるときだけ。
         例は式が文の数と合うものだけ）

見つけるもの:
  台帳と食い違う  制度名と「上限・最大・補助率・枠」がある文の金額・率が、その制度の行に無い
  台帳に無い要件  補助金の文の「売上・決算・資本金・従業員…以上/未満」の数が、制度の行に無い
  終わった制度    受付の終わった制度を、終わったと書かずに載せている
  台帳に無い数字  どの台帳にも無い数（誤りとは限らない。情報として並べ、FIXED_FACTS_OK は変えない）

    python scripts/fixed_facts.py                 # 全社（お客様の社は非公開のデータが読めるときだけ）
    python scripts/fixed_facts.py --site subsidy  # 1社（社の id か公開の id）

ページの一覧は sites/<id>.json（お客様の社は非公開の設定）の fixed_pages。無ければトップだけ。
CI のログは public なので、お客様の社は件数だけを出す（明細は手元で --site を付けて見る）。
"""
import argparse
import ast
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STATUS = ROOT / ".claude" / "skills" / "subsidy-advisor" / "references" / "program-status.md"
OWN_FACTS = ROOT / "data" / "first_party_facts.json"
PUBLIC_FACTS = ROOT / "data" / "public_facts.json"
VOICES = ROOT / "data" / "voices.json"
DATASETS = ROOT / "data" / "datasets"
PAGE_FACTS = ROOT / "data" / "fixed_page_facts.json"
GATES = ROOT / "tests" / "test_gates.py"
UA = "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"
WAIT = 1.0           # ページの間の待ち（本番に連続で当てない）
MAX_SHOWN = 10       # 1社の要対応の明細の上限
MAX_UNSOURCED = 15   # 全社を回すときの、1社の台帳に無い数字の明細（調査の表だけで80件を超える）

_ZEN = str.maketrans("０１２３４５６７８９，．％／～", "0123456789,.%/〜")
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MONEY = re.compile(rf"({NUM})\s*(億|万|千)?\s*円")
# 「5万〜150万円」の左側
MONEY_LEFT = re.compile(rf"({NUM})\s*(億|万)(?=\s*[〜~\-－ー]\s*(?:{NUM})\s*(?:億|万|千)?\s*円)")
# 「Q1 / 8」（設問の番号）・日付（11/12）は率ではない
RATE = re.compile(r"(?<![\dA-Za-z/.])([1-9])/([2-9]|10)(?![\d/])")
RATE_JA = re.compile(r"([2-9]|10)\s*分の\s*([1-9])")
PCT = re.compile(rf"({NUM})\s*(?:%|パーセント)")
WARI = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d)?)\s*割(?!引|増|安|高)")
COUNT = re.compile(rf"({NUM})\s*(店舗|社|件|院|名|人|か月|ヶ月|カ月|ケ月|年|倍|期|時間)")
# 「5万5,393件」（万の位を漢字で書いた数）
COUNT_MAN = re.compile(r"(\d+)万(\d{1,3}(?:,\d{3})|\d{1,4})?\s*(店舗|社|件|院|名|人)")
UNIT = {"名": "人", "ヶ月": "か月", "カ月": "か月", "ケ月": "か月"}
SCALE = {"億": 100_000_000, "万": 10_000, "千": 1_000, None: 1}
ERA = re.compile(r"(?:令和|平成|昭和)\s*$")

SUBSIDY = re.compile(r"補助|助成|交付|インボイス枠|通常枠")
SUBSIDY_PAGE = re.compile(r"補助金|助成金")
# 制度の上限・率を言う語が数のすぐ前（「上限350万円」「補助率2/3」）か、すぐ後ろ（「350万円まで」「350万円枠」）にあるもの。
# 文のどこかにあるだけで照らすと、モデルケースの「導入費550万円」まで食い違いに数えた（2026-11-13 の試行）
CLAIM = re.compile(r"上限|最大|補助額|助成額|補助率|助成率|限度")
CLAIM_BEFORE = re.compile(r"(?:上限|最大|補助額|助成額|補助率|助成率|限度額?)[はがの：:\s（(]{0,3}(?:約|最大)?\s*$")
CLAIM_AFTER = re.compile(r"\s*(?:まで|枠|が上限|を上限)")
# 当社の料金は台帳の対象ではなく、ログにも出さない
PRICE = re.compile(r"料金|月額|年額|税込|税抜|税別|初期費用|費用|価格|プラン|お見積|円\s*[/〜~]")
# 「月3万円」「月1万〜3万円」（月や年あたりの料金。補助金の文のときは料金ではない）
MONTHLY = re.compile(r"(?:月|年)\s*$|月\s*[\d,.]+\s*[万千億]?\s*[〜~\-－]\s*$")
REQ = re.compile(r"売上|年商|資本金|決算|設立|創業|開業|従業員|社員数|営業年数|事業年数|業歴|"
                 r"(?:採択|交付)(?:・(?:採択|交付))?を受け")
BOUND = re.compile(r"以上|以下|未満|超え|超|以内|満たない|決算\D{0,3}\d+\s*期")
SHORT = 40           # 表のセル・数字だけの行。主語（「売上の目安」「補助上限」）は隣の行にある
MIN_YEN = 10_000     # 「1円も出ません」は言い回しで、金額の主張ではない
RETIRED_OK = re.compile(r"終了|廃止|後継|旧|受付が終わ|終わっ|新規公募は|統合|代わり|ありません|できません")
# 直した誤りを書いた括弧（「…と書いていたので直した」）の数は、台帳の数ではない
CORRECTION = re.compile(r"（[^（）]*(?:誤|直した|書いていた)[^（）]*）")

# ページの制度名 → program-status.md の行の名前。上ほど狭い（インボイス枠の文は、インボイス枠の行だけと照らす）
PROGRAMS = [
    (r"インボイス枠|インボイス対応類型", r"インボイス枠"),
    (r"創業型", r"創業型"),
    (r"持続化補助金", r"持続化補助金"),
    (r"ものづくり|新事業進出", r"新事業進出・ものづくり"),
    (r"省力化", r"省力化"),
    (r"事業承継", r"事業承継"),
    (r"成長加速化", r"成長加速化"),
    (r"業務改善助成金", r"業務改善助成金"),
    (r"キャリアアップ助成金", r"キャリアアップ"),
    (r"人材確保等支援助成金|外国人労働者就労環境", r"人材確保等支援"),
    (r"省エネ", r"省エネ"),
    (r"創業助成", r"創業助成"),
    (r"CEV|クリーンエネルギー自動車", r"CEV"),
    (r"電子カルテ", r"電子カルテ|診療情報"),
    (r"AI導入補助金|IT導入補助金|デジタル化・AI導入", r"デジタル化・AI導入補助金"),
]


def _label(m):
    return re.sub(r"\s+", "", m.group(0))


def tokens(s):
    """文の中の数字つきの主張 [(開始, 終了, 比べる鍵の集合, 見せる形)]。日付・年号・電話・時刻は拾わない"""
    s = s.translate(_ZEN)
    out, taken = [], []

    def add(m, keys, label):
        if any(a < m.end() and m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append((m.start(), m.end(), keys, label))

    for m in MONEY.finditer(s):
        v = float(m.group(1).replace(",", "")) * SCALE[m.group(2)]
        add(m, {("円", round(v))}, _label(m))
    for m in MONEY_LEFT.finditer(s):
        v = float(m.group(1).replace(",", "")) * SCALE[m.group(2)]
        add(m, {("円", round(v))}, _label(m) + "円")
    for pat, num, den in ((RATE, 1, 2), (RATE_JA, 2, 1)):
        for m in pat.finditer(s):
            a, b = int(m.group(num)), int(m.group(den))
            if a < b:
                add(m, {("率", round(a / b, 4)), ("%", round(a / b * 100, 1))}, f"{a}/{b}")
    for m in PCT.finditer(s):
        v = float(m.group(1).replace(",", ""))
        add(m, {("%", round(v, 1)), ("率", round(v / 100, 4))}, _label(m))
    for m in WARI.finditer(s):
        v = float(m.group(1)) * 10
        add(m, {("%", round(v, 1)), ("率", round(v / 100, 4))}, _label(m))
    for m in COUNT_MAN.finditer(s):
        n = int(m.group(1)) * 10_000 + int((m.group(2) or "0").replace(",", ""))
        add(m, {(UNIT.get(m.group(3), m.group(3)), float(n))}, _label(m))
    for m in COUNT.finditer(s):
        n, unit = float(m.group(1).replace(",", "")), UNIT.get(m.group(2), m.group(2))
        if unit == "年" and (n >= 1900 or s[m.end():m.end() + 1] == "度" or ERA.search(s[:m.start()])):
            continue
        add(m, {(unit, n)}, _label(m))
    return sorted(out)


def keys_of(text):
    return {k for _, _, ks, _ in tokens(text) for k in ks}


class Ledger:
    """照らす台帳。programs は [(制度の行の名前, 行の文)]、facts は実績の文、retired は終わった制度の名前。
    exact は書き方まで同じときだけ通す文（調査の集計。31業種の小数の割合が、ほかの文の「85%」を通していた）、
    scoped は [(語の並び, 文)] で、語のどれかがページにあるときだけ通す（外部の統計の「約30%」が「工数削減30%」を通していた）"""

    def __init__(self, programs, facts, retired, exact=(), scoped=()):
        self.programs = [(n, CORRECTION.sub("", t)) for n, t in programs]
        self.retired = [r for r in retired if r]
        self.prog_keys = [(n, keys_of(t)) for n, t in self.programs]
        self.all_prog = set().union(*(k for _, k in self.prog_keys)) if self.prog_keys else set()
        self.fact_keys = set().union(*(keys_of(CORRECTION.sub("", str(f))) for f in facts)) if facts else set()
        self.exact = {label for t in exact for *_, label in tokens(str(t))}
        self.scoped = [([w for w in words if w], keys_of(str(t))) for words, t in scoped]

    def scoped_keys(self, page_text):
        return set().union(*(k for words, k in self.scoped if any(w in page_text for w in words)), set())

    def program_for(self, *texts):
        """文に出る制度の行（狭い名前を先に。文に無ければ前後の行で探す）。(名前, 鍵) か None"""
        for t in texts:
            for page, row in PROGRAMS:
                if re.search(page, t):
                    rows = [(n, k) for n, k in self.prog_keys if re.search(row, n)]
                    if rows:
                        return re.search(page, t).group(0), set().union(*(k for _, k in rows))
        return None

    def page_program(self, text):
        """ページで一番多く出る制度。要件の表のセル（「④ 決算・申告」）は制度名を書かないので、ページの主題で照らす。
        全部の行と照らすと、ほかの制度の「40万×2期」で「決算2期」が通っていた（2026-11-13 の試行）"""
        best, top = None, 1
        for page, _ in PROGRAMS:
            hits = re.findall(page, text)
            got = self.program_for(hits[0]) if len(hits) > top else None
            if got:
                best, top = got, len(hits)
        return best


def program_rows(path=STATUS):
    """program-status.md の表の行 [(制度, 制度と状況の文)]"""
    rows = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.split("## 未確認")[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 2 or set(cells[0]) <= set(":- ") or cells[0] == "制度":
            continue
        rows.append((cells[0], cells[0] + " " + cells[1]))
    return rows


def retired_programs():
    """受付の終わった制度（RETIRED_PROGRAMS と自社の ng_terms。program-status.md が両方に入れると決めている）"""
    names = []
    try:
        m = re.search(r"^RETIRED_PROGRAMS = (\{[^\n]*\})", GATES.read_text(encoding="utf-8"), re.M)
        names += list(ast.literal_eval(m.group(1))) if m else []
    except (OSError, ValueError, SyntaxError):
        pass
    import sites as S
    for sid, cfg in S.load_all().items():
        if not S.is_client(sid):
            names += [t for t in cfg.get("ng_terms") or [] if t not in names]
    return names


def _claims(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(f.get("claim") or "") + " " + str(f.get("period") or "") for f in d.get("facts") or []]


def dataset_facts(folder=DATASETS):
    """公開している一次データの引用用の文と行。行の分子・分母は文に無いことがある（「74件のうち64件」）"""
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        unit, n_unit = str(d.get("unit") or ""), re.sub(r"（.*?）", "", str(d.get("n_unit") or ""))
        out.append(str(d.get("sentence") or ""))
        for r in d.get("rows") or []:
            if isinstance(r, dict):
                out.append(f"{r.get('value')}{unit}" + (f" {r['num']}{n_unit} {r['den']}{n_unit}"
                                                         if r.get("num") is not None and r.get("den") is not None else ""))
    return out


def survey_facts():
    """当社の調査の集計から、ページを作る関数で計算した値。コーポレートの /services/aio の業種の表・ラボのトップの
    まとまりの図は industry_ai_sources、補助金LPのトップの区画は subsidy/research が作る"""
    import importlib.util
    import industry_ai_sources as IAS
    out = []
    hls = [h for h in (IAS.headline(i) for i in IAS.live_inds()) if h]
    for h in hls:
        s = json.loads((IAS.OUT / f"{h['ind']}-summary.json").read_text(encoding="utf-8"))
        out.append(f"{h['name']} {h['questions']}問 {h['lp']}% {h['lc']}% {h['oa']}% 出典{sum(s['total'].values())}件")
    if hls:
        out.append(" ".join(text_lines(IAS.home_section())))
    # scripts/research.py と名前がぶつかるので、ファイルの場所で読む（build.py と同じ）
    spec = importlib.util.spec_from_file_location("subsidy_research", ROOT / "scripts" / "subsidy" / "research.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    d = R.data("subsidy", "")
    if d:
        out.append(" ".join(text_lines(R.top_html(d))))
    return out


def _round_half_up(v, dec):
    return math.floor(v * 10 ** dec + 0.5) / 10 ** dec


def case_ok(case):
    """例の式（calc）を計算し直して、結果が文の数と合うか。式に使う数も文にある数だけ（換算の100は除く）"""
    import derived_facts as DF
    claim = str(case.get("claim") or "").translate(_ZEN)
    have = {float(x.replace(",", "")) for x in re.findall(NUM, claim)}
    calc = case.get("calc") or []
    for c in calc:
        want = re.search(NUM, str(c.get("is") or "").translate(_ZEN))
        try:
            got = DF._eval(ast.parse(str(c.get("expr") or ""), mode="eval"), [])
        except (SyntaxError, ValueError):
            return False
        used = {float(x.replace(",", "")) for x in re.findall(NUM, str(c.get("expr") or ""))} - {100.0}
        if not want or not used <= have:
            return False
        w = want.group(0).replace(",", "")
        if _round_half_up(got, len(w.split(".")[1]) if "." in w else 0) != float(w) or float(w) not in have:
            return False
    return bool(calc)


def page_facts(sid, path=PAGE_FACTS):
    """[(語の並び, 文)]。外部の統計（出典の URL のあるものだけ）と、その社の例（式が合うものだけ）"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = [(f.get("words") or [], f["claim"]) for f in d.get("outside") or []
           if str(f.get("url") or "").startswith("https://") and f.get("org") and f.get("checked")]
    out += [(c.get("words") or [], c["claim"]) for c in d.get("examples") or []
            if sid in (c.get("sites") or []) and case_ok(c)]
    return out


def ledger_for(sid):
    """その社を照らす台帳。お客様の社は、お客様の一次情報と会社情報だけを実績にする"""
    import private_store
    import sites as S
    if S.is_client(sid):
        facts = _claims(private_store.client_path(sid, "facts.json"))
        comp = private_store.read_json(sid, "company.json", {}) or {}
        facts += [str(v) for k, v in comp.items() if not str(k).startswith("_")]
        return Ledger(program_rows(), facts, retired_programs())
    try:
        voices = json.loads(VOICES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        voices = []
    facts = _claims(OWN_FACTS) + _claims(PUBLIC_FACTS) + \
        [" ".join(str(v.get(k) or "") for k in ("quote", "number", "who")) for v in voices if isinstance(v, dict)]
    return Ledger(program_rows(), facts, retired_programs(), exact=dataset_facts() + survey_facts(),
                  scoped=page_facts(sid))


INLINE = r"span|b|strong|em|i|u|a|small|sup|sub|mark|abbr|time|data|code|ruby|rt|rp|wbr"


def text_lines(page):
    """読者に見える文を行に分ける。文字の飾り（span など）は行を割らない（「350」と「万円」が別の span に分かれていた）"""
    t = re.sub(r"<(script|style|noscript|template|svg|head)\b.*?</\1>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(rf"</?(?:{INLINE})\b[^>]*>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = html.unescape(t).replace(" ", " ")
    return [re.sub(r"\s+", " ", l).strip() for l in t.splitlines() if l.strip()]


def _sentence(line, start, end):
    a = max(line.rfind(c, 0, start) for c in "。！？") + 1
    ends = [i for i in (line.find(c, end) for c in "。！？") if i >= 0]
    return line[a:(min(ends) + 1) if ends else len(line)].strip()


def check_html(page, ledger, url=""):
    """1ページの明細 [{kind, url, text, value, note}]。kind は mismatch / requirement / retired / unsourced"""
    lines = text_lines(page)
    whole = " ".join(lines).translate(_ZEN)
    page_sub = len(SUBSIDY_PAGE.findall(whole)) >= 3
    page_prog = ledger.page_program(whole) if page_sub else None
    known = ledger.fact_keys | ledger.all_prog | ledger.scoped_keys(whole)
    out = []
    for i, raw in enumerate(lines):
        line = raw.translate(_ZEN)
        prev = lines[i - 1].translate(_ZEN)[-60:] if i else ""
        nxt = lines[i + 1].translate(_ZEN)[:60] if i + 1 < len(lines) else ""
        short = len(line) <= SHORT
        for name in ledger.retired:
            for m in re.finditer(re.escape(name), line):
                s = _sentence(line, m.start(), m.end())
                if not RETIRED_OK.search(s):
                    out.append({"kind": "retired", "url": url, "text": s, "value": name,
                                "note": "受付の終わった制度（RETIRED_PROGRAMS）を、終わったと書かずに載せている"})
        for a, b, keys, label in tokens(line):
            unit, value = next(iter(keys))
            if value == 0 or (unit == "円" and value < MIN_YEN):
                continue
            s = _sentence(line, a, b)
            wide = " ".join((prev, line, nxt))
            local_sub = bool(SUBSIDY.search(s) or SUBSIDY.search(wide))
            if unit == "円" and not local_sub and (PRICE.search(s) or MONTHLY.search(line[max(0, a - 14):a])):
                continue
            prog = ledger.program_for(s, wide)
            item = {"url": url, "text": s if not short else wide.strip(), "value": label}
            if (local_sub or page_sub) and REQ.search(wide if short else s) and BOUND.search(s):
                req = prog or page_prog
                if not keys & (req[1] if req else ledger.all_prog):
                    out.append(dict(item, kind="requirement",
                                    note=f"{req[0] if req else '補助金'}の申請の要件として台帳（公募要領で確かめた行）に無い"))
                continue
            near = CLAIM_BEFORE.search(line[max(0, a - 12):a]) or CLAIM_AFTER.match(line[b:b + 4]) \
                or (short and (CLAIM.search(prev) or CLAIM.search(nxt)))
            if prog and local_sub and unit in ("円", "率", "%") and near:
                if not keys & prog[1]:
                    out.append(dict(item, kind="mismatch", note=f"{prog[0]}の台帳の行に無い"))
                continue
            if keys & known or label in ledger.exact:
                continue
            out.append(dict(item, kind="unsourced", note="どの台帳にも無い"))
    return out


def fetch(url, timeout=30):
    """(本文, 理由)。取れなければ本文は None。一時的な失敗は1回だけ取り直す"""
    why = ""
    for n in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace"), ""
        except urllib.error.HTTPError as e:
            why = f"HTTP {e.code}"
            if e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            why = type(e).__name__
        time.sleep(5 if n == 0 else 0)
    return None, why


def pages_of(cfg):
    dom = str(cfg.get("domain") or "").strip().rstrip("/")
    if not dom:
        return []
    return ["https://" + dom + (p if p.startswith("/") else "/" + p) for p in cfg.get("fixed_pages") or ["/"]]


def check_site(sid, cfg, get=None):
    """(明細, 取れなかったページ [(url, 理由)], 見たページ数)。同じ文はページをまたいでも1回だけ数える。
    台帳に無い数字は同じ数を1件にまとめる（同じ「1.5〜3時間」が4ページに6回出ていた）"""
    led = ledger_for(sid)
    get = get or fetch
    items, failed, seen, n = [], [], {}, 0
    for k, url in enumerate(pages_of(cfg)):
        if k:
            time.sleep(WAIT)
        page, why = get(url)
        if page is None:
            failed.append((url, why))
            continue
        n += 1
        for it in check_html(page, led, url):
            key = (it["kind"], it["value"]) if it["kind"] == "unsourced" else (it["kind"], it["text"])
            if key in seen:
                old = seen[key]
                if it["kind"] == "unsourced":
                    old["more"] = old.get("more", 0) + (it["text"] != old["text"])
                elif it["value"] not in old["value"].split("・"):
                    old["value"] += "・" + it["value"]
                continue
            seen[key] = it
            items.append(it)
    return items, failed, n


LABEL = {"mismatch": "台帳と食い違う数字", "requirement": "台帳に無い申請の要件", "retired": "終わった制度",
         "unsourced": "台帳に無い数字"}
BAD = ("mismatch", "requirement", "retired")


def report(name, items, failed, n, hide, full=True):
    """1社の出力の行。hide はお客様の社を CI で見せるとき（件数だけ）。full でなければ台帳に無い数字は先頭だけ"""
    cnt = {k: sum(1 for it in items if it["kind"] == k) for k in LABEL}
    head = "・".join(f"{LABEL[k]} {cnt[k]}" for k in LABEL)
    out = [f"■ {name}: {n}ページを確認（{head}）"]
    bad = [it for it in items if it["kind"] in BAD]
    if hide:
        if bad:
            out.append(f"要対応: {name} の固定ページに " + "・".join(f"{LABEL[k]} {cnt[k]}件" for k in BAD if cnt[k])
                       + f"（明細は手元で python scripts/fixed_facts.py --site {name}）")
        if failed:
            out.append(f"要対応: {name} の固定ページを {len(failed)}件取得できませんでした（点検していません）")
        if cnt["unsourced"]:
            out.append(f"情報: {name} の固定ページの台帳に無い数字 {cnt['unsourced']}件（明細は手元で --site {name}）")
        return out
    for it in bad[:MAX_SHOWN]:
        out.append(f"要対応: 固定ページの{LABEL[it['kind']]}: {name} {it['url']}: {it['value']} 「{it['text'][:90]}」"
                   f"（{it['note']}）")
    if len(bad) > MAX_SHOWN:
        out.append(f"要対応: {name} の固定ページの明細はほか {len(bad) - MAX_SHOWN}件（python scripts/fixed_facts.py --site {name}）")
    for url, why in failed:
        out.append(f"要対応: 固定ページを取得できませんでした: {name} {url}（{why}。点検していません）")
    uns = [it for it in items if it["kind"] == "unsourced"]
    if uns:
        out.append(f"情報: {name} の固定ページの台帳に無い数字 {len(uns)}件（誤りとは限らない。出典を台帳に足すか、文を直す）")
        shown = uns if full else uns[:MAX_UNSOURCED]
        out += [f"  台帳に無い数字: {it['url']}: {it['value']} 「{it['text'][:80]}」"
                + (f"（ほか{it['more']}か所）" if it.get("more") else "") for it in shown]
        if len(uns) > len(shown):
            out.append(f"  …ほか {len(uns) - len(shown)}件（全部は python scripts/fixed_facts.py --site {name}）")
    return out


def targets(only=None):
    """[(社の id, 設定)] と、非公開のデータが読めず飛ばしたお客様の社の公開の id"""
    import sites as S
    cfgs = S.load_all()
    loaded = {cfg.get("public_id") for cfg in cfgs.values()}
    skipped = []
    for p in sorted(S.SITES_DIR.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        if raw.get("client") and raw.get("id") not in loaded and raw.get("id") not in cfgs:
            skipped.append(raw.get("id"))
    if only:
        sid = S.resolve(only)
        return ([(sid, cfgs[sid])] if sid in cfgs else []), [s for s in skipped if s == only]
    return [(sid, cfg) for sid, cfg in cfgs.items() if cfg.get("domain")], skipped


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap =argparse.ArgumentParser(description="固定ページの数字を本番から取って台帳と照らす")
    ap.add_argument("--site", help="社の id か公開の id（無ければ全社）")
    a = ap.parse_args()
    import private_store
    import sites as S
    ci = bool(os.environ.get("GITHUB_ACTIONS"))
    todo, skipped = targets(a.site)
    if a.site and not todo and not skipped:
        print(f"{a.site} という社はありません")
        print("FIXED_FACTS_OK=unknown")
        return 1
    bad = unknown = False
    for pid in skipped:
        private_store.require(pid, "固定ページの事実の点検")
        unknown = True
    for sid, cfg in todo:
        client = S.is_client(sid)
        name = S.public_id(sid) if client else sid
        items, failed, n = check_site(sid, cfg)
        for line in report(name, items, failed, n, hide=client and ci, full=bool(a.site)):
            print(line, flush=True)
        bad |= any(it["kind"] in BAD for it in items)
        unknown |= bool(failed) or n == 0
    print(f"FIXED_FACTS_OK={'no' if bad else 'unknown' if unknown else 'yes'}")
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
