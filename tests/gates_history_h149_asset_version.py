"""h149: 配信の直前に、写真の場所へ中身の指紋の版の印を付ける（同じ名前で差し替えた写真が端末の控えで古く出続けた。2026-11-02）"""
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_asset_version_marks_local_photos_only():
    sys.path.insert(0, str(ROOT / "scripts"))
    import asset_version as AV
    print("\n■ 写真の場所に版の印を付ける。外のサイト・無いファイル・写真でないものには付けない。何度かけても同じ")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "images").mkdir()
        (root / "images" / "a.webp").write_bytes(b"one")
        (root / "blog").mkdir()
        html = ('<img src="/images/a.webp" srcset="/images/a.webp 1x, ../images/a.webp 2x">'
                '<img src="https://zz.example/images/a.webp"><img src="/images/none.webp"><a href="/images/">x</a>'
                '<div style="background:url(/images/a.webp)"></div>')
        (root / "blog" / "p.html").write_text(html, encoding="utf-8")
        AV.run(root)
        once = (root / "blog" / "p.html").read_text(encoding="utf-8")
        AV.run(root)
        twice = (root / "blog" / "p.html").read_text(encoding="utf-8")
        (root / "images" / "a.webp").write_bytes(b"two")
        AV.run(root)
        changed = (root / "blog" / "p.html").read_text(encoding="utf-8")
    marks = re.findall(r"a\.webp\?v=([0-9a-f]{8})", once)
    check("自分の写真4か所（src・srcset 2つ・url()）に付き、外のサイトと無いファイルには付かない",
          (len(marks), "zz.example/images/a.webp\"" in once, "none.webp\"" in once), (4, True, True))
    check("何度かけても同じ・中身が変わると印が変わる", (once == twice, set(re.findall(r"\?v=([0-9a-f]{8})", changed)) != set(marks)),
          (True, True))
    for wf in ("deploy.yml", "pipeline.yml", "focus-mode.yml", "weekly-optimize.yml", "pipeline-multi.yml"):
        src = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        n_deploy = src.count("pages deploy site")
        n_ver = len(re.findall(r"asset_version\.py site\s*&&\s*npx --yes wrangler@[\d.]+ pages deploy site", src))
        check(f"{wf}: 送り出しのすべての直前に版の印", n_ver, n_deploy)
