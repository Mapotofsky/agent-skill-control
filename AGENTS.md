# Skill Hub Repository Rules

- 修改前读取 `README.md`、`profiles/catalog.json` 和 `profiles/deployments.json`，并运行 `git status --short --branch` 与 `npm run publish:check`。
- 本 Hub 只管理 `skills/self` 与 `skills/third-party` 中的共享 Skill；其他项目拥有的专属 Skill 不得加入 catalog、deployments 或发布目标。
- 第三方 Skill 更新后必须审查 `git diff`，不得自动提交。
- 修改后运行 `npm test`、`npm run validate` 和 `npm run publish:check`。
- 未经明确要求，不执行无关的外部清理或 Git commit。
