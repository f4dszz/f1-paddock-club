# F1 Paddock Club — Intelligence Roadmap

> 7 candidate features for the next intelligence layer. File-level change clarity, honest cost/risk profiles, sequenced rollout.
>
> Bilingual style: 中文叙述 + 英文路径 / 标识符。
>
> Last verified against codebase: 2026-05-05。所有 `file:line` 引用基于当前 main。

---

## 范围说明 (Scope)

本文档评估 7 个候选能力，每个分为三类:

- **pipeline** — Lane 1 风格，在 LangGraph DAG 里加节点 / 加分支
- **skill** — Lane 1+Lane 2 共享的工具层 / 领域知识层 (`backend/tools/` 的扩展模式)
- **hybrid** — 同时落在 graph 节点 + tools 工具上

每个候选都按"今天的状态 → 加什么 → 文件级改动 → 接入点 → 风险 → 依赖"五层展开。**所有"今天的状态"都引用 verified line 号，不是凭记忆。**

---

## 1. F1 Domain Skill [skill]

**Status today** (verified): 现有 F1 领域知识非常薄。`_race_calendar.py` 只有 `{round, gp_name, city, country, race_date, sprint?, not_scheduled?}`，没有赛道名、没有 race-week 时间表、没有夜赛/通勤标注。`_CIRCUIT_NAMES` 散在 `search_tickets.py:48-71` 仅用于查询消歧；其它启发式（"Singapore 是夜赛/酒店要离 MRT 近"）烘焙在 `agents/__init__.py` 的 prompt 里。

**What we're adding**: 一份单点真源的 F1 赛事元数据表 — 赛道全名、官方周末日程 (FP1/FP2/FP3/Quali/Sprint/Race 的本地时间)、是否夜赛、推荐住宿区域（圈内 vs. 市中心）、典型通勤难点（Monza 当地火车 / Singapore MRT / Las Vegas Strip 封路）。Tour/Itinerary agent 拿到结构化提示后，行程不再泛泛"参观 Duomo"，而是"FP1 周五 13:30 起 → 周五午前到达 Monza 镇"。Ticket agent 的查询会把"Lateral Parabolic"自动映射到正确赛道命名。

**File changes**:
- **MODIFY** `backend/tools/_race_calendar.py` — 给每条 race 字典追加 `circuit_name`/`session_schedule`/`is_night_race`/`stay_zones`/`commute_notes` 字段；保留 `all_races()` 旧 shape 不变 (新字段 `NotRequired`)，新增 `enrich(gp_name) -> dict` 返回完整元数据。官方赛道 URL 暂不纳入，避免维护一批未验证、非 booking 的外链。
- **MODIFY** `backend/tools/search_tickets.py:48-71` — 删除本地 `_CIRCUIT_NAMES`，统一从 `_race_calendar.enrich()` 拉取
- **MODIFY** `backend/tools/search_hotels.py:94-106` — `_HOTEL_LOCATION_ALIASES` 与新的 `stay_zones` 合并
- **MODIFY** `backend/agents/__init__.py` — itinerary / tour 的 prompt 注入 `enrich(gp_name)` 的 session_schedule + commute_notes
- **CREATE** `backend/tools/_f1_domain.py` — 把 `enrich()`、`circuit_name_for(gp_name)`、`night_race_set()` 集中导出，避免 `_race_calendar.py` 膨胀
- **State 改动**: 无（领域知识纯只读，不写 state）
- **WS 消息**: 无新类型

**Where it plugs in**: `_race_calendar.enrich()` 被 `agents/tour.py`、`agents/itinerary.py`、`tools/search_tickets.py`、`tools/search_hotels.py` 引用。Lane 2 自动受益（refine 的工具走同一份）。

**Risk + effort**: **S**。最大风险是数据维护成本（赛季中赛道日程会调整），用 `Last verified` 注释 + e2e 矩阵的 row 1.x 把 22 站全跑一遍兜底。第二风险是字段命名不当导致 prompt 体积膨胀 → 严格 `NotRequired` 收敛到 4-6 个字段。

