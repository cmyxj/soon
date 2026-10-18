#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游戏资讯爬虫 —— 生成 games.json 供网页读取。

数据源：
  1. IGDB 官方 API（推荐）：拉「未来 N 天即将发售」的游戏，按热度(popularity)降序，
     设置阈值区分【大作区】与【普通区】，封面图走官方 CDN 外链。
  2. 限时白嫖：手动维护 free-data.json（Epic/GOG/Steam 限免，自动抓取后续版本接入）。

用法：
  python crawler.py                 # 真实抓取（需先在 config.json 填 IGDB client_id / client_secret）
  python crawler.py --demo          # 无 key 演示：用内置示例生成同结构 json，跑通整条链路
输出：
  crawler/output/games.json
"""
import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
FREE_PATH = os.path.join(BASE, "free-data.json")
OUT_PATH = os.path.join(BASE, "output", "games.json")

IGDB_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_API_URL = "https://api.igdb.com/v4/games"
COVER_URL = "https://images.igdb.com/igdb/image/upload/t_cover_big_2x/{image_id}.jpg"


# ---------- 配置 ----------
def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------- IGDB 客户端 ----------
def get_igdb_creds(cfg):
    """取 IGDB 凭证：优先环境变量（GitHub Secrets），其次 config.json。"""
    ig = cfg.get("igdb", {}) or {}
    cid = os.environ.get("IGDB_CLIENT_ID") or ig.get("client_id")
    csec = os.environ.get("IGDB_CLIENT_SECRET") or ig.get("client_secret")
    return cid, csec


def igdb_token(cid, csec):
    """换取 IGDB 访问令牌（Twitch OAuth）。Twitch 端点必须用 POST 提交参数。"""
    body = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csec,
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        IGDB_TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def igdb_query(cid, token, body):
    """向 IGDB /games 端点发送 Apicalypse 查询。IGDB 要求 Content-Type: text/plain。"""
    req = urllib.request.Request(
        IGDB_API_URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Client-ID": cid,
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Content-Type": "text/plain",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"[IGDB ERROR] HTTP {e.code}: {detail}", file=sys.stderr)
        raise


# ---------- 字段处理 ----------
def map_platforms(abbrs):
    """IGDB 平台缩写 -> 页面用到的键(pc/ps/xbox/sw)。"""
    out = set()
    for a in abbrs or []:
        aa = a.lower()
        if "switch" in aa:
            out.add("sw")
        elif "playstation" in aa or aa.startswith("ps"):
            out.add("ps")
        elif "xbox" in aa:
            out.add("xbox")
        elif aa in ("pc",) or any(k in aa for k in ("windows", "linux", "mac")):
            out.add("pc")
    return list(out)[:4]


def default_store(plats):
    """预购/商店按钮默认跳官方商店首页（真实预售链接后续接入）。"""
    s = {}
    if "pc" in plats:
        s["pc"] = "https://store.steampowered.com"
    if "ps" in plats:
        s["ps"] = "https://store.playstation.com"
    if "xbox" in plats:
        s["xbox"] = "https://www.xbox.com/zh-CN/games"
    if "sw" in plats:
        s["sw"] = "https://www.nintendo.com"
    return s


RETRO_KEYWORDS = ("remaster", "remake", " hd", "classic", "collection", "20th", "anniversary", "传奇", "合集", "重制")


def is_retro(name):
    ln = name.lower()
    return any(k in ln for k in RETRO_KEYWORDS)


def clamp(s, n=90):
    return (s or "").strip()[:n]


def normalize_game(raw):
    plats = map_platforms(raw.get("platforms"))
    if not plats:
        return None
    ts = raw.get("first_release_date")
    if not ts:
        return None
    date_iso = datetime.datetime.fromtimestamp(ts).isoformat()
    name = raw.get("name") or "未命名"
    retro = is_retro(name)
    genres = [g.get("name") for g in raw.get("genres", []) if g.get("name")][:2]
    cover = None
    if raw.get("cover") and raw.get("cover").get("image_id"):
        cover = COVER_URL.format(image_id=raw["cover"]["image_id"])
    return {
        "id": raw.get("id"),
        "title": name,
        "cat": "remaster" if retro else "new",
        "plats": plats,
        "tags": genres,
        "retro": retro,
        "date": date_iso,
        "desc": clamp(raw.get("summary")),
        "cover": cover,
        "store": default_store(plats),
        "popularity": raw.get("hypes") or raw.get("follows"),
        "hypes": raw.get("hypes"),
        "rating": raw.get("aggregated_rating") or raw.get("rating"),
    }


# ---------- IGDB 拉取 ----------
def fetch_upcoming(cfg, now, days_ahead, limit, cid, csec):
    token = igdb_token(cid, csec)
    body = (
        "fields name,slug,cover.image_id,platforms.abbreviation,genres.name,"
        "first_release_date,hypes,follows,aggregated_rating,rating,summary;"
        f" where first_release_date > {now} & first_release_date < {now + days_ahead * 86400};"
        " sort hypes desc;"
        f" limit {limit};"
    )
    raw_games = igdb_query(cid, token, body)
    games = []
    for g in raw_games:
        norm = normalize_game(g)
        if norm:
            games.append(norm)
    return games


# ---------- 演示数据（--demo 用，无 key 也能跑通） ----------
def demo_games():
    def mk(id_, title, plats, days, popularity, retro=False, tags=None):
        ts = int(datetime.datetime.now().timestamp()) + days * 86400
        return {
            "id": id_, "title": title,
            "cat": "remaster" if retro else "new",
            "plats": plats,
            "tags": tags or ["RPG"],
            "retro": retro,
            "date": datetime.datetime.fromtimestamp(ts).isoformat(),
            "desc": f"（演示数据）{title} 是即将发售的 {'怀旧重制' if retro else '新作'}，此处为示例描述。",
            "cover": None,
            "store": default_store(plats),
            "popularity": popularity, "hypes": None, "rating": None,
        }
    return [
        mk(9001, "星河传说 Remastered", ["ps", "xbox", "pc"], 12, 8000, retro=True, tags=["RPG", "高清重制"]),
        mk(9002, "机甲风暴 20周年合集", ["pc", "sw"], 20, 6000, retro=True, tags=["动作", "合集"]),
        mk(9003, "旧日幻境：遗迹", ["ps", "pc", "sw"], 6, 5200, tags=["探索", "3D"]),
        mk(9004, "像素王国 2", ["sw", "pc"], 26, 1500, tags=["冒险", "像素"]),
        mk(9005, "暗夜残响：导演版", ["pc"], 3, 2800, tags=["恐怖"]),
        mk(9006, "深海迷踪", ["pc"], 30, 600, tags=["解谜", "叙事"]),
    ]


# ---------- 限免数据 ----------
def load_free():
    if os.path.exists(FREE_PATH):
        with open(FREE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    return []


# ---------- 组装输出 ----------
def build(cfg):
    now = int(datetime.datetime.now().timestamp())
    days_ahead = cfg.get("days_ahead", 45)
    limit = cfg.get("limit", 60)
    threshold = cfg.get("popularity_threshold", 85)

    ig = cfg.get("igdb", {})
    cid, csec = get_igdb_creds(cfg)
    has_key = bool(cid) and bool(csec)

    if has_key:
        games = fetch_upcoming(cfg, now, days_ahead, limit, cid, csec)
        if not games:
            print("IGDB 拉取为空，改用演示数据兜底", file=sys.stderr)
            games = demo_games()
    else:
        print("未配置 IGDB key，使用 --demo 演示数据（config.json 填 key 后即为真实抓取）", file=sys.stderr)
        games = demo_games()

    big = [g for g in games if (g.get("popularity") or 0) >= threshold]
    normal = [g for g in games if (g.get("popularity") or 0) < threshold]

    payload = {
        "generated_at": datetime.datetime.now().isoformat(),
        "threshold": threshold,
        "big_count": len(big),
        "normal_count": len(normal),
        "games": big + normal,   # 前段为大作区，后段为普通区
        "free": load_free(),
    }
    return payload


def main():
    ap = argparse.ArgumentParser(description="生成 games.json")
    ap.add_argument("--demo", action="store_true", help="强制用演示数据（不依赖 IGDB key）")
    args = ap.parse_args()

    cfg = load_config()
    if args.demo:
        cfg["igdb"] = {}   # 强制走演示数据，但保留 config 的热度阈值

    payload = build(cfg)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("已生成:", OUT_PATH)
    print(f"大作区 {payload['big_count']} 款 | 普通区 {payload['normal_count']} 款 | 白嫖 {len(payload['free'])} 款")
    print(f"热度阈值: popularity >= {payload['threshold']}")


if __name__ == "__main__":
    main()
