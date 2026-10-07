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
    python scripts/outreach.py --resolve 09 sent|notsent        # 「送れたか不明」を Resend の画面で確かめた結果

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
import copy
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse

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
          "published": "掲載された", "unknown": "送れたか不明（Resend の画面で確かめて --resolve）"}

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
# URL に使える ASCII の文字だけ。以前は日本語まで URL とみなし、当社URLの直後に空白なしで続く文
# （「…/research/では997件が…」「…/research/やhttps://他社/」）の数字・他社URLを検査から外していた（2026-10-07 再現）
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]+", re.I)
# http の無いドメインだけの書き方（example.com/x・www.example.co.jp）。当社以外のURLとして止める
BARE_HOST = re.compile(r"(?<![A-Za-z0-9.@/_-])((?:www\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
                       r"(?:com|net|org|jp|io|co|info|biz|me|ai|app|dev|xyz|tv|us|uk|cn|kr|tw|asia|tokyo|site|"
                       r"online|tech|blog|page|link|news|so|to|ly|gl|cc|fm|be|jobs|pro|work|shop|store))"
                       r"(?![A-Za-z0-9-])")
MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DIG = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")
# 漢字の数（「八割」「三千社」）。数字の検査をすり抜けて、材料に無い割合・件数が書けていた（2026-10-07 再現）。
# 単位の付くものだけを数にする（「十分」「一部」のような語は数にしない）。「一」だけのもの（一社・一度）は数えない
KANJI_NUM = re.compile(r"[〇一二三四五六七八九十百千]+(?:[万億][〇一二三四五六七八九十百千]*)*"
                       r"(?=[割倍件社人名問院店校軒台本個回年日%]|業種|種類|か月|ヶ月|カ月|パーセント|施設|万|億)")
KANJI_DIGIT = {c: i for i, c in enumerate("〇一二三四五六七八九")}
# 数字のあとの千・万・億（「3千社」「2万件」）は桁まで含めて1つの数にする
UNIT_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*([千万億])")
UNIT = {"千": 1000, "万": 10 ** 4, "億": 10 ** 8}
# 媒体の見分けに使えない共用の窓口（フォームの外部サービス・フリーメール）。ここではドメインでなく窓口そのもので見分ける。
# ドメインで見分けると、Google フォームの宛先どうしが同じ媒体として90日止め合い、配信停止も巻き込む
SHARED_HOSTS = ("forms.gle", "docs.google.com", "form.run", "forms.office.com", "tayori.com", "formzu.net",
                "jotform.com", "form.jotform.com", "typeform.com", "ssl.form-mailer.jp", "gmail.com", "yahoo.co.jp",
                "ymail.ne.jp", "outlook.com", "outlook.jp", "hotmail.com", "icloud.com", "me.com")


# ---------------------------------------------------------------- 置き場

def _p(name):
    return STORE_DIR / name


class Ledger(dict):
    """読んだ時点の宛先（seen: 宛先の鍵 → JSON の並び）を持つ台帳。保存のときに、自分が変えた宛先だけを書くために使う"""
    seen = None


def _dump(t):
    return json.dumps(t, ensure_ascii=False, sort_keys=True)


def _tkey(t):
    return t.get("id"), t.get("name", "")


def _snapshot(targets):
    seen = {}
    for t in targets:
        seen.setdefault(_tkey(t), []).append(_dump(t))
    return seen


def _read_disk():
    p = _p("targets.json")
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"_readme": "言及の依頼の宛先（公開リポジトリに置かない。.gitignore 済み）", "targets": []}


def load():
    d = Ledger(_read_disk())
    d.seen = _snapshot(d["targets"])
    return d


# 両方の工程が同じ宛先を変えたとき、こちらの変更より残すもの。配信停止は必ず残し、
# 送った・送れたか不明・掲載・返事の記録は、下書きの段の変更で戻さない
_KEEP_DISK = {"stopped": None, "sent": ("new", "hold", "drafted"), "unknown": ("new", "hold", "drafted"),
              "published": ("new", "hold", "drafted"), "replied": ("new", "hold", "drafted")}


