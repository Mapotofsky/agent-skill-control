# Prompt Optimizer

用于生成、重写或诊断可复用提示词的个人技能。它只在用户明确处理 prompt / 提示词时触发，不把一般的模型失败自动归因于提示词，也不劫持本应直接完成的任务。

## 核心方法

技能以目标和结果为中心，只补充会改变执行的内容：

- 当前目标与成功标准；
- 相关、当前、可信的上下文或证据；
- 工作范围、授权和副作用边界；
- 消费方真正需要的输出契约；
- 提问、失败和停止条件。

角色、受众、格式、示例、XML、编号步骤和数量限制均为按需工具，不是固定模板。需要可核查性时，要求结论、关键依据、假设、不确定性和验证结果，不要求展示完整内部推理。

## 工作模式

| 模式 | 何时使用 | 默认交付 |
|---|---|---|
| 直接优化 | 已有 prompt，或需求足以形成草案 | 可复制提示词 + 1–3 项关键说明 |
| 引导补充 | 决定性缺口可能造成高返工、高风险或不可逆后果 | 最小澄清问题，随后给提示词 |
| 纯诊断 | 用户明确不要重写 | 影响最大的缺陷、证据和改进方向 |

低风险的模糊请求不会因为缺少受众、格式或长度而被机械拦截；技能会采用最小合理假设并明确标注。已知信息不会重复询问。

## 环境适配

- **Codex / agent**：目标、当前状态、范围、授权、验收和停止条件优先；让 agent 自选路径。
- **OpenAI API**：按需区分 developer 与 user 内容，并在调用层考虑工具 schema、Structured Outputs、reasoning、verbosity、缓存和 eval。
- **普通聊天 / 写作**：只在改变结果时补充目的、受众、语气和格式。
- **Claude / 其他模型**：使用通用原则或该平台已核验的机制，不移植 OpenAI 专用参数。

## 上下文治理

长历史应压缩为当前有效状态、约束、已完成事项和未决问题。指令、引用材料、示例和数据应明确分离。中央假设被纠正后，应重建依赖部分并输出干净的当前版本。若历史噪声过大，优先改写源提示词并在新会话使用。

## 文件结构

```text
prompt-optimizer/
├── SKILL.md
├── README.md
└── references/
    ├── examples.md
    └── interview-bank.md
```

`SKILL.md` 只保留共享决策规则；环境差异和较长示例按需从 references 加载。

## 官方依据

OpenAI 专用行为与参数以当前官方文档为准：

- [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Reasoning best practices](https://developers.openai.com/api/docs/guides/reasoning-best-practices)
- [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [Codex skills and progressive disclosure](https://learn.chatgpt.com/docs/build-skills)
