# -*- coding: utf-8 -*-
"""管制塔スプレッドシートの見た目を整え、文字が切れていないかを実物で検査する。

整形そのものは Apps Script の formatBook（automation/gas/format.gs）が持つ。
シートを書き換えられるのは管制塔の口だけなので、ここからは呼ぶだけにする。
Apps Script のエディタを開いて関数を選ぶ手作業を無くすためのもの。

検査は手元から読んで行う。「整えたつもりで実は切れている」を防ぐため、
書式を推測せず、実際のセルの折り返し設定と列幅を取得して突き合わせる。

  文字が切れるのは次の2つだけ。ここを不合格にする。
    - 本文セルが折り返しでない（CLIP / OVERFLOW だと右端で切れる）
    - 見出しが列幅に入らない（見出しは折り返さない運用のため切れる）
  折り返して縦に伸びるのは切れていないので、助言にとどめる。

  python scripts/sheet_format.py           # 整えてから検査
  python scripts/sheet_format.py --check   # 検査だけ（書き換えない）
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SA = ROOT / "indexing-service-account.json"

TALL = 6.0   # 折り返して何行を超えたら「広げたほうがいい」と言うか


def _px(s):
    """おおよその表示幅。日本語は全角として数える"""
    return sum(13 if ord(c) > 0x2E80 else 7 for c in str(s))


def _sheet_id():
    env = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    for k in ("HUB_SHEET_ID", "SPREADSHEET_ID"):
        m = re.search(r"^%s\s*=\s*(.+)$" % k, env, re.M)
        if m and m.group(1).strip().strip('"').strip("'"):
            return m.group(1).strip().strip('"').strip("'")
    return ""


def _api(sid):
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    c = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    c.refresh(Request())
    h = {"Authorization": "Bearer " + c.token}
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + sid

    def get(u):
        return json.load(urllib.request.urlopen(
            urllib.request.Request(base + u, headers=h), timeout=120))
    return get


def wanted_widths():
    """format.gs が定めている列幅を読む。手元の定義と実物を比べるために使う"""
    src = (ROOT / "automation" / "gas" / "format.gs").read_text(encoding="utf-8")
    block = re.search(r"const COL_WIDTH = \{(.*?)\n\};", src, re.S)
    if not block:
        return {}
    out = {}
    for m in re.finditer(r"'([^']+)'\s*:\s*\[([^\]]*)\]", block.group(1)):
        out[m.group(1)] = [int(x) for x in re.findall(r"\d+", m.group(2))]
    return out


def check(sid):
    """(切れているもの, 広げたほうがよいもの, 配信待ちのもの) を返す"""
    get = _api(sid)
    titles = [s["properties"]["title"]
              for s in get("?fields=sheets.properties.title")["sheets"]]
    rng = lambda n: "&".join(
        "ranges=" + urllib.request.quote("'%s'!A1:N%d" % (t.replace("'", "''"), n))
        for t in titles)

    # 折り返しは先頭数行を見れば足りる（formatBook は列単位で揃えるため）
    grid = get("?includeGridData=true&fields=sheets(properties.title,data("
               "columnMetadata.pixelSize,rowData(values(effectiveFormat.wrapStrategy,"
               "formattedValue))))&" + rng(4))["sheets"]
    vals = get("/values:batchGet?" + rng(300))["valueRanges"]

    want = wanted_widths()
    cut, tall, stale = [], [], []
    for s, vr in zip(grid, vals):
        title = s["properties"]["title"]
        data = s.get("data", [{}])[0]
        widths = [c.get("pixelSize", 100) for c in data.get("columnMetadata", [])]
        rows = vr.get("values") or []
        if not rows:
            continue
        heads = rows[0]

        # 1. 本文が折り返しでない列は、右端で切れる
        for r in data.get("rowData", [])[1:]:
            for i, v in enumerate(r.get("values", [])):
                if not v.get("formattedValue"):
                    continue
                w = v.get("effectiveFormat", {}).get("wrapStrategy")
                if w != "WRAP":
                    name = heads[i] if i < len(heads) else "第%d列" % (i + 1)
                    msg = "%s / %s 列が折り返しになっていません（%s）" % (title, name, w)
                    if msg not in cut:
                        cut.append(msg)

        # 2. 見出しは折り返さない運用なので、幅に入らなければ切れる
        for i, head in enumerate(heads):
            w = widths[i] if i < len(widths) else 100
            if _px(head) + 16 > w:
                cut.append("%s / 見出し「%s」が幅%dに入りません" % (title, head, w))

            longest = max((str(r[i]) for r in rows[1:] if i < len(r)), key=_px, default="")
            lines = _px(longest) / max(1, w - 12)
            if lines > TALL:
                tall.append("%s / %s 列: 最長%d字が幅%dで約%.0f行になります"
                            % (title, head, len(longest), w, lines))

        # 手元の format.gs を直しても、Apps Script へ配信するまで実物は変わらない。
        # 直したつもりで効いていない、を見えるようにする
        for i, px in enumerate(want.get(title, [])):
            actual = widths[i] if i < len(widths) else None
            if actual is not None and actual != px and i < len(heads):
                stale.append("%s / %s 列: 実物%d ← format.gs は%d"
                             % (title, heads[i], actual, px))
    return cut, tall, stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="書き換えず検査だけ")
    a = ap.parse_args()

    sid = _sheet_id()
    if not sid:
        print("HUB_SHEET_ID が .env にありません")
        return 1

    if not a.check:
        import hub_client
        if not hub_client.enabled():
            print("管制塔の口（HUB_URL / HUB_SECRET）が設定されていません")
            return 1
        r = hub_client._post({"action": "admin", "task": "format"})
        if not r.get("ok"):
            print("整形に失敗しました:", str(r)[:300])
            return 1
        print("■ 整えました")
        for line in str(r.get("result", "")).splitlines():
            if line.strip():
                print("   ", line)

    cut, tall, stale = check(sid)
    print("\n■ 文字が切れていないか")
    if cut:
        print("   SHEET_OK=no（%d件）" % len(cut))
        for x in cut[:15]:
            print("    -", x)
    else:
        print("   SHEET_OK=yes（切れている列はありません）")

    if tall:
        print("\n   参考: 縦に伸びている列（切れてはいません）")
        for x in tall[:10]:
            print("    -", x)
        print("   広げるなら automation/gas/format.gs の COL_WIDTH を直します")

    if stale:
        print()
        print("   配信待ち: format.gs の直しが、まだ実物に届いていません（%d件）"
              % len(stale))
        for x in stale[:10]:
            print("    -", x)
        print("   Apps Script のエディタで format.gs を更新すると効きます")
    return 1 if cut else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        m = re.search(r'"message"\s*:\s*"([^"]+)"', b)
        print("失敗 HTTP %s: %s" % (e.code, (m.group(1) if m else b)[:300]))
        sys.exit(1)