**Depends on / unblocks**: 无依赖，可立即做。**强烈解锁 #2 (Travel Docs)** — ICS 导出需要 session_schedule。**轻度解锁 #3 (Multi-GP)** — 比较时需要"夜赛 / 周末类型"维度。

---

## 2. Booking-link Normalization Skill [skill]

**Status today** (verified): 每个 `search_*.py` 自己产生 URL，没有中心化校验。来源混杂：SerpAPI 原始链接 (`search_flights.py:188`、`search_hotels.py:218`)、Google Maps 网址 (`search_hotels.py:293`)、Firecrawl 官方 URL 字典 `_TICKET_URLS` (`search_tickets.py:36-43`，默认 `https://tickets.formula1.com/en`)、LLM-fallback 硬编码 (`search_flights.py:319`、`search_hotels.py:361`)。**没有 URL 有效性校验，没有归一化层**。前端 Book 按钮直接 `href` 跳转 (`prototype.jsx`)。

**What we're adding**: 一个中央 link-normalizer，给每条 ticket/transport/hotel 项加上：
- `link` — 归一化后的可跳转 URL（去 tracking 参数、统一协议、无效则降级到 provider 主页）
- `link_type` — `"deeplink" | "search" | "homepage"` 三档置信度（已有 `NotRequired` 字段）
- `booking_confidence` — `"high" | "medium" | "low"` 给前端显示提示词

前端在 `link_type=search` 时 Book 按钮文案改成 "Search on Booking.com →"，避免误导用户以为是直接预订链接。

**File changes**:
- **CREATE** `backend/tools/_links.py` — 导出 `normalize(url, provider) -> tuple[str, link_type, confidence]`、`fallback_for(provider) -> str`、`PROVIDER_HOMEPAGES` 常量表
- **MODIFY** `backend/tools/search_flights.py:188, 319` — 出口前过 `normalize()`
- **MODIFY** `backend/tools/search_hotels.py:218, 293, 361` — 同上
- **MODIFY** `backend/tools/search_tickets.py:36-43` — `_TICKET_URLS` 改用 `_links.PROVIDER_HOMEPAGES["f1_official"]` 拼接，去重
- **MODIFY** `frontend/prototype.jsx` — Book 按钮根据 `item.link_type` 切换文案 + 置信度小图标
- **State 改动**: 无（`link_type` / `booking_confidence` 已在 `state.py:24-26, 38-40, 53-56` 定义为 `NotRequired`，今天就是没人写）
- **WS 消息**: 无新类型（继续走 `result`）

**Where it plugs in**: 三个 `search_*.py` 在返回前调用 `_links.normalize()`；前端在 `prototype.jsx` 渲染 Book 按钮处读 `link_type`。Lane 2 自动受益。

**Risk + effort**: **S**。风险点 1：HTTP HEAD 校验链接会引入网络抖动 → 默认只做 URL 解析（合法 scheme + host 在白名单），不做活性探测。风险点 2：归一化把 SerpAPI 的 affiliate 参数误删 → 归一化前先白名单"必须保留参数"。

**Depends on / unblocks**: 无依赖。**直接解锁 #1 (Critic)** 的"链接质量"检查项。**轻度解锁 #2 (Travel Docs)** — PDF 里的 "Book this hotel" 链接需要置信度提示。

---

## 3. Intent Classifier Skill [skill]

**Status today** (verified): 当前模式判断在 `refine.py:833-834` 是裸字符串检查 — `has_plan = bool(state.get("tickets") or state.get("transport") or state.get("hotel"))`，无 LLM 分类。Refine 内部所有意图（约束变更 / 行程编辑 / 探索性提问 / 重新规划）都丢给 ReAct supervisor 自己判。`refine_constraints.py` 已经实现了启发式约束抽取（`merge_constraints` 在 `refine.py:828-830` 调用），但更高层的"用户到底想干嘛"没分类。

