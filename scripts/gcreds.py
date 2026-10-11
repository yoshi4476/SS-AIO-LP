# -*- coding: utf-8 -*-
"""Googleサービスアカウントの認証情報を読み込む（全スクリプト共通の入口）

GitHub SecretsやWindowsのエディタ経由でJSONを扱うとBOM付きになることがあり、
google-authの from_service_account_file はBOMを弾いてクラッシュする。
ここで utf-8-sig として読み、辞書から生成することで環境差を吸収する。

AI（claude）が動く手順では、同じ場所に鍵ではなく「読むだけ・1時間で切れる許可証」が置かれる
（agent_guard.py --lock）。鍵が置かれていると、外の文章に仕込まれた指示に従った AI が鍵ごと持ち出せる。
許可証は検索の実績（Search Console）とアクセス解析（GA4）を読む範囲だけで、台帳（Sheets）は読めない。
"""
import json
from pathlib import Path

TOKEN_TYPE = "agent_access_token"


def load(path, scopes):
    info = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if info.get("type") == TOKEN_TYPE:
        from google.oauth2.credentials import Credentials
        return Credentials(token=info["token"], scopes=info.get("scopes"))
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)
