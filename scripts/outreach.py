# -*- coding: utf-8 -*-
"""言及の依頼（媒体への情報提供・寄稿の提案・プレスリリース・取材の立候補）を、承認制の半自動にする（2026-10-07）。

**なぜ要るか**: AI検索の見え方に最も効くのは言及（相関 YouTube 0.71・リンク無しの Web 言及 0.66。被リンクは 0.22）。
宛先と依頼文の下書きはデスクトップの md にあるが、1通ずつ手で直して送る形で止まっていた。
ここでは「下書き → 検査 → 人の承認 → 送る → 記録 → 掲載の照合」をつなぐ。**送るかどうかは人だけが決める。**

言及の監視は mentions.py の役目のまま（掲載されたら `mentions.py --add`。ここはその台帳を読むだけ）。

    python scripts/outreach.py --import "<デスクトップの md>"   # 宛先を取り込む（何度でも。状況は残す）
    python scripts/outreach.py                                  # 台帳の状況
    python scripts/outreach.py --draft [--id 09] [--limit 5]    # Claude に下書きを書かせ、検査を通ったものだけ残す
    python scripts/outreach.py --review                         # 承認の画面（送る・直す・やめる）
    python scripts/outreach.py --track                          # mentions の台帳と突き合わせ、掲載を記録する
    python scripts/outreach.py --reply 09 "返事の要旨"           # 返事を記録する
    python scripts/outreach.py --stop 09                        # 配信停止の申し出。以後この媒体へは送らない

守ること:
  - **宛先・連絡先・下書き・送った記録は公開リポジトリに置かない**（data/outreach/ は .gitignore）。CI では使わない
  - 下書きに書いてよい数字は、持ち込む当社の公開ページと、登録済みの一次情報（data/first_party_facts.json）にあるものだけ。
    それ以外の数字が1つでもあれば捨てる（最大3回まで書き直させる）
  - 採択率・支援社数・料金・お客様の声は書かない（legal_claims.py と同じ検出に加えて、料金・声の語を止める）
  - 掲載の見返り（リンク・紹介料・相互掲載・謝礼）を持ちかけない（Google のリンクスパムのポリシー）
  - 送信者情報（社名・住所・連絡先）と配信停止の方法は機械が必ず付ける（特定電子メール法）
  - 承認した後に文面を変えたら承認は無効。1日の上限 DAILY_CAP 通・同じ媒体（ドメイン）へは COOLDOWN_DAYS 日送らない
  - 送信は既存の Resend の経路（.env の RESEND_API_KEY / LEAD_FROM_EMAIL）。返信先は会社の正規の窓口

終了コードは常に0（CLAUDE.md 8.7）。判定は OUTREACH_OK= の印で行う。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

STORE_DIR = ROOT / "data" / "outreach"
FACTS = ROOT / "data" / "first_party_facts.json"
COMPANY = ROOT / "data" / "company_profile.json"
MENTIONS = ROOT / "data" / "mentions.json"
SITE = ROOT / "site"

DAILY_CAP = 10
COOLDOWN_DAYS = 90
MAX_TRIES = 3
JST = timezone(timedelta(hours=9))
OWN_HOSTS = ("ai.7senses.co.jp", "corp.7senses.co.jp", "lp.7senses.co.jp")

STATUS = {"new": "未着手", "drafted": "下書きあり", "sent": "送った", "skipped": "やめた",
          "stopped": "配信停止", "hold": "保留（有料・条件あり）", "replied": "返事あり",
          "published": "掲載された"}

# 持ち込む材料（md の「持ち込むもの」の語 → 当社の公開ページ）。上から順に見て、当たったものを全部使う
MATERIAL = [("歯科", "research/dental-ai-sources"), ("クリニック", "research/clinic-ai-sources"),
            ("不動産", "research/fudosan-ai-sources"), ("工務店", "research/koumuten-ai-sources"),
            ("リフォーム", "research/koumuten-ai-sources"), ("士業", "research/shigyou-ai-sources"),
            ("20問", "research/ai-answers")]
MATERIAL_DEFAULT = "research"

# 一次情報のうち、依頼文に使わないもの。当社サービスの成績（契約数・継続率・店舗数）は媒体の多くが
# 「宣伝目的は対象外」としており、3,200店舗は単位が未確定（company_profile.never_use）
FACT_DENY = re.compile(r"契約|継続率|解約|G-ran|運用を開始|導入した|導入しています|導入支援|補助金|3,200|店舗以上")

# 依頼文で止めるもの（legal_claims.find に加えて）
PRICE = re.compile(r"\d[\d,，]*\s*(?:円|万円)|料金|価格|値段|月額|割引|お見積")
VOICE = re.compile(r"お客様の声|喜びの声|ご感想|お客様から(?:の)?(?:評価|評判)")
# 掲載の見返り・リンクのお願い（リンクスパムのポリシー）
QUID = re.compile(r"相互リンク|相互掲載|被リンク|dofollow|nofollow|紹介料|謝礼|報酬|お礼として|対価|見返り|"
                  r"掲載料をお支払|費用(?:は|を)当社(?:が|で)負担|ギフト券|"
                  r"リンクを(?:張|貼|設置|掲載|いただ|お願)|リンクして(?:いただ|ください|もら)|"
                  r"(?:当社|弊社)(?:の)?(?:サイト|ページ)(?:から|で)[^。\n]{0,12}(?:紹介|リンク)します")
BANNED = re.compile(r"www\.7senses\.co\.jp|株式会社セブンセンシズ|採択率|支援社数|3,?200\s*(?:店舗|社)")
URL_RE = re.compile(r"https?://[^\s）)」』>、。]+")
MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DIG = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")


# ---------------------------------------------------------------- 置き場

def _p(name):
    return STORE_DIR / name


def load():
    p = _p("targets.json")
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"_readme": "言及の依頼の宛先（公開リポジトリに置かない。.gitignore 済み）", "targets": []}


def save(d):
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _p("targets.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def sent_log():
    p = _p("sent.jsonl")
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _append_sent(rec):
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    with _p("sent.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def now():
    return datetime.now(JST)


def find(d, tid):
    for t in d["targets"]:
        if t["id"] == str(tid).zfill(2):
            return t
    return None


def _event(t, kind, note="", at=None):
    t.setdefault("history", []).append({"at": (at or now()).isoformat(timespec="seconds"),
                                        "event": kind, "note": note})


# ---------------------------------------------------------------- 取り込み

def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _host(url):
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _kind(bring, window):
    s = bring + window
    if "寄稿" in s:
        return "寄稿の提案"
    if "プレスリリース" in bring:
        return "プレスリリース"
    # 「取材の依頼・情報提供フォーム」のような窓口の名前だけでは取材の立候補にしない
    if "取り組み" in bring or "立候補" in s:
        return "取材の立候補"
    if "会社紹介" in bring:
        return "会社紹介"
    return "情報提供"


def parse_md(text):
    """md の「宛先の一覧」の表を読む。1行＝1宛先。番号の無い行（本人が記入する区分）は読まない"""
    sec = re.search(r"^##\s*1\..*?(?=^##\s*2\.|\Z)", text, re.S | re.M)
    body = sec.group(0) if sec else text
    rows, group, by_base = [], "", {}
    for line in body.splitlines():
        h = re.match(r"^###\s*(.+)$", line)
        if h:
            group = h.group(1).strip()
            continue
        if not line.startswith("|"):
            continue
        c = _cells(line)
        if len(c) < 7 or not re.fullmatch(r"\d+", c[0]):
            continue
        num, prio, name_col, window, bring, fee, reason = c[:7]
        urls = URL_RE.findall(name_col)
        name = re.sub(r"\s+", " ", URL_RE.sub("", name_col)).strip()
        base = name.split("（")[0].strip()
        media = urls[0] if urls else ""
        w_urls, w_mails = URL_RE.findall(window), MAIL_RE.findall(window)
        if not media:
            media = by_base.get(base, "") or (w_urls[0] if w_urls else "")
        by_base.setdefault(base, media)
        if w_mails:
            channel, contact = "email", w_mails[0]
        elif re.search(r"会員登録|企業登録|予約|投げ込み|応募用紙|持参", window) or not w_urls:
            channel, contact = "manual", (w_urls[0] if w_urls else "")
        else:
            channel, contact = "form", w_urls[0]
        # 費用の欄だけで決める（理由の欄の「有料を案内されたら断る」で保留にしない）
        hold = bool(re.search(r"有料|会員であることが条件", fee))
        verify = bool(re.search(r"検索結果|要確認|確かめる", window + reason + fee))
        rows.append({"id": num.zfill(2), "priority": prio, "group": group, "name": name,
                     "media_url": media, "domain": _host(media or contact), "channel": channel,
                     "contact": contact, "window": URL_RE.sub("", window).strip(" （）()"),
                     "kind": _kind(bring, window), "bring": bring, "fee": fee, "about": reason,
                     "verify_first": verify, "status": "hold" if hold else "new"})
    return rows


def import_md(path):
    """取り込んだ件数を返す。既にある宛先は、状況・下書き・履歴を残して窓口の情報だけ更新する"""
    rows = parse_md(Path(path).read_text(encoding="utf-8-sig"))
    d = load()
    have = {(t["name"], t["id"]): t for t in d["targets"]}
    for r in rows:
        old = have.get((r["name"], r["id"]))
        if old:
            status = old.get("status", "new")
            old.update({k: v for k, v in r.items() if k != "status"})
            if status in ("new", "hold"):
                old["status"] = r["status"]
        else:
            _event(r, "imported", Path(path).name)
            d["targets"].append(r)
    save(d)
    return len(rows)


# ---------------------------------------------------------------- 材料と検査

def page_text(rel):
    """当社の公開ページ（site/ の生成物）から本文の文字だけを取る。ナビ・フッターは外す"""
    p = SITE / rel / "index.html"
    if not p.is_file():
        return ""
    t = p.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def facts_for_outreach():
    try:
        fs = json.loads(FACTS.read_text(encoding="utf-8")).get("facts", [])
    except (OSError, ValueError):
        return []
    return [f for f in fs if f.get("verifiable", True) and not FACT_DENY.search(f.get("claim", ""))]


def material(t):
    """{"pages": [(URL, 本文)], "facts": [文]}。下書きに書いてよいのはこの中の事実だけ"""
    rels = []
    for word, rel in MATERIAL:
        if word in t.get("bring", "") and rel not in rels:
            rels.append(rel)
    if not rels or re.search(r"29業種|横断|調査公開|取り組み", t.get("bring", "")):
        rels.insert(0, MATERIAL_DEFAULT)
    pages = [(f"https://ai.7senses.co.jp/{rel}/", page_text(rel)[:6000]) for rel in rels[:3]]
    return {"pages": [(u, x) for u, x in pages if x], "facts": [f["claim"] for f in facts_for_outreach()]}


def numbers(text):
    """文中の数字の集合（URL・メールの中は数えない。全角は半角に、桁区切りは外し、10.0 は 10 に）"""
    t = MAIL_RE.sub(" ", URL_RE.sub(" ", (text or "").translate(DIG)))
    out = set()
    for m in re.finditer(r"\d+(?:[.,]\d+)*", t):
        s = m.group().replace(",", "")
        try:
            f = float(s)
        except ValueError:
            continue
        out.add(str(int(f)) if f.is_integer() else repr(f))
    return out


def allowed_numbers(mat):
    src = " ".join(x for _, x in mat["pages"]) + " " + " ".join(mat["facts"])
    return numbers(src)


def inspect(subject, body, mat):
    """下書きの問題点（空なら通る）。送る直前にもう一度通す"""
    import legal_claims
    text = f"{subject}\n{body}"
    why = []
    extra = sorted(numbers(text) - allowed_numbers(mat), key=lambda x: (len(x), x))
    if extra:
        why.append("材料に無い数字: " + "・".join(extra[:8]))
    hits = legal_claims.find(text)
    if hits:
        why.append("採択率・支援社数・代行と読める文: " + hits[0][1][:40])
    for name, pat in (("料金・価格", PRICE), ("お客様の声", VOICE), ("掲載の見返り・リンクのお願い", QUID),
                      ("使わない表記", BANNED)):
        m = pat.search(text)
        if m:
            why.append(f"{name}: {m.group(0)}")
    for u in URL_RE.findall(text):
        if urlparse(u).netloc.lower() not in OWN_HOSTS:
            why.append(f"当社以外のURL: {u[:50]}")
            break
    if MAIL_RE.search(text):
        why.append("本文にメールアドレス（署名は機械が付ける）")
    if not (200 <= len(body) <= 1500):
        why.append(f"本文の長さ {len(body)}字（200〜1500字）")
    if not subject.strip():
        why.append("件名が空")
    return why


# ---------------------------------------------------------------- 送信者情報（特定電子メール法）

def company():
    return json.loads(COMPANY.read_text(encoding="utf-8"))


def footer(t, c=None):
    """署名と配信停止の案内。Claude には書かせず、ここで必ず付ける"""
    c = c or company()
    where = t.get("contact") or t.get("media_url") or ""
    return ("\n\n――――――――――――――――\n"
            f"{c['name']}（法人番号 {c['corporate_number']}）\n"
            f"代表取締役 {c['ceo']}\n"
            f"〒{c['postal']} {c['address']}\n"
            f"TEL {c['tel']}（{c['hours']}）\n"
            f"Email {c['email']}\n"
            f"AI集客ラボ {c['sites']['ai-lab']}\n\n"
            f"本メールは、貴媒体が公開している窓口（{where}）宛てに、{c['name']}がお送りしています。\n"
            f"今後このようなご連絡が不要でしたら、本メールに「配信停止」とご返信いただくか、"
            f"{c['email']} までお知らせください。以後お送りしません。")


def has_sender_info(text, c=None):
    c = c or company()
    return all(x in text for x in (c["name"], c["address"], c["email"], c["tel"], "配信停止"))


def compose(t):
    dr = t["draft"]
    return dr["subject"], dr["body"] + footer(t)


# ---------------------------------------------------------------- 下書き（Claude）

PROMPT = """あなたはセブンセンシズ株式会社の代表・原口優です。下の媒体の公開窓口へ送る「{kind}」の文面を書いてください。