**What we're adding**: 一个轻量意图分类层，把用户消息映射到 `{refine, edit, explore, replan, export, compare}` 六类之一，再喂给 supervisor。好处：
- `replan` 直接走 Lane 1 而不是劝说 supervisor（消除"换 GP 必须发 type=plan"的约束，见 CLAUDE.md 已知缺口）
- `export` 触发 #2 Travel Docs 而不进 ReAct
- `compare` 触发 #3 Multi-GP pipeline
- `explore`（"Monza 周边好玩吗"）走轻量直答路径，不进工具循环，省 token

**File changes**:
- **CREATE** `backend/tools/_intent.py` — 导出 `classify(user_message, has_plan, history) -> Intent`，先用规则匹配（关键字 + 正则），命中 fallback 才用 LLM 单次分类
- **MODIFY** `backend/refine.py:833-834` — `has_plan` 之外加 `intent = classify(...)`，根据 intent 走不同 branch
- **MODIFY** `backend/refine.py:851-855` — 当 `intent in {"export", "replan", "compare"}` 时，跳过 ReAct supervisor，直接 raise 一个 `IntentRedirect` 异常，被 `main.py` 的 WS handler 捕获并改派
- **MODIFY** `backend/main.py` (WS handler around `_send_trace` / `type="chat"` 处理) — 捕获 `IntentRedirect`，下发 `type="reply"` + `intent_action` 字段给前端
- **State 改动**: 在 `state.py:72-104` 增加 `last_intent: NotRequired[str]` 仅供 trace 使用
- **WS 消息**: 服务端 → 客户端新增 `type="reply"` 的 `intent_action` 子字段（值: `redirect_to_export | redirect_to_replan | redirect_to_compare`），客户端凭此触发对应 UI

**Where it plugs in**: `refine.refine_plan()` 入口处。规则匹配命中 → 短路返回；LLM 分类只在歧义时调用一次 (温度 0)。

**Risk + effort**: **M**。风险点 1：分类错误 → 用户 "我想换酒店" 被判为 `replan` → 重做整个 Lane 1，体验灾难。**Mitigation**: rule-based 优先（只接受确定信号词如 "重新规划"/"换一站"/"导出"），LLM 仅做兜底；并保留 `?debug=1` trace 显示 `last_intent` 让用户能反馈。风险点 2：增加一次 LLM 调用 → 端到端延迟。**Mitigation**: 仅在规则不命中时才调，~80% 消息走 rule-only 路径。

**Depends on / unblocks**: 无强依赖。**解锁 #2 (Travel Docs)**（"导出 PDF" 自然语言入口）和 **#3 (Multi-GP)**（"Monza 和 Singapore 哪个划算" 自然语言入口）。可独立先做但实用价值要等 #2/#3 落地才显现。

---

## 4. Critic / QA Pipeline [pipeline]

**Status today** (verified): Lane 1 完全没有自检环节。仅有的两道闸：货币枚举 + 行程日期 (`main.py:216-228`、`_trip_dates.py:37-78`) 在 API 边界；`recompute.py` 守 `price>0` + 货币换算。**LLM 一致性、URL 有效性、是否答非所问、是否有"幻觉酒店"全无检查**。budget 不通过会 retry hotel (`graph.py:97-108`、`budget.py:41-47`)，但这是预算约束、不是质量约束。