def _merge(d, disk):
    """disk の宛先に、d で変えた宛先だけを重ねる。d で触っていない宛先は disk の方を d にも写す（その場で）。
    返り値は (書く宛先の並び, d に無く disk にだけある宛先)。
    承認の画面を開いたまま --draft を走らせると、画面の保存が読んだ時点の台帳を丸ごと書き、
    その間の下書き・配信停止を消していた（2026-10-07 再現）"""
    seen = getattr(d, "seen", None)
    mine = {}
    for t in d["targets"]:
        mine.setdefault(_tkey(t), []).append(t)
    out, only_disk, pos = [], [], {}
    for x in disk.get("targets", []):
        k = _tkey(x)
        i = pos[k] = pos.get(k, -1) + 1
        t = mine[k].pop(0) if mine.get(k) else None
        if t is None:
            out.append(x)
            only_disk.append(x)
            continue
        lst = (seen or {}).get(k) or []
        before = lst[i] if i < len(lst) else None
        if seen is not None and _dump(t) == before:
            keep_disk = True                                     # こちらは触っていない
        elif before is not None and _dump(x) != before:          # 両方が変えた
            rule = _KEEP_DISK.get(x.get("status"), ())
            keep_disk = rule is None or t.get("status") in rule
        else:
            keep_disk = False
        if keep_disk and t is not x:
            t.clear()
            t.update(copy.deepcopy(x))
        out.append(t)
    out += [t for ts in mine.values() for t in ts]
    return out, only_disk


def refresh(d):
    """ほかの工程（--draft・--stop・別の画面）が書いた分を、こちらで触っていない宛先にだけ取り込む（その場で）"""
    if getattr(d, "seen", None) is None or not _p("targets.json").is_file():
        return d
    disk = _read_disk()
    _, only_disk = _merge(d, disk)
    d["targets"] += [copy.deepcopy(x) for x in only_disk]
    # 取り込めた（disk と同じになった）宛先は、読んだ時点を disk に合わせる。こちらで変えた宛先は変えたまま
    now_seen = _snapshot(disk.get("targets", []))
    for k, dumps in now_seen.items():
        mine = [_dump(t) for t in d["targets"] if _tkey(t) == k]
        old = d.seen.get(k) or []
        d.seen[k] = [dumps[i] if i < len(dumps) and i < len(mine) and mine[i] == dumps[i]
                     else (old[i] if i < len(old) else None) for i in range(max(len(dumps), len(mine)))]
    return d


