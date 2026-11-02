# dogfood 首轮留痕：Windows 办公机安装 + 首个真实项目（2026-11-02）

## 背景

visual-report 在家用 Mac 开发至 Phase 4b 全可用。2026-11-02 起在办公 Windows 机
（中文 GBK 控制台、uv 管的 Python 3.14）安装 skill 并完成首轮真实使用：
一是安装与跨平台管线验证，二是用本地项目完整跑了一次报告生成（另一会话执行）。
本文记录来路：修了什么、为什么、还欠什么。

## 已修复问题（按发现顺序）

### 第一波：安装与跨平台（5 笔提交）

| 问题 | 根因 | 修复 | commit |
|---|---|---|---|
| 渲染最后一步 UnicodeEncodeError 崩溃（exit 1，HTML 实已生成） | 中文 Windows 控制台重定向输出回退 GBK，`✓/✗` 不在 GBK 内 | 8 个入口统一 UTF-8 reconfigure 守卫（Mac/Linux 无操作） | `3ea2611` |
| deck.py SyntaxWarning | JS 模板 `\d` 无效转义，3.15 起报错 | 改 `\\d`，JS 输出逐字节不变 | `2d2319d` |
| static_check.py 文档用法示例脚本名错 | 历史改名遗留 | 更正 | `7bae0e4` |
| README 装不了 / 测试数过期 | PEP 668 环境裸 pip 被拒；测试数写死 38（实际 65） | 补 uv 指引、数字同步 | `6c392ce` |
| `license = {text=...}` 弃用告警 | setuptools>=77 要求 SPDX 字符串 | 改 `license = "MIT"` 并升 `setuptools>=77` | `c459821` |

### 第二波：真实项目 dogfood 反馈落地（6 笔提交）

| 问题 | 根因 | 修复 | commit |
|---|---|---|---|
| 同页多张 diagram 时 static_check 报 dup-id FAILED | 每张 SVG 写死 `<marker id="vr-arrow">` | 按**块 ID** 派生（无块 ID 时"容器 ID+块序"兜底） | `e3f0799` |
| 产物换行跨平台不一致 | Windows 文本模式默认翻 CRLF，Mac 为 LF，同 plan 字节不同 | 所有 HTML 产物写盘点 `newline="\n"` | `67a1007` |
| Schema 报错不可定位（dogfood 返工主因，4 轮才修完一处超长 label） | oneOf 聚合错误只报"整块不匹配"，maxLength 违规藏在 context 里 | `best_match` 下钻到最相关叶子 + maxLength 补数量（`实际 41 > 上限 40`） | `320a5c1` |
| visual_check 在 Chrome 起不来的机器上无浏览器可用 | 回退链缺系统 Edge | Chrome → Edge → Chromium 三级回退 | `00333f4` |
| label 限长没写进 reference | 只藏在 schema description 里 | block-reference 明确节点 ≤40 / 边 ≤20、按字符数计中英文同计 | `06a31fc` |
| 示例产物落后于渲染器 | —— | 重渲染同步 | `e7b571b` |

### 第三波：审查回环（同日，dogfood 会话复审实测后回传）

| 问题 | 根因 | 修复 | commit |
|---|---|---|---|
| 同块多处违规只报一处（复审新发现，B5） | jsonschema 把所有不匹配变体的错误**平铺**进 context，best_match 只返回最相关一片——同变体的其他违规被吞，修一个验一次再冒一个，一轮返工变两轮 | best_match 只用来「选变体」，按 schema_path 首段（变体下标）过滤收全该变体叶子；其余变体的 type/const 噪音仍挡在外面 | `7c094dd` |
| plan/HTML 路径错或 JSON 非法时裸 traceback（复审 nit） | 入口未包裹文件读取 | validate / render / to_slides / preview / static_check 五个入口一行式友好提示 | `06035dd` |
| README 测试数一天内过期两次（62 → 65 → 66） | 写死数字没有维护触发点 | 改为不写数字的表述 | 本文件同笔提交 |

### 第四波：用户目检反馈（边标签几何）+ 宽图策略讨论

| 问题 | 根因 | 修复 | commit |
|---|---|---|---|
| 边标签胶囊描边压箭头线 | 胶囊底边恰好落在线上（ly-7 + 高 19 = 线 y） | 线上标签整体抬高 3px，底边与线保持间隙 | `fe07249` |
| 步骤多（邻列短段）时标签压两端节点盒 | 段放不下时兜底分支无节点约束；且 rect_free 本就不查节点 | rect_free 增节点盒判定 + 行间走廊候选（可滑动）+ lint 增「标签压节点」 | `fe07249` |
| demo-report 在新 lint 下暴露走廊交叉死局 | router→agent 横穿走廊的线把唯一放标签窗口劈开——算法无解，属布局问题 | 穷举 row1 六种排布选语义最优（agent 置 router 正下方，38% 分流变垂直直边） | `f7023bd` |
| 宽图（≥5 列）等比缩小后文字偏小 | 栏宽 860px 固定，缩放是渲染器唯一选择 | 建议级 ⚠ 图宽超标（推荐纵向重排 + tb / wide / 拆图） | 后续提交 |

宽图策略结论（用户提出"横滑窗口"设想后讨论定案）：报告的核心承诺含**打印成 PDF**，
横滑在纸面必然裁切，不做默认；正确姿势是 plan 阶段消灭"过宽"——纵向重排（报告纵向
滚动免费、横向才贵）、wide section、拆图，由 ⚠ 建议引导。若未来确需屏上 1:1 浏览，
可做 opt-in 的 `overflow-x:auto` + `@media print` 恢复等比缩（屏滑纸缩），记入备选。

### 值得记下的复盘：dup-id 的两次修复

