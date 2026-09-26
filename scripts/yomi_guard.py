# -*- coding: utf-8 -*-
"""読み上げの読み違いを、作った声を聞き直して見つけ、直して、覚える。

**なぜ要るか**: 「32坪」が「さんじゅうふたつぼ」、「断熱等性能等級」が「とうせいの」と
読まれていた。台本を目で見ても分からず、音声を全部聞き直すのは現実的でない。
そこで、作った声を音声認識で文字に戻し、台本と「発音のかな」で突き合わせる。

- ずれた語は、辞書の読み（かな）で読ませて作り直し、もう一度聞き直す
- 直ったら `data/yomi_dict.json` に覚える。次の動画からは最初から正しく読む
- 直らなかったものは `data/yomi_issues.jsonl` に残し、週次の検査が知らせる

音声認識（faster-whisper）が入っていない環境では何もしない（動画づくりは止めない）。

    python scripts/yomi_guard.py --check "延床32坪です" a.mp3   # 1本だけ試す
    python scripts/yomi_guard.py --report                     # 直らなかった読み（週次）
    python scripts/yomi_guard.py --selftest
"""
import argparse
import datetime
import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICT = ROOT / "data" / "yomi_dict.json"
ISSUES = ROOT / "data" / "yomi_issues.jsonl"
MODEL = os.environ.get("YOMI_MODEL", "medium")
_model = _tagger = None


def load_dict():
    try:
        return json.loads(DICT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_dict(s):
    """覚えた読みを当てる（長い語から。短い語が長い語の一部を先に食わないように）"""
    for w, k in sorted(load_dict().items(), key=lambda x: -len(x[0])):
        s = s.replace(w, k)
    return s


def available():
    if os.environ.get("YOMI_CHECK", "1") == "0":
        return False
    try:
        import faster_whisper  # noqa: F401
        import fugashi  # noqa: F401
        return True
    except ImportError:
        return False


def _tag():
    global _tagger
    if _tagger is None:
        import fugashi
        _tagger = fugashi.Tagger()
    return _tagger


def tokens(s):
    """(表記, 発音のかな)。発音で比べる（助詞の「は」は「ワ」、長音は「ー」で揃う）"""
    out = []
    for w in _tag()(s):
        pron = getattr(w.feature, "pron", None) or getattr(w.feature, "kana", None) or ""
        if pron in ("*", None):
            pron = ""
        if not pron and re.fullmatch(r"[ぁ-ゖァ-ヺー]+", w.surface):
            pron = w.surface
        out.append((w.surface, _norm(pron)))
    return out


def _norm(k):
    """カタカナにそろえ、長音と小さな揺れを落とす（トウ／トー、ヂ／ジ）"""
    k = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in k)
    k = re.sub(r"[^ァ-ヺー]", "", k)
    k = k.replace("ヂ", "ジ").replace("ヅ", "ズ").replace("ヲ", "オ")
    k = re.sub(r"(?<=[オコソトノホモヨロゴゾドボポョ])ウ", "ー", k)
    k = re.sub(r"(?<=[エケセテネヘメレゲゼデベペ])イ", "ー", k)
    return k.replace("ー", "")


def spoken_form(s, heard=False):
    """比べる前にそろえる。台本は実際に読ませた文（読み替え後）にする。
    聞き取った文には英字・数字・記号をそろえるだけで、台本側の読み替えは通さない。
    （両方に通すと、読み替えの誤り自体が一致して見逃す。実際「医療法人の」を
    「医療法ひとの」に化けさせていたのに、両側が同じく化けて検出できなかった）"""
    import video_make as V
    s = s.replace("ヶ月", "か月").replace("ケ月", "か月").replace("カ月", "か月")
    if heard:
        s = s.replace("〇〇", "まるまる").replace("○○", "まるまる").replace("%", "パーセント").replace("％", "パーセント")
        s = V.COUNTER_RE.sub(V._counter, s.replace(",", ""))   # 「3つ」「10件」は助数詞の読みに
    else:
        s = V.read_text(apply_dict(s))
    # 英字は1文字ずつカタカナの読みに（「UA」と「ユーエー」、「GPT」と「ジーピーティー」を同じにする）
    s = re.sub(r"[A-Za-z]", lambda m: LETTER.get(m.group(0).upper(), ""), s)
    s = re.sub(r"\d+", lambda m: V.kana_num(int(m.group(0))) if int(m.group(0)) < 10000 else m.group(0), s)
    return s


LETTER = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                  "エー ビー シー ディー イー エフ ジー エイチ アイ ジェー ケー エル エム エヌ オー "
                  "ピー キュー アール エス ティー ユー ブイ ダブリュー エックス ワイ ゼット".split()))


def hear(path, beam=5):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    # ひらがなで書き起こさせる。数字や漢字で書かれると、どう読んだかが消える
    # （「さんじゅうふたつぼ」が「32つぼ」と書かれ、読み違いを見逃した）
    segs, _ = _model.transcribe(str(path), language="ja", beam_size=beam, vad_filter=False,
                                initial_prompt="ひらがなで、きこえたとおりに かきおこします。")
    return "".join(s.text for s in segs)


