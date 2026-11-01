# Design Rules — 视觉规划规则

## 信息密度

- 一个 section 一个核心信息，3~6 个块为宜；
- prose 布局的 text 块建议 ≤ 3 段；超过就拆 section 或改用 cards；
- KPI 不超过 6 个，超过就砍——"什么都重要等于什么都不重要"。

## 布局节奏

1. 相邻 section 尽量换布局 + 交替 `alt` 背景；
2. 全篇 prose = 失败；至少出现 2 种非 prose 布局；
3. hero 只有一个（首个 section），conclusion 只有一个（收尾）；
4. 图表多的 section 用 `chart-focus` + `wide: true`。

## 标题

- section title 写**观点**（action title），不写话题：
  - ✗ "系统概述" → ✓ "三层架构把响应时间压到 40ms"
  - ✗ "数据分析" → ✓ "Q4 流量增长 58%，移动端首次过半"
- kicker 用于章节分类标签（如"背景 / 方案 / 数据 / 风险 / 计划"）。

## 语义色

- 主题 token 已定义 chart-1~6 序列；同一篇报告中**同一含义只用同一颜色**（如"收入"始终 chart-1）；
- KPI 的 `trend` 是箭头方向、`good` 是颜色好坏，两者解耦：**"下降即改善"的指标**（响应时长、故障率、成本）要写 `"trend": "down", "good": true`，避免"改善却标红"。

## 图表诚实（ADR-009）

- 缺失数据 = null，折线断线呈现；
- 截取过的时间窗口、非零基线的柱状图都要在 caption 或 dataNote 说明；
- 示意/估算数据必须 dataNote 标注，不允许静默混入真实数据。

## 内容真实性

- 所有数字必须能在素材里找到出处；素材没有数据就别造图表，改用 cards 表达定性结论。
