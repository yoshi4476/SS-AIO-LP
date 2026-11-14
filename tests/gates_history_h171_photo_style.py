"""記事のサムネイル（写真の棚）を作る指示に、暗い撮り方と高齢の人物を入れない（2026-11-15 運用者
「AI集客ラボの記事のサムネイルが全体的に暗いので違う写真に」「年老いた人や暗めのものは使わないで」）。
前の指示は「Documentary realism」「夕方の静かな雰囲気」（2枚目以降）と、介護の鍵に高齢の入居者を入れていて、
作り直しても新しい記事でまた暗い写真・高齢の人物ができる作りだった"""
import re

from test_gates import check

DARK = re.compile(r"\b(evening|late afternoon|late-day|dusk|night|moody|quieter mood|dim|muted|cool blue light|"
                  r"documentary realism|no frontal faces)\b", re.I)
OLD = re.compile(r"\b(elderly|older|senior|grey hair|gray hair)\b", re.I)
BRIGHT = re.compile(r"\bbright", re.I)


def bad_words(text):
    """暗い撮り方・高齢の人物を指す語（「no elderly」のように否定しているものは数えない）"""
    t = re.sub(r"\bno (elderly|older|grey hair|gray hair)[^,.;]*", "", text, flags=re.I)
    t = re.sub(r"\bno (dark|moody)[^,.;]*", "", t, flags=re.I)
    return sorted({m.group(0).lower() for m in DARK.finditer(t)} | {m.group(0).lower() for m in OLD.finditer(t)})


def test_shelf_prompts_are_bright_and_without_elderly_people():
    import photo_shelf as S
    print("\n■ 写真の棚: 作る指示に暗い撮り方・高齢の人物を入れない（明るい取材写真の指示にする）")
    check("検査は悪い例を拾う（夕方・高齢の入居者）",
          bad_words("Evening or late afternoon light, quieter mood. A caregiver supporting an elderly resident"),
          ["elderly", "evening", "late afternoon", "quieter mood"])
    check("検査は語の一部を拾わない（folder の older）", bad_words("handing over a document folder"), [])
    check("検査は否定の書き方を拾わない（no elderly people・no dark or moody lighting）",
          bad_words("Bright and airy. no elderly people and no grey hair. no dark or moody lighting"), [])
    check("共通の指示（STYLE）に暗い撮り方・高齢の語が無い", bad_words(S.STYLE), [])
    check("共通の指示（STYLE）は明るい撮り方を言う", bool(BRIGHT.search(S.STYLE)), True)
    check("撮り方の変え方（VARIANT）に暗い撮り方が無い", [v for v in S.VARIANT if bad_words(v)], [])
    check("鍵ごとの場面に暗い撮り方・高齢の人物が無い", [k for k, _, scene in S.ALL if bad_words(scene)], [])
    _, _, prompt = S.missing()[0] if S.missing() else ("", "", S.STYLE)
    check("実際に作る指示（missing の1件目）にも無い", bad_words(prompt), [])
