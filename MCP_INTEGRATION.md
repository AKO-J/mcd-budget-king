# MCP 集成说明

## 使用的 MCP Server

- **名称**：`mcd-mcp`（麦当劳中国官方 MCP）
- **地址**：`https://mcp.mcd.cn`
- **协议**：Streamable HTTP
- **认证**：`Authorization: Bearer <MCD_MCP_TOKEN>`，Token 从麦当劳 MCP 开放平台（`https://open.mcd.cn/mcp`）手机号登录后在控制台激活获取
- **WorkBuddy 接入**：在 WorkBuddy「专家·技能·连接器 → 自定义连接器 → 配置 MCP」中填入 `mcp-config.example.json` 内容并启用

## 使用的 Tool（已实测，2026-10-10）

- `query-nearby-stores`：按城市（默认"温州"）查找一家到店自取门店，拿到 `storeCode`
- `query-meals`：用 `storeCode`（`orderType=1` 到店，`beType=1` 到店自取）拉取该门店餐品列表，取每个餐品的 `name` / `currentPrice`（现价）/ 所属分类

工具通过 `tools/list` 动态发现。本项目只调用**只读**的菜单/价格查询工具，不创建订单、不触及支付。任一步骤失败自动回退本地示例菜单。

## 调用流程

```text
用户输入预算/需求
  → 检查 MCD_MCP_TOKEN 是否存在
  → 连接 https://mcp.mcd.cn，tools/list 发现可用工具
  → 调用菜单查询工具，获取商品名称 / 品类 / 价格（及营养信息，如有）
  → 归一化为内部结构 {id, name, category, price, satiety}
  → 组合优化求解（吃饱模式：0-1 背包 DP；省钱模式：按品类取最低价）
  → 输出推荐组合 + 总价 + 饱腹度
  → 任一步骤失败 → 回退本地 menu.json 示例菜单并明确提示数据来源
```

## 业务价值

- **实时性**：价格与供应随 MCP 实时数据变化，避免写死菜单导致的推荐过期
- **准确性**：优化器基于真实价格求解，"最划算"结论可验证，而非 LLM 幻觉
- **安全边界**：只读调用，不下单；Token 走环境变量，不进仓库（见 CONTEST_DECLARATION.md 信息安全声明）

## 降级策略

MCP 不可用（无 Token、网络失败、工具变更）时，自动使用 `menu.json` 本地示例菜单完成演示，并在输出中标注数据来源。核心优化逻辑与数据源解耦，切换不影响求解。
