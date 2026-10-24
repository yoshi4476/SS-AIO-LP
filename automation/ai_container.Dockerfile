# 不具合を直す AI（自動修復）と、その検証を動かすコンテナ（2026-10-11 の点検）。
# ランナーのプロセス・ファイル・docker に届かない場所で動かし、終われば中の処理はすべて消える。
# 使う側: .github/workflows/selfheal.yml の repair、.github/workflows/agent-jail-check.yml の repair-container
# 作り方: requirements.txt と一緒に空のフォルダへ写して docker build する（リポジトリ全体を送らない）
# 元のイメージはハッシュで、道具は版で固定する（取りに行くたびに中身が変わらないように。2026-10-24 の点検）
FROM node:22-bookworm-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS node
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
COPY --from=node /usr/local/bin/node /usr/local/bin/
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update -qq && apt-get install -y -qq --no-install-recommends git fonts-noto-cjk > /dev/null \
 && rm -rf /var/lib/apt/lists/* && npm install -g --silent @anthropic-ai/claude-code@2.1.302
COPY requirements.txt /tmp/requirements.txt
RUN pip install --quiet --no-cache-dir -r /tmp/requirements.txt
