# -*- coding: utf-8 -*-
"""記事の内容に合う写真を、配信先サイトの在庫素材から選ぶ

使い方（単体確認）:
    python scripts/pick_photo.py <記事slug> [--site subsidy]

なぜ必要か:
配信先の一覧ページは在庫写真を順番に使い回しているため、記事の中身と絵が合わない。
「費用の記事に工場の写真」のような取り違えは、読む前の信頼を落とす。
本文とタイトルの語から最も近い写真を選び、記事固有のサムネイルとして置く。

写真が1枚も一致しなかった場合は None を返す（無理に当てない）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 写真ごとの想定内容。タイトルに出た語は本文より重く数える
PHOTO_KEYWORDS = {
    "calculator": ["費用", "相場", "金額", "予算", "いくら", "計算", "コスト", "料金",
                   "補助率", "上限", "経費", "支出", "単価"],
    "analytics":  ["採択率", "データ", "分析", "推移", "統計", "割合", "効果", "実績",
                   "指標", "grafu", "グラフ", "比較", "件数"],
    "documents":  ["書類", "必要書類", "提出", "様式", "証明書", "添付", "申請書",
                   "記入", "写し", "納税証明"],
    "paperwork":  ["申請", "手続き", "事務", "作業", "準備", "スケジュール", "締切",
                   "期限", "流れ", "ステップ", "登録"],
    "meeting-jp": ["相談", "支援", "サポート", "打ち合わせ", "面談", "ヒアリング",
                   "代行", "依頼", "問い合わせ", "アドバイス"],
    "handshake":  ["ベンダー", "選び方", "業者", "パートナー", "契約", "委託",
                   "外注", "アウトソーシング", "提携"],
    "chip":       ["AI", "生成AI", "ChatGPT", "ツール", "システム", "ソフト",
                   "デジタル", "テクノロジー", "自動化"],
    "code":       ["開発", "システム開発", "プログラム", "実装", "カスタマイズ", "API"],
    "building":   ["法人", "会社", "企業", "事業所", "中小企業", "本社", "オフィス"],
    "warehouse":  ["在庫", "倉庫", "物流", "小売", "卸", "配送"],
    "factory":    ["製造", "工場", "生産", "製造業", "ライン"],
    "renovation": ["店舗", "改装", "内装", "リフォーム", "工事"],
    "osaka":      ["大阪", "関西", "近畿", "地域", "地元"],
}
# 汎用度が高く、他が当たらないときの受け皿
FALLBACK = "paperwork"
TITLE_WEIGHT = 4
MIN_SCORE = 3  # これ未満なら「合う写真がない」と判断する


def available(lib: Path):
    """在庫にある写真だけを候補にする（ロゴと人物写真は除く）"""
    out = {}
    for name in PHOTO_KEYWORDS:
        for cand in (f"{name}.webp", f"{name}.jpg"):
            p = lib / cand
            if p.is_file():
                out[name] = p
                break
    return out


def score(name, title, body):
    kws = PHOTO_KEYWORDS[name]
    t = sum(TITLE_WEIGHT * title.count(k) for k in kws)
    b = sum(min(body.count(k), 4) for k in kws)  # 1語の連呼で偏らないよう上限を付ける
    return t + b


def pick(title, body, lib: Path):
    """(写真名, パス, スコア) を返す。合うものが無ければ (None, None, 0)"""
    cands = available(lib)
    if not cands:
        return None, None, 0
    ranked = sorted(((score(n, title, body), n) for n in cands), reverse=True)
    best_score, best = ranked[0]
    if best_score < MIN_SCORE:
        if FALLBACK in cands:
            return FALLBACK, cands[FALLBACK], 0
        return None, None, 0
    return best, cands[best], best_score


def make_thumbnail(src: Path, dest: Path, size=(1200, 630)):
    """一覧カード用に 1200x630 へ切り抜いて保存する（宣言サイズと実寸を合わせる）"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    tw, th = size
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    im = im.resize((round(sw * scale), round(sh * scale)), Image.LANCZOS)
    left, top = (im.width - tw) // 2, (im.height - th) // 2
    im = im.crop((left, top, left + tw, top + th))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=82, method=6)
    return dest


def main():
    import yaml
    slug = sys.argv[1]
    import sites as _sm
    site = (sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv
            else _sm.primary())
    src = ROOT / "articles" / f"{slug}.md"
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", src.read_text(encoding="utf-8-sig"), re.S)
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    lib = ROOT / ".publish-work" / site / "assets" / "img"
    name, path, sc = pick(meta["title"], body, lib)
    print(f"記事: {meta['title']}")
    print(f"選定: {name}（スコア {sc}）→ {path}")
    for s, n in sorted(((score(n, meta['title'], body), n) for n in available(lib)), reverse=True)[:5]:
        print(f"   {s:4d}  {n}")


if __name__ == "__main__":
    main()
