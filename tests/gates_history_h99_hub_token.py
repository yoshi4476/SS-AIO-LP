# -*- coding: utf-8 -*-
"""2026-10-12: 記事を書く AI に渡していた管制塔の「AI 用の合言葉」（HUB_AGENT_SECRET）は、全社の狙う語の台帳に書けて、
全社（お客様の社を含む）の語の一覧も読めた。AI は外の文章を読むので、仕込まれた指示に従えば別のお客様の語を読み出せる。
その回の社だけに効く使い捨ての通行証（scripts/hub_token.py）に置き換えた（お客様どうしの守秘）。

- Python で作った通行証を、管制塔（hub.gs）がそのまま通す（同じ署名・同じ照合。agentPass_ と hub_token.verify）
- 期限切れ・署名違い・書き換え・別の社への書き込み・公開済みの取り下げ（force）・読めない社の次の語・1日の量の上限超え・
  合言葉そのもの・空の鍵で作った署名は通さない
- 一覧（all_kw・kw_overlaps）は読める社の行だけ。食い合いの確かめ・重複の知らせ・次の語の注意に、読めない社の語を出さない
  （AI が送る組をそのまま使うと「別の社が持つ語なら止まる」で語を1文字ずつ当てられる）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"
HUB = GAS / "hub.gs"
HARNESS = ROOT / "tests" / "gas_leads_harness.js"
AGENT = "agent-test-secret-0123456789abcd"
ZZ, YY = "client-zz", "client-yy"          # 架空のお客様（ZZ が通行証の回の社、YY は別のお客様）
OWN = ["ai-lab", "corporate"]
KW_HEAD = ["サイト", "キーワード", "状態", "優先度", "想定カテゴリ", "狙い", "登録日", "着手日", "公開日", "記事URL", "備考"]
OV_HEAD = ["日時", "語", "社A", "地域A", "社B", "地域B", "状態", "備考"]


def _kw(site, kw, st="未着手", url=""):
    return [site, kw, st, "A", "", "", "2026-10-01", "", "", url, ""]


def _tabs():
    return {"KW台帳": [KW_HEAD, _kw(ZZ, "歯科 集客 費用"), _kw(ZZ, "歯科 集客 事例", "公開済み", "https://zz.example/a/"),
                       _kw(YY, "外壁塗装 費用"), _kw(YY, "歯科 集客 費用", "公開済み", "https://yy.example/b/"),
                       _kw(OWN[0], "aio 対策")],
            "KW重複の確認": [OV_HEAD, ["2026-10-01", "歯科 集客 費用", ZZ, "", YY, "", "未確認", ""],
                          ["2026-10-01", "aio 対策", OWN[0], "", ZZ, "", "未確認", ""]],
            "エラーログ": [["日時", "サイト", "工程", "エラー内容", "対応", "状態"]]}


def _run(plan, agent=AGENT):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        hp = Path(d) / "hub.gs"
        hp.write_text(HUB.read_text(encoding="utf-8").replace("'AGENT_SECRET_XXXXXXXX'", f"'{agent}'"), encoding="utf-8")
        r = subprocess.run([node, str(HARNESS), str(hp), str(GAS / "contact.hub.gs")], input=json.dumps(plan, ensure_ascii=False),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError(f"受付を動かせませんでした: {(r.stderr or r.stdout)[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _zz(**kw):
    import hub_token as HT
    return HT.mint([ZZ], [ZZ] + OWN, secret=AGENT, **kw)


def _sites(x):
    """応答に出てきた社の id（入れ子の中も）"""
    out = set()

    def walk(v):
        if isinstance(v, dict):
            for k, y in v.items():
                if k in ("site", "site_a", "site_b") and isinstance(y, str):
                    out.add(y)
                walk(y)
        elif isinstance(v, list):
            for y in v:
                walk(y)
    walk(x)
    return out


def test_python_token_passes_gas_and_both_judge_alike():
    print("\n■ 通行証: Python で作った通行証を管制塔がそのまま通し、悪い通行証は Python と管制塔の両方が同じく断る")
    import hashlib
    import hmac
    import time
    import hub_token as HT
    now = time.time()
    good = _zz()
    body, sig = good.rsplit("~", 1)
    f = good.split("~")
    unsigned = lambda b, key=AGENT: b + "~" + hmac.new(key.encode(), b.encode(), hashlib.sha256).hexdigest()
    cases = {
        "良い通行証": good,
        "期限切れ": _zz(now=now - 9 * 3600),
        "別の鍵の署名": HT.mint([ZZ], [ZZ], secret="another-secret-0123456789"),
        "書ける社を書き換え（署名はそのまま）": "~".join([f[0], f"{ZZ},{YY}", f[2], f[3], sig]),
        "期限を延ばす（署名はそのまま）": "~".join([f[0], f[1], f[2], str(int(f[3]) + 86400), sig]),
        "区切りの数が違う": body,
        "大文字の署名": body + "~" + sig.upper(),
        "全角の数字の期限": unsigned("~".join([f[0], f[1], f[2], "１" * 10])),
        "社の id に使えない文字": unsigned("~".join([f[0], "a b", f[2], f[3]])),
        "版が違う": unsigned("~".join(["v2", f[1], f[2], f[3]])),
        "合言葉そのもの": AGENT,
    }
    out = _run({"calls": [["agentPass_", t] for t in cases.values()]})
    if out is None:
        print("  WARN  node が無いため管制塔の照合は確かめられません")
        return
    gas = dict(zip(cases, out["calls"]))
    py = {k: HT.verify(t, AGENT) for k, t in cases.items()}
    check("通るのは良い通行証だけ（管制塔）", [k for k, v in gas.items() if v], ["良い通行証"])
    check("通るのは良い通行証だけ（Python の verify）", [k for k, v in py.items() if v[0]], ["良い通行証"])
    g = gas["良い通行証"] or {}
    check("管制塔と Python で、書ける社・読める社が同じ（読める社に書ける社を含む）",
          (g.get("w"), sorted(set(g.get("r") or [])), py["良い通行証"][1], sorted(set(py["良い通行証"][2]))),
          ([ZZ], sorted([ZZ] + OWN), [ZZ], sorted([ZZ] + OWN)))
    empty = unsigned("~".join([f[0], f[1], f[2], f[3]]), key="")
    out2 = _run({"calls": [["agentPass_", empty], ["agentPass_", good]]}, agent="")
    check("鍵が空のまま配られた管制塔は、空の鍵で作った署名も通さない（誰でも作れるため）", out2["calls"], [None, None])
    try:
        HT.mint([ZZ], [ZZ], secret="short")
        short = "作れた"
    except ValueError:
        short = "断った"
    check("短い鍵では通行証を作らない", short, "断った")


def test_token_reaches_only_its_own_site():
    print("\n■ 通行証: 書けるのはその回の社だけ・読めるのは読める社の行だけ・合言葉そのものは通らない")
    tok = _zz()
    ctx_lie = {"groups": {ZZ: "g", YY: "g", OWN[0]: "g"}}      # AI が全社を同じ組と偽る
    posts = [
        {"action": "add_kw", "secret": tok, "site": ZZ, "keywords": ["新しい語"]},                       # 0 書ける社
        {"action": "kw_conflict", "secret": tok, "site": ZZ, "keyword": "外壁", "ctx": {}},               # 1 前方一致で当てる
        {"action": "claim_kw", "secret": tok, "site": ZZ, "keyword": "歯科 集客 費用", "ctx": {}},         # 2 別のお客様と同じ語
        {"action": "add_kw", "secret": tok, "site": ZZ, "keywords": ["外壁塗装 費用"], "ctx": ctx_lie},   # 3 別のお客様の語
        {"action": "error_log", "secret": tok, "site": ZZ, "phase": "p", "message": "m"},                 # 4
        {"action": "add_kw", "secret": tok, "site": YY, "keywords": ["乗っ取り"]},                         # 5 別の社へ
        {"action": "error_log", "secret": tok, "site": "", "phase": "p", "message": "社なし"},             # 6
        {"action": "retire_kw", "secret": tok, "site": ZZ, "keywords": ["歯科 集客 事例"], "force": True},  # 7 公開済みを落とす
        {"action": "add_kw", "secret": AGENT, "site": ZZ, "keywords": ["合言葉"]},                        # 8 合言葉そのもの
        {"action": "next_kw", "secret": tok, "site": ZZ},                                                # 9 読む操作を POST で
        {"action": "lead_status", "secret": tok, "site": ZZ},                                            # 10 許していない操作
        {"action": "add_kw", "secret": _zz(now=0), "site": ZZ, "keywords": ["期限切れ"]},                 # 11 期限切れ
    ]
    gets = [
        {"action": "all_kw", "secret": tok},                       # 0
        {"action": "kw_overlaps", "secret": tok},                  # 1
        {"action": "next_kw", "secret": tok, "site": ZZ},          # 2
        {"action": "kw_status", "secret": tok, "site": ZZ},        # 3
        {"action": "next_kw", "secret": tok, "site": YY},          # 4 読めない社
        {"action": "next_kw", "secret": tok, "site": ""},          # 5 全社
        {"action": "kw_status", "secret": tok},                    # 6 全社の集計
        {"action": "all_kw", "secret": AGENT},                     # 7 合言葉そのもの
        {"action": "all_kw", "secret": "$SECRET"},                 # 8 全権の合言葉（これまでどおり）
    ]
    # 書く操作と読む操作は別の台帳で動かす（着手した語は次の語に出ないため）
    out = _run({"tabs": _tabs(), "show": ["KW台帳"], "posts": posts})
    if out is None:
        print("  WARN  node が無いため管制塔の動きは確かめられません")
        return
    res, g = out["results"], _run({"tabs": _tabs(), "gets": gets})["gets"]
    ledger = out["shown"]["KW台帳"][1:]
    check("書ける社へ: 語を足す・着手・食い合いの確かめ・エラーの記録ができる",
          [res[i].get("ok") for i in (0, 1, 2, 3, 4)], [True] * 5)
    check("別のお客様と同じ語・前方一致の語を送っても、応答に別のお客様の社が出ない（組を偽っても）",
          sorted(_sites([res[1], res[2], res[3]]) - {ZZ}), [])
    check("食い合いの確かめで、別のお客様の語の有無が分からない（前方一致でも着手可のまま）",
          (res[1].get("level"), res[1].get("other_site"), res[1].get("other_group")), (0, [], []))
    check("別の社への書き込み・社を名指さない記録は断る", (res[5].get("error"), res[6].get("error")), ("forbidden", "forbidden"))
    check("別の社の台帳に行が増えない", [r[1] for r in ledger if r[0] == YY], ["外壁塗装 費用", "歯科 集客 費用"])
    check("通行証では公開済みの取り下げ（force）が効かない", (res[7].get("retired"), [r[2] for r in ledger if r[1] == "歯科 集客 事例"]),
          (0, ["公開済み"]))
    check("合言葉そのもの・読む操作の POST・許していない操作・期限切れは通らない",
          [res[i].get("error") for i in (8, 9, 10, 11)], ["unauthorized"] * 4)
    check("台帳に足したのは書ける社の分だけ", [r[1] for r in ledger if r[0] == ZZ][2:], ["新しい語", "外壁塗装 費用"])
    check("全社の一覧（all_kw）は読める社の行だけ", (g[0].get("ok"), sorted(_sites(g[0]))), (True, sorted([ZZ, OWN[0]])))
    check("重複の確認（kw_overlaps）は両方の社が読める行だけ",
          [(r["site_a"], r["site_b"]) for r in g[1].get("rows", [])], [(OWN[0], ZZ)])
    check("次の語（next_kw）は読める社だけ・注意に読めない社の語を出さない",
          (g[2].get("keyword"), g[2].get("cross_site_warning"), sorted(_sites(g[2]) - {ZZ})), ("歯科 集客 費用", [], []))
    check("件数（kw_status）は読める社を名指したときだけ", (g[3].get("ok"), g[3].get("site")), (True, ZZ))
    check("読めない社・全社の次の語と全社の集計は断る", [x.get("error") for x in g[4:7]], ["forbidden"] * 3)
    check("合言葉そのものでは読めない", g[7].get("error"), "unauthorized")
    check("全権の合言葉はこれまでどおり全社を読める", sorted(_sites(g[8])), sorted([ZZ, YY, OWN[0]]))


def test_token_has_a_daily_limit():
    print("\n■ 通行証: 1日に足せる語は60・取り下げは30・着手と戻しは30まで（超えたら ok:false）")
    tok = _zz()
    add = lambda n, p: {"action": "add_kw", "secret": tok, "site": ZZ, "keywords": [f"{p}{i}" for i in range(n)]}
    posts = [add(40, "あ"), add(21, "い"), add(20, "う"),
             {"action": "retire_kw", "secret": tok, "site": ZZ, "keywords": [f"え{i}" for i in range(31)]},
             {"action": "retire_kw", "secret": tok, "site": ZZ, "keywords": [f"え{i}" for i in range(30)]},
             {"action": "unclaim_kw", "secret": tok, "site": ZZ, "keywords": [f"お{i}" for i in range(30)]},
             {"action": "claim_kw", "secret": tok, "site": ZZ, "keyword": "歯科 集客 費用"},
             add(1, "別の通行証") | {"secret": _zz(hours=7)}]
    out = _run({"tabs": _tabs(), "posts": posts, "cache": True})
    if out is None:
        print("  WARN  node が無いため管制塔の動きは確かめられません")
        return
    res = out["results"]
    check("足す: 40 → 21（超える）→ 20（ちょうど60）", [(r.get("ok"), r.get("error")) for r in res[:3]],
          [(True, None), (False, "limit"), (True, None)])
    check("取り下げ: 31 は断り、30 は通す", [(r.get("ok"), r.get("error")) for r in res[3:5]], [(False, "limit"), (True, None)])
    check("戻し30の後の着手は断る（着手と戻しで30）", [(r.get("ok"), r.get("error")) for r in res[5:7]], [(True, None), (False, "limit")])
    check("数えるのは通行証ごと（別の通行証は別に数える）", res[7].get("ok"), True)


def test_cli_scope_and_output():
    print("\n■ hub_token.py: 社の範囲・ファイル（0600）・標準出力に通行証も社の id も出さない")
    import hub_token as HT
    import sites as S
    cfg = {OWN[0]: {}, OWN[1]: {}, ZZ: {"client": True, "group": "zz"}, ZZ + "2": {"client": True, "group": "zz"},
           YY: {"client": True}, "client-xx": {"client": True, "group": "own"}}
    pub = {"pub-zz": ZZ}
    with mock.patch.object(S, "load_all", lambda: cfg), mock.patch.object(S, "own_ids", lambda: list(OWN)), \
            mock.patch.object(S, "resolve", lambda s: pub.get(s, s)), \
            mock.patch.object(S, "is_client", lambda s: bool(cfg.get(s, {}).get("client"))):
        # 組は sites.group_key（設定の group。'own' と書いても自社の組には入れない）。範囲・通行証・仕事の数え方が同じ組を見る
        got = [HT.scope_sites(s) for s in ("own", "pub-zz", YY, "client-xx", "nope")]
    check("自社の回は自社の社だけ、お客様の回は同じ組のお客様＋読むだけの自社、知らない社は作らない",
          got, [(OWN, OWN), ([ZZ, ZZ + "2"], [ZZ, ZZ + "2"] + OWN), ([YY], [YY] + OWN), (["client-xx"], ["client-xx"] + OWN), None])
    env = {k: v for k, v in os.environ.items() if k not in ("HUB_AGENT_SECRET", "GITHUB_ACTIONS")}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "sub" / "token"

        def cli(extra_env):
            return subprocess.run([sys.executable, str(ROOT / "scripts" / "hub_token.py"), "--scope", "own", "--out", str(out)],
                                  env={**env, **extra_env}, capture_output=True, text=True, encoding="utf-8", timeout=120)
        none = cli({})
        check("鍵が無ければ何も書かずに HUB_TOKEN=none・終了コード0",
              (none.returncode, none.stdout.strip().splitlines()[-1:], out.exists()), (0, ["HUB_TOKEN=none"], False))
        ok = cli({"HUB_AGENT_SECRET": AGENT})
        tok = out.read_text(encoding="utf-8") if out.exists() else ""
        own = S.own_ids()
        v = HT.verify(tok, AGENT)
        check("鍵があれば、読める社＝書ける社＝自社の社の通行証をファイルに書く",
              (ok.returncode, v[0], sorted(v[1]), sorted(v[2])), (0, True, sorted(own), sorted(own)))
        check("標準出力は印だけ（通行証・社の id を出さない）",
              (ok.stdout.strip().splitlines(), tok in ok.stdout, [s for s in own if s in ok.stdout]),
              ([f"HUB_TOKEN=ok（書ける社 {len(own)}・読める社 {len(own)}）"], False, []))
        if os.name != "nt":
            check("ファイルは本人だけが読める（0600）", oct(out.stat().st_mode & 0o777), "0o600")
        ci = cli({"HUB_AGENT_SECRET": AGENT, "GITHUB_ACTIONS": "true"})
        tok2 = out.read_text(encoding="utf-8")
        check("CI では最初に通行証を ::add-mask:: で伏せる", ci.stdout.splitlines()[:1], [f"::add-mask::{tok2}"])


def test_hub_client_sends_the_token_when_no_full_secret():
    print("\n■ hub_client: 全権の合言葉があればそれ、無ければ通行証（HUB_AGENT_TOKEN）を送る")
    import hub_client as HC
    tok = _zz()
    with mock.patch.object(HC, "HUB_SECRET", ""), mock.patch.dict(os.environ, {"HUB_AGENT_TOKEN": tok, "SITE_ID": ""}):
        a = (HC._secret() == tok, HC._token_site())
    with mock.patch.object(HC, "HUB_SECRET", "full"), mock.patch.dict(os.environ, {"HUB_AGENT_TOKEN": tok}):
        b = (HC._secret(), HC._token_site())
    check("通行証を送り、社を名指さない記録は通行証の書ける社へ・全権の合言葉があればそちら", (a, b), ((True, ZZ), ("full", "")))
