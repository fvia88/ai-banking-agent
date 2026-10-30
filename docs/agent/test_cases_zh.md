# bank.ly 测试用例

所有测试均使用模拟银行数据，转账和订阅取消均为模拟操作。

已记录的测试运行中，所有实际执行的测试均无失败。测试范围涵盖智能体行为、后端流程、财务分析、安全策略、订阅管理及共享契约。

## 1. 运行方法

激活项目虚拟环境后，在仓库根目录运行。

| 用途 | 命令 | 预期 |
|---|---|---|
| 整体测试 | `PYTHONPATH=backend python -m pytest -q --ignore=agent/tests/test_providers.py` | 796 通过，22 跳过 |
| 单个模块 | `PYTHONPATH=backend python -m pytest agent -q`（或 `backend`、`security`、`finance`、`subscriptions`、`tests`） | 全部通过 |
| 列出收集用例 | `PYTHONPATH=backend python -m pytest --collect-only -q` | 列出每个测试 ID |
| 订阅交叉检查 | `python - < p5_check.py` | `TOTAL: 27 OK, 0 MISMATCH` |
| 订阅命令行 | `python -m subscriptions.cli fixtures/transactions.json` | 列出 StreamBox 和 CloudMusic |

已记录结果：**796 通过，22 跳过，0 失败**（共收集 818 项）。

原测试环境说明：`agent/tests/test_providers.py` 导入 `google` 包，默认环境未安装，因此上述运行排除此文件。该记录使用确定性模拟提供器；运行相应提供器测试需先安装依赖。本说明对应源文档记录的环境。

## 2. 按模块统计

| 模块 | 测试数 | 文件数 | 覆盖范围 |
|---|---|---|---|
| 智能体 P1（`agent/tests`） | 352 | 7 | 对话流程、状态、轮次、请求措辞、服务、工具结果与 CLI。 |
| 后端 P2（`backend/tests`） | 260 | 25 | 审批及撤销、执行、日限额、MFA、安全锁、并发、迁移、续接、元数据及模块集成。 |
| 安全策略 P4（`security/tests`） | 84 | 1 | 权限分级策略判断。 |
| 财务 P3（`finance/tests`） | 46 | 2 | 分析、分类与异常检测。 |
| 订阅 P5（`subscriptions/tests`） | 62 | 5 | 检测、已存记录映射、取消决策、流程和 CLI。 |
| 共享契约（`tests`） | 14 | 1 | 各模块共享模型与枚举。 |
| **合计** | **818** | **41** | 796 通过，22 跳过。 |

22 项跳过均为 PostgreSQL 专项，需将 `MIGRATION_TEST_POSTGRES_ADMIN_URL` 指向可丢弃 PostgreSQL 服务器。原运行机器未提供该环境（无 Docker）。分布为 `test_migrations.py` 9 项、`test_security_concurrency.py` 6 项、`test_approval_cancellation.py` 5 项、`test_agent_continuation.py` 1 项、`test_safety_lock.py` 1 项。覆盖迁移与请求竞态；其他测试覆盖 SQLite 相关逻辑，但不能证明该机器已验证 PostgreSQL 竞态行为。

## 3. 测试文件明细

