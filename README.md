# Visual Report

**AI 驱动的可持续编辑型图文报告与演示文稿生成工具**：把 Markdown 和项目素材变成精美的**单文件离线 HTML**——图文报告 + 幻灯片双模式，含图表、架构图、KPI、时间线，双击即可打开，断网可用，可直接邮件发送或打印成 PDF。

> An AI-native visual content engine: structured plans → deterministic rendering → single-file offline HTML reports & slide decks.

![hero](docs/screenshots/hero.png)

![architecture](docs/screenshots/architecture.png)

![data](docs/screenshots/data.png)

*报告模式示例：[demo-report](examples/demo-report/output/visual-report.html)（企业季度报告，33KB 单文件）*

![deck](docs/screenshots/deck.png)

*幻灯片模式示例：[demo-deck](examples/demo-deck/output/visual-deck.html)（15 分钟宣讲版，方向键翻页 / F 全屏 / O 总览 / N 演讲备注）*

## 核心特性

- ✍️ **AI 写计划，程序做渲染**：Agent 产出结构化的 `report-plan.json`（JSON Schema 校验），Python Renderer 确定性渲染——相同输入永远得到相同输出，AI 不直接拼接 HTML
- 📴 **严格离线**：CSS/图表/图片全部内嵌，无 CDN、无在线字体、无运行时依赖；静态检查门禁强制保证（2MB 目标 / 5MB 硬上限）
- 📊 **构建期图表**：柱状图/折线图/环形图与**流程/架构图**（网格坐标声明式节点）在构建时渲染为静态 SVG，零 JavaScript 运行时；缺失数据自动断线呈现，不编造
- 🎨 **Token 化主题**：主题 = 一份 CSS 变量文件，内置 minimal / corporate / tech / editorial / dashboard 五套，一条命令生成全部主题的真实预览供挑选（Show-Don't-Tell）
- ✅ **三层质量门禁**：Schema 校验（ID 唯一性、白名单、离线约束）+ 静态检查（外部资源、锚点、重复 ID、弱标题、体积）+ 浏览器视觉检查（可选 Playwright：双视口溢出/裂图检测 + 全页及分节截图），不过门禁不交付
- 🖥️ **幻灯片模式**：10 种版式、1280×720 缩放画布、原生 JS 运行时（翻页/全屏/总览/进度/演讲者备注，仅 ~150 行零依赖）、报告一键转 deck 脚手架
- 🔄 **自然语言持续修改**：改的是检查点 plan 而非 HTML——`revise.py` 一键完成校验→渲染→质检→快照→节点级 diff 历史；渲染失败自动保留上一版，支持 `log` 查历史、`rollback` 一键回滚

## 快速开始

```bash
pip install markdown-it-py jsonschema   # 仅有的两个依赖

# 用示例跑通全链路
python scripts/validate.py examples/demo-report/report-plan.json          # 第一层：Schema 校验
python -m visual_report.render examples/demo-report/report-plan.json \
    -o output/report.html --base-dir examples/demo-report                # 渲染单文件 HTML
python scripts/static_check.py output/report.html                        # 第二层：静态质检
```

在 Claude Code 中作为 Skill 使用：把本仓库放入 skills 目录（或 `~/.claude/skills/visual-report`），然后：

```
/visual-report 请把当前目录的季度总结 md 生成一份图文 HTML 报告
```

## 工作流

```
素材（Markdown/项目资料）
   ↓ Agent：内容理解与叙事规划
report-plan.json（稳定 ID + 结构化块）
   ↓ scripts/validate.py（必须 PASS）
Python Renderer（布局 + 主题 + 构建期 SVG 图表 + 资源内嵌）
   ↓ scripts/static_check.py（必须非 FAILED）
output/visual-report.html —— 双击打开，断网可用，可打印成 PDF
```

## 支持的块类型

text（Markdown）/ heading / list / quote / callout / code / image（自动 base64 内嵌）/ kpi（含涨跌语义）/ chart（bar·line·donut，支持多序列与缺失值断线）/ table / timeline / cards / columns —— 详见 [references/block-reference.md](references/block-reference.md)。

报告 8 种布局：hero / prose / two-col / cards / kpi / chart-focus / timeline / conclusion；幻灯片 10 种版式：title / section / bullets / kpi / chart / diagram / quote / two-col / table / statement。

## 路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 报告生成 MVP（本仓库当前范围） | ✅ 可用 |
| Phase 2 | 更多主题与布局、架构/流程图（diagram 块）、风格预览、视觉检查 | ✅ 可用 |
| Phase 3 | 持续修改闭环（节点 diff / 快照 / 历史 / 回滚 / 失败保护） | ✅ 可用 |
| Phase 4a | 幻灯片模式（Slide Schema/Renderer/运行时/示例） | ✅ 可用 |
| Phase 4b | 多格式输入（DOCX/PDF/CSV/JSON）、Agent 生态适配、英文 README | 规划 |

**未实现的功能不在本 README 宣称范围内**（例如 DOCX/PDF/CSV 多格式输入尚未支持）。

## 项目结构

```
├── SKILL.md                    # Agent Skill 入口（工作流与行为规范）
├── references/                 # Agent 按需加载的参考文档
├── schemas/report.schema.json  # 中间格式 Schema（白名单 + ID 规范）
├── visual_report/              # Python Renderer
├── assets/                     # base.css（token 消费）+ themes/（token 定义）
├── scripts/                    # validate / static_check / visual_check 质检 + preview / revise
├── examples/demo-report/       # 完整示例（含产物与质检报告）
└── tests/                      # pytest（Schema 用例集 + golden-file 渲染基准）
```

## 开发

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # 38 个测试
UPDATE_GOLDEN=1 .venv/bin/pytest       # 渲染行为有意变更时更新 golden 基准
```

## License

MIT
