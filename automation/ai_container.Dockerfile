# 不具合を直す AI（自動修復）と、その検証を動かすコンテナ（2026-10-11 の点検）。
# ランナーのプロセス・ファイル・docker に届かない場所で動かし、終われば中の処理はすべて消える。
# 使う側: .github/workflows/selfheal.yml の repair、.github/workflows/agent-jail-check.yml の repair-container
# 作り方: requirements.txt と一緒に空のフォルダへ写して docker build する（リポジトリ全体を送らない）
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update -qq && apt-get install -y -qq --no-install-recommends git fonts-noto-cjk > /dev/null \
 && rm -rf /var/lib/apt/lists/* && npm install -g --silent @anthropic-ai/claude-code
COPY requirements.txt /tmp/requirements.txt
RUN pip install --quiet --no-cache-dir -r /tmp/requirements.txt
