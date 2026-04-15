# F1 Paddock Club —— 多智能体旅行助手

> 基于 LangGraph 编排的多智能体系统，一次性帮你规划整趟 F1 大奖赛之旅 —— 门票、机票、酒店、按天行程、城市观光与美食、动态预算 —— 全部跑在一条并行流水线里。

简体中文 · [English](./README.md)

---

## 项目缘起

最初想解决的问题很朴素：「我同时在用 Claude / GPT / Gemini 处理一个任务的不同步骤，每一步都要手动切窗口、复制粘贴，太累了。」

我们没有做一个抽象的「通用编排器」，而是选了一个**目标明确、好演示**的场景 —— **规划一次去看 F1 大奖赛的旅行**，借此把多智能体编排的能力落地：

- 一个**接待员（concierge）**解析需求；
- 一个**门票智能体**找看台票；
- **交通**和**酒店**两个智能体**并行**搜索；
- 拿到出行基础信息后，**行程**和**观光**两个智能体再次**并行**生成内容；
- 最后一个**预算智能体**汇总所有花费，如果超预算就**回头**让酒店智能体重新找便宜选项（最多重试 2 次）。

整条流程是一张 [LangGraph](https://github.com/langchain-ai/langgraph) 状态图：并行扇出、条件边、强类型共享状态，一气呵成。

---

## 架构图

```
              ┌─────────────┐
              │ parse_input │
              └──────┬──────┘
                     ▼
              ┌──────────────┐
              │ ticket_agent │
              └──────┬───────┘
            ┌────────┴────────┐
            ▼                 ▼
   ┌────────────────┐ ┌──────────────┐
   │ transport_agent│ │ hotel_agent  │   （并行）
   └────────┬───────┘ └──────┬───────┘
            └────────┬────────┘
                     ▼
            ┌────────┴────────┐
            ▼                 ▼
   ┌────────────────┐ ┌──────────────┐
   │ itinerary_agent│ │ tour_agent   │   （并行）
   └────────┬───────┘ └──────┬───────┘
            └────────┬────────┘
                     ▼
              ┌──────────────┐
              │ budget_agent │
              └──────┬───────┘
                     │
       ┌─────────────┴──────────────┐
       │ 是否超预算？（最多重试 2 次） │
       │   是 → increment_retry → hotel_agent
       │   否 → END
       └────────────────────────────┘
```

共享状态 `TravelPlanState` 仅在 `messages` 字段上使用 `Annotated[list, operator.add]` reducer（这是唯一被并行节点同时写入的字段）。其他字段（`tickets`、`transport`、`hotel` 等）使用 LangGraph 默认的替换语义——每个字段只有一个智能体写入，不会冲突。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 编排 | **LangGraph**（状态机 + 并行扇出 + 条件边） |
| 大模型 | **可插拔** —— 默认 OpenAI，也可切到 Anthropic，通过 `LLM_PROVIDER` 环境变量切换。同时支持任意 OpenAI 兼容代理（设置 `OPENAI_BASE_URL`） |
| 后端 | **Python 3.12+** + **FastAPI** + **Uvicorn** |
| 流式推送 | **WebSocket**（`/ws`），把每个智能体的状态实时推给前端 |
| 前端 | React 原型（`frontend/prototype.jsx`），后续迁移到 Next.js |

---

## 当前进度（Phase 3 已完成）

| 阶段 | 状态 | 内容 |
|---|---|---|
| **1 — 图 + Mock 数据** | ✅ 已完成 | LangGraph 完整接好，7 个智能体返回 mock 数据，CLI 端到端跑通，FastAPI 端点可用。 |
| **2 — 真实大模型调用** | ✅ 已完成 | `itinerary_agent` 与 `tour_agent` 调用真实大模型（`with_structured_output`）。Provider 可切换（OpenAI/Anthropic）。无 key 时自动回退 mock。 |
| **3 — 外部数据 + Supervisor** | ✅ 已完成 | SerpAPI（机票/酒店）、Firecrawl（门票抓取）、Supervisor 对话式调整、`/ws` 双通道路由、多币种预算（EUR/USD/CNY）、行程日期计算。详见下方。 |
| **4 — 前端** | ⏳ 下一步 | 把 `prototype.jsx` 接上 `/ws`，后续迁移到 Next.js。 |
| **5 — 打磨与部署** | ⏳ 待定 | 安全基线、错误处理、持久化、部署。 |

### Phase 3 —— 具体做了什么

- **工具层**（`backend/tools/`）：`search_flights`（SerpAPI google_flights + google_search 并行）、`search_hotels`（SerpAPI google_hotels + google_maps 并行）、`search_tickets`（Firecrawl 抓取 + google_search + LLM 提取）。全部三层降级：真实 API → LLM 估算 → mock。磁盘缓存 + TTL。
- **Supervisor 智能体**（`backend/refine.py`）：双模式——从自然语言规划 + 对已有计划做精细化调整。State-aware 工具工厂自动从已有计划上下文填充参数。
- **`/ws` 双通道路由**：`type=plan` → Lane 1（完整并行 DAG），`type=chat` → Lane 2（Supervisor 调整）。连接级会话状态维持。
- **预算精度**：多币种转换（EUR/USD/CNY）、正确的行程日期计算（出发/返回/入住/退房）、往返机票处理。

---

## 项目结构

```
f1-paddock-club/
├── CLAUDE.md                  # 给 Claude Code 的完整设计上下文
├── README.md                  # 英文版
├── README.zh-CN.md            # ← 你正在看这一份
├── backend/
│   ├── main.py                # FastAPI：POST /plan、WS /ws
│   ├── graph.py               # LangGraph 编排器 + CLI 测试
│   ├── state.py               # TravelPlanState（强类型共享状态）
│   ├── llm.py                 # 可插拔大模型客户端封装（Phase 2 新增）
│   ├── agents/__init__.py     # 7 个智能体节点函数
│   ├── refine.py              # Lane 2：Supervisor 智能体（双模式规划 + 调整）
│   ├── _session.py            # WebSocket 会话管理（对话记忆 + plan state 分层）
│   ├── tools/                 # 外部数据工具（SerpAPI、Firecrawl、缓存、币种、日期、赛历）
│   ├── logging_config.py      # 文件日志配置（写到 logs/）
│   ├── requirements.txt
│   └── .env.example           # 列出所有支持的环境变量
├── frontend/
│   ├── prototype.jsx          # Paddock Club React 应用（已接 /ws）
│   ├── src/main.jsx           # Vite 入口
│   ├── index.html             # HTML 壳
│   ├── vite.config.js         # Vite 开发服务器配置（端口 3000）
│   └── package.json           # React + Vite 依赖
└── start.sh                   # 一键启动后端 + 前端
```

---

## 快速开始

### 一键启动（后端 + 前端）

```bash
# 首次安装
cd backend && pip install -r requirements.txt && cp .env.example .env
# 编辑 .env —— 至少填入 OPENAI_API_KEY
cd ../frontend && npm install
cd ..

# 启动
./start.sh
# 后端: http://localhost:8000
# 前端: http://localhost:3000（自动打开浏览器）
```

### 手动安装

#### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

#### 2.（可选）配置大模型 Provider

不设置 API key 也能跑 —— 涉及大模型的两个智能体（`itinerary`、`tour`）会自动回退到 mock 数据。配上 key 之后才会真正调用模型。推荐用 `.env` 文件来管理：

```bash
cd backend
cp .env.example .env
# 然后编辑 .env，把你的 key 填进去
```

默认配的是 **OpenAI**，任何 OpenAI key 都能直接用：

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini          # 可选，这就是默认值
# OPENAI_BASE_URL=https://...       # 可选，用 OpenAI 兼容代理时填
```

想用 Claude？切一下 provider：

```ini
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-5
# ANTHROPIC_BASE_URL=https://...    # 可选，用 Anthropic 兼容代理时填
```

想用 OpenAI 兼容的第三方服务（DeepSeek、Moonshot/Kimi、智谱 GLM、阿里通义、本地 vLLM 等）？保持 `LLM_PROVIDER=openai`，把 `OPENAI_BASE_URL` 指过去就行：

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=<那家服务给你的 key>
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

> 不想用 `.env` 文件？直接 `export` 同名变量也行 —— `llm.py` 两种来源都会读。`.env` 已经在 `.gitignore` 里，不会被 commit。

### 3. 跑 CLI 测试

```bash
# 在 backend/ 目录下
python graph.py
```

> **Windows 用户注意**：日志里有 `↔`、`→` 等 Unicode 箭头。如果你的控制台是 `gbk` 编码，会报 `UnicodeEncodeError`。改用 `PYTHONIOENCODING=utf-8 python graph.py`，或先执行 `chcp 65001`。

正常输出大概长这样：

```
=== MESSAGES (execution trace) ===
  [concierge] Planning your Italian GP trip from New York...
  [ticket]    Found 3 ticket options for Italian GP
  [hotel]     Found 2 stays in Monza (5 nights)
  [transport] Found flights New York ↔ Monza
  [plan]      Created 5-day itinerary (OpenAI)
  [tour]      Curated 5 recommendations (OpenAI)
  [budget]    Total €2189 / €2500 — within budget ✓
```

末尾的 `(OpenAI)` / `(Anthropic)` / `(mock)` 标签告诉你这一步是哪个 provider 答的，或者是不是回退到了 mock 数据。

### 4. 启动 API 服务

```bash
# 在 backend/ 目录下
uvicorn main:app --reload
# → http://localhost:8000
```

#### POST `/plan`

```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "gp_name": "Italian GP",
    "gp_city": "Monza",
    "gp_date": "Sep 6",
    "origin": "New York",
    "budget": 2500,
    "stand_pref": "mid",
    "extra_days": 2,
    "stops": "Milan 2 days → Lake Como → Monza",
    "special_requests": "需要无障碍酒店，喜欢素食餐厅"
  }'