| 文件 | 测试数 | 覆盖内容 |
|---|---|---|
| `agent/tests/test_service.py` | 94 | 智能体服务行为* |
| `agent/tests/test_conversation_acceptance.py` | 71 | 调用方辅助函数的三轮验收，不调用在线 API。 |
| `agent/tests/test_request_wording.py` | 61 | 请求措辞理解* |
| `agent/tests/test_tool_results.py` | 50 | 工具结果处理* |
| `agent/tests/test_conversation_turns.py` | 45 | 逐轮对话* |
| `agent/tests/test_conversation_state.py` | 20 | 会话状态* |
| `agent/tests/test_cli.py` | 11 | 智能体命令行* |
| `agent/tests/test_providers.py` | 未运行 | 模型提供器，需要 `google` 包（见第1节）。 |
| `backend/tests/test_approval_cancellation.py` | 30 | 撤销待审批票据，不执行或逆转银行操作。 |
| `backend/tests/test_security_bridge.py` | 27 | P4 安全桥接及应用路径强制执行。 |
| `backend/tests/test_metadata_transport.py` | 20 | P2 HTTP 元数据与 P1 参数、摘要、审批输入隔离。 |
| `backend/tests/test_migrations.py` | 19 | 升级可丢弃数据库结构，不使用应用数据库。 |
| `backend/tests/test_agent_continuation.py` | 18 | 可信审批结果回到 P1，不直接执行依赖提案。 |
| `backend/tests/test_mfa.py` | 18 | HTTP 与真实执行器中的 OTP/MFA 生命周期。 |
| `backend/tests/test_p5_integration.py` | 16 | HTTP 调用 P5 真实函数与取消持久化。 |
| `backend/tests/test_security_integration.py` | 16 | P2 使用标准提案及当前上下文调用 P4。 |
| `backend/tests/test_daily_transfers.py` | 14 | 真实 P1/P4 和审批路由中的上海跨日边界。 |
| `backend/tests/test_security_concurrency.py` | 12 | 并发 YELLOW 确认的安全回归。 |
| `backend/tests/test_p1_integration.py` | 11 | 后端集成智能体* |
| `backend/tests/test_safety_lock.py` | 11 | P4 真实策略下跨操作、持久化的重复失败保护。 |
| `backend/tests/test_finance_signoff.py` | 7 | 应用实际数据的支出输出验收。 |
| `backend/tests/test_milestone1.py` | 7 | 第一阶段流程* |
| `backend/tests/test_policy.py` | 7 | 后端策略* |
| `backend/tests/test_security_details.py` | 6 | 默认真实策略与原子、仅一次的升级审计。 |
| `backend/tests/test_action_execution.py` | 5 | 事务、重放保证和 YELLOW 失败处理。 |
| `backend/tests/test_approvals.py` | 5 | 审批* |
| `backend/tests/test_subscription_storage.py` | 3 | 订阅记录存储* |
| `backend/tests/test_finance_adapter.py`、`test_subscriptions.py` | 各 2 | 适配器* |
| `backend/tests/test_clarification.py`、`test_cross_scenario.py`、`test_execution.py`、`test_read_loop.py` | 各 1 | 单场景* |
| `security/tests/test_policy.py` | 84 | 安全策略模块完整测试。 |
| `finance/tests/test_analytics.py` | 31 | `analyze_spending` 汇总、校验和边界。 |
| `finance/tests/test_categories_anomalies.py` | 15 | 分类、异常、安全和隔离。 |
| `tests/test_contracts.py` | 14 | 共享模型与枚举* |

## 4. 人工检查的跨模块场景

第6节列出端到端检查：通过聊天取消订阅、审批、执行、重复保护、重启、余额、不允许的请求及规划器。

## 5. 订阅模块（P5）用例

规则：只使用借记、去重、按商户分组，价格带 5%；每周间隔 6 至 8 天、每月 27 至 33 天、每年 360 至 370 天。两笔置信分 0.40、三笔 0.70、四笔 0.85、五笔及以上 0.90，金额变化减 0.10。检测器不读取备注，不声明支持取消；状态和支持以已存记录为准。判断顺序：`SUBSCRIPTION_NOT_FOUND`、`AMBIGUOUS_SUBSCRIPTION`、`ALREADY_CANCELLED`、`CANCELLATION_NOT_SUPPORTED`、`ELIGIBLE`。始终要求确认。

### 5.1 检测器（`test_detector.py`，21 项）

| ID | 场景 | 预期结果 |
|---|---|---|
| D1 | 空输入 | 空报告。 |
| D2 | 明确月扣款 | 一个每月候选。 |
| D3 | 每周扣款 | 检出每周周期。 |
| D4 | 每年扣款 | 检出每年周期。 |
| D5 | 单次扣款 | 不识别为订阅。 |
| D6 | 两次扣款 | 低置信候选（0.40）。 |
| D7 | 更多扣款 | 置信分更高。 |
| D8 | 日期不规律 | 不检出。 |
| D9 | 金额差异大 | 不检出。 |
| D10 | 价格小幅变化 | 检出，降低置信分。 |
| D11 | 新价格仅一笔 | 不编造订阅。 |
| D12 | 同商户两服务 | 分开保留。 |
| D13 | 贷记 | 忽略。 |
| D14 | 重复交易 | 不增加证据。 |
| D15 | 大小写和空格 | 归一化。 |
| D16 | 输入乱序 | 输出相同。 |
| D17 | 备注注入指令 | 视为数据，输出不变。 |
| D18 | 原始支持标记 | 始终 false。 |
| D19 | 共享夹具 | 仅 StreamBox（39.00）和 CloudMusic（19.00）。 |
| D20 | 阈值 0.70 | 区分“可能”与“较可能周期扣款”。 |
| D21 | 三笔金额波动 | 仍低于 0.70。 |

### 5.2 映射与取消判断（`test_mapping.py` 24 项，`test_eligibility.py` 2 项）

