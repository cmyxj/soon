#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地自检：模拟 http 部署形态，验证 games.json 可访问且字段与网页对齐。
用法：python serve_check.py <站点根目录>
"""
import json
import sys
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

def check_html_and_json():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    import os
    os.chdir(ROOT)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    base = f"http://127.0.0.1:{port}"
    html = "soon.html"

    with urllib.request.urlopen(base + "/" + urllib.parse.quote(html), timeout=10) as r:
        html_ok = r.status == 200
    with urllib.request.urlopen(base + "/games.json", timeout=10) as r:
        data = json.load(r)
    server.shutdown()

    required = {"id", "title", "plats", "cat", "retro", "date", "desc", "cover", "store", "tags"}
    games = data.get("games", [])
    ok = html_ok and all(required <= set(g) for g in games) if games else html_ok
    print(f"HTML 可访问: {html_ok}")
    print(f"games.json: 大作区 {data.get('big_count')} / 普通区 {data.get('normal_count')} / 白嫖 {len(data.get('free', []))}")
    print(f"游戏字段齐全: {all(required <= set(g) for g in games) if games else False}  (共 {len(games)} 款)")
    print(f"字段示例: {sorted(games[0].keys()) if games else '无'}")
    return 0 if (html_ok and games) else 1

if __name__ == "__main__":
    import urllib.parse
    sys.exit(check_html_and_json())