def save(d):
    """自分が変えた宛先だけを書く（保存の直前に読み直す）"""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    disk = _read_disk()
    targets, _ = _merge(d, disk)
    out = {**disk, **{k: v for k, v in d.items() if k != "targets"}, "targets": targets}
    d["targets"] = targets
    _p("targets.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if isinstance(d, Ledger):
        d.seen = _snapshot(targets)


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


def media_key(media, contact=""):
    """同じ媒体かを見分ける鍵（90日・1日の上限・配信停止の照合に使う）。
    媒体のURLがあればそのドメイン。無ければ窓口のドメイン（メールは @ の後ろ）。
    窓口が共用のサービス（Google フォーム・フリーメール）なら、窓口そのもの。
    以前はメールだけの宛先で鍵が空になり、90日も配信停止も効かなかった（2026-10-07 再現）"""
    for v in (media, contact):
        v = (v or "").strip()
        if not v:
            continue
        if MAIL_RE.fullmatch(v):
            h = v.rsplit("@", 1)[1].lower()
        else:
            h = _host(v)
        if not h:
            continue
        return v.lower() if h in SHARED_HOSTS else h
    return ""


def _key(t):
    return t.get("domain") or media_key(t.get("media_url"), t.get("contact"))


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
            media = by_base.get(base, "") or next((u for u in w_urls if _host(u) not in SHARED_HOSTS), "")
        if media:
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
                     "media_url": media, "domain": media_key(media, contact), "channel": channel,
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
            # 下書きの後に費用が有料に変わったら保留へ戻す（下書きのまま承認・送信できていた。2026-10-07 再現）
            if status in ("new", "hold") or (status == "drafted" and r["status"] == "hold"):
                old["status"] = r["status"]
                if old["status"] == "hold":
                    old.pop("approval", None)
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


def _kanji_int(s):
    """「三千二百」→ 3200、「二〇二六」→ 2026（位取りの字が無ければ1字ずつ並べた数）"""
    if not re.search(r"[十百千万億]", s):
        return int("".join(str(KANJI_DIGIT[c]) for c in s))
    total = section = num = 0
    for c in s:
        if c in KANJI_DIGIT:
            num = KANJI_DIGIT[c]
        elif c in "十百千":
            section += (num or 1) * {"十": 10, "百": 100, "千": 1000}[c]
            num = 0
        else:
            total += ((section + num) or 1) * UNIT[c]
            section = num = 0
    return total + section + num


def _num_key(f):
    return str(int(f)) if float(f).is_integer() else repr(float(f))


def numbers(text):
    """文中の数字の集合（URL・メールの中は数えない。全角は半角に、桁区切りは外し、10.0 は 10 に。
    「3千」「2万」は桁まで含めた数に、単位の付く漢字の数（八割・三千社）も数にする）"""
    t = BARE_HOST.sub(" ", MAIL_RE.sub(" ", URL_RE.sub(" ", (text or "").translate(DIG))))
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    out = set()
    for m in UNIT_NUM.finditer(t):
        out.add(_num_key(float(m.group(1)) * UNIT[m.group(2)]))
    t = UNIT_NUM.sub(" ", t)
    for m in KANJI_NUM.finditer(t):
        if m.group() != "一":
            out.add(_num_key(_kanji_int(m.group())))
    for m in re.finditer(r"\d+(?:[.,]\d+)*", t):
        s = m.group().replace(",", "")
        try:
            f = float(s)
        except ValueError:
            continue
        out.add(_num_key(f))
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
    others = [u for u in URL_RE.findall(text) if urlparse(u).netloc.lower() not in OWN_HOSTS]
    others += [h for h in BARE_HOST.findall(MAIL_RE.sub(" ", URL_RE.sub(" ", text)))
               if h.lower() not in OWN_HOSTS]
    if others:
        why.append(f"当社以外のURL: {others[0][:50]}")
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
            + (f"本メールは、貴媒体が公開している窓口（{where}）宛てに、{c['name']}がお送りしています。\n"
               f"今後このようなご連絡が不要でしたら、本メールに「配信停止」とご返信いただくか、"
               f"{c['email']} までお知らせください。以後お送りしません。"
               if t.get("channel") == "email" else
               # フォームに貼る文面で「本メールにご返信」と書くと、返信できない窓口に返信を求めることになる
               f"本連絡は、貴媒体が公開している窓口（{where}）から、{c['name']}がお送りしています。\n"
               f"今後このようなご連絡が不要でしたら、{c['email']} まで「配信停止」とお知らせください。"
               f"以後お送りしません。"))


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
    # 送れるのは「下書きあり」だけ。送った・返事あり・掲載・送れたか不明の宛先は、承認が残っていても止める
    if t.get("status") != "drafted":
        why.append(f"状況が「{STATUS.get(t.get('status'), t.get('status'))}」")
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
    key, contact = _key(t), (t.get("contact") or "").lower()
    if not key:
        why.append("媒体を見分けられない（媒体のURLも窓口も無い）")
    stopped = set()
    for x in d["targets"]:
        if x.get("status") == "stopped":
            stopped |= {_key(x), (x.get("contact") or "").lower()} - {""}
    if {key, contact} & stopped:
        why.append("同じ媒体から配信停止の申し出がある")
    today = when.astimezone(JST).date()
    n_today = sum(1 for r in log if _at(r) and _at(r).astimezone(JST).date() == today)
    if n_today >= DAILY_CAP:
        why.append(f"今日はもう{n_today}通送った（上限{DAILY_CAP}通）")
    for r in log:
        same = (key and r.get("domain") == key) or (contact and (r.get("contact") or "").lower() == contact)
        if same and _at(r):
            ago = when - _at(r)
            if ago < timedelta(days=COOLDOWN_DAYS):
                why.append(f"同じ媒体へ{ago.days}日前に送った（{COOLDOWN_DAYS}日あける）")
                break
    return why


def _at(r):
    """送った記録の時刻（時差つき）。時差の無い記録は日本時間とみなす"""
    try:
        v = datetime.fromisoformat(r["at"])
    except (KeyError, TypeError, ValueError):
        return None
    return v if v.tzinfo else v.replace(tzinfo=JST)


