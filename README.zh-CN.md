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

共享状态 `TravelPlanState` 在所有 list 字段上使用 `Annotated[list, operator.add]` reducer，这样并行节点可以同时往同一个列表里追加内容，不会互相覆盖。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 编排 | **LangGraph**（状态机 + 并行扇出 + 条件边） |
| 大模型 | **Claude**，通过 `langchain-anthropic` 接入 |
| 后端 | **Python 3.12+** + **FastAPI** + **Uvicorn** |
| 流式推送 | **WebSocket**（`/ws`），把每个智能体的状态实时推给前端 |
| 前端 | React 原型（`frontend/prototype.jsx`），后续迁移到 Next.js |

---

## 当前进度（Phase 2 进行中）

| 阶段 | 状态 | 内容 |
|---|---|---|
| **1 — 图 + Mock 数据** | ✅ 已完成 | LangGraph 完整接好，7 个智能体全部返回 mock 数据，CLI 可端到端跑通，FastAPI 的 `/plan` 和 `/ws` 都能用。 |
| **2 — 真实大模型调用** | 🟡 进行中 | `itinerary_agent` 与 `tour_agent` 已切到 **Claude**，使用 `langchain-anthropic` 的 `with_structured_output`。当 `ANTHROPIC_API_KEY` 未设置或调用失败时，自动回退到 mock 数据。 |
| **3 — 外部数据工具** | ⏳ 待开始 | 接入 SerpAPI 拉机票/酒店、接入门票搜索源。 |
| **4 — 前端迁移** | ⏳ 待开始 | 把 `prototype.jsx` 迁到 Next.js，对接 `/ws`。 |
| **5 — 打磨与部署** | ⏳ 待开始 | 错误处理、运行结果持久化、部署上线。 |

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
│   ├── llm.py                 # Claude 客户端封装（Phase 2 新增）
│   ├── agents/__init__.py     # 7 个智能体节点函数
│   ├── tools/__init__.py      # 外部工具占位（Phase 3+）
│   └── requirements.txt
└── frontend/
    └── prototype.jsx          # Paddock Club 主题的 React 原型
```

---

## 快速开始

### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2.（可选）设置 Anthropic API Key

不设置 key 也能跑 —— 涉及大模型的两个智能体（`itinerary`、`tour`）会自动回退到 mock 数据。设置之后才会真正调用 Claude。

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Windows cmd / git-bash
set ANTHROPIC_API_KEY=sk-ant-...
```

可选：覆盖默认模型（默认是 `claude-sonnet-4-5`）。

```bash
export ANTHROPIC_MODEL=claude-sonnet-4-6
```

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
  [plan]      Created 5-day itinerary (Claude)
  [tour]      Curated 5 recommendations (Claude)
  [budget]    Total €2189 / €2500 — within budget ✓
```

末尾的 `(Claude)` / `(mock)` 标签告诉你这一步走的是真实大模型还是 mock 回退。

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
    "gp_date": "Sep 7",
    "origin": "New York",
    "budget": 2500,
    "stand_pref": "mid",
    "extra_days": 2,
    "stops": "Milan 2 days → Lake Como → Monza",
    "special_requests": "需要无障碍酒店，喜欢素食餐厅"
  }'
```

#### WebSocket `/ws`

发送同样的 JSON，服务端会随着每个智能体完成推送 `{type: "message", data: {...}}`，最后再推一个 `{type: "result", data: {...}}` 和 `{type: "done"}`。

---

## 各智能体一览

| 智能体 | 输入 | 输出 | Mock 还是大模型？ |
|---|---|---|---|
| `parse_input` | 用户表单 | 标准化的 state | 纯逻辑 |
| `ticket_agent` | 比赛、日期、偏好、预算 | 3 个看台票方案 | mock（Phase 3 接真实数据） |
| `transport_agent` | 出发地、城市、日期、中转 | 机票 + 当地交通 | mock（Phase 3 → SerpAPI） |
| `hotel_agent` | 城市、日期、剩余预算 | 2–3 个住宿 | mock（Phase 3 → SerpAPI） |
| `itinerary_agent` | 上面所有结果 + 特殊需求 | 按天行程 | **Claude**（Phase 2） |
| `tour_agent` | 城市、天数、特殊需求 | 景点 + 美食 | **Claude**（Phase 2） |
| `budget_agent` | 全部输出 | 费用明细 + 是否超预算 | 纯逻辑 |

---

## 后续路线图

- **Phase 3** —— 把 `tools/` 接到 SerpAPI（机票、酒店）和门票搜索源，逐步替换 `ticket`/`transport`/`hotel` 的 mock。
- **Phase 4** —— 把 React 原型迁到 Next.js，前端通过 `/ws` 实时驱动「规划中」界面。
- **Phase 5** —— 完善错误处理、运行结果持久化、部署上线。

---

## 协议

待定。
