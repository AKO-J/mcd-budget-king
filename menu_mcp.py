# -*- coding: utf-8 -*-
"""从麦当劳官方 MCP (https://mcp.mcd.cn) 获取实时菜单。

调用链：query-nearby-stores（按城市找一家到店自取门店）
      → query-meals（拉该门店的餐品列表，含现价）
任意环节失败（无 Token、未装 mcp 包、网络失败、工具变更）都返回 None，
由调用方回退到本地示例菜单。绝不抛异常给上层之外的用户。
"""

import json
import os

MCP_URL = "https://mcp.mcd.cn"
# 默认查询参数：到店自取场景；门店编码在运行时优先动态查询，失败才用此兜底
_DEFAULT_STORE = {"storeCode": "3330439", "orderType": 1, "beType": 1}
_DEFAULT_CITY = "温州"


def _sanitize_no_proxy():
    """httpx2 解析 no_proxy 时，形如 [::1] 的条目会抛 InvalidURL。

    只在当前进程内剔除这类条目（其余代理配置保持不动），调用方负责恢复。
    返回 (key, 原值) 列表。
    """
    saved = []
    for key in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(key)
        if val and ("[" in val or "]" in val):
            saved.append((key, val))
            cleaned = ",".join(p for p in val.split(",") if "[" not in p and "]" not in p)
            os.environ[key] = cleaned
    return saved


def _restore_no_proxy(saved):
    for key, val in saved:
        os.environ[key] = val


def _extract_json(text):
    """从 MCP 返回的文本块里抠出真正的 JSON（前面可能带有说明文字）。"""
    start = text.find('{"success"')
    if start < 0:
        start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def _satiety_hint(name, category):
    """启发式饱腹度：仅用于排序，不代表营养价值，详见 README 注意事项。"""
    text = f"{name} {category}"
    if any(k in text for k in ("套餐", "单人餐", "全家桶", "双人餐")):
        return 10
    if any(k in text for k in ("堡", "汉堡", "鸡腿", "鸡翅", "麦乐鸡", "板烧", "鳕鱼")):
        return 8
    if any(k in text for k in ("薯条", "薯饼", "小食", "派", "玉米")):
        return 6
    if any(k in text for k in ("麦旋风", "圆筒", "圣代", "甜品")):
        return 4
    if any(k in text for k in ("可乐", "咖啡", "饮料", "茶", "牛奶", "豆浆")):
        return 2
    return 5


def _normalize_meals(data):
    """把 query-meals 的返回统一成内部结构。"""
    categories = data.get("categories") or []
    detail = data.get("meals") or {}
    items = []
    for cat in categories:
        cat_name = cat.get("name", "其他")
        for meal in cat.get("meals") or []:
            code = meal.get("code")
            info = detail.get(code) or {}
            name = info.get("name") or code or "未知餐品"
            try:
                price = float(info.get("currentPrice", 0))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            items.append({
                "id": f"mcp_{code}",
                "name": name,
                "category": cat_name,
                "price": price,
                "satiety": _satiety_hint(name, cat_name),
            })
    # 按 code 去重（同一餐品可能出现在多个分类）
    seen, uniq = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            uniq.append(it)
    return uniq


def _new_api_fetch(token, timeout):
    """基于 mcp>=2.x 的 streamable_http_client。"""
    import asyncio
    from mcp.client.streamable_http import streamable_http_client, httpx2
    from mcp import ClientSession

    async def _go():
        saved = _sanitize_no_proxy()
        try:
            client = httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                trust_env=True,
            )
            async with streamable_http_client(MCP_URL, http_client=client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}

                    async def _call(name, args):
                        result = await session.call_tool(name, args)
                        for block in result.content:
                            text = getattr(block, "text", "")
                            if not text:
                                continue
                            data = _extract_json(text)
                            if isinstance(data, dict):
                                return data
                        return None

                    store = dict(_DEFAULT_STORE)
                    if "query-nearby-stores" in names:
                        resp = await _call("query-nearby-stores", {
                            "beType": 1, "searchType": 2,
                            "city": _DEFAULT_CITY, "keyword": _DEFAULT_CITY,
                        })
                        data = (resp or {}).get("data") or []
                        if data and data[0].get("storeCode"):
                            store["storeCode"] = data[0]["storeCode"]

                    if "query-meals" not in names:
                        return None
                    resp = await _call("query-meals", store)
                    data = (resp or {}).get("data")
                    if not data:
                        return None
                    return _normalize_meals(data) or None
        finally:
            _restore_no_proxy(saved)

    return asyncio.run(_go())


def _old_api_fetch(token, timeout):
    """兼容旧版 mcp 包（streamablehttp_client，headers 直传）。"""
    import asyncio
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async def _go():
        headers = {"Authorization": f"Bearer {token}"}
        async with streamablehttp_client(MCP_URL, headers=headers, timeout=timeout) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                if "query-meals" not in names:
                    return None
                result = await session.call_tool("query-meals", _DEFAULT_STORE)
                for block in result.content:
                    text = getattr(block, "text", "")
                    if not text:
                        continue
                    data = _extract_json(text)
                    if isinstance(data, dict) and data.get("data"):
                        return _normalize_meals(data["data"]) or None
                return None

    return asyncio.run(_go())


def fetch_menu(token, timeout=20):
    """返回商品列表；失败返回 None。"""
    try:
        import mcp  # noqa: F401
    except ImportError:
        return None
    try:
        return _new_api_fetch(token, timeout)
    except Exception:
        pass
    try:
        return _old_api_fetch(token, timeout)
    except Exception:
        return None
