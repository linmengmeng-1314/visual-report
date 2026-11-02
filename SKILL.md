---
name: visual-report
description: 把 Markdown / 项目素材生成精美的单文件离线 HTML 图文报告或幻灯片（含图表、架构图、KPI、时间线；报告带目录导航与打印导出，幻灯片带翻页/全屏/总览/演讲备注）。当用户要求"生成报告 / 项目汇报 / 阶段总结 / 图文文档 / 宣讲 PPT / 幻灯片 / 把 md 转成好看的 HTML"，且素材超过 3 段或 1 个文件时使用。不适用于：可编辑的 .pptx 文件、只要纯文本摘要、单文件代码修改。
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
① 素材提取          素材含 md/txt/csv/json/docx/pdf 多文件时：python scripts/extract.py 素材目录/ -o .visual-report/material.md
                     → 生成带来源与数值列标记的素材摘要，基于它做内容规划（docx/pdf 需 [input] 可选依赖）
② 内容规划          确定叙事结构（背景→目标→成果→风险→计划 等），先想清楚每节说什么
③ 写 report-plan    按 references/block-reference.md 的块类型组装 JSON（示例见 examples/）
④ 风格预览（可选）  用户未指定主题且内容重要时：python scripts/preview.py report-plan.json
                     生成 5 份真实主题预览让用户挑，选定后写回 meta.theme
⑤ 第一层校验        python scripts/validate.py report-plan.json     → 必须 PASS
⑥ 渲染              python -m visual_report.render report-plan.json -o output/visual-report.html
⑦ 第二层质检        python scripts/static_check.py output/visual-report.html --json output/qa/static-check.json
                     → FAILED 必须修复重渲染；WARNING 酌情
⑧ 第三层质检（可选）已装 playwright 时：python scripts/visual_check.py output/visual-report.html
                     → 溢出/裂图检查 + 全页及分节截图存证；未装则自动跳过（不阻断）
⑨ 交付              告知用户 HTML 路径；提醒可断网打开、可浏览器打印成 PDF
```

预览真实性规则（ADR-010，强制）：预览必须是**真实内容渲染出的完整页面**；禁止占位文本；禁止在预览页面上出现 "Option A / preview / 模板" 等流程字样；用户挑的是审美，不是参数。

若用户系统无 Python 依赖：`pip install markdown-it-py jsonschema`（仅两个轻量依赖）；Python 为 uv 管理或 externally-managed（PEP 668）时改用 `uv pip install --system --break-system-packages markdown-it-py jsonschema`。

## 主题选择

| 主题 | 适用 |
|---|---|
| minimal | 技术方案、通用报告（默认） |
| corporate | 正式项目汇报、对上汇报 |
| tech | 技术分享、架构介绍（深色） |
| editorial | 研究报告、深度分析（衬线杂志风） |
| dashboard | 经营分析、指标汇报（数据驾驶舱） |

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

## 幻灯片模式

用户要宣讲/演示时，生成 slide-plan.json（结构与 report-plan 平行，`slides[]` 替代 `sections[]`）：

1. 版式：title / section / bullets / kpi / chart / diagram / quote / two-col / table / statement，一页一个核心主题；
2. 标题写结论；每页信息密度低于报告（正文 ≤ 5 条要点）；
3. 每页写 `notes`（演讲备注，按页 ID 存储不串页）；
4. 校验渲染质检与报告同一套命令（validate.py / render / static_check.py 自动识别 slides）；
5. **报告转 deck**：`python scripts/to_slides.py report-plan.json -o slide-plan.json` 生成骨架（KPI/图表/架构图直接复用），然后按宣讲时长精炼叙事——15 分钟 ≈ 10 页，禁止把长文直接切片。

## 修改流程（生成过的报告）

用户用自然语言提修改时：
1. 找到该报告的 report-plan.json（与 HTML 同目录或 `.visual-report/` 下）；
2. **只改受影响的 section/block 节点**（按 ID 定位），禁止整体重写 plan；
3. 用修订命令代替手工重渲染（自动完成：校验 → 渲染 → 质检 → 快照 → 记历史 → 失败保留旧产物）：
   ```
   python scripts/revise.py apply report-plan.json -o output/visual-report.html --note "一句话说明改了什么"
   ```
4. 向用户复述变更摘要（apply 输出的节点级 diff）；
5. 用户说"改错了/回上一版"时：`python scripts/revise.py rollback report-plan.json -o output/visual-report.html`；
6. 查看全部历史：`python scripts/revise.py log report-plan.json`。

修改意图 → 文件路由速查：文案/详略/结论 → 改对应 block 的 content；布局/图表类型/图方向 → 改 section.layout 或 block 的 chartType/diagram 节点；整体风格 → 改 meta.theme（建议先跑 preview 让用户挑）；章节增删 → 增删 section（新 section 记得分配新 ID）。有歧义先问用户，不要自行大范围改写。

## 反模式（不要做）

- ✗ 直接手写或拼接 HTML 字符串
- ✗ 编造素材里没有的数字凑图表
- ✗ 所有 section 用同一种布局
- ✗ 在 plan 的 content 字段里写 HTML 标签（只允许 Markdown）
- ✗ 引用外链图片/字体/脚本
- ✗ 用户要幻灯片/演示文稿时强行用本工具（明确告知：幻灯片模式在路线图 Phase 4）
