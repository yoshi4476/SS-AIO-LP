# -*- coding: utf-8 -*-
"""2026-10-11 運用者「メールお客さんのものは大丈夫か」。お客様のメールアドレスは公開側に出ていなかったが、
問い合わせの見分け（leadAiKind_）が Gemini に送る文に、お名前と本文（中のメールアドレス・電話番号を含む）を
そのまま入れていた。見分けに要らない個人の情報は送らない（お名前は形だけ、本文の連絡先は伏せる）
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

GAS = ROOT / "automation" / "gas"

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const ctx = { console, PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) } };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
ctx.leadDetailBase_ = () => '';
const p = ctx.leadKindPrompt_('ai-lab', 'contact', { name: '山田 太郎', company: '株式会社サンプル', email: 'taro.yamada@sample.co.jp',
  tel: '090-1234-5678', message: '集客の相談です。折り返しは taro.yamada@sample.co.jp か 06-4305-7547 へ。10名の会社です。' });
const shapes = ['', 'テスト', '12345', '佐藤'].map(ctx.leadNameShape_);
console.log(JSON.stringify({ p, shapes }));
"""


def test_lead_kind_prompt_sends_no_names_or_contacts():
    print("\n■ 問い合わせの見分け: Gemini にお名前・メールアドレス・電話番号を送らない（判断に要る中身だけ）")
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため確かめられません")
        return
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "h.js"
        h.write_text(HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(h), str(GAS / "hub.gs"), str(GAS / "contact.hub.gs")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError(f"受け口を動かせませんでした: {(r.stderr or r.stdout)[-300:]}")
    o = json.loads(r.stdout.strip().splitlines()[-1])
    p = o["p"]
    check("お名前・メールアドレス（ローカル部）・電話番号は送らない",
          [w for w in ("山田", "太郎", "taro.yamada", "090-1234-5678", "06-4305-7547") if w in p], [])
    check("見分けに要る中身（本文の用件・会社名・メールのドメイン・数字）は残す",
          all(w in p for w in ("集客の相談です", "株式会社サンプル", "sample.co.jp", "10名")), True)
    check("お名前は形だけ（なし・試しの言葉・数字や記号だけ・伏せた）",
          o["shapes"], ["なし", "あり（「テスト」などの試しの言葉）", "あり（数字や記号だけ）", "あり（伏せています）"])