def resend_mail(to, subject, text, reply_to):
    """既存の経路（Resend）。送り元は .env の LEAD_FROM_EMAIL（通知・レポートと同じ）"""
    import send_reports as SR
    key, frm = SR.env("RESEND_API_KEY"), SR.env("LEAD_FROM_EMAIL", "AI集客ラボ <info@ai.7senses.co.jp>")
    if not key or "YOUR_" in key:
        raise RuntimeError("RESEND_API_KEY が未設定です")
    # ヘッダの URI に生の日本語は置けない（RFC 2369・3986）。件名は %XX にする
    unsub = f"<mailto:{reply_to}?subject={quote('配信停止')}>"
    payload = json.dumps({"from": frm, "to": [to], "subject": subject, "text": text, "reply_to": reply_to,
                          "headers": {"List-Unsubscribe": unsub}}).encode()
    # 同じ宛先・同じ文面の送り直しを Resend 側で1通にまとめる（24時間）。応答を受け取れずに送り直したときの二重送信を防ぐ
    idem = "outreach-" + hashlib.sha256(f"{to}\n{subject}\n{text}".encode("utf-8")).hexdigest()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Idempotency-Key": idem, "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8") or "{}").get("id", "")


def send_approved(d, t, mailer=None, when=None):
    """承認済みの1通を送る（メールの窓口だけ）。フォームの窓口は mark_posted で記録する。
    返り値は (送れたか, 理由の一覧)"""
    if t.get("channel") != "email":
        return False, ["メールの窓口ではない（フォームは貼って送ったあと記録する）"]
    refresh(d)
    why = blockers(d, t, when=when)
    if why:
        return False, why
    subject, text = compose(t)
    try:
        mid = (mailer or resend_mail)(t["contact"], subject, text, company()["email"])
    except Exception as e:
        if not sent_maybe(e):
            raise
        # 応答を受け取れなかった（読み取りのタイムアウト・切断・5xx）。届いている恐れがあるので、
        # 下書きのまま残すと次に押したとき二重に送る。「不明」にして、人が確かめるまで送らない
        t["status"] = "unknown"
        t["unknown"] = {"at": (when or now()).isoformat(timespec="seconds"), "subject": subject,
                        "approved_by": t.pop("approval", {}).get("by", "")}
        _event(t, "send_unknown", f"{type(e).__name__}: {str(e)[:120]}")
        save(d)
        return False, [f"送れたか分かりません（{type(e).__name__}）。Resend の画面で確かめ、"
                       f"--resolve {t['id']} sent か notsent で記録してください"]
    _record(d, t, "email", subject, mid, when)
    return True, []


def sent_maybe(e):
    """送信の例外のうち、相手に届いている恐れがあるもの。4xx（Resend が受け付けなかった）と、
    つながる前の失敗（名前解決・接続拒否）は届いていない"""
    if isinstance(e, HTTPError):
        return e.code >= 500
    if isinstance(e, URLError):
        return isinstance(e.reason, TimeoutError)
    # .env が無い（FileNotFoundError）は送る前の失敗
    return isinstance(e, OSError) and not isinstance(e, FileNotFoundError)


def mark_posted(d, t, when=None):
    """フォームに貼って送った（人が送った）ことを記録する。承認・上限・90日の条件は同じ"""
    if t.get("channel") == "email":
        return False, ["メールの窓口は send_approved で送る"]
    refresh(d)
    why = blockers(d, t, when=when)
    if why:
        return False, why
    subject, _ = compose(t)
    _record(d, t, t.get("channel", "form"), subject, "", when)
    return True, []


def _record(d, t, channel, subject, mid, when=None):
    when = when or now()
    _append_sent({"at": when.isoformat(timespec="seconds"), "id": t["id"], "domain": _key(t),
                  "contact": t.get("contact", ""), "channel": channel, "subject": subject, "message_id": mid,
                  "approved_by": (t.get("approval") or {}).get("by", "")})
    t["status"] = "sent"
    t["sent_at"] = when.isoformat(timespec="seconds")
    _event(t, "sent", channel, when)
    save(d)


def resolve(d, t, sent):
    """「送れたか不明」を人が Resend の画面で確かめた結果を記録する。届いていたら送った記録へ
    （90日・1日の上限に数える）、届いていなければ下書きへ戻す（承認はやり直し）"""
    if t.get("status") != "unknown":
        return False
    u = t.pop("unknown", {})
    if sent:
        when = datetime.fromisoformat(u["at"]) if u.get("at") else now()
        t["approval"] = {"by": u.get("approved_by", "")}
        _record(d, t, "email", u.get("subject", ""), "", when)
        t.pop("approval", None)
    else:
        t["status"] = "drafted"
        _event(t, "resolved", "届いていないと確かめた")
    save(d)
    return True