| ID | 场景 | 预期结果 |
|---|---|---|
| M1 | ID 与商户相同 | 匹配。 |
| M2 | ID 不同，商户名相同 | 按名称匹配。 |
| M3 | 名称大小写、空格不同 | 匹配。 |
| M4 | 未知商户或空存储 | `SUBSCRIPTION_NOT_FOUND` |
| M5 | ID 相同、商户不同 | 不匹配。 |
| M6 | 其他用户记录 | 不匹配。 |
| M7 | 同商户不同价格 | 按价格区分。 |
| M8 | 同商户同价格 | `AMBIGUOUS_SUBSCRIPTION` |
| M9 | 同商户但价格均不符 | `SUBSCRIPTION_NOT_FOUND` |
| M10 | 重复 ID 记录 | `AMBIGUOUS_SUBSCRIPTION` |
| M11 | 活动且支持取消 | `ELIGIBLE` |
| M12 | 活动但不支持取消 | `CANCELLATION_NOT_SUPPORTED` |
| M13 | 已取消 | `ALREADY_CANCELLED` |
| M14 | 取消后再请求 | 拒绝。 |
| M15 | 已取消且不支持 | 优先报告 `ALREADY_CANCELLED`。 |
| M16 | 检测标记 true，存储 false | 以存储记录为准。 |
| M17 | 其他用户记录 | 未找到。 |
| M18 | 共享夹具 | StreamBox 合格，CloudMusic 不合格。 |
| M19 | 信息补全 | 仅匹配、活动且支持的记录设置支持 true。 |
| M20 | 已取消记录或候选标记补全 | 均不信任。 |
| M21 | 信息补全 | 保留其他字段，不修改输入。 |

### 5.3 流程（`test_walkthrough.py`，12 项）与 CLI（`test_cli.py`，3 项）

| ID | 场景 | 预期结果 |
|---|---|---|
| W1 | 列出共享夹具 | 两个候选及证据 ID。 |
| W2 | 仅列出 | 不授予取消权限。 |
| W3 | 仅支持且验证过的名称 | 符合资格。 |
| W4 | 取消、重列、重试 | 仍作证据列出；重试 `ALREADY_CANCELLED`。 |
| W5 | 取消一个订阅 | 其他记录不变。 |
| W6 | 其他用户 | 看不到记录。 |
| W7 | 检出但未存储 | 仍为候选。 |
| W8 | 置信等级 | 不决定匹配或权限。 |
| W9 | Alice 的 iQIYI VIP Monthly，两笔 45.00，相隔 30 天 | `sub_iqiyi_vip_monthly`，每月，0.40，证据 `tx_demo_003`、`tx_demo_002`。 |
| W10 | Alice 候选 ID 与存储 ID 不同 | 按名称映射 `sub_iQIYI_01`，符合资格。 |
| W11 | 其他用户查询 Alice 记录 | 未找到。 |
| W12 | Alice 取消后重复 | 拒绝重复。 |
| C1 | CLI 文本报告 | 列出 StreamBox、CloudMusic，不列 Metro。 |
| C2 | CLI `--json` | 有效 JSON，金额为字符串。 |
| C3 | CLI 文件缺失 | 退出码 2，`File not found`。 |

`p5_check.py` 以可读脚本重复 27 条规则（13 条列表及 Alice 场景、8 条检测、6 条映射）；末行应为 `TOTAL: 27 OK, 0 MISMATCH`。

## 6. 真实后端人工运行记录

使用 `python backend/start.py`、仓库外临时数据库及演示请求头 `X-Demo-User-Id: usr_demo_01`（Alice），另有说明除外。详见 `expected_outputs.md` 的第 7 至 9 节。

| ID | 请求 | 预期结果 | 观察结果 |
|---|---|---|---|
| A1 | `GET /api/v1/subscriptions` | iQIYI 候选，45.00，每月，0.4。 | 通过 |
| A2 | `GET /api/v1/subscriptions/records` | `sub_iQIYI_01`，活动状态。 | 通过 |
| A3 | `GET /api/v1/subscriptions?account_id=acc_khong_ton_tai` | 404。 | 通过 |
| A4 | 聊天：`Cancel iQIYI VIP Monthly subscription` | `PENDING_CONFIRMATION`，一个已存 ID 提案，记录仍活动。 | 通过 |
| A5 | 无请求体确认 | 422，无变化。 | 通过 |
| A6 | 使用 `confirmation_id`、`action_digest` 确认 | `COMPLETED`，一个审计 ID，记录 `cancelled`。 | 通过 |
| A7 | 重复确认 | 幂等重放，相同审计 ID。 | 通过 |
| A8 | 新会话再次取消 | `REJECTED`、`ALREADY_CANCELLED`，无操作。 | 通过 |
| A9 | 同数据库重启 | 数据保留，仍为 `cancelled`。 | 通过 |
| A10 | 前后余额 | 均为 15250.00 CNY。 | 通过 |
| A11 | `user_001` 请求 `Cancel CloudMusic subscription` | 不可用，无操作。 | 通过 |
| A12 | `Cancel Netflix subscription` | 未找到，提供验证过的选项，无操作。 | 通过 |
| A13 | `Cancel my subscription` | 询问完整名称，无操作。 | 通过 |
| A14 | `Cancel StreamBox subscription` | `PENDING_CONFIRMATION`，一个提案，两记录仍活动。 | 通过 |
| A15 | `Cancel iQIYI ... then transfer 45 CNY to Bob` | 先提案并取消一次，随后提出转账。 | **待解决**：该次记录未提出转账步骤，由 P1、P2 跟进。 |
