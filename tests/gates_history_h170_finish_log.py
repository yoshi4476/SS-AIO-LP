"""公開の後の手順（publish_flow --finish）の出力を、お客様の社の記事ではそのまま CI のログに出さない（2026-11-13）。
finish の出力には題・slug・確認のコマンドが入る。CI のログは public で、伏せる語の一覧に無い回もあった"""
import re
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent
CALL = re.compile(r"publish_flow\.py --finish")


def unmasked(text):
    """--finish を呼ぶ行のうち、出力を受け取って印の行だけに絞る形になっていないもの"""
    bad = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not CALL.search(line) or line.lstrip().startswith("#"):
            continue
        near = "\n".join(lines[i:i + 3])
        if not ("fout=$(" in line and "grep -E '^PUBLISH_(STAGE|FAIL)='" in near and '"$name" = "$slug"' in near):
            bad.append(f"{i + 1}: {line.strip()[:80]}")
    return bad


def test_finish_output_is_masked_for_clients():
    print("\n■ 公開の後の手順の出力を、お客様の社の記事ではそのまま出さない")
    raw = ('          while read -r site slug; do\n'
           '            python scripts/publish_flow.py --finish "$site" "$slug" < /dev/null \\\n'
           '              || echo "::warning::失敗"\n')
    good = ('            fout=$(python scripts/publish_flow.py --finish "$site" "$slug" < /dev/null 2>&1) || rc=$?\n'
            '            if [ "$name" = "$slug" ]; then echo "$fout"; else echo "$fout" | grep -E \'^PUBLISH_(STAGE|FAIL)=\' || true; fi\n')
    check("検出器: そのまま出す形を拾う", bool(unmasked(raw)), True)
    check("検出器: 印の行に絞る形は通す", unmasked(good), [])
    bad = []
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        bad += [f"{p.name}:{x}" for x in unmasked(p.read_text(encoding="utf-8"))]
    check("workflow の --finish はすべて印の行に絞る形", bad, [])
