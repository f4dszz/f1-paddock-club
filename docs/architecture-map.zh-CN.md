# F1 Paddock Club 架构地图

这份文档用来帮助维护者快速掌握项目，不是新功能说明。目标是回答三个问题：数据从哪里来、状态在哪里被改、用户为什么能相信界面上的结果。

## 1. 两条 Lane

**Lane 1：初始规划**

- 入口：`backend/graph.py`。
- 触发：WebSocket `type="plan"` 或 `POST /plan`。
- 结构：固定 LangGraph DAG，先取票，再并行取航班和酒店，再并行生成行程和探索，最后计算预算。
- 写状态：每个 agent 只写自己的字段，例如 `tickets`、`transport`、`hotel`、`itinerary`、`tour`、`budget_summary`。
- 并发点：`transport_agent` 和 `hotel_agent` 可以并行；`itinerary_agent` 和 `tour_agent` 可以并行。
- 回退策略：真实 API 失败时回退到 LLM 估算或 mock，卡片会带 source/provider metadata，避免把估算伪装成真实库存。

**Lane 2：聊天 refinement**

- 入口：`backend/refine.py`。
- 触发：WebSocket `type="chat"`。
- 结构：ReAct supervisor 决定要不要调用工具，只改用户要求的局部内容。
- 写状态：先复制当前 `plan_state`，工具成功后再把更新写回；失败时不提交半成品。
- 保护线：如果用户要求修改行程或探索，但没有工具真的写回卡片，回复不能说“已更新”。

## 2. 三种记忆

**Plan state**

- 位置：`TravelPlanState`，定义在 `backend/state.py`。
- 作用：保存当前计划的事实结果，例如票、航班、酒店、行程、预算。
- 特点：这是结果卡片的数据来源，前端不应该自己猜最终状态。

**Conversation history**

- 位置：WebSocket session，见 `backend/_session.py`。
- 作用：保存最近几轮聊天，帮助 supervisor 理解“它”“再便宜一点”这类上下文。
- 特点：短期、滚动、可丢失，不适合保存硬业务约束。

**Active constraints**

- 位置：`state.active_constraints`。
- 作用：保存应该跨多轮持续生效的硬约束，例如只要直飞、只要万豪/希尔顿、素食、无障碍、避免奢华。
- 特点：比 chat history 更可靠，但目前仍是 WebSocket 内存态，刷新页面或后端重启会丢失。

## 3. Quote 为什么不改 Plan

前端用户点击不同票、航班或酒店时，会发送：

```json
{"type":"quote","data":{"quote_id":1,"selections":{"ticket":[0],"transport":[1],"hotel":[2]}}}
```

后端只重新计算这组选择的预算，不修改 `session["plan_state"]`，也不写聊天历史。原因是用户点击卡片经常是试探行为，如果每次点击都改主计划，结果会很难回滚，也会污染后续 chat refinement。

当前规则：

- 没有 selection 时显示 baseline，也就是每类默认最便宜可计价项。
- 有 selection 时显示 selected total，未选类别继续使用 baseline。
- 如果用户选了未计价项，预算变成 incomplete amber，不显示绿色 within-budget。
- `quote_id` 只用于前端过滤过期响应，不是安全凭证。

## 4. Hard Constraint Reconciler

位置：`backend/refine_constraints.py`。

它的职责不是“重新搜索”，而是在工具返回结果之后做最后一致性检查：

- 如果 `active_constraints.direct_only=true`，主航班列表不能出现转机选项。
- 如果 `active_constraints.allowed_hotel_brands=["Marriott","Hilton"]`，主酒店列表不能混入非匹配品牌。
- 如果它删掉了卡片，会重新计算预算，避免预算还引用已删除选项。

为什么需要它：外部 provider、LLM fallback 或 mock 都可能返回不完全符合约束的数据。最后一道 deterministic filter 可以避免界面“说只要直飞，但卡片里还有 1 stop”这种信任问题。

当前边界：

- 它只在约束变化或航班/酒店被更新时运行，避免无关聊天回合隐式刷新卡片。
- 酒店品牌匹配使用 canonical alias，不用宽泛 substring，避免把短 token 错当品牌。
- 未来更好的做法是把“哪些卡片被删、为什么删”也返回给前端，做成可解释的 diff。

## 5. Explainability 数据路径

位置：`backend/tools/_rationale.py` 和 `frontend/components/ExplainabilityPanel.jsx`。

票、航班、酒店卡片会带 `_rationale`，前端显示：

- 推荐原因：例如价格、距离、直飞、官方链接。
- 命中的约束：例如 direct-only 或 hotel brand。
- Source path：最终卡片来源对应的数据路径。
- Trade-offs：这张卡相对其他卡的取舍。

注意：`source path` 不是完整 runtime trace。它说明“这类卡片按什么数据梯队产生”，不保证每个 provider 都真实尝试过。真正的运行 trace 目前只在 `?debug=1` 的 debug 面板里显示有限事件。

## 6. 前端模块边界

当前仍是 Vite + React 原型，但主文件已开始瘦身：

- `frontend/prototype.jsx`：应用状态、WebSocket、页面编排。
- `frontend/domain/`：纯转换和展示规则，例如结果转换、预算文案、约束文案、日期校验。
- `frontend/components/`：只负责渲染，例如 GP 选择、欢迎表单、预算、聊天、结果卡、解释面板、Paddock 地图。

维护原则：

- 新的展示逻辑优先放 `components/`。
- 不依赖 React state 的规则优先放 `domain/`。
- `prototype.jsx` 不再继续堆大块 JSX。

## 7. 后端模块边界

当前后端拆分目标是让每个文件回答一个问题：

- `backend/main.py`：HTTP/WebSocket 边界、请求校验、session 写入。
- `backend/graph.py`：Lane 1 DAG。
- `backend/agents/*.py`：每个 planning agent 的节点逻辑。
- `backend/refine.py`：Lane 2 supervisor 编排入口。
- `backend/refine_editing.py`：itinerary/tour 文本更新 helper。
- `backend/refine_constraints.py`：硬约束 reconciler。
- `backend/tools/`：外部数据工具、缓存、日期、预算、rationale。

维护原则：

- 请求校验放 `main.py`，不要散落到前端。
- 预算保持 pure function，`quote` 和 `budget_agent` 都复用同一个计算逻辑。
- Supervisor 可以决定调用什么工具，但不能被允许任意浅合并 state 来制造预算结果。
- 真实外部数据失败是正常路径，fallback 必须如实标注。

## 8. 面试讲法

这个项目的亮点不是“用了 agent”，而是把 agent 放进可控状态机里：

- 初始规划用 LangGraph，因为依赖关系固定，适合并行 fan-out 和条件重试。
- 后续修改用 supervisor，因为用户自然语言变化太多，固定 DAG 不灵活。
- 短期对话记忆和结构化约束分开，避免模型忘记硬业务规则。
- 预算 quote 不改主状态，避免 UI 点击污染真实计划。
- Explainability 解释最终卡片的业务理由，但不夸大成完整审计日志。
- 最重要的 trade-off：现在仍是 demo 级 session 内存态，没有账户、数据库、长期偏好和生产鉴权；这是上线前必须补的工程层。
