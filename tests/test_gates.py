# -*- coding: utf-8 -*-
"""品質ゲートの回帰テスト

実行: python tests/test_gates.py

ここにあるのは、実際に起きた不具合をそのまま固定したもの。
どれもコードを読むだけでは見つからず、動かして初めて分かった。

  1. 食い合い検査が、審査対象の語そのものの台帳行を重複と数え、
     どのKWも弾かれてパイプラインがKWを1件も取得できなくなった
  2. 狙う語を文字の類似で比べ、「it導入補助金 学習塾」と
     「it導入補助金 飲食店」を同じものとみなした（88件中ほとんどが誤検出）
  3. タグの開始と終了の数だけを見ていたため、閉じ忘れと余分な閉じが
     相殺し、</content> が公開HTMLに残った
  4. 採点とビルドで文字数の数え方が違い、同じ記事が5,251字と4,922字になった
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FAIL = []


def check(name, got, want):
    ok = got == want
    print(f"  {'OK' if ok else 'NG'}  {name}" + ("" if ok else f"  （得た {got!r} / 期待 {want!r}）"))
    if not ok:
        FAIL.append(name)


# ── 1. 狙う語の判定 ──────────────────────────────
def test_kw_conflicts():
    from cannibal_check import kw_conflicts, norm_kw
    print("\n■ 狙う語の食い合い判定")
    arts = [{"slug": "a", "kw": "aio診断", "title": "AIO診断のやり方", "desc": "", "h2": [], "cat": "aio"},
            {"slug": "b", "kw": "it導入補助金 学習塾", "title": "学習塾のIT導入補助金", "desc": "", "h2": [], "cat": "aio"},
            {"slug": "c", "kw": "整骨院 集客", "title": "整骨院の集客", "desc": "", "h2": [], "cat": "aio"}]
    check("表記ゆれを同じ語とみなす", bool(kw_conflicts("aio 診断", arts)), True)
    check("全角も同じ語とみなす", norm_kw("ＡＩＯ診断") == norm_kw("aio診断"), True)
    # 業種が違うだけのKWを弾かない（実データで88件中ほとんどが誤検出だった）
    check("業種違いは食い合いにしない", bool(kw_conflicts("it導入補助金 飲食店", arts)), False)
    check("狭い語は広い語に含まれる", bool(kw_conflicts("整骨院 集客 口コミ", arts)), True)
    check("無関係な語は通す", bool(kw_conflicts("動物病院 集客", arts)), False)


# ── 2. タグの対応 ────────────────────────────────
def test_tag_balance():
    sys.path.insert(0, str(ROOT / "scripts"))
    from live_check import tag_balance
    print("\n■ タグの対応検査")
    check("正しい入れ子は通る", tag_balance("<div><p>あ</p></div>"), [])
    check("void要素は数えない", tag_balance("<div><img src='x'><br></div>"), [])
    # 数を数えるだけだと、この2つは相殺して見つからない
    both = tag_balance("<div>あ</content>")
    check("閉じ忘れと余分な閉じを両方見つける", len(both), 2)
    check("開始タグの無い閉じを見つける",
          any("対応する開始タグが無い" in x for x in tag_balance("<p>あ</p></content>")), True)
    check("コードブロック内は無視する", tag_balance("<script>if(a</b>){}</script>"), [])


# ── 3. 文字数の数え方 ────────────────────────────
def test_char_count():
    import md2html
    print("\n■ 文字数の数え方")
    body = "## 見出し\n\n本文です。\n\n| 列A | 列B |\n|:--|:--|\n| あ | い |\n"
    plain = re.sub(r"\s|<[^>]+>", "", md2html.convert(body)[0])
    # 見出しの # や表の | を数えない（採点とビルドで食い違う原因だった）
    check("記法の記号を数えない", ("#" in plain) or ("|" in plain), False)
    check("本文は数える", "本文です。" in plain, True)


# ── 4. 管制塔の食い合い判定（GAS） ──────────────────
def test_hub_gas():
    print("\n■ 管制塔（GAS）の食い合い判定")
    src = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")

    def fn(name):
        m = re.search(rf"function {name}\(.*?\n\}}\n", src, re.S)
        return m.group(0) if m else ""

    harness = """
var READS = 0, ROWS = [];
for (var i = 0; i < 60; i++) ROWS.push(['ai-lab','重複語' + (i%3), '公開済み','A','','','','','','','']);
for (var i = 0; i < 40; i++) ROWS.push(['ai-lab', i < 20 ? '重複語' + (i%3) : '新しい語' + i,
                                        '未着手','B','','','','','','','']);
function kwRows_() { READS++; return ROWS; }
"""
    js = harness + fn("normKw_") + fn("kwConflict_") + fn("nextKw_") + """
var r = nextKw_('ai-lab');
console.log(JSON.stringify({reads: READS, kw: r.keyword,
                            skipped: (r.skipped_conflict||[]).length}));
"""
    tmp = ROOT / "tests" / "_hub_tmp.js"
    tmp.write_text(js, encoding="utf-8")
    try:
        out = subprocess.run(["node", str(tmp)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        import json
        d = json.loads(out.stdout.strip() or "{}")
    finally:
        tmp.unlink(missing_ok=True)
    # 自分の台帳行を重複と数えると、どのKWも弾かれてパイプラインが止まる
    check("自分の行を重複と数えない", bool(d.get("kw", "").startswith("新しい語")), True)
    # 候補ごとに台帳を読み直すと、未着手が数百件でGASの実行時間の上限に当たる
    check("台帳の読み取りは1回だけ", d.get("reads"), 1)
    check("本当の重複だけを飛ばす", d.get("skipped"), 20)


# ── 5. 執筆後ゲートの自己照合 ────────────────────
def test_self_exclusion():
    """書いた記事が自分自身と「完全一致」で止まった事故の再現。
    正当な新記事3本が全部この誤検出で止まり、その回の執筆が無駄になった。"""
    from kw_guard import judge
    print("\n■ 執筆後ゲートの自己照合")
    import glob, re
    # 実在の記事を1本選び、自分のKWで審査する
    f = sorted(glob.glob(str(ROOT / "articles" / "*.md")))[0]
    slug = Path(f).stem
    fm = Path(f).read_text(encoding="utf-8-sig").split("---", 2)[1]
    kw = (re.search(r"^keyword:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
    lv_with, _ = judge(kw, "", use_gsc=False, exclude_slug=slug)
    lv_without, _ = judge(kw, "", use_gsc=False)
    check("自分を除けば自分とは食い合わない", lv_with < 2, True)
    check("除かなければ完全一致で止まる（検査自体は生きている）", lv_without, 2)


def main():
    for t in (test_kw_conflicts, test_tag_balance, test_char_count, test_hub_gas,
              test_self_exclusion):
        try:
            t()
        except Exception as e:
            print(f"  NG  {t.__name__} が例外で止まりました: {type(e).__name__} {e}")
            FAIL.append(t.__name__)
    print(f"\n{'失敗 ' + str(len(FAIL)) + '件: ' + ', '.join(FAIL) if FAIL else 'すべて通りました'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
