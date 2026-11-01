---
name: visual-report
description: 把 Markdown / 项目素材生成精美的单文件离线 HTML 图文报告（含图表、KPI、时间线、目录导航、打印导出）。当用户要求"生成报告 / 项目汇报 / 阶段总结 / 图文文档 / 把 md 转成好看的 HTML"，且素材超过 3 段或 1 个文件时使用。不适用于：单页幻灯片/演示文稿（暂未支持）、只要纯文本摘要、单文件代码修改。
---

# Visual Report

输入素材 → 内容规划 → report-plan.json → Schema 校验 → 确定性渲染 → 单文件离线 HTML。

## 核心约束（必读）

1. **你不写 HTML**。你写的是结构化的 report-plan.json，渲染由 `python -m visual_report.render` 完成。
2. **校验不过不渲染**。每次渲染前先跑 validate；失败就修 plan，绝不绕过。
3. **内容真实性**：不得编造素材中不存在的数据；示意数据必须加 `dataNote` 标注。
4. **稳定 ID**：section/block 的 id 一经生成不随意变更（后续自然语言修改依赖它定位）。
5. **严格离线**：图片只允许本地路径（构建期 base64 内嵌）或 data: URI；禁止任何 http(s) 资源。

## 工作流

```
① 理解素材          读用户给的 Markdown/目录，识别主题、受众、关键数据、适合图表化的内容
② 内容规划          确定叙事结构（背景→目标→成果→风险→计划 等），先想清楚每节说什么
③ 写 report-plan    按 references/block-reference.md 的块类型组装 JSON（示例见 examples/）
④ 第一层校验        python scripts/validate.py report-plan.json     → 必须 PASS
⑤ 渲染              python -m visual_report.render report-plan.json -o output/visual-report.html
⑥ 第二层质检        python scripts/static_check.py output/visual-report.html --json output/qa/static-check.json
                     → FAILED 必须修复重渲染；WARNING 酌情
⑦ 交付              告知用户 HTML 路径；提醒可断网打开、可浏览器打印成 PDF
```

若用户系统无 Python 依赖：`pip install markdown-it-py jsonschema`（仅两个轻量依赖）。

## 主题选择

| 主题 | 适用 |
|---|---|
| minimal | 技术方案、通用报告（默认） |
| corporate | 正式项目汇报、对上汇报 |
| tech | 技术分享、架构介绍（深色） |

用户未指定时根据内容推荐并在 plan 里写 `meta.theme`。

## 布局速查

`hero`（封面，仅首个 section）· `prose`（图文正文）· `two-col`（对比双栏）· `cards`（要点卡片）· `kpi`（指标概览）· `chart-focus`（数据图表）· `timeline`（计划/历程）· `conclusion`（结论收尾）

同一篇报告布局要有变化，禁止全部用 prose。标题写"观点"而非"话题"（✗"系统概述" ✓"三层架构将响应时间降低 40%"）。

## Reference 路由表

| 主题 | 文件 | 何时加载 |
|---|---|---|
| 全部块类型 + report-plan 完整示例 | references/block-reference.md | 组装 plan 时（必读） |
| 设计规则（信息密度、语义色、图表选型） | references/design-rules.md | 视觉规划时 |
| 修改已有报告 | 本文件"修改流程"节 | 用户要求改报告时 |

## 修改流程（生成过的报告）

用户用自然语言提修改时：
1. 找到该报告的 report-plan.json（与 HTML 同目录或 `.visual-report/` 下）；
2. **只改受影响的 section/block 节点**（按 ID 定位），禁止整体重写 plan；
3. 重新走 ④⑤⑥（校验 → 渲染 → 质检）；
4. 向用户说明改了哪些节点。

## 反模式（不要做）

- ✗ 直接手写或拼接 HTML 字符串
- ✗ 编造素材里没有的数字凑图表
- ✗ 所有 section 用同一种布局
- ✗ 在 plan 的 content 字段里写 HTML 标签（只允许 Markdown）
- ✗ 引用外链图片/字体/脚本
- ✗ 用户要幻灯片/演示文稿时强行用本工具（明确告知：幻灯片模式在路线图 Phase 4）
