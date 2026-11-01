# Block Reference — report-plan.json 全量块类型

> 组装 plan 时的必读参考。所有 `content` 字段只允许 Markdown 字符串（禁止 HTML）；
> `id` 规范 `^[a-z0-9]+(-[a-z0-9]+)*$`，全文档唯一。

## 骨架

```json
{
  "meta": {
    "title": "报告标题",            // 必填
    "subtitle": "副标题",
    "author": "署名",
    "date": "2026-11",
    "theme": "minimal",             // minimal | corporate | tech，必填
    "lang": "zh-CN",
    "schemaVersion": "0.1",
    "footer": "页脚文字（可选，默认自动生成）"
  },
  "sections": [ ... ]
}
```

## section

```json
{ "id": "data-analysis", "layout": "chart-focus", "kicker": "数据",
  "title": "标题（写观点）", "subtitle": "可选副标题",
  "alt": false, "wide": false, "blocks": [ ... ] }
```

- `layout`：hero / prose / two-col / cards / kpi / chart-focus / timeline / conclusion
- `alt: true` 用交替背景色（相邻 section 视觉区分）
- `wide: true` 宽内容区（大图表/表格用）

## 块类型（13 种）

### text — Markdown 正文
`{"id": "...", "type": "text", "content": "**加粗**、`代码`、[链接](#)、列表都支持"}`

### heading — 小节标题
`{"type": "heading", "level": 2, "content": "实现细节"}`（level 2 或 3）

### list — 列表
`{"type": "list", "ordered": true, "items": ["第一", "第二"]}`

### quote — 引用
`{"type": "quote", "content": "引文", "cite": "出处"}`

### callout — 重点提示
`{"type": "callout", "tag": "风险", "content": "Markdown 内容"}`（tag 默认"要点"）

### code — 代码块
`{"type": "code", "language": "python", "caption": "可选说明", "content": "print('hi')"}`

### image — 图片（严格离线）
`{"type": "image", "src": "assets/arch.png", "alt": "架构图", "caption": "可选", "maxWidth": "80%"}`
src 只允许本地路径或 data: URI，**禁止 http(s)**。

### kpi — 指标卡片（1~6 个）
```json
{"type": "kpi", "items": [
  {"label": "可用性", "value": "99.95%", "delta": "同比 +0.05%", "trend": "up"},
  {"label": "故障时长", "value": "3.2h", "delta": "环比 -1.1h", "trend": "down", "good": true},
  {"label": "节点数", "value": "12"}
]}
```
- `trend`：箭头**方向**（up ▲ / down ▼ / flat）
- `good`：颜色**好坏**（true 绿 / false 红），默认 up=绿、down=红
- 指标"下降即改善"的场景（响应时长、故障率、成本）必须显式 `"good": true`，否则会出现"改善却标红"的语义错误。

### chart — 图表（构建期渲染 SVG，零运行时）
```json
{"type": "chart", "chartType": "bar", "caption": "季度请求量",
 "unit": "万", "dataNote": "数据来源：监控平台",
 "data": {"labels": ["Q1","Q2"], "values": [120, 158]}}
```
- 单序列：`data.values`；多序列（bar/line）：`data.series: [{"name":"P50","values":[...]}]`
- **缺失值用 null**（折线自动断线呈现，禁止编造补齐）
- chartType: bar（对比）/ line（趋势）/ donut（占比）

### table — 表格
`{"type": "table", "columns": ["模块","状态"], "rows": [["渲染器","已实现"]]}`

### timeline — 时间线（2+ 项）
`{"type": "timeline", "items": [{"time": "Q4", "title": "上线", "desc": "说明"}]}`

### cards — 要点卡片（2~6 张）
`{"type": "cards", "items": [{"icon": "🚀", "title": "性能", "content": "Markdown"}]}`

### columns — 双栏对比
`{"type": "columns", "cols": ["左栏 Markdown", "右栏 Markdown"]}`

## 图表选型速查

| 问题 | 用什么 |
|---|---|
| 几个类别的数量对比 | bar |
| 随时间变化/趋势 | line（多指标用 series） |
| 占比构成 | donut |
| 单个关键数字 | kpi（不是图表） |
| 计划/里程碑 | timeline |
| 优劣对比 | columns 或 table |
