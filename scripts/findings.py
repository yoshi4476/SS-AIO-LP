# -*- coding: utf-8 -*-
"""週次の検査が見つけたものを、1か所に集めて知らせる。

個々の検査は `|| true` を付けて呼んでいる。1つ止まっても週次全体を
止めたくないためだが、その結果として終了コードが捨てられ、何を見つけても
実行ログの奥に埋もれて誰にも届いていなかった。実際、会社表記のゆれと
AIO基盤の欠けは毎週検出されうるのに、Slackには「週次最適化: success」
としか出ていない。

ここは検査をまとめて回し、出力から「見つかったもの」だけを抜き出して、
GitHubの注釈と通知本文に載る形にする。**ここ自体は決して止まらない**
（常に0で終わる）。知らせるのが仕事であって、止めるのは各検査の仕事。

通知の本文で「要対応」にするのは、新しく出たもの・悪化したもの・期限のあるものだけ。
毎週続いているもの（前の週と同じ）と人が動かせないもの（STEADY）は、本文の下の「情報」にまとめる。
週次のメールに要対応が毎週15種前後並び、本当の異常が埋もれていたため（2026-10-08）。
判定（judge・*_OK= の印・終了コード）は変えず、知らせ方だけを分ける。前の週に出たものは
data/findings_seen.json（明細はハッシュだけ）に残し、CI の回だけ書き換える。
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from notify_slack import INFO_MARK  # noqa: E402  （ここより下の情報では通知を送らない）

OUT = ROOT / "automation" / "logs" / "findings.txt"
SEEN = ROOT / "data" / "findings_seen.json"
MAX_LINES = 6        # 1検査あたりの明細。多すぎると通知が読まれなくなる
TIMEOUT = 900
JST = timezone(timedelta(hours=9))
# 持ち越す「要対応」の鮮度。週次の間隔（7日）に1日の余裕を足した長さ。
# 2026-09-23 に書かれた findings.txt が手元に残り、取り込み済みの「2026-08 ぶんが未取込です」を
# 10日後にも現在の問題として読ませてしまった。いつの記録かが書かれていなかったため
STALE_DAYS = 8
HEADER = re.compile(r"^# 生成: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")


def written_at(path, header=True):
    """findings.txt がいつの記録か。

    header=True は先頭の「# 生成:」行（検査を回した時刻）、無ければ最終更新時刻。
    header=False は最終更新時刻だけ（後の工程が追記した行の鮮度を見るとき）。
    """
    try:
        if header:
            m = HEADER.match(io.open(path, encoding="utf-8").readline())
            if m:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        return datetime.fromtimestamp(Path(path).stat().st_mtime, JST)
    except OSError:
        return None


def carry_over(path, own, now=None):
    """前の工程が書いた「要対応」を持ち越す。古いファイルの分は持ち越さない。

    検査は毎回回し直すので、古いファイルに残った要対応は今の状態ではない。
    最後に追記された時刻（最終更新）で見る。生成時刻で見ると、同じ回の後の工程が
    足した行まで捨ててしまう。
    """
    if not Path(path).exists():
        return [], ""
    note = stale_note(written_at(path, header=False), now)
    if note:
        return [], note
    prev = []
    for l in io.open(path, encoding="utf-8").read().splitlines():
        if l.startswith("要対応") and l not in own and l not in prev:
            prev.append(l)
    return prev, ""


def stale_note(src, now=None, days=STALE_DAYS):
    """記録が古ければ「（古い記録・YYYY-MM-DD 時点）」を返す。新しければ空文字。"""
    if src is None:
        return ""
    now = now or datetime.now(JST)
    if now - src <= timedelta(days=days):
        return ""
    return "（古い記録・%s 時点）" % src.astimezone(JST).strftime("%Y-%m-%d")

# 読むだけの検査だけを入れる。書き換える工程を入れると週次で二重に走る。
# 明細の書き方が検査ごとに違うため、拾う形をここで明示する
CHECKS = [
    # 過去の誤りの棚卸し（2026-10-03・85件）から作った本番の確認。門（tests/gates_history_*.py）では見られない配信先・外部の状態
    ("過去の誤りの再発（配信・画像・転送・robots・llms.txt）", "history_checks_a.py", re.compile(r"^要対応:|^\s+×")),
    ("過去の誤りの再発（動画の説明欄・取り下げた旧URL）", "history_checks_b.py", re.compile(r"^要対応:|^\s+×")),
    ("過去の誤りの再発（レポートの数字・公開本数の照合）", "history_checks_c.py", re.compile(r"^要対応:|^\s+×")),
    ("過去の誤りの再発（鍵の配布・外部APIの生死・配信先の依存）", "history_checks_d.py", re.compile(r"^要対応:|^\s+×")),
    ("YouTube の公開動画（重複・字幕なし・台帳漏れ）", "youtube_upload.py --audit", re.compile(r"^\s{2}(自前の字幕|台帳に無い|同じ題)")),
    ("AIO基盤（robots・llms.txt・構造化データ）", "aio_check.py",
     re.compile(r"未記載:|不足:|取得できません|記事が載っていません")),
    ("量産の指紋（同型記事・定型文・長さの偏り）", "scaled_guard.py",
     # 明細は先頭数行しか通知に載らない。組の一覧を拾うと肝心の「要対応」が押し出される
     re.compile(r"^要対応:")),
    ("SNS の鍵の期限（Threads・LinkedIn は60日）", "social_connect.py --check",
     re.compile(r"^要対応:")),
    # GitHub の定時は3〜8時間遅れるため、Cloudflare Worker が時刻どおりに起動している。止まると黙って遅れに戻る
    ("定時の起動役（Cloudflare Worker）の起動と鍵の期限", "sched_guard.py --watch",
     re.compile(r"^要対応:")),
    ("動画の読み違い（聞き直して直せなかった読み）", "yomi_guard.py --report",
     re.compile(r"^要対応:|^\s{2}- ")),
    ("YouTube の許可の上限（未確認アプリは累計100）", "youtube_upload.py --users",
     re.compile(r"^要対応:")),
    # 指示での改修（site_renovate）が反映後の確認で外れ、自動で戻した回。台帳を読むだけ（改修は走らせない）
    ("サイト改修の自動の戻し", "site_renovate.py --report",
     re.compile(r"^要対応:")),
    ("監修待ちの記事", "editorial_review.py --pending",
     re.compile(r"^要対応:|^\s{2}- ")),
    # 組の違う社（お客様どうし・お客様と自社）が同じ語を持った。弾かずに登録してあるので、
    # 地域を見て両方使うか片方を外すかを運用者が決める（管制塔の「KW重複の確認」）
    ("KW重複の確認（組の違う社が同じ語）", "hub_client.py overlaps",
     re.compile(r"^要対応:|^\s{2}- ")),
    ("会社表記のゆれ（NAP）", "nap_check.py",
     re.compile(r"^\s{2}-\s")),
    ("内部リンクの積み上がり", "auto_review.py",
     re.compile(r"上限\+\d+本|同じ言い回し\d+本")),
    # 記事を増やした分だけ伸びているか。合計が伸びていても、新しい記事が既存記事の
    # 表示を置き換えているだけのことがある。公開からの週数をそろえて比べる（期間の単純比較は
    # 公開後の山からの自然な落ち込みを食い合いと読む。2026-10-05 に分かった）
    ("記事の出しすぎ（増やした分が伸びているか）", "content_yield.py",
     re.compile(r"^\s*要対応:")),
    # 用語集は記事の定義から機械で作るため、記事と同じ語で上に出ることがある（2026-10-05 実測 60語）。
    # noindex・正規URLは機械で変えず、人が決める
    ("用語集が記事より上に出る語", "cannibal_check.py --glossary",
     re.compile(r"^\s*要対応:")),
    # フォームの送信が台帳に残っているか。管制塔が弾いた問い合わせはメールにだけ届き、
    # 台帳にも件数にも出ない（2026-09 に AI集客ラボで3日分が残っていなかった）
    ("問い合わせの取りこぼし（GA4と台帳）", "lead_reconcile.py",
     re.compile(r"^\s*要対応:")),
    # WordPress の社のプラグインは自分で新しい版に置き換わる。書き換えを許さないサーバーでは古いまま残るので知らせる
    ("WordPress の橋渡し（プラグインの版・自己更新）", "wp_bridge.py --check",
     re.compile(r"^要対応:")),
    # お客様の社の検索エンジンへの最初の接続（Search Console のオーナー・zip の残り）。先方にお願いするまで消えない
    ("検索エンジンへの接続（お客様の社）", "search_connect.py --check",
     re.compile(r"^要対応:")),
    # ヒアリングシートと鍵の登録から見た機能ごとの準備状況（お客様の社）。本番は読まない（本番は onboard_check）。
    # Search Console のオーナーは上の search_connect が知らせるので、ここでは重ねて出さない
    ("機能ごとの準備状況（ヒアリングと鍵・お客様の社）", "intake_readiness.py --all",
     re.compile(r"^要対応:")),
    # Ahrefs の Site Audit と同じ観点を3サイトの本番に当てる（外部リンク切れ・乗っ取られたドメインへの転送も）
    ("サイト監査（Ahrefs相当・3サイトの本番）", "seo_audit.py --live --all --external",
     re.compile(r"^要対応:")),
    # 先方の作り次第の項目（まとめのページ・head の構造化データ/hreflang/robots/OGP・sitemap・llms.txt・robots.txt・計測・
    # IndexNow/Bing のファイル・動画の CSP・統合の301）が本番で動いているか。先方に頼む1文まで出す
    ("最初の接続の点検（先方の作り次第の項目）", "onboard_check.py --all",
     re.compile(r"^要対応:")),
    # 量産と見られている兆候と1日の本数（落としたサイトは要対応として知らせる）
    ("量産の兆候と本数（Google の大量生成の定義）", "pace.py",
     re.compile(r"^\s*(要対応:|兆候:)")),
    ("数字の信頼性", "data_sanity.py",
     re.compile(r"^\s*注意\s+(?!\d+件)\S")),
    ("ラッコキーワードの消費", "rakko.py",
     re.compile(r"今月の消費")),
    # 面の欠け。1本ずつ選んでいると、同じマスに重なり、空いたマスが残る。
    # 検索エンジンとAIが「この分野を扱うサイト」と見るのは面の広さによる
    ("盤面の空き（業種×手法）", "coverage.py",
     re.compile(r"空いているマス")),
    # 順位は保証できないが、順位を決める要因のうちこちら側にあるものは
    # 100%満たせる。その達成率を毎週出す
    ("こちら側で決まる要因の達成率", "guarantee.py",
     re.compile(r"^  [×] |^  合計 ")),
    # 触っていない記事と比べて差が出ない施策は、続けても時間を使うだけ
    ("打った手の効き（対照群あり）", "effect_ab.py",
     re.compile(r"差が無い施策|対照群と差が無い")),
    # 競合と比べて、先月はAIの出典に出ていた語が外れた／一次データが無いと勝てない語（書き直しでは埋まらない）
    ("AIのシェアが下がった語（競合比較）", "compete.py --check",
     re.compile(r"^要対応:|^\s{2}- ")),
    # 書き直しの種類ごとの効き（28日後）。タイトル以外は当てたまま効いたかが分からなかった
    ("書き直しの効き（種類別・28日・対照群比）", "effect_ab.py --rewrites",
     re.compile(r"効かない種類")),
    # 2通りで一致しなかった計測。原因を確かめるまで、その数字は使えない
    ("計測の食い違い", "measure.py --log",
     re.compile(r"^  \d{4}-\d{2}-\d{2}")),
    # 来月つくるもの。月次レポートにも載るが、週次でも気づけるようにする
    # 使っている判断が、実際の成果を言い当てているか。
    # 当たっていない判断で記事を選ぶと、努力の向き先がずれる
    # 自己申告の点数は門にならない。別工程の採点と並べて差を見る
    ("品質スコアの実態（別工程の採点）", "score_audit.py --compare",
     re.compile(r"点を割った記事|足切り")),
    # CTAが足りない記事。読み終えた人の行き先が1つしか無いと、そこで離脱する
    ("CTAの本数", "cta_fill.py",
     re.compile(r"^   \S+\s+いま\d箇所")),
    ("判断の当たり具合", "validate_rules.py",
     re.compile(r"逆になって|成果を分けていない判断")),
    # GSCの生成AIレポートはAPIから取れない。人が月1回CSVを落とすしかないため、
    # 落とし忘れると数字が永久に空く。前月ぶんが無ければ知らせる
    ("生成AIの表示回数（手動の取り込み）", "genai_import.py",
     re.compile(r"ぶんが未取込です")),
    # 外部での言及。被リンク（0.218）よりリンク無しの言及（0.656）のほうが
    # AI検索の可視性と3倍強く相関する。消えた掲載に気づくために毎週見る
    ("外部での言及", "mentions.py --check",
     re.compile(r"消えた言及 \d+件|まだ1件も登録されていません")),
    # 指名検索。AI検索での可視性との相関 0.392 は被リンク 0.218 の約2倍
    # （Ahrefs・75,000ブランド）。引用→認知→指名検索の流れが効いているかを見る
    ("指名検索の推移", "brand_search.py",
     re.compile(r"前の28日より減っています")),
    # AIのクローラーが塞がれば、記事の中身に関係なくAI検索から消える。
    # Cloudflare が 2026-09-15 から既定でブロックする方針に変えたため、毎週見る
    ("AIクローラーの到達", "ai_crawler_check.py",
     re.compile(r"塞がっている組み合わせ|回答用のクローラーが塞がって")),
    # 図解・アイキャッチの文字が枠からはみ出す・英語が混ざる・画像が欠ける。
    # 記事の点数には出ず、読者の画面にだけ出る崩れのため、描いた元の文字列で測る
    ("画像の崩れ", "image_check.py",
     re.compile(r"^\s+(\S+: .*(はみ出します|英語だけ|項目です)|画像がありません)")),
    # 宣言した主要クエリが起点より上がったか。ページ単位の工程では
    # 「何を上げたかったのか」が残らず、上がったかどうかを後から言えない
    ("主要クエリの推移", "key_queries.py --track",
     re.compile(r"^\s+\S+（.+→.+） … ")),
    ("サイト構成の提案", "structure_plan.py",
     re.compile(r"^\s+\d+\.\d\s+(新しい|書き足し|統合)")),
    # 記事サムネイルの写真は、題名の語で棚から選ぶ。棚に無い業種・作業が増えたら知らせる
    ("記事サムネイルの写真の棚", "photo_shelf.py --check",
     re.compile(r"^SHELF_OK=no")),
    # 公開30日後の引用確認。引用0は新記事では普通なので知らせず、全件失敗（鍵・枠）だけを要対応にする
    ("新記事の公開30日後のAI引用", "ai_followup.py --report",
     re.compile(r"^要対応:")),
]

# 「問題あり」を表す印。検査ごとに語尾が違うため、値の側で見る
BAD = re.compile(r"(?:[A-Z_]+_OK=no|LIVE_CHECK=ng|KW_GATE=block|RAKKO_MONTH=over)")
GOOD = re.compile(r"(?:[A-Z_]+_OK=yes|LIVE_CHECK=ok|KW_GATE=ok|RAKKO_MONTH=ok)")
# 取れずに確かめられなかった印。終了コード0でも「問題なし」に数えない
UNKNOWN = re.compile(r"[A-Z_]+_OK=unknown|GROWTH_DROP=unknown")


# 判定はせず「情報:」の行だけを本文に添える。要対応にしないので、これだけでは通知は送られない。
# 期間のある取り組み（集中モード）は、期間外に何も出さない側で終わらせる
INFO = ["focus_report.py --line"]

# 毎週出る性質で、人が動かせないもの。新しく出ても「情報」にまとめる（理由は通知に添える）
STEADY = {
    "数字の信頼性": "直しようのない計測の事実（二重計上・国の取れない流入など）を毎週出す検査。"
                    "数字を報告する前に読む前提条件で、消す警告ではない（CLAUDE.md 8.7）",
    "盤面の空き（業種×手法）": "空いたマスは月次の report_actions が台帳へ積み、記事の枠が埋める（人の手は要らない）",
    "サイト構成の提案": "提案は月次の report_actions が台帳へ積み、記事の枠が書く（月次レポートにも載る）",
    "こちら側で決まる要因の達成率": "達成率という状態の数字。欠けた要因は週次・月次の自動の工程が直す",
    "判断の当たり具合": "判断（品質スコア・内部リンクの下限など）が成果を分けているかの検証。本数が少ないうちは"
                        "同じ結果が毎週出る。直すのは判断の基準で、毎週の作業ではない",
    "主要クエリの推移": "宣言した語の順位の推移と、割り当てた手（統合・書き直しなど週次の自動の工程）の一覧。毎週同じ語が並ぶ",
}
# 期限のあるもの。前の週と同じでも要対応のまま（遅れると取り返せない）
DEADLINE = {
    "SNS の鍵の期限（Threads・LinkedIn は60日）": "期限あり: 切れるとその間の投稿が落ちる",
    "YouTube の許可の上限（未確認アプリは累計100）": "期限あり: 上限に達すると新しい社のチャンネルをつなげない",
    "生成AIの表示回数（手動の取り込み）": "期限あり: 取り込みを忘れた月は数字が永久に空く（APIが無く、人がCSVを落とすしかない）",
    "定時の起動役（Cloudflare Worker）の起動と鍵の期限": "期限あり: 止まっている間、記事・救済・動画・週次が3〜8時間遅れて動く",
}
# 前の工程が足した行のうち、この回の仕事が失われたもの。続いていても要対応のまま
LOST = re.compile(r"作れませんでした|push|配信に落ち|反映されていません|届いていません")
# 明細の中の件数。同じ明細でも件数が増えたら「悪化」
COUNT = re.compile(r"(\d[\d,]*)\s*(?:件|本|語|組|箇所|か所|ページ)")


def norm(line):
    """数字を伏せた明細（毎週変わる順位・回数・日付で「新しい」と読まない）"""
    return re.sub(r"\s+", " ", re.sub(r"\d+(?:[.,]\d+)*", "#", str(line))).strip()


def sig(line):
    return hashlib.sha1(norm(line).encode("utf-8")).hexdigest()[:12]


def counted(lines):
    return sum(int(m.group(1).replace(",", "")) for ln in lines for m in COUNT.finditer(ln))


def notice(key, lines, seen, today, state="要対応", steady="", deadline=""):
    """要対応にするか「情報」に下げるか。(要対応か, 理由, 先に見せる明細, 次の週へ残す記録) を返す。
    seen は前の週の記録（{key: {first, sigs, n, count}}）。明細の順位・回数は伏せて比べ、件数は別に比べる"""
    prev = seen.get(key)
    all_sigs = [sig("状態:" + state)] + [sig(ln) for ln in lines]
    was = set((prev or {}).get("sigs") or [])
    new = [ln for ln in lines if sig(ln) not in was] if prev else list(lines)
    first = (prev or {}).get("first") or today
    count, n = counted(lines), len(lines)
    rec = {"first": first, "sigs": sorted(set(all_sigs))[:300], "n": n, "count": count}
    try:
        weeks = (date.fromisoformat(today) - date.fromisoformat(first)).days // 7 + 1
    except ValueError:
        weeks = 1
    rest = [ln for ln in lines if ln not in new]
    if deadline:
        return True, deadline, new + rest, rec
    if steady:
        return False, f"{weeks}週目 — {steady}", list(lines), rec
    if not prev:
        return True, "新しく出ました", list(lines), rec
    if new or not set(all_sigs) <= was:
        return True, f"新しい明細 {len(new)}件" if new else "状態が変わりました", new + rest, rec
    if count > int(prev.get("count") or 0):
        return True, f"先週より増えました（{prev.get('count')}→{count}）", list(lines), rec
    if n > int(prev.get("n") or 0):
        return True, f"先週より増えました（{prev.get('n')}→{n}件）", list(lines), rec
    return False, f"{weeks}週目・先週と同じ", list(lines), rec


def load_seen(path=None):
    try:
        return json.loads(Path(path or SEEN).read_text(encoding="utf-8")).get("items") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def save_seen(items, today, path=None):
    p = Path(path or SEEN)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": today, "items": dict(sorted(items.items()))}, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")


def compose(rows, prev, seen, today, extra_info=()):
    """通知の本文（先頭の「# 生成:」の次から）と、次の週へ残す記録を組み立てる。
    rows は [(検査名, 判定, 明細)]、prev は前の工程が足した「要対応」の行。
    返すのは (本文の行, 記録, 要対応にした数, 情報に下げた [(検査名か行, 理由)])"""
    items, act, info = {}, [], []
    for label, state, det in rows:
        if state == "問題なし":
            continue
        a, why, show, rec = notice(label, det, seen, today, state,
                                   STEADY.get(label, ""), DEADLINE.get(label, ""))
        items[label] = rec
        (act if a else info).append((state, label, why, show))
    c_act, c_info = [], []
    for ln in prev:
        key = "行:" + sig(ln)
        a, why, _, rec = notice(key, [ln], seen, today,
                                deadline="この回の仕事が失われています（続いていても要対応）" if LOST.search(ln) else "")
        items[key] = rec
        (c_act if a else c_info).append((ln, why))

    body = [ln for ln, _ in c_act]
    for state, label, why, show in act:
        body.append("%s: %s" % (state, label))     # この形は carry_over が「自分の行」と見分ける形のまま
        body.append("   （%s）" % why)
        body += ["   " + d[:80] for d in show[:3]]
    if not act and not c_act:
        quiet = not any(r[1] != "問題なし" for r in rows) and not prev
        body.append("検査%d件すべて問題なし" % len(rows) if quiet
                    else "今週あらたに対応が要るものはありません（続いているものは下の「情報」）")
    if info or c_info or extra_info:
        body.append("%s（毎週続いているもの・人が動かせないもの。急ぎではありません） ―――" % INFO_MARK)
        for state, label, why, show in info:
            body.append("情報: %s（%s%s）" % (label, "動かせず・" if state == "動かせず" else "", why))
            body += ["   " + d[:80] for d in show[:2]]
        for ln, why in c_info:
            body.append("情報: %s（%s）" % (re.sub(r"^要対応[:：]?\s*", "", ln), why))
        body += list(extra_info)
    downgraded = [(label, why) for _, label, why, _ in info] + [(ln, why) for ln, why in c_info]
    return body, items, len(act) + len(c_act), downgraded


def info_lines():
    out = []
    for script in INFO:
        if not (ROOT / "scripts" / script.split()[0]).exists():
            continue
        text, _ = run(script)
        out += [l.strip() for l in text.splitlines() if l.startswith("情報:")]
    return out


def run(script):
    """検査を1本動かして、出力と終了コードを返す。落ちても例外にしない。"""
    try:
        # 引数つきの指定（"measure.py --log"）も受ける。
        # rakko だけ特別扱いしていたため、他の検査に引数を渡せなかった
        parts = script.split()
        name, extra = parts[0], parts[1:]
        args = (["--check"] if name == "rakko.py" else []) + extra
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / name)] + args,
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
        return (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired:
        return "（%d秒で応答がありませんでした）" % TIMEOUT, 124
    except Exception as e:
        return "（起動できません: %s）" % e, 127


def judge(text, rc):
    """印を最優先で見る。印が無い検査だけ終了コードに頼る。

    印を先に見るのは、終了コードが「見つかった」と「壊れた」を
    区別できないため。実際それで一度、正常な検出を不具合と読み違えた。
    """
    if BAD.search(text):
        return "要対応"
    if UNKNOWN.search(text):
        return "動かせず"
    if GOOD.search(text):
        return "問題なし"
    if rc in (124, 127):
        return "動かせず"
    return "問題なし" if rc == 0 else "要対応"


def details(text, pat):
    seen, out = set(), []
    for ln in text.splitlines():
        s = ln.rstrip()
        if not s.strip() or not pat.search(s):
            continue
        # 表の桁揃えがそのまま通知に出ると読めない
        t = re.sub(r"[ 　]{2,}", " ", s.strip())
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def annotate(level, msg):
    """GitHub Actions の注釈。ローカルではただの1行として出る"""
    print("::%s::%s" % (level, msg.replace("\n", " ")))


def main():
    ap = argparse.ArgumentParser(
        description="週次の検査をまとめて回し、見つかったものを集める")
    ap.add_argument("--quiet", action="store_true",
                    help="各検査の生の出力を表示しない")
    ap.add_argument("--remember", action="store_true",
                    help="今回出たものを data/findings_seen.json に残す（CI では付けなくても残す）")
    a = ap.parse_args()

    rows, lines = [], []
    for label, script, pat in CHECKS:
        # 引数つき（"measure.py --log" など）も扱えるようにする。
        # 実在の判定はファイル名だけで行う
        fname = script.split()[0]
        if not (ROOT / "scripts" / fname).exists():
            rows.append((label, "動かせず", ["%s がありません" % fname]))
            continue
        print("\n===== %s（%s） =====" % (label, script), flush=True)
        text, rc = run(script)
        if not a.quiet:
            print(text.rstrip())
        state = judge(text, rc)
        rows.append((label, state, details(text, pat) if state == "要対応" else []))

    print("\n" + "=" * 60)
    print("■ 週次で見つかったもの\n")
    bad = [r for r in rows if r[1] != "問題なし"]
    for label, state, det in rows:
        mark = {"問題なし": "OK  ", "要対応": "要対応", "動かせず": "動かせず"}[state]
        print("  %s %s%s" % (mark, label,
                             "（%d件）" % len(det) if det else ""))
        for d in det[:MAX_LINES]:
            print("       " + d[:100])
        if len(det) > MAX_LINES:
            print("       …ほか%d件" % (len(det) - MAX_LINES))

    # 前の工程が追記した「要対応」（クレジット切れ・学びの棚卸し・実測など）を残す。
    # 以前は "w" で上書きしていたため、どれも通知に1件も載らなかった。
    # この検査自身が前回書いた行は持ち越さない（直っても残り続けるため）。
    # 先週分の持ち越しは、ワークフロー側がジョブの冒頭でファイルを消して防ぐ
    own = {"%s: %s" % (s, label) for label, _, _ in CHECKS for s in ("要対応", "動かせず")}
    try:
        prev, dropped = carry_over(OUT, own)
    except Exception as e:      # 持ち越しに失敗しても、今回の結果は必ず書く
        prev, dropped = [], ""
        print("  前回の要対応を読めませんでした: %s" % e)
    if dropped:
        print("  前回のファイルは%sのため、要対応を持ち越しません" % dropped)
    # いつ回した結果かを必ず先頭に書く。日付の無い記録は、古くても今の問題に見える
    lines.append("# 生成: %s JST（この時点で検査を回し直した結果）"
                 % datetime.now(JST).strftime("%Y-%m-%d %H:%M"))
    # 通知に載せる本文。Slackが読める長さに収める。要対応は新しく出た・悪化した・期限のあるものだけ
    today = datetime.now(JST).date().isoformat()
    body, items, n_act, down = compose(rows, prev, load_seen(), today, info_lines())
    lines.extend(body)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("\n  通知用に書き出しました: %s" % OUT.relative_to(ROOT))
    if down:
        print("\n■ 情報に下げたもの（毎週続いている・人が動かせない）")
        for what, why in down:
            print("  %s … %s" % (what[:60], why[:90]))
    # 前の週と比べるための記録。手元で試した回が CI の比べる相手にならないよう、CI の回だけ書く
    if os.environ.get("GITHUB_ACTIONS") or a.remember:
        save_seen(items, today)

    down_names = {what for what, _ in down}
    for label, state, det in bad:
        if label in down_names:
            annotate("notice", "%s（情報: 先週から続いている・人が動かせない）" % label)
        elif state == "動かせず":
            annotate("error", "検査が動きません: %s" % label)
        else:
            annotate("warning", "%s — %s" % (
                label, " / ".join(d[:60] for d in det[:2]) or "詳細は実行ログ"))

    print("FINDINGS=%d" % len(bad))
    print("FINDINGS_ACTION=%d" % n_act)
    return 0   # 知らせるのが仕事。ここで止めない


if __name__ == "__main__":
    sys.exit(main())
