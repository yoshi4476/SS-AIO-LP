# -*- coding: utf-8 -*-
"""自動修復の AI のコンテナから外へ出る通信を、許可した宛先（Claude の API）だけに絞る中継（2026-10-24 の点検）。

AI のコンテナは外へ出られない内部の網に置き、この中継だけを通す（HTTPS_PROXY）。中継は HTTPS の CONNECT だけを受け、
宛先が ALLOW にあるときだけ通す。AI が外の文章の指示で書いたコードが、claude の利用の鍵（CLAUDE_CODE_OAUTH_TOKEN）を
別の宛先へ送る道を塞ぐ。中身（TLS）は読まない・残さない。

selfheal.yml の repair が、AI の作業場の写しではなく本体の写し（ランナーの checkout）から読んで動かす。
    python scripts/egress_proxy.py [--port 3128]
"""
import argparse
import asyncio

ALLOW = {("api.anthropic.com", 443)}
LIMIT = 8192


async def pipe(r, w):
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001  閉じ損ねは無視（片側がもう閉じている）
            pass


def target(head):
    """CONNECT の1行目から宛先を読む。許可していなければ None"""
    try:
        method, where, _ = head.split(b"\r\n", 1)[0].decode("ascii").split(" ", 2)
        host, port = where.rsplit(":", 1)
        dest = (host.lower().strip("[]"), int(port))
    except (ValueError, UnicodeDecodeError):
        return None
    return dest if method == "CONNECT" and dest in ALLOW else None


async def handle(cr, cw):
    try:
        head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 15)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        cw.close()
        return
    dest = target(head)
    if dest is None:
        cw.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await cw.drain()
        cw.close()
        print("拒否: " + head.split(b"\r\n", 1)[0][:120].decode("ascii", "replace"), flush=True)
        return
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection(*dest), 15)
    except (OSError, asyncio.TimeoutError):
        cw.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await cw.drain()
        cw.close()
        return
    cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await cw.drain()
    await asyncio.gather(pipe(cr, uw), pipe(ur, cw))


async def main(port):
    srv = await asyncio.start_server(handle, "0.0.0.0", port, limit=LIMIT)
    print(f"EGRESS_PROXY=ready :{port}（許可: {', '.join(f'{h}:{p}' for h, p in sorted(ALLOW))}）", flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3128)
    asyncio.run(main(ap.parse_args().port))
