# Skill Hub

本仓库是 Codex 与 WorkBuddy 共用 Skill 的源码 monorepo。源码与运行时发现目录完全分离：Git 只管理 `skills/`，发布器根据配置在宿主发现目录中建立 Junction。

## 源码布局

```text
skills/
├── self/          # 本人发布和维护的 Skill
└── third-party/   # 审查后保存的第三方上游快照
```

`skills/self` 是本人发布和维护 Skill 的统一入口。以后不再为单个 self Skill 建立独立 repository；本 monorepo 是这些 Skill 唯一的维护仓库。

| Skill | 简介 |
| --- | --- |
| [`awesome-ppt`](skills/self/awesome-ppt/) | 使用既定 pptxgenjs 工作流生成可编辑、可复现并经过 QA 的 PowerPoint。 |
| [`car-buying-framework`](skills/self/car-buying-framework/) | 以场景、安全和机制为优先级提供选车、比较与反营销检查框架。 |
| [`critical-analysis`](skills/self/critical-analysis/) | 为研究、事实核查、技术诊断和高风险决策提供证据分级与批判性分析流程。 |
| [`data-insight-visual-analysis`](skills/self/data-insight-visual-analysis/) | 从业务判断出发组织数据洞察、方法选择、视觉表达、证据回查与行动闭环。 |
| [`ieee-author-alignment`](skills/self/ieee-author-alignment/) | 诊断并修复 IEEE conference LaTeX 模板中的作者块对齐问题。 |
| [`mechanism-political-economy-framework`](skills/self/mechanism-political-economy-framework/) | 使用机制传导链分析宏观叙事、政策、产业与分配问题。 |
| [`prompt-optimizer`](skills/self/prompt-optimizer/) | 生成、重写、迁移和评审可复用提示词。 |
| [`recording-knowledge-compiler`](skills/self/recording-knowledge-compiler/) | 将录音、视频、课件和辅助材料无损编译为知识库讲义或指导手册。 |
| [`video-evidence-extraction`](skills/self/video-evidence-extraction/) | 从本地音视频提取可核查的转写、关键帧和时间对齐证据。 |

`skills/third-party` 保存经过审查的上游快照。每个 Skill 的 repository 和可选 subpath 记录在 [`profiles/catalog.json`](profiles/catalog.json)；没有可核实 repository 的条目由更新器标记为 `manual-only`，不会猜测或自动更新。

## 配置

- [`profiles/catalog.json`](profiles/catalog.json)：按 `self` 和 `thirdParty` 记录源码所有权、状态与第三方来源。`active` 可部署，`retired` 只保留源码。
- [`profiles/deployments.json`](profiles/deployments.json)：定义 global 与 scoped 部署，以及 `shared`、`codexOnly`、`workbuddyOnly` 三种宿主分配。
- [`profiles/paths.example.json`](profiles/paths.example.json)：机器本地 scope 路径配置示例。
- `profiles/paths.local.json`：本机 scope alias 到项目根目录的映射；被 Git 忽略。

全局发现目录按宿主约定从用户目录推导：Codex 使用 `$HOME\.agents\skills`，WorkBuddy 使用 `$HOME\.workbuddy\skills`。scoped 部署分别使用 `<scope>\.agents\skills` 与 `<scope>\.workbuddy\skills`。

## 部署边界

- 全局发布：Skill 在当前用户的所有相应宿主环境中可发现。
- scoped 发布：Skill 只通过已配置项目根下的宿主发现目录可发现；项目根必须已存在。
- 项目专属 Skill：由对应项目拥有，不进入本 Hub，也不进入 catalog、deployments 或第三方更新流程。

同一 Skill/宿主不能同时全局和 scoped 发布，也不能发布到嵌套的父子 scope。发布器不会覆盖普通目录、普通文件、项目内部 Junction 或健康且指向其他来源的 Junction；配置目标目录中的失效 Junction 会进入发布清理计划。

## 验证与发布

```powershell
npm test
npm run validate
npm run publish:check
npm run publish:status
npm run publish:apply
```

`validate` 在验证配置的同时检测配置目标目录中的失效 Junction，发现失效项时列出详情并返回失败。`publish:check` 是 dry-run，输出 `CREATE`、`KEEP`、`REMOVE` 和 `CONFLICT`；失效 Junction 标记为 `REMOVE / INVALID`，仍需部署的位置会同时生成 `CREATE`。`publish:apply` 仅在零冲突时执行，并且只删除精确指向本 monorepo 同名 Skill 源或执行时仍然失效的 Junction。

配置 scoped 发布时，先复制本地模板并填写已存在的项目根：

```powershell
Copy-Item profiles/paths.example.json profiles/paths.local.json
```

然后在 `profiles/deployments.json` 的 `scoped` 中使用相同 alias。

## 第三方更新

默认只获取上游并报告文件差异：

```powershell
npm run thirdparty:check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/update-third-party.ps1 -Skill frontend-design
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/update-third-party.ps1 -Repository https://github.com/anthropics/skills
```

显式应用后再审查 Git diff：

```powershell
npm run thirdparty:update
git diff
```

更新器按 repository 分组，每个上游仓库只获取一次。它不生成版本锁、哈希或 checksum，不自动提交，也不设置自动或定时更新。
