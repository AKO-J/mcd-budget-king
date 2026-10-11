#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
穷鬼点单王：预算约束下的麦当劳最优点餐

两种模式：
  吃饱模式：给定预算，在预算内选择饱腹度总分最高的商品组合（0-1 背包，DP 精确求解）
  省钱模式：给定必选品类及数量，选择总价最低的组合（每品类独立取最低价，最优性显然）

菜单优先从麦当劳 MCP (https://mcp.mcd.cn) 实时获取，失败时回退本地示例菜单。
"""

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------- 菜单加载 ----------------

def load_local_menu(path=None):
    path = path or os.path.join(BASE_DIR, "menu.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["items"]


def load_menu(use_mcp):
    """返回 (商品列表, 数据来源标注)。"""
    if use_mcp:
        token = os.environ.get("MCD_MCP_TOKEN", "").strip()
        if not token:
            print("[warn] 未设置 MCD_MCP_TOKEN，回退本地示例菜单", file=sys.stderr)
        else:
            try:
                from menu_mcp import fetch_menu
                items = fetch_menu(token)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] MCP 模块异常，回退本地示例菜单：{e}", file=sys.stderr)
                items = None
            if items:
                print(f"[info] 已从麦当劳 MCP 获取实时菜单，共 {len(items)} 件商品", file=sys.stderr)
                return items, "麦当劳 MCP 实时菜单"
            print("[warn] MCP 菜单获取失败，回退本地示例菜单", file=sys.stderr)
    return load_local_menu(), "本地示例菜单"


# ---------------- 组合优化 ----------------

def _to_jiao(yuan):
    return int(round(yuan * 10))


def knapsack_max_satiety(items, budget_yuan):
    """0-1 背包 DP：预算内最大化饱腹度。精确求解。

    同分时取总价最低。返回 (选中商品列表, 总价, 总饱腹度)。
    用二维表保证重构时每件商品至多选一次。
    """
    budget = _to_jiao(budget_yuan)
    n = len(items)
    prices = [_to_jiao(it["price"]) for it in items]
    values = [int(it["satiety"]) for it in items]

    dp = [[0] * (budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        p, v = prices[i - 1], values[i - 1]
        prev, row = dp[i - 1], dp[i]
        for w in range(budget + 1):
            best = prev[w]
            if p <= w:
                cand = prev[w - p] + v
                if cand > best:
                    best = cand
            row[w] = best

    best_sat = max(dp[n])
    best_w = min(w for w in range(budget + 1) if dp[n][w] == best_sat)
    picked, w = [], best_w
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            picked.append(items[i - 1])
            w -= prices[i - 1]
    picked.reverse()
    total_price = round(sum(it["price"] for it in picked), 2)
    total_satiety = sum(int(it["satiety"]) for it in picked)
    return picked, total_price, total_satiety


def cheapest_combo(items, requirements):
    """省钱模式：requirements 为 {品类: 数量}，每品类取最便宜的指定数量。

    各品类相互独立，贪心即最优。返回 (选中商品列表, 总价)。
    """
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    picked = []
    for cat, cnt in requirements.items():
        cands = sorted(by_cat.get(cat, []), key=lambda x: x["price"])
        if len(cands) < cnt:
            raise ValueError(f"品类「{cat}」商品不足：需要 {cnt} 件，仅有 {len(cands)} 件")
        picked.extend(cands[:cnt])
    total = round(sum(it["price"] for it in picked), 2)
    return picked, total


# ---------------- 输出 ----------------

def render(picked, total_price, total_satiety, budget, mode, source):
    lines = [f"[{mode}模式] 预算 {budget:.1f} 元（数据来源：{source}）", "推荐组合："]
    if not picked:
        lines.append("  （预算内无可选项）")
    for it in picked:
        lines.append(f"  - {it['name']} x1  {it['price']:.2f} 元  饱腹度 {it['satiety']}")
    lines.append(f"总价：{total_price:.2f} 元，剩余预算：{budget - total_price:.2f} 元")
    if total_satiety:
        lines.append(f"总饱腹度：{total_satiety}（启发式评分，仅供参考）")
    return "\n".join(lines)


def parse_need(s):
    req = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        sep = ":" if ":" in part else "：" if "：" in part else None
        if sep is None:
            raise ValueError(f"无法解析需求项：{part}（格式如 汉堡:1）")
        cat, cnt = part.split(sep, 1)
        req[cat.strip()] = int(cnt.strip())
    if not req:
        raise ValueError("省钱模式需要 --need 指定必选品类，如 \"汉堡:1,饮料:1\"")
    return req


def main(argv=None):
    ap = argparse.ArgumentParser(description="穷鬼点单王：预算约束下的麦当劳最优点餐")
    ap.add_argument("--budget", type=float, required=True, help="预算（元）")
    ap.add_argument("--mode", choices=["吃饱", "省钱"], default="吃饱", help="优化目标")
    ap.add_argument("--need", default="", help="省钱模式必选品类，如 \"汉堡:1,饮料:1\"")
    ap.add_argument("--mcp", action="store_true", help="尝试从麦当劳 MCP 获取实时菜单")
    ap.add_argument("--menu", default=None, help="本地菜单 JSON 路径（默认 menu.json）")
    args = ap.parse_args(argv)

    if args.budget <= 0:
        print("预算必须大于 0", file=sys.stderr)
        return 2

    items, source = load_menu(args.mcp)
    if args.menu:
        items, source = load_local_menu(args.menu), f"本地菜单（{args.menu}）"
    items = [it for it in items if it.get("price", 0) > 0]
    if not items:
        print("菜单为空，无法推荐", file=sys.stderr)
        return 1

    try:
        if args.mode == "吃饱":
            picked, total, satiety = knapsack_max_satiety(items, args.budget)
            if total > args.budget + 1e-9:
                print("预算过低，无可选项", file=sys.stderr)
                return 1
            print(render(picked, total, satiety, args.budget, "吃饱", source))
        else:
            req = parse_need(args.need)
            picked, total = cheapest_combo(items, req)
            if total > args.budget + 1e-9:
                print(f"最便宜的组合也要 {total:.2f} 元，超出预算 {args.budget:.1f} 元", file=sys.stderr)
                return 1
            print(render(picked, total, 0, args.budget, "省钱", source))
    except ValueError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
