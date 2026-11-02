"""h150: 当社調べで AI のログインが切れていたら、その AI に聞くのをやめる（15分の時間切れで止まった。2026-11-02）"""
import sys

from test_gates import check, ROOT


def test_own_survey_stops_on_auth_failure():
    sys.path.insert(0, str(ROOT / "scripts"))
    import ai_cite_check as AC
    import own_survey as O
    print("\n■ ログインが切れた AI には残りの問いを聞かない。ほかの理由の失敗は次の問いへ進む")
    calls = {"ChatGPT": 0, "Gemini": 0}

    def dead(q):
        calls["ChatGPT"] += 1
        raise RuntimeError("codex exec が失敗しました: Your refresh token was already used. Please log out and sign in again")

    def flaky(q):
        calls["Gemini"] += 1
        raise RuntimeError("timeout")

    keep, keep_text = O.engines, AC.answer_text
    O.engines = lambda site: {"ChatGPT": dead, "Gemini": flaky}
    try:
        O.ask("ai-lab", ["q1", "q2", "q3"])
    finally:
        O.engines, AC.answer_text = keep, keep_text
    check("ログイン切れは1問でやめ、ほかの失敗は全部の問いを試す", calls, {"ChatGPT": 1, "Gemini": 3})
    check("良い例（ほかの失敗）を拾わない", bool(O.AUTH_FAIL.search("timeout")), False)