■ 媒体: {name}（{media}）
■ 窓口: {window}
■ 媒体について分かっていること: {about}
■ 持ち込むもの: {bring}

■ 使ってよい事実（これ以外の事実・数字は書かない）
{pages}
--- 当社の登録済みの一次情報 ---
{facts}

■ 決まり
- 媒体の読者にとって何が新しいかを先に書く。当社サービスの宣伝・営業の文にしない
- 数字は上の材料にある数字を、そのままの値で、時点（調査日）と母数（質問数・出典の件数）を添えて使う。
  計算した数字・丸めた数字・材料に無い数字は1つも書かない
- 料金・価格・採択率・支援社数・お客様の声・MEO の店舗数は書かない
- 掲載の見返り（リンク・紹介料・相互掲載・謝礼）を持ちかけない。リンクを張ってほしいと頼まない。掲載の判断は先方に委ねる
- 「出典（社名・調査名・URL・調査年月）を明記すれば自由に引用できる」ことは書いてよい
- URL は上の材料の当社のページ（https://ai.7senses.co.jp/...）だけ。メールアドレスは書かない
- 署名・会社の所在地・連絡先・配信停止の案内は書かない（あとで機械が付ける）
- 宛名は「{name_short} 編集部 御中」など。ですます調・1文60字以内・本文400〜900字
{extra}
出力は JSON 1つだけ: {{"subject": "件名", "body": "本文"}}"""


def build_prompt(t, mat, extra=""):
    pages = "\n".join(f"--- 当社の公開ページ {u} ---\n{x}" for u, x in mat["pages"]) or "（なし）"
    facts = "\n".join(f"- {f}" for f in mat["facts"]) or "（なし）"
    return PROMPT.format(kind=t["kind"], name=t["name"], media=t.get("media_url", ""),
                         window=t.get("window", ""), about=t.get("about", ""), bring=t.get("bring", ""),
                         pages=pages, facts=facts, name_short=t["name"].split("（")[0].split(" ")[0],
                         extra=extra)


def ask_claude(prompt):
    """claude -p に書かせる（道具は使わせない）。返り値は標準出力"""
    import auto_rewrite as AR
    r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "1", *AR.model_args(), "--allowedTools", ""],
              timeout=600, stdin_text=prompt)
    return r.stdout or ""


def _parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d.get("subject"), str) or not isinstance(d.get("body"), str):
        return None
    return {"subject": d["subject"].strip(), "body": d["body"].strip()}


def draft_one(t, ask=None, extra=""):
    """検査を通った下書きを t["draft"] に置いて True。MAX_TRIES 回とも外れたら捨てて False"""
    ask = ask or ask_claude
    mat = material(t)
    if not mat["pages"]:
        _event(t, "draft_failed", "持ち込む当社のページが site/ に無い")
        return False
    note = extra
    last = []
    for i in range(MAX_TRIES):
        got = _parse(ask(build_prompt(t, mat, note)))
        if not got:
            last = ["JSONが返らない"]
        else:
            last = inspect(got["subject"], got["body"], mat)
            if not last:
                t["draft"] = {**got, "at": now().isoformat(timespec="seconds"), "tries": i + 1,
                              "material": [u for u, _ in mat["pages"]]}
                t.pop("approval", None)
                t["status"] = "drafted"
                _event(t, "drafted", f"{i + 1}回目で検査を通った")
                return True
        note = extra + "\n■ 前回の文面は次の理由で使えませんでした。直してください: " + " / ".join(last)
    _event(t, "draft_failed", " / ".join(last)[:200])
    return False


def edit_draft(t, subject, body):
    """人が直した文面を検査し直して置く。承認は外れる"""
    why = inspect(subject, body, material(t))
    if why:
        return why
    t["draft"] = {**t.get("draft", {}), "subject": subject.strip(), "body": body.strip(),
                  "at": now().isoformat(timespec="seconds"), "edited": True}
    t.pop("approval", None)
    t["status"] = "drafted"
    _event(t, "edited")
    return []


# ---------------------------------------------------------------- 承認と送信

def _digest(t):
    s, b = compose(t)
    return hashlib.sha256(f"{t.get('channel')}\n{t.get('contact')}\n{s}\n{b}".encode("utf-8")).hexdigest()


def approve(t, who="運用者"):
    """承認の画面からだけ呼ぶ。承認した文面のハッシュを持つので、後で文面が変われば無効になる"""
    t["approval"] = {"by": who, "at": now().isoformat(timespec="seconds"), "digest": _digest(t)}
    _event(t, "approved", who)


def blockers(d, t, log=None, when=None):
    """送れない理由（空なら送れる）"""
    when = when or now()
    log = sent_log() if log is None else log
    why = []
    if t.get("status") in ("stopped", "skipped", "hold"):
        why.append(f"状況が「{STATUS[t['status']]}」")
    if not t.get("draft"):
        why.append("下書きが無い")
        return why
    ap = t.get("approval")
    if not ap:
        why.append("承認されていない")
    elif ap.get("digest") != _digest(t):
        why.append("承認の後に文面か宛先が変わった（承認し直す）")
    s, b = compose(t)
    bad = inspect(t["draft"]["subject"], t["draft"]["body"], material(t))
    if bad:
        why.append("検査: " + " / ".join(bad))
    if not has_sender_info(b):
        why.append("送信者情報・配信停止の案内が無い")
    if t.get("channel") == "email" and not MAIL_RE.fullmatch(t.get("contact", "")):
        why.append("宛先のメールアドレスが無い")
    stopped = {x["domain"] for x in d["targets"] if x.get("status") == "stopped" and x.get("domain")}
    if t.get("domain") in stopped:
        why.append("同じ媒体から配信停止の申し出がある")
    today = when.astimezone(JST).date().isoformat()
    n_today = sum(1 for r in log if r.get("at", "")[:10] == today)
    if n_today >= DAILY_CAP:
        why.append(f"今日はもう{n_today}通送った（上限{DAILY_CAP}通）")
    for r in log:
        if r.get("domain") and r.get("domain") == t.get("domain"):
            try:
                ago = when - datetime.fromisoformat(r["at"])
            except (KeyError, ValueError):
                continue
            if ago < timedelta(days=COOLDOWN_DAYS):
                why.append(f"同じ媒体へ{ago.days}日前に送った（{COOLDOWN_DAYS}日あける）")
                break
    return why


def resend_mail(to, subject, text, reply_to):
    """既存の経路（Resend）。送り元は .env の LEAD_FROM_EMAIL（通知・レポートと同じ）"""
    import send_reports as SR
    key, frm = SR.env("RESEND_API_KEY"), SR.env("LEAD_FROM_EMAIL", "AI集客ラボ <info@ai.7senses.co.jp>")
    if not key or "YOUR_" in key:
        raise RuntimeError("RESEND_API_KEY が未設定です")
    payload = json.dumps({"from": frm, "to": [to], "subject": subject, "text": text, "reply_to": reply_to,
                          "headers": {"List-Unsubscribe": f"<mailto:{reply_to}?subject=配信停止>"}}).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8") or "{}").get("id", "")


def send_approved(d, t, mailer=None, when=None):
    """承認済みの1通を送る（メールの窓口だけ）。フォームの窓口は mark_posted で記録する。
    返り値は (送れたか, 理由の一覧)"""
    if t.get("channel") != "email":
        return False, ["メールの窓口ではない（フォームは貼って送ったあと記録する）"]
    why = blockers(d, t, when=when)
    if why:
        return False, why
    subject, text = compose(t)
    mid = (mailer or resend_mail)(t["contact"], subject, text, company()["email"])
    _record(d, t, "email", subject, mid, when)
    return True, []


def mark_posted(d, t, when=None):
    """フォームに貼って送った（人が送った）ことを記録する。承認・上限・90日の条件は同じ"""
    if t.get("channel") == "email":
        return False, ["メールの窓口は send_approved で送る"]
    why = blockers(d, t, when=when)
    if why:
        return False, why
    subject, _ = compose(t)
    _record(d, t, t.get("channel", "form"), subject, "", when)
    return True, []


def _record(d, t, channel, subject, mid, when=None):
    when = when or now()
    _append_sent({"at": when.isoformat(timespec="seconds"), "id": t["id"], "domain": t.get("domain", ""),
                  "channel": channel, "subject": subject, "message_id": mid, "approved_by": t["approval"]["by"]})
    t["status"] = "sent"
    t["sent_at"] = when.isoformat(timespec="seconds")
    _event(t, "sent", channel, when)
    save(d)


def skip(d, t, why=""):
    t["status"] = "skipped"
    t.pop("approval", None)
    _event(t, "skipped", why)
    save(d)


# ---------------------------------------------------------------- 返事と掲載

def track(d=None, mentions=None):
    """mentions の台帳に、依頼した媒体のページが載ったら「掲載された」にする。記録した件数を返す"""
    d = d or load()
    if mentions is None:
        try:
            mentions = json.loads(MENTIONS.read_text(encoding="utf-8")).get("items", [])
        except (OSError, ValueError):
            mentions = []
    n = 0
    for t in d["targets"]:
        if t.get("status") not in ("sent", "replied") or not t.get("domain"):
            continue
        for m in mentions:
            host = _host(m.get("url", ""))
            if host == t["domain"] or host.endswith("." + t["domain"]):
                if m.get("added", "9999") >= (t.get("sent_at") or "")[:10]:
                    t["status"] = "published"
                    t["mention"] = m["url"]
                    _event(t, "published", m["url"])
                    n += 1
                    break
    if n:
        save(d)
    return n


# ---------------------------------------------------------------- 承認の画面

def review():
    import tkinter as tk
    import webbrowser
    from tkinter import messagebox

    d = load()
    queue = [t for t in d["targets"] if t.get("status") == "drafted"]
    if not queue:
        print("  承認待ちの下書きがありません（--draft で作る）")
        return
    root = tk.Tk()
    root.title("言及の依頼の承認")
    root.geometry("900x780")
    pos = {"i": 0}
    head = tk.Label(root, anchor="w", justify="left", font=("Yu Gothic UI", 11, "bold"))
    head.pack(fill="x", padx=10, pady=(10, 2))
    info = tk.Label(root, anchor="w", justify="left", fg="#444")
    info.pack(fill="x", padx=10)
    subj = tk.Entry(root, font=("Yu Gothic UI", 11))
    subj.pack(fill="x", padx=10, pady=6)
    body = tk.Text(root, wrap="char", font=("Yu Gothic UI", 10), height=24)
    body.pack(fill="both", expand=True, padx=10)
    foot = tk.Label(root, anchor="w", justify="left", fg="#666", font=("Yu Gothic UI", 8))
    foot.pack(fill="x", padx=10)
    note = tk.Label(root, anchor="w", justify="left", fg="#b00020")
    note.pack(fill="x", padx=10, pady=4)
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=10, pady=10)

    def cur():
        return queue[pos["i"]] if pos["i"] < len(queue) else None

    def show():
        t = cur()
        if not t:
            messagebox.showinfo("終わり", "承認待ちの下書きはもうありません")
            root.destroy()
            return
        head.config(text=f"[{pos['i'] + 1}/{len(queue)}] {t['name']}（{t['kind']}）")
        how = {"email": "メールで送る", "form": "フォームに貼る", "manual": "手で出す"}[t["channel"]]
        info.config(text=f"窓口: {t.get('contact') or t.get('window')} ／ {how} ／ 費用: {t.get('fee', '')}")
        subj.delete(0, "end")
        subj.insert(0, t["draft"]["subject"])
        body.delete("1.0", "end")
        body.insert("1.0", t["draft"]["body"])
        foot.config(text="（送るときに機械が付ける署名・配信停止の案内）" + footer(t)[:160].replace("\n", " ") + "…")
        msgs = blockers(d, {**t, "approval": {"digest": _digest(t), "by": "-"}})
        if t.get("verify_first"):
            msgs.insert(0, "窓口は検索結果で確かめたもの。送る前に窓口のページを開いて確かめてください")
        note.config(text="\n".join(msgs))

    def nxt():
        pos["i"] += 1
        show()

    def fix():
        t = cur()
        why = edit_draft(t, subj.get(), body.get("1.0", "end"))
        save(d)
        note.config(text=("直した文面は検査に通りません: " + " / ".join(why)) if why else "直した文面を保存しました")

    def send():
        t = cur()
        if subj.get().strip() != t["draft"]["subject"] or body.get("1.0", "end").strip() != t["draft"]["body"]:
            note.config(text="文面が直されています。先に「直す」で保存してください")
            return
        if t.get("verify_first") and not messagebox.askyesno("確認", "窓口のページを開いて、宛先が正しいことを確かめましたか？"):
            return
        if not messagebox.askyesno("送る", f"{t['name']} へ、この文面で出します。よろしいですか？"):
            return
        approve(t)
        if t["channel"] == "email":
            try:
                ok, why = send_approved(d, t)
            except Exception as e:
                ok, why = False, [f"送れませんでした: {e}"]
        else:
            s, b = compose(t)
            root.clipboard_clear()
            root.clipboard_append(f"{s}\n\n{b}")
            if t.get("contact"):
                webbrowser.open(t["contact"])
            if not messagebox.askyesno("フォーム", "件名と本文をコピーしてフォームを開きました。\n貼って送信し終えたら「はい」"):
                t.pop("approval", None)
                save(d)
                return
            ok, why = mark_posted(d, t)
        if not ok:
            t.pop("approval", None)
            save(d)
            note.config(text="出せません: " + " / ".join(why))
            return
        nxt()

    def drop():
        skip(d, cur(), "承認の画面で「やめる」")
        nxt()

    for label, fn in (("送る", send), ("直す", fix), ("やめる", drop), ("あとで", nxt)):
        tk.Button(bar, text=label, width=12, command=fn).pack(side="left", padx=4)
    tk.Button(bar, text="媒体を開く", command=lambda: webbrowser.open(cur().get("media_url") or "")).pack(side="right")
    show()
    root.mainloop()


# ---------------------------------------------------------------- 状況

def summary(d):
    ts = d["targets"]
    if not ts:
        print("  宛先がまだありません（--import で取り込む）")
        print("OUTREACH_OK=unset")
        return
    by = {}
    for t in ts:
        by[t.get("status", "new")] = by.get(t.get("status", "new"), 0) + 1
    print("■ 言及の依頼")
    print("  " + " ／ ".join(f"{STATUS.get(k, k)} {v}件" for k, v in sorted(by.items())))
    log = sent_log()
    today = now().date().isoformat()
    print(f"  今日送った {sum(1 for r in log if r.get('at', '')[:10] == today)}通（上限{DAILY_CAP}通）／累計 {len(log)}通")
    stale = [t for t in ts if t.get("status") == "sent" and t.get("sent_at")
             and now() - datetime.fromisoformat(t["sent_at"]) > timedelta(days=30)]
    if stale:
        print(f"  送って30日たち、返事も掲載もない {len(stale)}件（--reply で返事を記録・mentions.py --add で掲載を登録）")
    print("OUTREACH_OK=yes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="imp", metavar="MD")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--id")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--reply", nargs=2, metavar=("ID", "MEMO"))
    ap.add_argument("--stop", metavar="ID")
    a = ap.parse_args()

    if a.imp:
        n = import_md(a.imp)
        print(f"  宛先を{n}件取り込みました（{STORE_DIR.relative_to(ROOT)}。公開リポジトリには置きません）")
        return 0
    if a.review:
        review()
        return 0
    d = load()
    if a.draft:
        pool = [t for t in d["targets"] if t.get("status") == "new"
                and (not a.id or t["id"] == a.id.zfill(2))]
        pool.sort(key=lambda t: (t.get("priority", "C"), t["id"]))
        ok = 0
        for t in pool[:a.limit]:
            done = draft_one(t)
            ok += done
            print(f"  {'○' if done else '×'} {t['id']} {t['name'][:30]}"
                  + ("" if done else f"  {t['history'][-1]['note'][:80]}"))
            save(d)
        print(f"  下書き {ok}/{min(len(pool), a.limit)}件が検査を通りました（--review で承認）")
        return 0
    if a.track:
        print(f"  掲載を記録 {track(d)}件")
        return 0
    if a.reply or a.stop:
        t = find(d, a.reply[0] if a.reply else a.stop)
        if not t:
            print("  その番号の宛先がありません")
            return 0
        if a.stop:
            t["status"] = "stopped"
            t.pop("approval", None)
            _event(t, "stopped", "配信停止の申し出")
        else:
            t["status"] = "replied" if t.get("status") != "published" else t["status"]
            t.setdefault("replies", []).append({"at": now().isoformat(timespec="seconds"), "memo": a.reply[1]})
            _event(t, "replied", a.reply[1][:80])
        save(d)
        print(f"  {t['id']} を「{STATUS[t['status']]}」にしました")
        return 0
    summary(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
