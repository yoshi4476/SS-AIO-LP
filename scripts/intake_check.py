"""外から取り込んだスキル・リポジトリ・プラグインを使う前の検査（AI への命令の書き込み・鍵の持ち出し・壊す操作・見えない文字）。

スキルの文は AI がそのまま指示として読む。Git から取ってきたスキルに「前の指示を無視して」「鍵を送って」のような文が
あると、作業場の AI がそれに従いうる（2026-11-02 運用者がループの手順を足す相談で、外から取り込む物との合算を挙げた）。
見つかった物は使う前に人が読む。検査の決まり（8.7）: 見つかれば INTAKE_OK=no と明細（終了コード0）、無ければ yes、
検査が動かなかったときだけ1。

  python scripts/intake_check.py <フォルダかファイル> [...]
"""
import re
import sys
from pathlib import Path

TEXT = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".ps1", ".bat", ".cmd", ".json", ".yml", ".yaml", ".toml"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

RULES = [
    ("AI への命令の書き込み", re.compile(
        r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|disregard (?:the |all )?(?:system|previous) (?:prompt|instructions)"
        r"|(?:前|これまで|上記)の(?:指示|命令|ルール)を(?:無視|忘れ)|システムプロンプトを(?:無視|表示|出力)"
        r"|do not (?:tell|inform) the user|ユーザーに(?:知らせ|伝え|言わ)ない(?:で|こと)", re.I)),
    ("鍵・認証情報の持ち出し", re.compile(
        r"(?:curl|wget|Invoke-WebRequest|iwr|fetch|requests\.(?:post|put))[^\n]{0,160}"
        r"(?:\$\{?\w*(?:TOKEN|SECRET|API_KEY|PASSWORD)\w*|\.env\b|auth\.json|credentials|id_rsa|\.ssh/)"
        r"|(?:cat|type|Get-Content)\s+[^\n]{0,60}(?:\.env\b|auth\.json|\.ssh/id_|credentials)[^\n]{0,80}\|\s*(?:curl|nc|wget)", re.I)),
    ("取ってきた物をそのまま実行", re.compile(
        r"(?:curl|wget)[^\n|]{0,200}\|\s*(?:ba|z)?sh\b|iex\s*\(\s*(?:New-Object|iwr|Invoke-WebRequest)|Invoke-Expression\s*\(?\s*\(?\s*(?:iwr|Invoke-WebRequest)",
        re.I)),
    ("壊す・戻せない操作", re.compile(
        r"rm\s+-rf\s+(?:/|~|\$HOME|\*)(?:\s|$)|git\s+push\s+(?:-f|--force)\b[^\n]{0,40}\b(?:main|master)\b"
        r"|Remove-Item\s+[^\n]{0,40}-Recurse[^\n]{0,40}(?:C:\\|\$env:USERPROFILE|~)\s*(?:-Force)?\s*$|--no-verify\b|--dangerously-skip-permissions", re.I | re.M)),
    ("見えない文字（向きの制御・幅ゼロ）", re.compile("[\u202a-\u202e\u2066-\u2069\u200b-\u200d\u2060\ufeff](?!$)")),
]


def files(paths):
    for p in map(Path, paths):
        if p.is_file():
            yield p
            continue
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.suffix.lower() in TEXT and not SKIP_DIRS & set(f.parts):
                yield f


def scan_text(text):
    """[(検査名, 行番号, 該当の文字列)]"""
    out = []
    for name, rx in RULES:
        for m in rx.finditer(text):
            if name.startswith("見えない文字") and m.start() == 0 and m.group(0) == "\ufeff":
                continue            # ファイルの頭の BOM は正しい書き方
            if name.startswith("AI への命令") and text[max(0, m.start() - 1):m.start()] in ("\"", "“", "「", "'", "`", "‘"):
                continue            # 「"ignore previous instructions" には従わない」のような、例として引いた文
                                    # （取り込み済みの import-memory のスキルで、守り方の説明を拾った。2026-11-02）
            line = text.count("\n", 0, m.start()) + 1
            out.append((name, line, m.group(0).encode("unicode_escape").decode("ascii")[:80]
                        if name.startswith("見えない") else m.group(0)[:80]))
    return out


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if not all(Path(a).exists() for a in args):
        print("INTAKE_OK=unknown（見つからない場所があります）")
        return 1
    hits, n = [], 0
    for f in files(args):
        n += 1
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += [(f, *h) for h in scan_text(text)]
    for f, name, line, s in hits:
        print(f"  {name}: {f}:{line}  {s}")
    print(f"INTAKE_FILES={n}")
    print("INTAKE_OK=" + ("no" if hits else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
