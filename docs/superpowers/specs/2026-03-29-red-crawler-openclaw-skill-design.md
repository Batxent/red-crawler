# Red Crawler OpenClaw Skill Design

## Context

当前 `red-crawler` 已经具备这些稳定能力：

- 通过 Playwright 登录并保存 `state.json`
- 基于 seed 账号执行单次抓取
- 执行 nightly collection
- 生成 weekly report
- 从 SQLite 中列出高质量可联系账号

现有能力的事实源已经很清楚：`red-crawler` CLI。  
因此 OpenClaw Skill 不应该重写抓取逻辑，而应该把现有 CLI 封装成一个稳定、可移植、可复用的高层能力。

## Goal

提供一个可移植的通用 OpenClaw Skill，让其他用户在本地拥有 `red-crawler` 仓库和运行环境时，可以通过自然语言稳定调用这些能力：

- 登录并保存会话状态
- 单次 seed 抓取
- 夜间采集
- 周报导出
- 联系人候选列表查询

## Non-Goals

本期明确不做这些事：

- 不重写 `red-crawler` 的业务逻辑
- 不直接用浏览器工具替代 CLI 抓取流程
- 不自动安装 `uv`、Playwright 或仓库依赖
- 不内置敏感状态文件或账号信息
- 不做远程执行、多机器调度或 GUI 配置向导

## Approaches Considered

### Option A: 薄封装 Skill

把每个 CLI 子命令直接暴露成 Skill action。

优点：

- 实现最简单
- 与现有 CLI 一一对应

缺点：

- 自然语言体验差
- 缺少统一的参数补齐和错误解释
- 更像工具集合，不像完整能力

### Option B: 编排型 Skill

对外暴露一个高层 Skill，内部根据用户意图路由到有限 action，再调用现有 CLI。

优点：

- 体验最好
- 保持 CLI 为唯一执行源
- 便于做统一配置、校验、错误处理和结果摘要

缺点：

- 编排层需要更严谨的 schema 设计

### Option C: 强流程 Workflow Skill

把登录、抓取、夜采、报表串成固定流程。

优点：

- 流程约束强
- 对固定操作场景稳定

缺点：

- 灵活性差
- 不适合日常多样请求

## Decision

采用 `Option B`，并进一步收敛为：

- 单 Skill
- 显式 `action`
- 现有 CLI 作为唯一执行源

这意味着：

- OpenClaw 负责识别用户意图
- Skill 负责把意图收敛成结构化 action
- 执行层只负责调用 `uv run red-crawler ...`

第一性原则是：真正稳定的边界不是自然语言，而是有限动作、明确参数和单一事实源。

## Proposed Skill Shape

Skill 名称建议为 `red-crawler-ops`。

目录结构：

```text
red-crawler-ops/
  SKILL.md
  manifest.yaml
  config.example.yaml
  src/
    index.py
  tests/
    test_index.py
```

职责边界：

- `SKILL.md` 负责触发语义、示例和限制说明
- `manifest.yaml` 负责输入输出 schema 和运行时元数据
- `src/index.py` 负责配置合并、校验、命令构造、命令执行、结果映射
- `tests/` 负责编排层自动化测试

## Input Design

Skill 对外输入采用“共享字段 + action 特定字段”的统一模型。

核心字段：

- `action`
  - `login`
  - `crawl_seed`
  - `collect_nightly`
  - `report_weekly`
  - `list_contactable`
- `workspace_path`
- `storage_state`
- `db_path`
- `report_dir`
- `output_dir`
- `seed_url`
- `max_accounts`
- `max_depth`
- `include_note_recommendations`
- `crawl_budget`
- `days`
- `min_relevance_score`
- `limit`

动作约束：

- `login` 主要使用 `workspace_path` 和 `storage_state`
- `crawl_seed` 必须提供 `seed_url`
- `collect_nightly` 依赖 `storage_state`
- `report_weekly` 主要使用 `db_path` 和 `report_dir`
- `list_contactable` 主要使用 `db_path`、`min_relevance_score` 和 `limit`

## Config Design

