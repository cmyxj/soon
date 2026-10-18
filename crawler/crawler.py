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
def map_platforms(plats):
    """IGDB 平台 -> 页面键(pc/ps/xbox/sw)。plats 可能是 [{abbreviation/name}] 或 ["PC"]。"""
    out = set()
    for p in plats or []:
        if isinstance(p, str):
            abbr = p
        else:
            abbr = (p or {}).get("abbreviation") or (p or {}).get("name") or ""
        aa = (abbr or "").lower()
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


# 热门游戏中文名映射（IGDB 返回英文名，这里转成中文；未收录的保持英文）
ZH_TITLES = {
    "Grand Theft Auto VI": "侠盗猎车手 VI",
    "Grand Theft Auto VI: Ultimate Edition": "侠盗猎车手 VI：终极版",
    "Phantom Blade Zero": "影之刃零",
    "The Legend of Zelda: Ocarina of Time": "塞尔达传说：时之笛",
    "Call of Duty: Modern Warfare 4": "使命召唤：现代战争 4",
    "Final Fantasy Resonance": "最终幻想：共鸣",
    "The Wolf Among Us Remastered": "我们身边的狼：重制版",
    "Age of Empires IV: Raiders of the North": "帝国时代 IV：北方入侵者",
    "Godzilla: Destroy All Monsters Melee Remastered": "哥斯拉：毁灭全怪兽混战 重制版",
    "Sonic Pico Park": "索尼克：皮克公园",
    "One Piece: Grand Gourmet": "海贼王：大美食家",
    "World of Warcraft: Forever": "魔兽世界：永恒",
    "Nintendo Switch Sports Resort": "Nintendo Switch 运动度假村",
    "Croc 2: Kingdom of the Gobbos": "鳄鱼小顽皮 2：哥布林王国",
    "Gothic 3 Classic": "哥特王朝 3 经典版",
    "Remothered: Red Nun's Legacy": "雷莫茜德：红修女的遗产",
    "We Were Here Tomorrow": "我们曾在这里：明日",
    "Terrible Lizards": "恐怖蜥蜴",
    "Nocturnal II": "暗夜 2",
    "Hope in the City": "城市之光",
    "Warhammer Survivors": "战锤：幸存者",
    "Star Trek: Outposts Unknown": "星际迷航：未知前哨",
    "The Mailroom": "地狱邮件室",
    "Night Plane": "夜航班机",
    "Lost Host": "迷途小车",
    "Milki Delivery": "送奶记",
    "Am I Nima": "我是尼玛吗",
    "Trees Hate You": "树与你为敌",
    "Demon Bluff": "恶魔虚张声势",
    "Portabellows": "蘑菇大餐",
    "Hunter's Moon": "猎人之月",
    "Appulse": "脉冲弹珠",
    "Queen's Domain": "女王领域",
    "Lacey's Flash Games": "莱西的闪存游戏",
    "Cat Secretary": "猫咪秘书",
    "Neo Junk City": "新垃圾城",
    "Chivalware": "骑士拼图",
    "Wilderdark": "荒野暗夜",
    "Curse of Resthaven": "雷斯特港的诅咒",
    "Where the Seeds Fall": "种子飘落之处",
    "Stupid Never Dies": "蠢蛋永存",
    "Cozy Game Restoration": "温馨游戏修复师",
    "Wielders of the Essence": "精华之刃",
    "Virtue and a Sledgehammer": "美德与大锤",
    "Tom the Postgirl": "邮差女孩汤姆",
    "Hela: Of Mice & Magic": "赫拉：小鼠与魔法",
}

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
    title = ZH_TITLES.get(name, name)
    retro = is_retro(name)
    genres = [g.get("name") for g in raw.get("genres", []) if g.get("name")][:2]
    cover = None
    if raw.get("cover") and raw.get("cover").get("image_id"):
        cover = COVER_URL.format(image_id=raw["cover"]["image_id"])
    return {
        "id": raw.get("id"),
        "title": title,
        "title_en": name if name != title else None,
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


# ---------- 组装输出 ----------
def build(cfg):
    now = int(datetime.datetime.now().timestamp())
    days_ahead = cfg.get("days_ahead", 45)
    limit = cfg.get("limit", 60)
    top_n = cfg.get("top_n", 15)            # 精选总条数
    min_hypes = cfg.get("min_hypes", 8)     # 最低热度门槛（IGDB hypes 尺度）
    big_hypes = cfg.get("big_hypes", 120)   # 大作区门槛（hypes）

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

    def _hot(g):
        return g.get("hypes") or g.get("popularity") or 0

    # 精选：按热度降序，过滤冷门，只取前 top_n 款（宁缺毋滥）
    games = sorted(games, key=_hot, reverse=True)
    hot = [g for g in games if _hot(g) >= min_hypes][:top_n]

    # 大作区（高热度）与「更多精选」区
    big = [g for g in hot if _hot(g) >= big_hypes]
    normal = [g for g in hot if _hot(g) < big_hypes]

    payload = {
        "generated_at": datetime.datetime.now().isoformat(),
        "min_hypes": min_hypes,
        "top_n": top_n,
        "big_hypes": big_hypes,
        "big_count": len(big),
        "normal_count": len(normal),
        "games": big + normal,   # 前段为大作区，后段为更多精选区
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
    print(f"大作区 {payload['big_count']} 款 | 更多精选 {payload['normal_count']} 款")
    print(f"精选规则: hypes >= {payload['min_hypes']}，取前 {payload['top_n']} 款")


if __name__ == "__main__":
    main()