def diff(text, heard):
    """台本と聞き取りの、発音のずれ。[(台本の語, 台本の読み, 聞こえた読み)]"""
    tk = tokens(spoken_form(text))
    a = "".join(k for _, k in tk)
    b = "".join(k for _, k in tokens(spoken_form(heard, heard=True)))
    owner = []
    for i, (_, k) in enumerate(tk):
        owner += [i] * len(k)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal" or max(i2 - i1, j2 - j1) < 2:
            continue
        idx = sorted(set(owner[max(0, i1 - 1):max(i1 + 1, i2)]))
        words = "".join(tk[i][0] for i in idx)
        out.append((words, a[i1:i2], b[j1:j2]))
    return out


def fix_text(text, bad):
    """ずれた語を、解析器の読み（ひらがな）に置き換えた読み上げ文を返す"""
    import video_make as V
    s = V.read_text(apply_dict(text))
    learned = {}
    for w, _, _ in bad:
        # 助詞をまたいだ語（「も人」）を覚えると、別の文で誤読の原因になる。
        # ずれた範囲にある「漢字だけの1語」だけを読みに置き換える
        for t in _tag()(w):
            sf = t.surface
            if not re.fullmatch(r"[一-龥々]{2,}", sf) or sf not in s:
                continue
            kana = getattr(t.feature, "kana", "") or ""
            hira = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in kana)
            if hira and hira != sf:
                s = s.replace(sf, hira)
                learned[sf] = hira
    return s, learned


def _differs(text, path):
    """ずれを返す。ずれたら聞き取り方を変えてもう一度聞き、どちらかで一致すれば聞き取りの誤りとみなす"""
    bad = diff(text, hear(path))
    if bad and not diff(text, hear(path, beam=1)):
        return []
    return bad


def guard(text, path, synth):
    """作った声を聞き直し、ずれていれば作り直す。synth(読み上げ文, path) で声を作る関数を渡す。
    返り値: 残ったずれ（無ければ空）"""
    if not available():
        return []
    try:
        bad = _differs(text, path)
    except Exception as e:   # 検査が動かないことで動画を止めない
        print(f"  読みの検査を飛ばしました: {e}")
        return []
    if not bad:
        return []
    fixed, learned = fix_text(text, bad)
    if learned:
        synth(fixed, path)
        still = _differs(text, path)
        solved = {w: k for w, k in learned.items() if not any(w in x[0] or x[0] in w for x in still)}
        if solved:
            d = load_dict()
            d.update(solved)
            DICT.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(f"  読みを直して覚えました: {solved}")
        bad = still
    # 人が辞書で直せるのは漢字の読み。英字・かなだけのずれは聞き取りの揺れなので残さない
    bad = [x for x in bad if re.search(r"[一-龥々]", x[0])]
    if bad:
        with open(ISSUES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"date": datetime.date.today().isoformat(), "text": text,
                                "diff": bad}, ensure_ascii=False) + "\n")
    return bad


def report(days=14):
    """直らなかった読み。週次の検査が「要対応」として知らせる"""
    if not ISSUES.exists():
        print("YOMI_OK=yes")
        return 0
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = [json.loads(l) for l in ISSUES.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("date", "") >= since]
    if not rows:
        print("YOMI_OK=yes")
        return 0
    print(f"要対応: 読み上げで直せなかった読み {len(rows)}件（直近{days}日）。"
          "data/yomi_dict.json に正しい読みを足すと、次から直ります")
    for r in rows[:10]:
        for w, a, b in r["diff"][:2]:
            print(f"  - 「{w}」 台本 {a} → 声 {b}（{r['text'][:30]}）")
    print("YOMI_OK=no")
    return 0


def selftest():
    """検査が見かけの差を拾わず、本物の読み違いを拾うか"""
    ok = True
    for text, heard in (("最近お客さんに、AIで調べてきましたと言われます。", "最近お客さんにAIで調べてきましたと言われます"),
                        ("この3つを、3か月単位で見ます。", "この3つを3ヶ月単位で見ます"),
                        ("工務店の性能値です。", "公務店の性能値です")):
        d = diff(text, heard)
        if d:
            print(f"  NG 見かけの差を拾いました: {text} → {d}")
            ok = False
    d = diff("延床32坪です。", "のべゆかさんじゅうふたつぼです")
    if not d:
        print("  NG 本物の読み違い（32坪）を拾えません")
        ok = False
    import video_make as V
    if "ひと" in V.read_text("医療法人の事業承継と、個人の方。"):
        print("  NG 熟語の「人」を「ひと」に読み替えています")
        ok = False
    print("YOMI_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    sys.path.insert(0, str(ROOT / "scripts"))
    ap = argparse.ArgumentParser(description="読み上げの読み違いを聞き直して直す")
    ap.add_argument("--check", nargs=2, metavar=("TEXT", "AUDIO"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report()
    if a.selftest:
        return selftest()
    if a.check:
        for w, x, y in diff(a.check[0], hear(a.check[1])):
            print(f"「{w}」 台本 {x} → 声 {y}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