**What we're adding**: 在 `budget_agent` 之后插入 `critic_agent`，跑一组**确定性 + LLM-mixed** 检查项：
- `tickets`/`transport`/`hotel` 每条 `link` 域名在白名单 (借助 #2)
- `itinerary` 每天提到的城市在 `gp_city` 或合理通勤半径（借助 #1 的 `commute_notes`）
- `tour` 不重复推荐 (>2 项命中同一关键词触发"redo tour")
- 数值一致性：`budget_summary.total` 在 ±2% 误差内能从各项重算
- 文本相干性：itinerary 不出现"FP1 周日 14:00"这类时序错误（借助 #1 的 `session_schedule`）

发现失败时，critic 写 `critic_findings: list[dict]` 到 state，再走条件边重跑相关 agent；最多重跑一次。

**File changes**:
- **CREATE** `backend/agents/critic.py` — 导出 `critic_agent(state) -> dict`，返回 `{critic_findings, critic_pass: bool, messages: [...]}`
- **MODIFY** `backend/graph.py:74` 区域 — 注册 `critic_agent` 节点
- **MODIFY** `backend/graph.py:93-108` — 现在 `[itinerary, tour] → budget → critic → conditional`；条件边 `should_retry_critic` 决定 `done | retry_tour | retry_itinerary | retry_hotel`
- **MODIFY** `backend/agents/budget.py:41-47` — `should_retry_budget` 重命名 / 拆分，让 critic 接管最终条件
- **MODIFY** `backend/state.py:99-101` — 增加 `critic_findings: list[dict]`、`critic_pass: bool`、`critic_retry_count: int`
- **MODIFY** `backend/main.py:341-407` — `_build_trace_events` 增加 `critic_finding` 事件类型
- **State 改动**: 见上
- **WS 消息**: `type="trace"` 增加 `event="critic_finding"` 子类型 (`{rule, severity, target_field, hint}`)

**Where it plugs in**: 新节点位于 `budget_agent` 与 `END` 之间。retry 拓扑：critic 找到 `tour_repetition` → `retry_tour`；找到 `link_dead` → `retry_hotel`/相应 search agent；找到 `schedule_inconsistent` → `retry_itinerary`。

**Risk + effort**: **L**。`architecture-lessons.md #18` 明确警告 "optimization has diminishing returns" — critic 必须治真问题不是空转。**Mitigation 1**: 每条规则都用真实历史失败样本写出来；空 critic（无规则）不上线。**Mitigation 2**: `critic_retry_count` 上限 1（不是 2），避免无限循环。**Mitigation 3**: 失败规则按 `severity=warning|error` 区分；warning 仅写入 trace 不触发 retry。最大风险是延迟翻倍 — 改用并发：critic 内部 `asyncio.gather` 跑各检查项，整体 < 3s。

**Depends on / unblocks**: **依赖 #1 (F1 Domain)** 才能做 schedule_inconsistent 检查；**依赖 #2 (Booking Links)** 才能做 link_dead 检查。可以先实现 budget/repetition 两类不需依赖的规则上线 (S)，再逐步加规则到 L。

---

## 5. Travel Docs Skill [skill]

**Status today** (verified): 完全不存在。前端在 `prototype.jsx:281` 通过 `type="quote"` 实时算预算，但**没有 finalize 步骤、没有服务端持久化、没有导出**。Book 按钮是外链 fire-and-forget。所有 finalize 所需数据 (selectedTicket/Flight/Hotel、gp_date、depart/return、currency、budgetSummary.total) 在 done 阶段都已在 `prototype.jsx` 内存中 — 这是关键的好消息：**不需要服务器持久化即可生成文档**。

**What we're adding**: "导出旅行手册" — 三种格式：
- **PDF** — 行程总览 1 页 + 每天 1 页 (赛道地图 / 酒店地址 / 当日餐厅 / Book 链接)，使用 `anthropic-skills:pdf` 风格
- **ICS** — 含 FP1/FP2/Quali/Sprint/Race 的日历项 (借 #1 的 `session_schedule`)，外加酒店 check-in/out、出发航班的提醒
- **XLSX** — 预算明细表 (复用 `budget_summary.items`) + 链接列

前端新增"Export"按钮，触发 WS 上行 `type="export"`，服务端生成后通过 `type="export_ready"` 下发 base64 (PDF/XLSX) 或文本 (ICS)。

**File changes**:
- **CREATE** `backend/tools/_export_pdf.py` — 用 reportlab 或现有 PDF 库；导出 `build_pdf(state, selections) -> bytes`
- **CREATE** `backend/tools/_export_ics.py` — 纯文本拼接 RFC5545；导出 `build_ics(state, selections) -> str`
- **CREATE** `backend/tools/_export_xlsx.py` — openpyxl；导出 `build_xlsx(state, selections) -> bytes`
- **CREATE** `backend/agents/export.py` — 协调三个 export 函数，单点 `export_docs(state, selections, formats) -> dict[str, bytes|str]`
- **MODIFY** `backend/main.py` (WS handler) — 处理 `type="export"`，调用 `export_docs`，下发 `type="export_ready"`
- **MODIFY** `backend/requirements.txt` — 加 `reportlab`、`openpyxl`、`icalendar`
- **MODIFY** `frontend/prototype.jsx` — 在 Results 视图增加 Export 按钮组（PDF / ICS / XLSX 三个），处理 `type="export_ready"` 触发浏览器下载
- **State 改动**: 无（导出是只读快照）
- **WS 消息**: 客户端 → 服务端 `type="export"` (`{formats: ["pdf","ics","xlsx"], selections: {...}}`)；服务端 → 客户端 `type="export_ready"` (`{format, filename, data, mime}`) 和 `type="export_error"`

**Where it plugs in**: WS handler 同 `type="quote"` 平级；不进 LangGraph DAG，不走 ReAct。复用 `_state_snapshot()` 形态。

**Risk + effort**: **M**。风险点 1：PDF 排版手工、字体在 Linux 容器跑可能掉中文 → 用 `NotoSansCJK` 字体内嵌 + 单元测试覆盖中文 GP（如 "上海 GP"）。风险点 2：大文件通过 WS 下发可能超 `MAX_WS_MESSAGE_SIZE = 16KB` (`main.py:338`) → PDF 走分片或临时改用 HTTP `GET /api/export/{token}`，token 临时存内存（不破坏"WS 即会话"原则）。

**Depends on / unblocks**: **强依赖 #1 (F1 Domain)** — ICS 没有 `session_schedule` 就只是个 race-day 提醒，没差异化。**轻度依赖 #2 (Booking Links)** — PDF 内嵌外链需要置信度文案。**被 #3 (Intent Classifier)** 解锁自然语言入口。

---

## 6. Multi-GP Comparison Pipeline [pipeline]

**Status today** (verified): 单 GP 单选，前端 `prototype.jsx:253-259, 226` 强制 `gp_name` 单值。Graph 是无模块级 state 的 (`build_graph()` 每次新建)，verified `asyncio.gather(plan_trip(...), plan_trip(...))` 是安全的；`@cached` 是唯一共享状态而且是 feature。`architecture-lessons.md #17` 明确："Why not supervisor-only? Parallelism" — supervisor 不适合做并行多 GP 比较，需要 **a Lane-1-of-Lane-1s wrapper**，不是 ReAct 重构。

**What we're adding**: 用户可同时选 2-3 站 GP（如 Monza + Singapore + Las Vegas），系统并发跑各自完整 Lane 1，然后用 comparator 节点出比较卡片：每站的"最低总价 / 周末类型 / 旅行总时长 / 与预算差额 / 推荐指数"。前端用并排卡片 + 高亮"最佳"。

**File changes**:
- **CREATE** `backend/graph_multi.py` — 导出 `plan_trips(requests: list[dict]) -> list[dict]`，内部 `asyncio.gather(plan_trip(req) for req in requests)`，最后跑一次 `comparator_agent`
- **CREATE** `backend/agents/comparator.py` — 输入 `list[TravelPlanState]`，输出 `comparison_summary: dict` (按维度排序，标注 `best_value`/`shortest_trip`/`closest_to_budget`)
- **MODIFY** `backend/state.py` — 新增独立 `MultiGPComparison` TypedDict（不混进 `TravelPlanState`，保持 state 单一职责）
- **MODIFY** `backend/main.py` — WS 接受 `type="plan"` 时检测 `gp_names: list[str]` 字段（向后兼容：单值仍走老路径）
- **MODIFY** `frontend/prototype.jsx:253-259, 226` — GP 选择支持多选（最多 3 个），表单提交改 `gp_names`
- **State 改动**: 不改 `TravelPlanState`；新增 `MultiGPComparison`；session 持有 `list[plan_state]` 而非单 plan_state
- **MODIFY** `backend/_session.py` — 改 `plan_state` 为 `plan_states: list[dict]`（向后兼容：单 GP 时长度 1）
- **WS 消息**: `type="plan"` 上行字段 `gp_names: list[str]`；下行新增 `type="comparison"` 携带 `MultiGPComparison`；现有 `type="result"` 在多 GP 模式下每站发一次

**Where it plugs in**: WS handler 在 `type="plan"` 路径上分流：单 GP → 走 `plan_trip`；多 GP → 走 `plan_trips`。Lane 2 暂不支持跨 GP 编辑（refine 默认作用于"当前激活 GP"，由前端通过新增的 `active_gp_index` 字段指定）。

**Risk + effort**: **L**。坦率说: 这是 7 个里实施代价最高的。风险点 1：3 个 GP 并发等于同时打 3 倍 SerpAPI/Firecrawl，命中限流概率高 → 需要在 `_cache.py` 加并发去重 (verified 当前 NO concurrent-call deduplication, 两个 parallel caller 都打 wire)。风险点 2：前端从单 GP 假设拓宽到 list 形态，动了 `selections`、Book 按钮、budget bar 三处 — UI 重构面积不小。风险点 3：Lane 2 的 "active GP" 概念需要新规则，否则用户问 "换酒店" 会困惑哪一站。**Mitigation**: 第一版只支持 2 站对比 (限流压力 ≈ 2x 而非 3x)，前端在 chat 框上方明确标"现在编辑：Monza"。

**Depends on / unblocks**: **强烈建议先做 `_cache.py` 的 in-flight 去重** (verified gap, search_tickets.py:84-99 已经有 dynamic TTL，但还没有"并发同 key 只打一次 wire"的合并)。**依赖 #1 (F1 Domain)** 才能做有意义的"周末类型"对比。**被 #3 (Intent Classifier)** 自然语言触发。

---

## 7. Preference Learning Pipeline [pipeline]

**Status today** (verified): `active_constraints` 已经是一个 state field（`state.py:86`，由 form + chat 写入，`refine.py:828-830` 走 `merge_constraints`）。会话级 6 轮历史在 `_session.py` (MAX_TURNS=6)。**没有跨 session 的偏好记忆 — 因为 Phase 5 的多用户/持久化还没做**。`architecture-lessons.md #16` 提倡"两个 caller 用同一逻辑就抽公共"——偏好抽取应跟 recompute 同模式。

**What we're adding**: Phase-4-compatible MVP — 基于浏览器 localStorage 的隐式偏好学习。每次 Lane 1 done 时：
- 客户端汇总用户最终选择 (`selectedTicket.tag`、`selectedFlight.cabin`/stops、`selectedHotel.brand`/`stars`/`distance`、`tour` 中被点击 Book 链接的类别)
- 写入 `localStorage["f1pc_prefs"]`，结构 `{prefs: {hotel_brand_seen: {...}, flight_stops_seen: 0, ...}, last_updated}`
- 下一次 form 提交时，前端把 `prefs` 注入到 `special_requests`（隐式）或新增 `learned_prefs: dict` 字段（显式），server 在 `parse_input` 阶段并入 `active_constraints`

服务端只加 1 个 endpoint 用于 echo/decode；学习逻辑全在客户端。Phase 5 多用户上线后再迁到 server 持久化。

**File changes**:
- **CREATE** `frontend/src/preferences.js` — `recordChoice(state, selections)`、`getLearnedPrefs() -> dict`、`clearPrefs()`，写读 localStorage
- **MODIFY** `frontend/prototype.jsx` — done 时调 `recordChoice`，提交表单时 `formData.learned_prefs = getLearnedPrefs()`；Settings 增加"Clear preferences"按钮
- **MODIFY** `backend/main.py:202-214` (`TripRequest`) — 新增 `learned_prefs: dict[str, Any] = {}`
- **MODIFY** `backend/agents/__init__.py` 中的 `parse_input` — 把 `learned_prefs` 转换为 soft constraint 并并入 `active_constraints`
- **MODIFY** `backend/state.py` — `active_constraints` 已存在，无 schema 变化；额外增加 `learned_prefs: NotRequired[dict[str, Any]]` 仅 trace 用
- **CREATE** `backend/tools/_preferences.py` — `merge_learned_into_constraints(learned, current_constraints) -> dict`，与 `refine_constraints.merge_constraints` 同模式
- **State 改动**: `active_constraints` 形态扩张（新增 keys 如 `preferred_hotel_stars`、`preferred_cabin`），但仍是 `dict[str, Any]`
- **WS 消息**: 无新类型

**Where it plugs in**: `parse_input`（`agents/__init__.py`）入口；refine 的 supervisor 通过现有 `_constraints` 闭包 (`refine.py:263`) 自动看到。前端写时机 = `done` 阶段。

**Risk + effort**: **M**。风险点 1：偏好"沾粘"导致用户改不了 — 用户从 Marriott 一次切到 Hilton，下次依然推 Marriott。**Mitigation**: 用 last-N 加权而非全量计数；前端 Settings 提供"忘记我的偏好"按钮，并在 chat 中识别 "I don't want Marriott anymore" 时显式覆盖。风险点 2：localStorage 没有跨设备同步 → 接受这是 Phase 4 的边界，docstring 明确写"Phase 5 多用户上线后迁到 server"。风险点 3：`learned_prefs` 喂进 prompt 可能被 prompt injection 污染（恶意用户构造 special_requests 吐出去再输入）→ 服务端 `merge_learned_into_constraints` 必须 schema-validate (allowed key set + 类型白名单)。

**Depends on / unblocks**: 无强依赖。建议在 #4 (Critic) 之后做，因为偏好引入会让"Critic 觉得不合理"的边角增多 (例: 学到 "总订便宜酒店"，Singapore 这种贵城市可能违反，需要 critic 提示用户)。

---

## Recommended Order

按 "短期能上 + 复合解锁度高 + 风险递进" 排序，分 5 个 phase。每 phase 自身可发布。

### Phase A — Domain Foundation (week 1-2)
**Ship together**: #1 (F1 Domain Skill) + #2 (Booking-link Normalization Skill)

理由：
- 两者都是 **S 体量** 的 skill 类，无 state schema 变化、无 graph 拓扑变化、无 WS 协议变化 — 最低风险落点
- **复合解锁度最高**：#1 解锁 #2 (link 校验需要 provider 白名单和官方 URL 集中表)、#4 (critic 的 schedule 规则)、#5 (ICS 的 session_schedule)、#6 (compare 的"周末类型"维度)
- 这俩 **可并行实现**（不同文件，不冲突）
- Lane 1 + Lane 2 都自动受益，无前端改动也能看到 itinerary/tour 质量提升

**Acceptance**: e2e 矩阵 row 1.x 在 22 站全跑过；`?debug=1` trace 中 `tickets[*].link_type` 字段已落盘。

---

### Phase B — Critic MVP (week 3)
**Ship**: #4 (Critic) — 但只发"不依赖 #1/#2"的子集（budget consistency + tour repetition）

理由：
- 这两条规则就能解决最常见的"花了用户钱跑流程但结果有重复"投诉
- 完整 critic 是 L，但 MVP 只是 S — 降级版本先上、规则集逐周扩
- 等 #1/#2 落地后，再增量加 schedule/link 规则到完整 L

**Parallel work**: 同期可独立做 `_cache.py` in-flight 去重（verified gap），为 Phase D 的 multi-GP 减压。

**Acceptance**: trace 流里 critic_finding 事件可见；至少一次自动 retry_tour 在 e2e 抓到。

---

### Phase C — Travel Docs MVP (week 4-5)
**Ship**: #5 (Travel Docs)，三格式中先上 **ICS + XLSX**（轻量）；PDF 留 Phase D

理由：
- ICS 是用户感知最强的差异化能力："导入苹果日历自动有 FP1 提醒"是社交分享触发点
- XLSX 是技术债最低的格式（openpyxl 成熟）
- PDF 排版 + 中文字体是最耗时的 — 先把"导出"按钮和基建 (WS export 流) 立起来，PDF 内容放第二迭代
- 此时 #1 已 ship，ICS 能用 `session_schedule`；#2 已 ship，XLSX 链接列有置信度提示

**Acceptance**: 一站完整 plan 能导出 ICS + XLSX 并被苹果日历 / Excel 正确打开。

---

### Phase D — Conversational Reach (week 6-7)
**Ship together**: #3 (Intent Classifier) + #5 (Travel Docs PDF) + #4 (Critic 完整规则集)

理由：
- #3 是中等风险但产品级别最高的入口体验：用户输入 "导出 PDF" 直接触发 #5；输入 "Singapore 跟 Monza 比" 解锁 #6
- #5 PDF 此时与中文字体 / 排版迭代独立分支推进，与 #3 并行
- #4 把 schedule 规则、link 规则补齐，依赖此时已都 ship

**Acceptance**: 自然语言 "导出我这一站的 PDF 行程" 端到端工作；critic 的 5 类规则全在 e2e 矩阵里。

---

### Phase E — Multi-GP + Preferences (week 8-10)
**Ship sequentially**: 先 #6 (Multi-GP)，再 #7 (Preferences)

理由：
- #6 是 L 体量、UI 改造面积最大、限流风险最高 — 单独一个 phase 减少耦合故障
- `_cache.py` in-flight 去重必须先就位（Phase B 的 parallel work）
- #7 紧随其后，因为多 GP 体验下"偏好学习"的价值放大（用户在多站之间需要稳定偏好）
- #7 是 Phase-4-compatible MVP — 不阻塞 Phase 5 多用户改造

**Acceptance**: 用户能 2 站对比、看到 comparator 卡片；第二次访问表单能预填上次偏好；"Clear preferences" 按钮工作。

---

### 并行 vs. 阻塞总览

| 候选 | Phase | 阻塞 | 可与之并行 |
|-----|-------|------|----------|
| #1 F1 Domain | A | — | #2 |
| #2 Booking Links | A | — | #1 |
| #4 Critic MVP | B | 部分依赖 #1, #2（可降级先上） | `_cache.py` 去重 |
| #5 Travel Docs (ICS/XLSX) | C | #1 | — |
| #3 Intent Classifier | D | 价值依赖 #5/#6 已上 | #5 PDF |
| #5 Travel Docs PDF | D | #1 | #3, #4 完整版 |
| #4 Critic 完整 | D | #1, #2 | #3, #5 PDF |
| #6 Multi-GP | E | `_cache.py` 去重，#1 | — |
| #7 Preferences | E | 建议在 #4 之后 | — |

### 总建议
- **不要先做 #6 或 #7**。它们最性感但成本最高，前置依赖最多。
- **#1 + #2 是真正的杠杆点**。两个都很小，但下游 4 个候选都依赖。
- **Critic 必须分阶段上**。`architecture-lessons.md #18` 警告优化收益递减 — 用真实失败样本驱动规则集，不要写完整套规则再发。
- **Intent Classifier 的杠杆在 #5/#6 之后**。先做的话没体感，会显得 "为分类而分类"。
- 整条路线在 Phase 5 多用户/持久化之前都能落地，不需要等基建。
