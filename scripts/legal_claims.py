# -*- coding: utf-8 -*-
"""当社の採択率・支援社数の主張と、当社が申請書類を作成・代行すると読める表現を見つける（2026-10-07）。

当社（セブンセンシズ）は IT導入支援事業者として補助金の申請を支援する立場で、申請書類の作成代行は行わず
（官公署に出す書類の作成を業として請け負うのは行政書士の仕事）、採択を保証しない。当社の採択率・支援社数は
母数と期間の根拠が無いので載せない（景品表示法の優良誤認）。原稿の定型文として約75本に
「当社は…申請書類の作成、採択後の実績報告まで一貫して支援」が広がっていたため、文の単位で機械が止める。

一般の説明（士業の代行の説明・代行の相場・「支援事業者に書類の作成をどこまで手伝ってもらえるか」）は止めない。
主語が当社か、主語の無い書き手の文で、当社がする仕事として書かれているものだけを拾う。

    python scripts/legal_claims.py                 # 原稿と手書きのページを検査（LEGAL_OK=yes/no）
    python scripts/legal_claims.py articles/x.md   # 指定したファイルだけ
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SELF = r"(?:当社(?!調べ)|弊社|私たち|わたしたち|セブンセンシズ)"
OTHER = (r"(?:支援事業者|事業者|業者|専門家|行政書士|士業|コンサル|社労士|税理士|代行会社|サポート会社|"
         r"サポート先|相談先|依頼先|ベンダー|販売店|商工会)")
# 打ち消し。主張の語のすぐ後ろ（20字以内）にあるものだけを数える。文のどこかに「ではなく」があるだけで
# 通すと、「紹介ではなく、申請書類の作成まで代行します」を見逃す
NEG_AFTER = (r"^[^。\n]{0,20}?(?:(?:行い|いたし|し|でき|引き受け|請け負い|お受けし|載せ|書き|出し)ません|"
             r"行わ(?:ない|ず)|(?:行って|して)おらず|(?:書か|載せ|し|行わ|出さ)ない|ではなく|ではありません|"
             r"公表して(?:い)?(?:ない|ません))")
# 文のどこかにあれば作成者がお客様だと分かる言い方
NEG_ANY = r"(?:お客様(?:ご自身)?が作成|ご自身で作成)"

# 当社の採択率・通過率（数字か、高いと読ませる言い方を伴うもの）
RATE = r"(?:採択率|通過率|採択実績)"
RATE_VALUE = r"(?:\d+(?:\.\d+)?\s*[%％]|\d+割|高い|高水準|業界(?:トップ|最高)|実績)"
# 「90%+ 採択通過率」のバッジは数字と見出しが別の要素に分かれるので、タグを外して1行にした本文で見る。
# 数字の無い「支援社数・採択通過率を開示しているか」（相談先の選び方）は止めない
BADGE = (r"採択通過率\s{0,3}\d+(?:\.\d+)?\s*[%％]|\d+(?:\.\d+)?\s*[%％]\s*\+?\s{0,3}採択通過率|"
         r"(?:採択|通過)[^。\n]{0,20}\d+(?:\.\d+)?\s*[%％]\s*\+|\d+(?:\.\d+)?\s*[%％]\s*\+[^。\n]{0,20}(?:採択|通過)")
# 「※当社支援実績(2026年7月時点)」は母数の無い数字に当社の実績という裏づけを付ける注記
BASIS = r"※\s*当社の?支援実績"
# 当社の支援社数（数字を伴うもの）
COUNT = (r"(?:のべ\s*\d[\d,]*\s*社|支援社数[^。\n]{0,6}\d|\d[\d,]*\s*社以上(?:の|を|で|に)?[^。\n]{0,8}(?:支援|サポート|手がけ|手掛け)|"
         r"(?:支援|サポート)[^。\n]{0,8}\d[\d,]*\s*社以上)")
# 記事の題の後ろに付くサイト名（「申請代行の費用の相場|セブンセンシズ株式会社」）は主語ではない
SITE_SUFFIX = r"\s*[|｜]\s*(?:[^|｜]*[|｜]\s*)?セブンセンシズ株式会社\s*$"
# 当社が申請書類を作成・代行する
DAIKO = (r"(?:申請代行|申請の代行|申請を代行|代理申請|代行申請|作成代行|作成を代行|書類作成代行|"
         r"代わりに[^。\n]{0,10}(?:申請|作成|提出))")
DOC = (r"(?:申請書類|申請書|書類|事業計画書|計画書)(?:の|を)?(?:作成|準備)(?:から|まで|、|を|も|の)?"
       r"[^。\n]{0,40}?(?:(?:支援|サポート|お手伝い|伴走|代行)(?:して(?:い|き)|いたし|します|できます)|"
       r"一緒に進め(?:ます|てい)|引き受け|請け負)")
DOC_SELF = (r"(?:申請書類|申請書|事業計画書)(?:の|を)(?:作成|準備)|書類作成"
            r"(?=[^。\n]{0,40}?(?:支援|サポート|お手伝い|伴走|代行|引き受け|請け負|一緒に進め|行って|行い|いたし|します))")


def _sentences(text):
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"[*=_`#>]+", "", text)
    for s in re.split(r"[。！？!?\n]|\\n", text):
        s = s.strip()
        if s:
            yield s


def _hit(pat, s):
    """打ち消されていない一致があるか"""
    return any(not re.search(NEG_AFTER, s[m.end():]) for m in re.finditer(pat, s))


def find(text):
    """[(種類, 文)]。種類は rate（採択率）/ count（支援社数）/ daiko（作成・代行）"""
    out = []
    flat = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", flat))
    for m in re.finditer(BADGE, flat):
        out.append(("rate", flat[max(0, m.start() - 20):m.end() + 20].strip()))
    for m in re.finditer(BASIS, flat):
        out.append(("basis", flat[max(0, m.start() - 40):m.end() + 15].strip()))
    for s in _sentences(text):
        bare = re.sub(r"「[^」]*」|『[^』]*』", "", re.sub(SITE_SUFFIX, "", s))
        has_self = re.search(SELF, bare)
        # 「登録支援事業者として」は当社の肩書き。他の主語として数えない
        other = re.search(OTHER, re.sub(r"(?:登録|IT導入)?支援事業者(?:として|で|の当社)", "", bare))
        if has_self and _hit(RATE, bare) and re.search(RATE_VALUE, bare):
            out.append(("rate", s))
            continue
        # 支援社数は主語を省いた書き手の文でも出る（「創業から…のべ50社以上の導入を支援してきた経験からも」）
        if (has_self or not other) and _hit(COUNT, bare):
            out.append(("count", s))
            continue
        if re.search(NEG_ANY, bare):
            continue
        if has_self and (_hit(DAIKO, bare) or _hit(DOC_SELF, bare)):
            out.append(("daiko", s))
            continue
        # 主語の無い書き手の文（「対象ツールの選定から申請書類の作成…まで一貫して支援しています」）
        if not other and _hit(DOC, bare):
            out.append(("daiko", s))
    return out


def targets(root=ROOT):
    """検査する公開物。配信先（.publish-work）は作業コピーがあるときだけ見る"""
    root = Path(root)
    arts = root / "articles"
    out = sorted(p for p in arts.glob("*.md") if not p.name.startswith("_"))
    slugs = {p.stem for p in out}
    site = root / "site"
    # 管制塔の手書きのページ（記事の出力・まとめの生成ページは原稿の検査で見る）
    generated = {"aio", "seo", "meo", "ai-marketing", "industry", "topics", "glossary", "compare", "data",
                 "area", "en", "zh", "ko", "images", "css", "js", "videos", "author", "research", "blog", "wp"}
    if site.is_dir():
        for p in sorted(site.rglob("*.html")):
            rel = p.relative_to(site).parts
            if rel[0] not in generated:
                out.append(p)
        if (site / "llms.txt").is_file():
            out.append(site / "llms.txt")
    sub = root / ".publish-work" / "subsidy"
    if sub.is_dir():
        delivered = set(slugs)
        try:
            delivered |= set(json.loads((sub / "article-manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
        for p in sorted(sub.rglob("*.html")):
            rel = p.relative_to(sub).parts
            # dist は作り直しの出力。業種・比較・用語・テーマは pages.py が原稿から作る
            if rel[0] in ("dist", "node_modules", ".git", "industry", "compare", "glossary", "topics"):
                continue
            # 原稿から作った記事のページは原稿の検査で見る（配信し直すまで古い文が残るため）
            if len(rel) >= 3 and rel[0] == "blog" and rel[1] in delivered:
                continue
            out.append(p)
        for name in ("llms.txt", "client-config.json"):
            if (sub / name).is_file():
                out.append(sub / name)
    corp = root / ".publish-work" / "corporate"
    if corp.is_dir():
        out += sorted((corp / "src" / "lib").glob("*.ts"))
        for name in ("public/llms.txt", "EXTERNAL-MENTIONS.md"):
            if (corp / name).is_file():
                out.append(corp / name)
    return out


def scan(paths=None, root=ROOT):
    hits = []
    for p in paths or targets(root):
        try:
            text = Path(p).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for kind, s in find(text):
            hits.append((Path(p), kind, s))
    return hits


def main():
    paths = [Path(a) for a in sys.argv[1:]] or None
    hits = scan(paths)
    label = {"rate": "当社の採択率", "count": "当社の支援社数", "daiko": "当社が申請書類を作成・代行",
             "basis": "当社の支援実績の注記（母数なし）"}
    for p, kind, s in hits:
        try:
            rel = p.resolve().relative_to(ROOT)
        except ValueError:
            rel = p
        print(f"{rel}: {label[kind]}: {s[:120]}")
    print(f"LEGAL_OK={'no' if hits else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