为了让 Skill 能被其他用户复用，环境差异放到配置层，而不是写死在代码里。

建议提供这些默认配置项：

- `workspace_path`
- `runner_command`
- `storage_state`
- `db_path`
- `report_dir`
- `output_dir`
- `cache_dir`
- `default_crawl_budget`
- `default_report_days`
- `default_list_limit`

配置原则：

- 本地路径可配置
- 默认命令可配置
- 敏感状态文件内容不进入 Skill 包
- 输入参数始终可以覆盖配置默认值

## Output Design

Skill 输出统一为结构化对象，而不是原样转发 shell 文本。

建议字段：

- `status`
- `action`
- `command`
- `artifacts`
- `summary`
- `metrics`
- `next_step`
- `error`

语义要求：

- `status` 只区分 `success` 和 `error`
- `command` 记录真实执行的 CLI
- `artifacts` 返回生成文件路径
- `summary` 面向用户做高层解释
- `metrics` 提供可量化结果
- `next_step` 给出后续建议

## Internal Routing

`src/index.py` 只负责四个阶段：

1. 合并配置
2. 校验 action 和参数
3. 构造命令
4. 执行并映射结果

命令构造建议按 action 拆成纯函数：

- `build_login_command`
- `build_crawl_seed_command`
- `build_collect_nightly_command`
- `build_report_weekly_command`
- `build_list_contactable_command`

这样做有两个直接收益：

- 命令拼装逻辑可以独立测试
- CLI 参数变动时影响范围清晰

## Preconditions

正式执行命令前，Skill 先做外层环境检查：

- `workspace_path` 存在
- `workspace_path` 下存在 `pyproject.toml`
- `storage_state` 在非 `login` 场景下存在
- `db_path`、`report_dir`、`output_dir` 的父目录可创建
- `seed_url` 基本合法

这些检查的目的不是替代 CLI，而是尽早把环境错误转成清晰、可操作的结构化错误。

## Error Handling

错误分为四类：

- `configuration_error`
- `validation_error`
- `execution_error`
- `artifact_error`

每类错误统一返回：

- `status: error`
- `error_type`
- `message`
- `command`
- `suggested_fix`

典型示例：

- 缺少 `storage_state` 时提示先执行 `login`
- `workspace_path` 错误时提示检查仓库路径
- 命令执行失败时附带 action 和建议排查方向

## Testing Strategy

测试只覆盖编排层，不依赖真实小红书抓取。

建议分三层：

- 命令构造测试
- 参数校验测试
- mock 子进程的集成测试

重点验证：

- 输入能否稳定映射到 CLI argv
- 缺失参数时能否返回结构化错误
- 执行成功或失败时能否生成一致的输出对象

## V1 Scope

`v1` 只交付这些能力：

- 一个可安装的 Skill 目录
- 统一 action 执行器
- 可移植配置
- 结构化输出与错误
- mock 驱动的自动化测试

`v1` 明确不包含：

- 自动安装环境
- 自动初始化仓库
- 自动修复依赖问题
- 浏览器级直接抓取编排
- 远程执行

## Success Criteria

以下条件全部成立，视为 `v1` 完成：

- 其他用户修改配置后可在本机复用 Skill
- Skill 能把自然语言请求稳定映射到正确 action
- 每个 action 只调用现有 CLI，不复制业务逻辑
- 常见路径和状态问题能返回清晰错误
- 测试不依赖真实抓取环境
- Skill 默认行为不绑定作者本地路径

## Recommended Implementation Order

1. 编写 `manifest.yaml`、`config.example.yaml` 和 `SKILL.md`
2. 实现 `src/index.py` 的配置合并、校验和命令构造
3. 实现统一输出和错误模型
4. 补齐自动化测试
5. 使用 mock 和最小真实命令验证行为

## Open Questions

当前只保留一个待实现前再确认的问题：

- `list_contactable` 的输出是否需要进一步裁剪成更适合对话展示的摘要格式，还是直接依赖 CLI 文本输出并做轻量包装

这个问题不阻塞 `v1` 设计成立，可以在实现阶段处理。
