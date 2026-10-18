#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
白嫖爬虫 —— 生成 free.json 供网页「限时白嫖专区」读取。

数据源：
  1. Epic 每周免费（官方 API，自动抓取）
  2. GOG / Steam 等手动维护（free-data.json 补充）

输出：crawler/output/free.json

用法：
  python free-crawler.py
"""
import datetime
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
FREE_PATH = os.path.join(BASE, "free-data.json")
OUT_PATH = os.path.join(BASE, "output", "free.json")
EPIC_FREE_URL = ("https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
                 "?locale=zh-CN&country=CN&allowCountries=CN")


def fetch_epic_free():
    """抓取 Epic 当前免费游戏（100% off），返回 free 条目。"""
    req = urllib.request.Request(EPIC_FREE_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[Epic] 拉取失败: {e}", file=sys.stderr)
        return []
    elements = (((data or {}).get("data") or {}).get("Catalog")
                or {}).get("searchStore", {}).get("elements", [])
    now = int(datetime.datetime.now().timestamp())
    out = []
    for it in elements:
        promo = it.get("promotions") or {}
        offers = ((promo.get("promotionalOffers") or []) +
                  (promo.get("upcomingPromotionalOffers") or []))
        free_offer = None
        for grp in offers:
            for off in grp.get("promotionalOffers", []):
                if (off.get("discountSetting") or {}).get("discountPercentage") == 100:
                    free_offer = off
        price = ((it.get("price") or {}).get("totalPrice") or {})
        if free_offer is None and price.get("discountPrice") == 0:
            for grp in (promo.get("upcomingPromotionalOffers") or []):
                for off in grp.get("promotionalOffers", []):
                    free_offer = off
        if not free_offer:
            continue
        end_raw = free_offer.get("endDate")
        start_raw = free_offer.get("startDate") or it.get("effectiveDate")
        if not end_raw:
            continue
        try:
            end = datetime.datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            start = (datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                     if start_raw else None)
        except Exception:
            continue
        end_ts = int(end.timestamp())
        if end_ts <= now:
            st = "over"
        elif start and int(start.timestamp()) > now:
            st = "soon"
        else:
            st = "avail"
        slug = (it.get("urlSlug") or
                ((it.get("catalogNs") or {}).get("mappings") or [{}])[0].get("pageSlug") or "")
        url = ("https://store.epicgames.com/zh-CN/p/" + slug if slug
               else "https://store.epicgames.com/zh-CN/free-games")
        out.append({
            "title": it.get("title"),
            "platform": "epic",
            "st": st,
            "start": start.isoformat() if start else None,
            "end": end.isoformat(),
            "url": url,
            "note": "Epic 每周免费",
        })
    order = {"avail": 0, "soon": 1, "over": 2}
    return sorted(out, key=lambda x: order.get(x["st"], 9))


def load_free():
    if os.path.exists(FREE_PATH):
        with open(FREE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    return []


def main():
    free = fetch_epic_free() + load_free()
    seen = set()
    dedup = []
    for f in free:
        key = (f.get("title"), f.get("platform"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(f)
    payload = {
        "generated_at": datetime.datetime.now().isoformat(),
        "free": dedup,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    avail = sum(1 for x in dedup if x.get("st") == "avail")
    print("已生成:", OUT_PATH)
    print(f"白嫖 {len(dedup)} 款 | 可领取 {avail} 款")


if __name__ == "__main__":
    main()