第一次（dogfood 会话就地修）：模块级计数器 `vr-arrow-{n}`。**被自己的测试拦下**——
`test_render_deck_deterministic` 同进程渲染两次比对，计数器使第二次输出漂移，
违反 ADR-001（确定性）。教训有二：

1. 状态化方案先过"同输入渲染两次"这关再提交；
2. 渲染产物的 id 应从**稳定标识**（块 ID）派生，与 SKILL.md"稳定 ID"哲学一致，
   跨修订 diff 也更干净。

## Backlog（发现未实施）

### B1 主链方向与 direction 声明一致性 lint（dogfood 反馈 D）——✅ 已实施（同日，`c5a3c79`）

- 现象：`direction: lr` 的图里主链排成纵向三步，箭头先下后上折返；现有几何 lint
  （穿盒/压线/拐点/短线段）全部放行，靠无头截图目检才发现。
- 建议：WARNING 级 lint——主链边行进方向与 direction 相逆的占比超阈值（约 30%）时
  提示"主链与 direction 不符，考虑改 tb 或重排 at"；或在 block-reference 补 tb/lr 选择心法。
- 开放问题：阈值定多少；"主链"如何定义（入度最大的链？最长路径？）。
- 实施结论：「主链」按**跨主轴边占比**定义（网格坐标 |Δ列| vs |Δ行|，对角边不计），
  阈值 >30% 走**建议级**通道 `plan_warnings`（validate 打 ⚠、exit 0，不阻断渲染）；
  block-reference 同步补 direction 心法。实测：纵向两连边塞 lr → `⚠ 相逆边占 100%`。

### B2 无 playwright 时的降级视觉复核（dogfood 反馈 E2）——✅ 已实施（同日，`fccb087`）

- 配方：`msedge --headless --screenshot=full.png --window-size=1280,11000 file:///path`，
  实测可行，把第三层质检从"跳过"变"降级"。
- 注意点：Edge 截图文件落盘有秒级延迟，复核脚本要**轮询等文件**而非查一次；
  Chrome 常驻 + 管理员终端时 DevTools 管道问题同样影响 `--headless=new` 变体。
- 边界：截图只覆盖"目检"，溢出/裂图的自动判定仍需 playwright（JS 求值）。
- 实施结论：`degraded_screenshots()` 找系统浏览器（**Edge 优先**，Chrome 常不可用）无头
  整页截图、轮询落盘；Windows 办公机实测出图。一个坑记下：环境变量名是
  `ProgramFiles(x86)`（**无下划线**），第一版写成 `PROGRAM_FILES(X86)` 导致探测不到浏览器——
  这类小错只有真机验证能拦住。
- **实测矩阵（追问"管理员终端还是常驻实例的锅"时补做）**：Chrome 无头截图从提权
  终端派生**必失败**（默认 / 隔离 profile / no-sandbox 均无效）；普通权限 + 隔离
  profile 成功（179KB）；普通权限 + 默认 profile 失败（常驻实例占默认 profile，新进程
  只转发不截图）；Edge 在提权下也成功。结论：**提权是决定性因素，常驻实例是独立第二
  因素，两者都规避才行**——注意规避动作都在**工具侧**完成（隔离 profile 让截图进程
  自己开新门，用户照常用 Chrome、无需关闭；实测矩阵第 4 行即 Chrome 常驻时成功），
  只有提权因素需要用户换普通终端启动 Claude（archify 备忘"非管理员终端跑"同理）。
  据此降级截图统一加 `--user-data-dir` 隔离 profile，`_find_system_browser` 注释同步为实测结论。

### B3 渲染期自检（dogfood 反馈 A 的上游建议）——✅ 已实施（同日，`927bbe5`）

- 现状：渲染器若产出非法 HTML（如重复 id），靠 static_check 兜底拦截——分层有效，
  但"渲染器自己产出非法产物"理想态应从源头杜绝。
- 建议：render 主流程末尾加轻量 assert（同页 id 唯一性），违反即抛错不落盘。
- 增补论据（2026-11-02 复审）：render 期若 assert 同页 id 唯一，dup-id 这类问题连
  static_check 都到不了——兜底有效，但每层都不应产出下一层才能发现的问题。**优先级上调**。
- 实施：`render_report` 拆出 `_render_report_html`，报告/deck 双路径产出后统一过
  `_self_check`（重复 DOM id 抛 ValueError 不落盘）；配套 `f2b6387` 让 revise 渲染
  失败按契约转 ReviseError（旧产物保留），自检异常在各入口都表现为友好报错。
  **backlog 仅余 B4（环境项，非本仓库）。**

### B4（环境侧，非本仓库）uv ↔ setuptools 本地构建失败

- 现象：本机 `uv pip install -e .`（乃至任何 setuptools 本地包，最小纯 setuptools 包
  复现）失败：`expected value at line 1 column 1` / 响应文件非 UTF-8；uv 0.13.6 依旧。
- 已排除：visual-report 自身（最小包同样失败）、setuptools 本体（直调 hook 输出正常）、
  uv 版本、缓存。
- 疑似方向：安全软件干扰 uv 构建临时文件。本机绕法：`.pth` 指向仓库（editable 等效）。
- 动作项：向 uv 提 issue / 排查本机杀软。

## 经验沉淀

- 跨平台三坑一次全踩齐：**编码**（GBK 控制台）、**换行**（CRLF 写盘）、**构建隔离**
  （uv + PEP 668）。Mac 上三者天然无感——dogfood 换 OS 是最高性价比的测试。
- 分层质检的价值在本轮被实证：static_check 拦住了渲染器自身的 bug（dup-id）。
  兜底有效，但见 B3：理想态是每层不产出下一层才能发现的问题。
