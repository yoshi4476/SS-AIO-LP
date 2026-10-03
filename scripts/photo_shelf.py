# -*- coding: utf-8 -*-
"""記事サムネイルの「写真の棚」。3サイト（AI集客ラボ・コーポレート・補助金）共通。

    site/images/shelf/<鍵>-<番号>.webp   … 1600x900。鍵は業種（clinic・nail…）か作業（invoice・cost…）

記事の題名・狙う語から、まず業種を、業種が分からなければ作業を決めて、その鍵の写真を1枚選ぶ。
同じ鍵に複数枚あれば slug から決まった1枚にする（ビルドのたびに変わらず、一覧で同じ絵が並びにくい）。
写真は ChatGPT のサブスク（Codex CLI の画像生成）で作る。課金APIは使わない。

    python scripts/photo_shelf.py --check            # 棚に足りない鍵と、記事が何本ずつ当たるか
    python scripts/photo_shelf.py --generate [--limit 30]   # 足りない分を Codex で作る（codex login が要る）
    python scripts/photo_shelf.py --pick "<題名>"      # どの写真が当たるか
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "site" / "images" / "shelf"
PER_KEY = 3          # 1つの鍵に置く枚数（一覧で同じ絵が続かない最小）
# 記事の多い鍵は枚数を増やす（20本を3枚で回すと、一覧に同じ絵が何度も出る）
MORE = {"automation": 5, "clinic": 5, "kojin": 5, "outsource": 5, "invoice": 5, "bookkeeping": 5, "subsidy": 5, "kensetsu": 4}

# 業種（題名・狙う語に出る語で決める。上から順に見る＝具体的なものを先に）
INDUSTRIES = [
    ("dental", r"歯科", "A bright modern Japanese dental clinic treatment room with a dental chair and a dentist preparing instruments"),
    ("beauty-derm", r"美容皮膚科|美容外科|美容クリニック", "A calm, upscale Japanese aesthetic dermatology clinic consultation room with soft lighting"),
    ("seikotsu", r"整骨院|接骨院|整体", "A Japanese osteopathic clinic: a practitioner treating a patient's shoulder on a treatment bed"),
    ("kaigo", r"介護", "A Japanese care facility common room with a caregiver supporting an elderly resident, warm and respectful"),
    ("clinic", r"クリニック|医療|病院|医院|オンライン診療|集患", "A clean, modern Japanese clinic reception and waiting area with a receptionist"),
    ("nail", r"ネイル", "A Japanese nail salon: a nail technician working on a customer's hands at a tidy table"),
    ("esthe", r"エステ", "A serene Japanese esthetic salon treatment room with towels and soft light"),
    ("salon", r"美容室|美容院|ヘアサロン|サロン", "A stylish Japanese hair salon with a stylist cutting a customer's hair"),
    ("inshoku", r"飲食|レストラン|カフェ|居酒屋", "A small Japanese restaurant kitchen counter during service, chef plating food"),
    ("hotel", r"宿泊|ホテル|旅館", "A Japanese ryokan or small hotel front desk with a staff member welcoming a guest"),
    ("juku", r"学習塾|塾|スクール|教室", "A Japanese tutoring school classroom with a teacher helping a student at a desk"),
    ("fudosan", r"不動産|賃貸|売買|物件", "A Japanese real estate office: an agent showing property listings on a tablet to a couple"),
    ("koumuten", r"工務店|注文住宅|住宅会社|見学会|ハウスメーカー", "A newly built Japanese wooden custom home interior with a builder talking to the owners"),
    ("reform", r"リフォーム|外壁|塗装|リノベ", "A Japanese home renovation in progress: a craftsman installing new kitchen cabinets"),
    ("kensetsu", r"建設|建築|施工|工事", "A Japanese construction site with workers in helmets and a site manager checking a tablet"),
    ("unso", r"運送|物流|トラック|配送", "A Japanese logistics depot with delivery trucks and a driver checking a handheld device"),
    ("seizou", r"製造|工場|ものづくり|技能", "A tidy Japanese small factory floor with machines and a worker inspecting parts"),
    ("nougyou", r"農業|農家|精米|農機", "A Japanese farmer in a rice field or greenhouse checking crops, morning light"),
    ("jidousha", r"自動車整備|整備業|車検", "A Japanese auto repair shop with a mechanic working under a lifted car"),
    ("cleaning", r"クリーニング", "A Japanese dry cleaning shop counter with neatly hung garments"),
    ("kouri", r"小売|レジ|POS|店舗の|個人店", "A small Japanese retail shop with a shopkeeper at a modern POS register"),
    ("shigyou", r"税理士|社労士|士業|行政書士|会計事務所", "A Japanese tax accountant's office: a professional explaining documents to a client"),
    ("saas", r"SaaS|BtoB|法人向け|ウェビナー|展示会|ホワイトペーパー|商談|リード", "A Japanese B2B software company office: a sales team presenting to a client in a glass meeting room"),
    ("kojin", r"個人事業主|フリーランス|自営業|開業|創業|個人経営", "A Japanese sole proprietor working alone at a home office desk with a laptop and receipts"),
]
# 作業（業種が決まらないときに、題名の語で決める。上から順に見る）
TOPICS = [
    ("invoice", r"請求書|インボイス|適格請求", "Hands preparing and folding paper invoices next to a laptop on an office desk in Japan"),
    ("bookkeeping", r"記帳|帳簿|仕訳|勘定科目|通帳|口座", "A Japanese bookkeeper entering receipts into accounting software, receipts and a bank passbook on the desk"),
    ("expense", r"経費精算|経費|精算", "An employee photographing a receipt with a smartphone for expense reporting at an office desk"),
    ("payroll", r"給与|年末調整|社会保険|労務", "An HR staff member reviewing payroll on a monitor in a calm Japanese office"),
    ("closing", r"月次決算|決算|管理会計|売掛金|支払", "A small Japanese finance team reviewing monthly closing reports together at a meeting table"),
    ("outsource", r"BPO|アウトソーシング|外注|代行|委託|派遣|丸投げ", "A Japanese business owner handing over a document folder to an outside accounting partner across a desk"),
    ("efiling", r"電子申請|e-Gov|e-Tax|GビズID|電子帳簿|JCIP|届出", "A person completing an online government application on a laptop with a My Number card style ID card on the desk"),
    ("subsidy-docs", r"必要書類|書類|納税証明|実績報告|申請書|確定申告", "A neat stack of application documents, a stamp and a pen on a desk with a business owner checking them"),
    ("subsidy", r"補助金|助成金|給付金|採択|不採択", "A Japanese small business owner and a consultant reviewing a funding application on a laptop together"),
    ("automation", r"自動化|AI|OCR|マクロ|VBA|Python|エクセル|Excel|Notion|アプリ|iPhone|ツール|システム|ソフト", "A laptop showing an automated workflow dashboard in abstract shapes, a person reviewing it in a bright office"),
    ("security", r"セキュリティ|サイバー|情報漏えい", "A secure server room or an office laptop with a lock screen, cool blue light"),
    ("staffing", r"人手不足|求人|退職|引き継ぎ|属人化|マニュアル|残業", "A busy Japanese back office with one staff member overloaded with papers, colleagues in background"),
    ("cost", r"費用|相場|料金|いくら|価格|報酬|時給|手数料|補助額", "A calculator, a price estimate sheet and a laptop on a desk with a manager comparing costs"),
    ("reviews", r"口コミ|レビュー|評価", "A shop owner reading customer reviews on a smartphone behind the counter"),
    ("map", r"MEO|Googleマップ|マップ|GBP|ビジネスプロフィール", "A customer on a street holding a smartphone with a map app, a shopfront ahead"),
    ("sns", r"インスタ|Instagram|SNS|チラシ|イベント|セミナー", "A shop owner taking a product photo with a smartphone for social media"),
    ("aisearch", r"AIO|LLMO|AI検索|AI Overview|ChatGPT|生成AI", "A person reading an AI-generated answer on a laptop screen, the content abstract and blurred"),
    ("seo", r"SEO|ホームページ|サイト|記事|ブログ|ライター|導線|事例の書き方|施工事例", "A content team planning website articles with sticky notes and a large monitor"),
    ("marketing", r"集客|反響|資料請求|CVR|紹介|新患|予約", "A small business team reviewing inquiry numbers on a dashboard in a meeting"),
    ("office", r"", "A calm modern Japanese office with staff working at desks, natural light"),
]
ALL = INDUSTRIES + TOPICS
STYLE = ("Documentary realism, shot on a 35mm lens, believable everyday Japanese scene, natural light, "
         "not staged stock-photo smiles. Absolutely no text, letters, numbers, logos or watermarks; "
         "screens and papers show only abstract shapes or are out of focus.")
# 同じ鍵の2枚目・3枚目は撮り方を変える（同じ絵の色違いにしない）
VARIANT = ["Wide establishing shot.", "Medium shot focusing on the people and their hands.", "Different angle and time of day, close detail.",
           "Over-the-shoulder view, shallow depth of field.", "Evening or late afternoon light, quieter mood."]


def key_for(title, keyword=""):
    text = f"{title} {keyword}"
    for k, rx, _ in INDUSTRIES:
        if re.search(rx, text, re.I):
            return k
    for k, rx, _ in TOPICS:
        if re.search(rx, title, re.I):
            return k
    return "office"


def files(k):
    rx = re.compile(rf"^{re.escape(k)}-\d+\.webp$")
    return sorted(p.name for p in DIR.glob(f"{k}-*.webp") if rx.match(p.name))


def pick(title, keyword="", slug=""):
    """(鍵, /images/shelf/… の URL)。棚が空なら汎用の office、それも無ければ ("", "")"""
    k = key_for(title, keyword)
    fs = files(k) or files("office")
    if not fs:
        return "", ""
    i = int(hashlib.md5(str(slug or title).encode("utf-8")).hexdigest(), 16) % len(fs)
    jpg = fs[i][:-5] + ".jpg"
    if not (DIR / jpg).is_file():
        ensure_jpg()
    # 共有画像（LINE・X）に使われるので JPEG を返す。表示は industry_thumbs.shown が同じ名前の WebP に替える
    return k, f"/images/shelf/{jpg}"


def ensure_jpg():
    """WebP しか無い写真に、共有画像用の JPEG を作る（何度呼んでも同じ）"""
    from PIL import Image
    for w in DIR.glob("*.webp"):
        j = w.with_suffix(".jpg")
        if not j.is_file():
            Image.open(w).convert("RGB").resize((1200, 675), Image.LANCZOS).save(j, "JPEG", quality=82, optimize=True, progressive=True)


def path_of(url):
    return ROOT / "site" / url.lstrip("/")


# ---- 生成（ChatGPT のサブスク＝Codex CLI） ----

def _codex_one(prompt, out: Path):
    spec = ("Use your built-in image_gen tool. Do not write code, do not use any CLI fallback, do not copy or move files; "
            "just generate the image and then reply DONE.\nAspect ratio: landscape (16:9).\n\nRequest: " + prompt)
    import shutil
    exe = shutil.which("codex") or "codex"     # Windows では codex.cmd
    r = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--json",
                        "-c", 'model_reasoning_effort="low"', "-"],
                       # 指示は標準入力で渡す。Windows の codex.cmd は引数の改行で切れ、指示の無い絵が返ってきた
                       input=spec, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    m = re.search(r'"thread_id":"([^"]+)"', r.stdout or "")
    if not m:
        return False
    d = Path.home() / ".codex" / "generated_images" / m.group(1)
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not pngs:
        return False
    from PIL import Image
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(pngs[-1]).convert("RGB").resize((1600, 900), Image.LANCZOS).save(out, "WEBP", quality=76, method=6)
    ensure_jpg()
    return True


def missing():
    """[(鍵, 番号, 指示)] 足りない分"""
    out = []
    for k, _, scene in ALL:
        have = files(k)
        for n in range(1, MORE.get(k, PER_KEY) + 1):
            if f"{k}-{n}.webp" not in have:
                out.append((k, n, f"{STYLE} {VARIANT[(n - 1) % len(VARIANT)]} {scene}"))
    return out


def generate(limit=30, workers=3):
    from concurrent.futures import ThreadPoolExecutor
    todo = missing()[:limit]
    if not todo:
        print("SHELF_GEN=none")
        return 0
    ok = 0

    def job(t):
        k, n, prompt = t
        good = _codex_one(prompt, DIR / f"{k}-{n}.webp")
        print(("OK " if good else "NG ") + f"{k}-{n}", flush=True)
        return good

    with ThreadPoolExecutor(workers) as ex:
        ok = sum(ex.map(job, todo))
    print(f"SHELF_GEN={ok}/{len(todo)}")
    return ok


# ---- 配信先へ（コーポレート＝Next.js の JSON、補助金＝静的HTML） ----

def copy_to(dest_root: Path, url: str):
    """棚の写真を配信先の public 側へ複製し、配信先での URL を返す（WebP のみ。表示用）"""
    import shutil
    src = DIR / Path(url).with_suffix(".webp").name
    if not src.is_file():
        return ""
    d = dest_root / "images" / "shelf" / src.name
    d.parent.mkdir(parents=True, exist_ok=True)
    if not d.is_file() or d.stat().st_size != src.stat().st_size:
        shutil.copy2(src, d)
    return f"/images/shelf/{src.name}"


def sync_corp(repo: Path):
    """コーポレートの全記事JSONに photo（表示用の写真）を入れる。OG画像（eyecatch）は文字のカードのまま"""
    n = 0
    for f in sorted((repo / "src" / "content" / "blog").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        _, url = pick(d.get("title", ""), "", d.get("slug", f.stem))
        photo = copy_to(repo / "public", url) if url else ""
        if photo and d.get("photo") != photo:
            d["photo"] = photo
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            n += 1
    print(f"SHELF_CORP={n}")
    return n


def sync_subsidy(repo: Path):
    """補助金サイトの全記事の一覧カード用サムネイル（images/blog/<slug>/thumbnail.webp）を棚の写真で作り直す"""
    import pick_photo
    n = 0
    for page in sorted((repo / "blog").glob("*/index.html")):
        m = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        title = re.split(r"[｜|]", m.group(1))[0].strip()
        _, url = pick(title, "", page.parent.name)
        src = DIR / Path(url).with_suffix(".webp").name if url else None
        if not src or not src.is_file():
            continue
        pick_photo.make_thumbnail(src, repo / "images" / "blog" / page.parent.name / "thumbnail.webp")
        n += 1
    print(f"SHELF_SUBSIDY={n}")
    return n


# ---- 点検（週次の「要対応」に載る） ----

def _titles():
    import yaml
    for f in (ROOT / "articles").glob("*.md"):
        t = f.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        try:
            d = yaml.safe_load(m.group(1))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("title"):
            yield f.stem, str(d["title"]), str(d.get("keyword") or "")


def check():
    from collections import Counter
    use = Counter(key_for(t, k) for _, t, k in _titles())
    lack = [k for k, _, _ in ALL if len(files(k)) < MORE.get(k, PER_KEY)]
    print(f"棚の写真: {len(list(DIR.glob('*.webp')))}枚 / 鍵 {len(ALL)}種（各{PER_KEY}枚）")
    for k, n in use.most_common():
        print(f"  {k:14s} 記事{n:4d}本  写真{len(files(k))}枚")
    if lack:
        print(f"SHELF_OK=no 写真が足りない鍵 {len(lack)}種: {', '.join(lack[:12])}"
              "（手元で python scripts/photo_shelf.py --generate を実行。ChatGPT のサブスクで作る）")
    else:
        print("SHELF_OK=yes")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--generate" in a:
        lim = int(a[a.index("--limit") + 1]) if "--limit" in a else 30
        generate(lim)
    elif "--sync-corp" in a:
        sync_corp(Path(a[a.index("--sync-corp") + 1]))
    elif "--sync-subsidy" in a:
        sync_subsidy(Path(a[a.index("--sync-subsidy") + 1]))
    elif "--pick" in a:
        t = a[a.index("--pick") + 1]
        print(key_for(t), pick(t)[1])
    else:
        check()
