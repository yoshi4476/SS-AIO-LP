# -*- coding: utf-8 -*-
"""2026-11-20 書き直しの検算が、他サイトの記事で表示の決まり（当社の採択率・支援社数・作成代行）を見ていなかった。

品質ループの書き直しがコーポレートの記事に「当社は…インボイス制度に対応した22社を支援しました」を入れ、取り込まれた。
検算は表示の決まりを build.py の BLOCKED に任せていたが、build.py はコーポレート・補助金の記事を「他サイト」として
検査の前に飛ばす。品質ループは数字の検算も外しているので、何にも止められなかった。
架空の記事（zz-post）と一時の場所だけで試す。claude は呼ばない。記事・台帳には触れない。
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

ART = ("---\ntitle: zz の経理代行の費用と選び方5つ\nkeyword: zz 経理代行\ncategory: zz-cat\n"
       "description: " + "経理代行の費用の相場と、選ぶときに確かめる点をまとめました。" * 3 + "\n---\n"
       "本文。2023年4月から2026年9月までの22社の記録。[出典](https://zz.example/a)\n")
BAD = "当社は2023年4月から2026年9月までにインボイス制度に対応した22社を支援しました。"
GOOD = "当社は2023年4月から2026年9月までに、インボイス制度に22社で対応しました。"


def _check(AR, root, before_text, after_text):
    """before_text の記事を after_text に書き換え、品質ループと同じく数字の検算なしで check() を通す
    （kw_guard・build は通る扱い＝他サイトの記事を build.py が飛ばすのと同じ）"""
    p = root / "articles" / "zz-post.md"
    p.write_text(before_text, encoding="utf-8", newline="")
    before = AR.meta("zz-post")
    snap = AR.snapshot()
    p.write_text(after_text, encoding="utf-8", newline="")
    ok = subprocess.CompletedProcess([], 0, "", "")
    with mock.patch.object(AR, "sh", lambda *a, **k: ok), mock.patch.object(AR, "warns", lambda slug: []):
        return AR.check("zz-post", before, [], snap, numbers=False)


def test_rewrite_check_sees_legal_claims_on_other_sites():
    import auto_rewrite as AR
    import legal_claims
    print("\n■ 書き直しの検算: 他サイトの記事でも、当社の支援社数などを入れた直しを止める")
    check("例の文: 「22社を支援しました」は当たる・「22社で対応しました」は当たらない",
          (bool(legal_claims.find(BAD)), legal_claims.find(GOOD)), (True, []))
    with tempfile.TemporaryDirectory(prefix="gate_h201_", ignore_cleanup_errors=True) as td:
        root = Path(td)
        (root / "articles").mkdir()
        with mock.patch.object(AR, "ROOT", root):
            check("直していない記事は通る", _check(AR, root, ART, ART), "")
            got = _check(AR, root, ART, ART.replace("本文。", "本文。" + BAD))
            check("当社の支援社数の文を足した直しは止める（build.py が飛ばす他サイトの記事でも）",
                  got.startswith("表示の決まりに当たる文が増えました"), True)
            check("登録の言い方（22社で対応しました）は通す", _check(AR, root, ART, ART.replace("本文。", "本文。" + GOOD)), "")
            had = ART.replace("本文。", "本文。" + BAD)
            check("直す前から当たっていた文は、直しが作ったものではないので数えない",
                  _check(AR, root, had, had.replace("本文。", "本文です。")), "")
