"""配信する直前に、ページと CSS の中の写真の場所へ版の印（?v=中身の指紋8桁）を付ける。

python3 scripts/asset_version.py site

写真は同じ名前のまま中身を差し替える。写真は端末に長く控えられる（AI集客ラボ30日・補助金1年）ので、
場所が同じだと一度見た人には古い写真が出続けた（2026-11-02 に約420枚を差し替えて反映されなかった）。
中身の指紋を場所に付ければ、中身が変わったときだけ取り直させられる。リポジトリのページは変えず、配信の直前に付ける。
何度かけても同じ結果になる（付いている印は付け直す）。
"""
import hashlib
import re
import sys
from pathlib import Path

EXT = ("webp", "jpg", "jpeg", "png", "avif")
# 引用符・括弧・カンマ・空白の後ろから始まる、写真の拡張子で終わる場所（外のサイトの URL は対象にしない）
# Next.js の書き出しは、ページの中のデータに \"/images/a.webp\" の形でも持つので、後ろの \ も区切りとして扱う
URL = re.compile(r"(?<=[\"'(,\s])(?!https?:|//|data:)([\w./%-]+\.(?:" + "|".join(EXT) + r"))(\?v=[0-9a-f]{8})?(?=[\"')\s,\\])")
# ページ・CSS と、Next.js がページ移動のときに読むデータ（.txt）
SUFFIXES = (".html", ".css", ".txt")


def fingerprint(path, memo):
    if path not in memo:
        memo[path] = hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    return memo[path]


def version_text(text, page, root, memo):
    def sub(m):
        rel = m.group(1)
        f = (root / rel.lstrip("/")) if rel.startswith("/") else (page.parent / rel)
        try:
            f = f.resolve()
            f.relative_to(root)
        except (OSError, ValueError):
            return m.group(0)
        if not f.is_file():
            return m.group(0)
        return f"{rel}?v={fingerprint(f, memo)}"
    return URL.sub(sub, text)


def run(root):
    root = Path(root).resolve()
    memo, changed = {}, 0
    for page in root.rglob("*"):
        if page.suffix not in SUFFIXES or not page.is_file():
            continue
        text = page.read_text(encoding="utf-8", errors="surrogateescape")
        new = version_text(text, page, root, memo)
        if new != text:
            page.write_text(new, encoding="utf-8", errors="surrogateescape", newline="")
            changed += 1
    print(f"ASSET_VERSION ページ {changed} 本に写真の版の印を付けました（写真 {len(memo)} 枚）")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "site"))
