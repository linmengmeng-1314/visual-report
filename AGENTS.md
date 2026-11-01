# AGENTS.md — 给所有 Coding Agent 的入口说明

> 本文件面向 Claude Code 之外的 Agent（Codex / OpenClaw / Cursor / 通用 agent 框架）。
> Claude Code 用户请直接读 [SKILL.md](SKILL.md)，两者工作流一致。

## 这个仓库是什么

visual-report 是一个**确定性渲染器 + 质检门禁**：你（Agent）负责理解素材、规划叙事、产出结构化的 plan JSON；渲染、校验、打包由 Python 脚本完成。**你不要手写 HTML。**

## 你需要遵守的核心规则

1. 只写 plan（`report-plan.json` / `slide-plan.json`），渲染交给 `python -m visual_report.render`
2. plan 必须先过 `python scripts/validate.py`，不过不渲染
3. 内容字段只允许 Markdown，禁止 HTML 标签
4. 图片只允许本地路径或 data: URI，禁止 http(s)（离线门禁会拦）
5. 不得编造素材中不存在的数据；示意数据必须 `dataNote` 标注
6. section/block 的 id 用 `kebab-case` 且全文档唯一，一经分配不随意变更

## 命令速查（与 SKILL.md 工作流一一对应）

```bash
# ① 多格式素材 → 统一素材摘要（md/txt/csv/json 开箱即用；docx/pdf 需 pip install "visual-report[input]"）
python scripts/extract.py 素材目录/ -o .visual-report/material.md

# ② 组装 plan（块类型见 references/block-reference.md，幻灯片版式见 SKILL.md"幻灯片模式"节）

# ③ 校验 → 渲染 → 两层质检
python scripts/validate.py report-plan.json
python -m visual_report.render report-plan.json -o output/visual-report.html
python scripts/static_check.py output/visual-report.html --json output/qa/static-check.json

# ④ 可选：主题预览（Show-Don't-Tell）/ 第三层视觉检查（需 playwright）
python scripts/preview.py report-plan.json -o previews/
python scripts/visual_check.py output/visual-report.html

# ⑤ 修改已有产物（节点级 diff + 历史 + 回滚，别手改 HTML）
python scripts/revise.py apply report-plan.json -o output/visual-report.html --note "改了什么"
python scripts/revise.py rollback report-plan.json -o output/visual-report.html

# ⑥ 报告转幻灯片骨架（转完需按宣讲时长精炼叙事）
python scripts/to_slides.py report-plan.json -o slide-plan.json --theme tech
```

## 运行环境

- Python ≥ 3.9；必装依赖仅两个：`markdown-it-py`、`jsonschema`
- 可选：`playwright`（视觉检查）、`python-docx` + `pypdf`（docx/pdf 素材）
- 渲染与校验不依赖网络

## 质检退出码约定

| 退出码 | 含义 |
|---|---|
| 0 | PASS |
| 1 | WARNING（可酌情交付） |
| 2 | FAILED（必须修复，禁止交付） |
| 3 | SKIPPED（可选依赖未装，不阻断） |