```

#### WebSocket `/ws` —— 双通道会话

WebSocket 支持多轮会话，分两条通道：

**新建计划（Lane 1 —— 完整并行流水线）：**
```json
{"type": "plan", "data": {"gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "Sep 6", "origin": "New York", "budget": 2500, "extra_days": 2}}
```

**调整计划（Lane 2 —— Supervisor 智能体）：**
```json
{"type": "chat", "data": "我想住万豪，靠近赛道"}
```

服务端返回：
- `{"type": "message", "data": {"agent": "...", "text": "..."}}` —— 状态更新
- `{"type": "result", "data": {...}}` —— 完整状态快照（每条通道完成后）
- `{"type": "reply", "data": "..."}` —— Supervisor 的文字回复（仅 Lane 2）
- `{"type": "done"}` —— 当前请求完成

> **向后兼容**：直接发送 raw TripRequest JSON（不带 `{type, data}` 包装）会被自动识别并路由到 Lane 1。

> **注意**：首条消息用 `type=chat`（而非 `type=plan`）会走 Supervisor 的规划模式，只产出门票/机票/酒店/预算，**不包含**行程和观光推荐（3/5 sections）。要获得完整的 5/5 计划，请先用 `type=plan`。

#### 5. 启动前端

```bash
cd frontend
npm install   # 首次安装
npm run dev   # → http://localhost:3000
```

前端从 `/api/calendar` 加载 GP 赛历，通过 `/ws` 连接实时规划，渲染真实智能体结果。已结束的 GP 在选择网格中显示为半透明。

### 日志

每次运行都会往 `backend/logs/backend.log` 追加一份结构化日志（UTF-8 编码），每个智能体的状态消息、LLM 调用的起止、以及任何异常堆栈都会带上时间戳和来源模块名落进去。CLI 那份漂亮的 console 输出不动，文件日志是**额外**的审计轨迹，不是替代。

```bash
tail -f backend/logs/backend.log   # 实时跟踪
```

想看更详细的（LLM 初始化参数、调试行），把 `LOG_LEVEL=DEBUG` 写到 `.env` 里或 `export` 出来就行。`backend/logs/` 已经在 `.gitignore` 里，不会被提交。

---

## 各智能体一览

| 智能体 | 输入 | 输出 | Mock 还是大模型？ |
|---|---|---|---|
| `parse_input` | 用户表单 | 标准化的 state | 纯逻辑 |
| `ticket_agent` | 比赛、日期、偏好、预算 | 3 个看台票方案 | **Firecrawl + LLM 提取** → LLM 估算 → mock |
| `transport_agent` | 出发地、城市、日期、中转 | 机票 + 当地交通 | **SerpAPI google_flights** → LLM 估算 → mock |
| `hotel_agent` | 城市、日期、剩余预算 | 2–3 个住宿 | **SerpAPI google_hotels + maps** → LLM 估算 → mock |
| `itinerary_agent` | 上面所有结果 + 特殊需求 | 按天行程 | **大模型**（OpenAI / Anthropic）→ mock |
| `tour_agent` | 城市、天数、特殊需求 | 景点 + 美食 | **大模型**（OpenAI / Anthropic）→ mock |
| `budget_agent` | 全部输出 | 费用明细 + 是否超预算 | 纯逻辑 |

---

## 后续路线图

- **Phase 4（下一步）** —— 把 `frontend/prototype.jsx` 接上 `/ws`，后续迁移到 Next.js 实时规划界面。
- **Phase 5** —— 安全基线、错误处理、运行结果持久化、部署上线。

---

## 协议

待定。