def submit(d, t, confirm, copy=None, open_url=None, mailer=None, when=None):
    """承認の画面の「送る」の中身（画面から切り離して門で確かめる）。confirm(題, 文) -> bool。
    返り値 (送れたか, 理由)。人が途中でやめたら (None, [])。

    フォームの窓口は、上限・90日・配信停止を**コピーしてフォームを開く前に**確かめる。以前は人が貼って
    送った後に確かめていたため、上限に当たると「送ったのに記録されない」（90日が効かない）になっていた"""
    if t.get("verify_first") and not confirm("確認", "窓口のページを開いて、宛先が正しいことを確かめましたか？"):
        return None, []
    if not confirm("送る", f"{t['name']} へ、この文面で出します。よろしいですか？"):
        return None, []
    # 画面を開いた後の配信停止・送信を取り込んでから確かめる（読んだ時点の台帳のまま送っていた）
    refresh(d)
    approve(t)
    why = blockers(d, t, when=when)
    if not why:
        if t.get("channel") == "email":
            try:
                ok, why = send_approved(d, t, mailer, when)
            except Exception as e:
                ok, why = False, [f"送れませんでした: {e}"]
            if ok:
                return True, []
        else:
            s, b = compose(t)
            (copy or (lambda x: None))(f"{s}\n\n{b}")
            if t.get("contact"):
                (open_url or (lambda u: None))(t["contact"])
            if not confirm("フォーム", "件名と本文をコピーしてフォームを開きました。\n貼って送信し終えたら「はい」"):
                t.pop("approval", None)
                save(d)
                return None, []
            # 人がもう送った。条件は開く前に確かめたので、ここでは必ず記録する（記録しないと90日が効かない）
            _record(d, t, t.get("channel", "form"), s, "", when)
            return True, []
    t.pop("approval", None)
    save(d)
    return False, why


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
            # 登録日の無い言及・自社ドメインの言及は、依頼の後に載ったと言えないので数えない
            # （以前は登録日が無いと "9999" とみなし、依頼より前からある掲載を「掲載された」にしていた）
            if not m.get("added") or m.get("third") is False:
                continue
            if host == t["domain"] or host.endswith("." + t["domain"]):
                if m["added"] >= (t.get("sent_at") or "")[:10]:
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
    # 承認するのは署名・配信停止の案内まで含めた全文なので、途中で切らずに折り返して全部見せる
    foot = tk.Label(root, anchor="w", justify="left", fg="#666", font=("Yu Gothic UI", 8), wraplength=870)
    foot.pack(fill="x", padx=10)
    note = tk.Label(root, anchor="w", justify="left", fg="#b00020", wraplength=870)
    note.pack(fill="x", padx=10, pady=4)
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=10, pady=10)

    def cur():
        return queue[pos["i"]] if pos["i"] < len(queue) else None

    def show():
        refresh(d)
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
        foot.config(text="（送るときに機械が付ける署名・配信停止の案内）\n" + footer(t).strip())
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
        def copy(text):
            root.clipboard_clear()
            root.clipboard_append(text)
        ok, why = submit(d, t, messagebox.askyesno, copy, webbrowser.open)
        if ok is None:
            return
        if not ok:
            if t.get("status") == "unknown":
                messagebox.showwarning("送れたか不明", "\n".join(why))
                nxt()
                return
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
    ap.add_argument("--resolve", nargs=2, metavar=("ID", "sent|notsent"),
                    help="送れたか不明の宛先を、Resend の画面で確かめた結果で記録する")
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
    if a.resolve:
        t = find(d, a.resolve[0])
        if not t or a.resolve[1] not in ("sent", "notsent") or not resolve(d, t, a.resolve[1] == "sent"):
            print("  その番号の「送れたか不明」の宛先がありません（sent か notsent で指定）")
            return 0
        print(f"  {t['id']} を「{STATUS[t['status']]}」にしました")
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
            # 配信停止の後の返事（停止の申し出そのもの等）で停止を解かない。解くと同じ媒体の別の宛先へ送れた（2026-10-07 再現）
            if t.get("status") not in ("published", "stopped"):
                t["status"] = "replied"
            t.setdefault("replies", []).append({"at": now().isoformat(timespec="seconds"), "memo": a.reply[1]})
            _event(t, "replied", a.reply[1][:80])
        save(d)
        print(f"  {t['id']} を「{STATUS[t['status']]}」にしました")
        return 0
    summary(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
