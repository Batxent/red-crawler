# Red Crawler Next Steps Plan

## Context

当前版本已经具备这些能力：

- 通过 Playwright 登录态抓取小红书主页
- 从主页简介中抽取邮箱、手机号、微信、QQ 和弱商务线索
- 通过搜索结果页扩展相似账号
- 输出 `accounts.csv`、`contact_leads.csv`、`run_report.json`
- 为账号打上 `creator_segment` 和 `relevance_score`

当前最主要的问题不再是“能不能抓到”，而是“能不能稳定产出更准的账号名单和联系方式”。

## Priority 1: Tighten Candidate Filtering

### Goal

默认只保留更接近“个人博主”的账号，减少 `studio`、机构号、职业服务号混入结果。

### Why

当前输出已经能区分：

- `creator`
- `professional_artist`
- `studio`

但默认结果仍然会保留部分高分 `studio` 账号。这对“找美妆/穿搭博主联系方式”不是最优默认行为。

### Implementation

- 在 CLI 增加可配置筛选参数：
  - `--allowed-segments`
  - `--min-relevance-score`
- 默认行为改为优先只保留 `creator`
- `professional_artist` 和 `studio` 作为显式可选输出
- 在 `run_report.json` 中加入分型统计，便于复盘筛选效果

### Success Criteria

- 默认输出中的账号大部分为个人内容创作者
- `accounts.csv` 中 `studio` 占比显著下降
- 用户不需要手动二次筛掉明显机构号

## Priority 2: Improve Similar Account Recall

### Goal

提升相似账号召回质量，而不是单纯扩大数量。

### Why

当前扩展主要依赖搜索结果页作者。这个入口比评论区更合理，但还有两个明显问题：

- 搜索词还比较单一
- 搜索命中后过早停止，候选池不够大

### Implementation

- 不在第一个有结果的查询上提前停止
- 同一赛道下尝试多组搜索词：
  - `美妆博主`
  - `护肤博主`
  - `彩妆博主`
  - `化妆博主`
  - `穿搭博主`
  - `时尚博主`
- 去重后建立更大的候选池，再统一评分
- 在可能的情况下补抓更多搜索结果卡片，而不是只看首屏少量作者
- 从种子账号的标签、简介、笔记话题中反推出更细的赛道词

### Success Criteria

- 同一 seed 下，候选账号数量增加但相关度不下降
- 高分账号更多集中在同赛道创作者
- 低质普通用户和弱相关账号进入最终结果的比例下降

## Priority 3: Rank Results for Human Review

### Goal

让导出结果天然适合人工筛选，而不是导出后再手工做排序。

### Why

当前已有：

- `creator_segment`
- `relevance_score`

但这还只是基础字段，尚未形成真正面向人工复核的最终排序。

### Implementation

- 引入统一排序分，综合考虑：
  - 赛道匹配度
  - `creator_segment`
  - 粉丝量级
  - 是否命中明确联系方式
  - 是否命中商务关键词
- 在 `accounts.csv` 中新增：
  - `has_contact_lead`
  - `lead_count`
  - `sort_score`
- 导出时按 `sort_score` 从高到低排序
- 在 `run_report.json` 中加入前若干高分账号摘要

### Success Criteria

- 用户打开 `accounts.csv` 时，前几行就是最值得看的账号
- 命中联系方式的高相关账号优先靠前
- 人工筛选时间明显下降

## Priority 4: Continue Contact Extraction Improvements

### Goal

继续提高混淆联系方式的识别率，但避免为了召回率牺牲太多精度。

### Why

当前已经支持：

- `q邮箱`
- `@🐧.com`
- `艾特 / 点`
- `V / wx / w x / 卫星号`
- `日常在@...`
- `小号在@...`
- `加V看置顶`

剩余高频变体仍然值得补，但优先级低于候选质量和结果排序。

### Implementation

- 扩展更多邮箱域名混淆：
  - `163`
  - `126`
  - `gmail`
  - `outlook`
  - `hotmail`
- 扩展更多微信弱线索：
  - `v号`
  - `wx号`
  - `微:`
  - `薇:`
  - `合作见置顶`
  - `商务请私信`
- 将“可联系但未给出具体账号”的文案继续归类为 `other_hint`
- 保持测试驱动，不让弱规则污染现有高置信度抽取

### Success Criteria

- `contact_leads.csv` 中的邮箱、微信、QQ 命中率继续提升
- 弱线索有保留，但不会挤掉强结构联系方式
- 新规则不会明显增加误报

## Recommended Execution Order

1. 收紧默认账号筛选，只保留 `creator` 为主
2. 扩大并优化搜索召回候选池
3. 增加最终排序分和导出字段
4. 继续补联系方式混淆规则

## Short-Term Recommendation

如果目标是尽快拿到更可用的博主联系方式名单，建议先完成前 3 项，再继续做更多联系方式规则。当前瓶颈更偏向候选账号质量，而不是单条简介的解析能力。
