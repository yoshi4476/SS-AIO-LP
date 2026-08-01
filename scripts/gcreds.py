# -*- coding: utf-8 -*-
"""Googleサービスアカウントの認証情報を読み込む（全スクリプト共通の入口）

GitHub SecretsやWindowsのエディタ経由でJSONを扱うとBOM付きになることがあり、
google-authの from_service_account_file はBOMを弾いてクラッシュする。
ここで utf-8-sig として読み、辞書から生成することで環境差を吸収する。
"""
import json
from pathlib import Path


def load(path, scopes):
    from google.oauth2 import service_account
    info = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)
