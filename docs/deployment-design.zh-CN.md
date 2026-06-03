# 部署设计

> **状态：Phase 4.7（企业级底座）已实现。** 本文最初是设计稿，设计现已落地。
> `vercel.json`、`railway.json`、`.github/workflows/deploy-smoke.yml` 均已提交，
> 而且企业级底座的范围比本文最初的「无账号 / 无数据库」更大：Clerk OAuth、
> Postgres（SQLAlchemy + Alembic）、Sentry、`/healthz` + `/readyz`、CSP/HSTS 全部
> 已发布。**权威、逐步的从零部署 runbook 以英文版为准**，见英文 README 的
> 「Deploy from scratch (Vercel + Railway + Clerk + Sentry)」一节，以及
> `docs/superpowers/specs/2026-05-27-enterprise-floor-design.md`。本中文文档作为
> 前身设计依据（目标对比、CORS/Origin、token 模型、并发、磁盘状态限制）保留；
> 下文中描述「企业级底座之前」状态的段落（例如「没有数据库」「CORS 完全放开」
> 「不含部署实施代码」）**现已被取代，请以英文 [`deployment-design.md`](./deployment-design.md)
> 的对应 superseded 注解为准**。数据库备份 / PITR / 恢复流程见英文版第 13 节
> [Database backup, PITR, and restore](./deployment-design.md#13-database-backup-pitr-and-restore)。
>
> _部署门禁验证仍在进行：`T-001` 确定性 E2E 终审与 `T-DEPLOY-VERIFY` 门禁进行中，
> 因此请把部署理解为「配置已就绪、端到端验证待完成」，而非完全签收。_

_这份文档是让 F1 Paddock Club 从本地 demo 迁到公开托管环境的生产就绪设计。它原本是设计稿；该设计现已落地（见上方状态横幅）。_

_English version: [`deployment-design.md`](./deployment-design.md)._

范围最初**刻意收窄**（search 提供者扩展、移动端 / PWA、会话持久化、用户账号系统都曾被推迟；见 [12. 不做事项](#12-不做事项)）。**注意：** 企业级底座（Phase 4.7）此后已补上用户账号（Clerk OAuth）与持久化（Postgres saved trips），因此这两项「不做事项」现已实现。

## 1. 当前运行假设

系统目前的样子。下面的设计要么原样保留，要么干净地替换掉。

### 进程

- **后端**：FastAPI + Uvicorn，监听 `127.0.0.1:8001`。两个接口 —— `/plan`（HTTP POST）、`/ws`（WebSocket）。状态以"每个 WebSocket 连接一份"的方式存在进程内存里（`main.py` 里的 `session = create_session()`）。没有数据库。
- **前端**：Vite dev server 监听 `localhost:3000`，把 `prototype.jsx` 当作 React 应用提供。生产构建（`npm run build`）产出 `frontend/dist/` 下的纯静态包。

### 开发期拓扑 —— 隐式同源假设

前端对"要连哪个后端"**没有任何抽象**：

```js
const API_BASE = "";
const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;
```

请求发到页面本身所在的 host。开发阶段能跑是因为 `vite.config.js` 把 `/api/*` 和 `/ws` 都反代到后端。一旦前后端分到不同 origin（比如 Vercel + Railway）这个假设立刻崩；[第 4 节](#4-运行拓扑与-url-策略生产必须) 单独处理这件事。

### 密钥

`backend/.env` 存 `OPENAI_API_KEY`、`SERPAPI_API_KEY`、`FIRECRAWL_API_KEY`、`LLM_PROVIDER`，已 gitignore。`backend/.env.example` 列出期望的变量结构。前端目前不持有任何密钥。

### CORS

目前在 `backend/main.py` 里完全放开：

```python
CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
```

注释里的 `tighten in production` 就是本文档要还的债。

### WebSocket 消息循环

WS handler 是一条串行的接收循环：

```python
while True:
    raw = await ws.receive_text()
    if msg_type == "plan":
        await _handle_plan(ws, msg_data, session)
    elif msg_type == "chat":
        await _handle_chat(ws, msg_data, session)
```

因为 `_handle_plan` 是 `await` 之后才读下一条 `receive_text()`，所以**一条 WebSocket 连接天然无法并行处理两个 plan**。第二条 `plan` 消息在 socket 缓冲区里排队等前一条跑完。这个事实对 [第 8 节](#8-并发与限流) 的验收标准有直接影响。

### 本地磁盘写入

后端正常运行会写两个本地目录：

- `backend/logs/backend_YYYY-MM-DD.log` —— 运行日志
- `backend/tools/.cache/` —— SerpAPI / Firecrawl 结果的时间窗缓存

两个都 gitignore。两个都写在后端进程所在的文件系统上 —— 开发机上没问题，**但本设计选的托管平台上这是易丢状态**。第 9 节专门说这件事。

### 当前的并发情况

没有限流、没有 per-session 锁、没有全局并发上限。唯一已有的入站尺寸限制是 `MAX_WS_MESSAGE_SIZE = 16 * 1024`。一条 WebSocket 连接开着，用户想发多少 `plan` 都行（但会串行执行，原因见上）。

## 2. 部署目标选择

三个现实选项，按 7 条产品级维度比较。

| 维度 | Vercel（前端）+ Railway（后端） | Fly.io 单平台 | 自建 VPS |
|---|---|---|---|
| 静态前端托管 | 原生；全球 CDN，秒级生效 | 有 static service 可选 | 手动 Nginx 之类 |
| WebSocket 长连接 | Railway 后端原生支持；Vercel 自家 functions 对 WS 有限制 | 原生；进程常驻 | 原生；Nginx `proxy_read_timeout` 手配 |
| Python 后端部署门槛 | Railway 自动识别 `requirements.txt`，`git push` 触发部署 | 需要 Dockerfile；`fly launch` 可生成 | 全栈自己写（Dockerfile、systemd、TLS 证书） |
| 环境变量 / 密钥管理 | 两个控制台 —— Vercel env vars 管前端，Railway secrets 管后端 | 单控制台 | 手动 `.env`，靠 CI 或运维人工注入 |
| 日志 / 回滚 / 可观测性 | 每个平台自带 log 查看器和按 revision 回滚 | 单平台同上 | 自己搭（journalctl + SSH，或 Grafana/Loki） |
| 免费层冷启动 | Vercel 静态从不冷启动；Railway Hobby 只要不超出免费额度，小服务可以一直保持运行 | Fly 有 scale-to-zero，唤醒 1–5 秒 | VM 开着就一直热；但你一直在付钱 |
| 运维认知负担 | 两个平台，但每个都简单 | 一个平台，概念略多 | 最高 —— OS 补丁、证书续期、监控全得自己管 |

### 推荐

本阶段选择 **Vercel + Railway**。

理由：

1. 形态和 app 匹配 —— 静态 React 走 CDN，FastAPI 在 HTTPS 后面长跑且原生支持 WebSocket。
2. 免费层经济模型对 portfolio 项目合理。Vercel 静态层基本无限；Railway Hobby 每月含 $5 usage，对小型常驻 demo 很可能够用。**实际消耗取决于 CPU、内存、egress —— 部署第一周盯一下用量，不要把 $5 当成无限保障**。
3. `git push` 触发平台侧构建与部署，两边都支持控制台一键按 revision 回滚。

**Fly.io** 是正当 alternative —— 单平台、免费额度不错、心智模型更干净。不选它是因为 Dockerfile / `fly.toml` 的学习曲线，对当前 repo 而言是多余的复杂度。将来 Railway 的费用成为问题，迁 Fly 大概一周工作量。

**自建 VPS** 本阶段明确拒绝。TLS 续期、系统补丁、日志收集、监控这些运维面，对一个还在动的产品来说不值得现在扛。

## 3. 最小部署架构

```
┌────────────────────┐       HTTPS（静态）        ┌─────────────────────────┐
│  用户浏览器        │ ─────────────────────────▶ │  Vercel CDN             │
│                    │                            │  （prototype.jsx 构建）  │
│                    │                            └─────────────────────────┘
│                    │     HTTPS: POST /plan      ┌─────────────────────────┐
│                    │ ─────────────────────────▶ │  Railway                │
│                    │         WSS: /ws           │  FastAPI + Uvicorn      │
│                    │ ─────────────────────────▶ │  （后端进程）            │
└────────────────────┘                            └─────────────────────────┘
                                                         │
                                                    （出站调用）
                                                         │
                                                         ▼
                                          OpenAI / SerpAPI / Firecrawl
```

- 前端 bundle 由 Vercel CDN 提供。
- 后端是一个 Railway service，跑 `uvicorn main:app`，同进程 FastAPI 处理 `/api/*` REST 和 `/ws` WebSocket。
- 所有外部 provider（OpenAI、SerpAPI、Firecrawl）的流量都从 Railway 后端出站。前端看不到也不嵌入这些 key。
- 本阶段没有数据库、没有缓存层、没有队列。每 WebSocket 连接级别的进程内状态已经够用。

## 4. 运行拓扑与 URL 策略（生产必须）

### 问题

当前前端从页面自己的 host 推导后端 URL：

```js
const WS_URL = `${...}://${window.location.host}/ws`;
```

生产环境里前端在 `f1-paddock-club.vercel.app`，后端在 `f1-paddock-club-backend.up.railway.app`。页面不能向自己的 host 发 API 请求，必须显式地指向后端 URL。

### 决策

前端增加两个构建期环境变量：

- `VITE_BACKEND_URL` —— 比如 `https://f1-paddock-club-backend.up.railway.app`
- `VITE_WS_URL` —— 比如 `wss://f1-paddock-club-backend.up.railway.app/ws`

运行期前端优先使用它们，只在本地开发时回退到 `window.location` 推导：

```js
const BACKEND =
  import.meta.env.VITE_BACKEND_URL ||
  window.location.origin;          // 开发期：Vite proxy 处理 /api/*

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

fetch(`${BACKEND}/api/calendar`);
new WebSocket(WS_URL);
```

Vercel 在构建时注入这两个变量，最终落到编译后的 JS bundle 里。**这两个值是公开的，不是密钥** —— 暴露在前端 bundle 里是预期的、安全的。

### 为什么不用 Vercel rewrite 反代

Vercel 能把 `/api/*` 在边缘反代到 Railway，保持同源幻觉。拒绝这个方案是因为：

- 它**不处理 WebSocket** —— rewrite 规则不能反代 `wss://`。
- 它多了一跳但在当前规模没有实际价值。

直连跨域更简单，也更诚实地反映真实拓扑。

### 开发 vs 生产对照

| | 开发 | 生产 |
|---|---|---|
| 后端 URL | Vite proxy 到 `127.0.0.1:8001` | 显式 `VITE_BACKEND_URL` |
| WS URL | 同 host + Vite ws proxy | 显式 `VITE_WS_URL` |
| Origin | `http://localhost:3000` | `https://<vercel-domain>` |
| 后端 CORS | 宽松 `["*"]` | 严格白名单（第 6 节） |

## 5. 环境变量与密钥

### 变量清单

| 变量名 | 放哪里 | 谁读 | 是密钥吗？ |
|---|---|---|---|
| `OPENAI_API_KEY` | Railway env | 后端（`llm.py`） | **是** |
| `ANTHROPIC_API_KEY` | Railway env | 后端（`llm.py`） | **是** |
| `SERPAPI_API_KEY` | Railway env | 后端（`tools/search_*.py`） | **是** |
| `FIRECRAWL_API_KEY` | Railway env | 后端（`tools/search_tickets.py`） | **是** |
| `LLM_PROVIDER` | Railway env | 后端 | 否 |
| `LOG_LEVEL` | Railway env | 后端 | 否 |
| `ALLOWED_ORIGINS` | Railway env | 后端（`main.py` CORS / Origin 检查） | 否 |
| `DEMO_ACCESS_TOKEN` | Railway env | 后端（demo token 闸门，第 7 节） | **是** |
| `VITE_BACKEND_URL` | Vercel build env | 前端 bundle | 否；设计上公开 |
| `VITE_WS_URL` | Vercel build env | 前端 bundle | 否；设计上公开 |
| `VITE_DEMO_TOKEN` | Vercel build env | 前端 bundle | 否；刻意烘进公开 bundle（见第 7 节） |

### 规则

1. **密钥永远不进前端 bundle。** 任何 `VITE_` 前缀的变量都会被编译进公开静态 JS，只有非密钥值才能放那里。
2. **密钥永远不进 git 仓库。** `.env` 已 gitignore；`.env.example` 只描述形状不含值。
3. **开发和生产不共享密钥。** Railway 上的 OpenAI key 是生产专用；开发机用自己的 `.env`。
4. **Config 层级**：`backend/.env.example`（入 git，描述形状）→ `backend/.env`（本地，gitignore）→ Railway 环境变量（生产）。

## 6. CORS 与 WebSocket Origin

### CORS

当前的 `allow_origins=["*"]` 在生产环境下换成从 env 读的白名单：

```python
import os

_ALLOWED = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED or ["http://localhost:3000"],  # 开发期兜底
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

生产 `ALLOWED_ORIGINS` 设成正好是 Vercel 前端 URL。其他 origin 在 CORS 层就被拒掉，根本进不了业务 handler。

### WebSocket Origin 检查

CORS **不会自动保护 WebSocket**。浏览器在 WS 握手时会发 HTTP `Origin` header（RFC 6455 §4.2.1），但应用得自己检查：

```python
@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    if _ALLOWED and origin not in _ALLOWED:
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    ...
```

**这是浏览器侧的建议性保护（advisory），不是鉴权（authentication）**。浏览器会如实发 `Origin`；脚本客户端（curl、Python `websockets` 等）想伪造什么就伪造什么。Origin 限制能抬高随意跨站滥用的门槛，但挡不住知道后端 URL 的有心人。把它当作一个卫生层，不是安全边界。真正保护后端的那层在 [第 7 节](#7-最小访问控制基线)。

## 7. 最小访问控制基线

本阶段**不**引入用户账号、JWT、OAuth、密码登录系统 —— 那些属于后续多用户阶段。

但本阶段**也不让后端完全裸奔**。完全开放的 `/ws` 和 `/plan`，加上每次请求会烧 OpenAI + SerpAPI credit 的 agent 链，是真实的成本滥用面。仅靠 Vercel Deployment Protection **不能解决这个问题** —— Railway 后端 URL 是**另一个 origin**，浏览器直连到那里；只要有人发现后端 URL，就能绕过前端闸门。

所以本阶段的基线是 **两层闸门**：

### 第 1 层：前端 —— Vercel Deployment Protection

在 Vercel 项目上开启自带的 Deployment Protection。访问 Vercel URL 时页面会要求输入密码才显示内容。不需要应用代码改动；具体可用范围和能力**依赖 Vercel plan**（Hobby plan 的保护范围比 Team plan 窄）。这一层把"随手点进来的人"挡在外面，不负责"保护后端"。

### 第 2 层：后端 —— 共享 demo token

Railway env 里存一个 `DEMO_ACCESS_TOKEN`。后端只在请求带对 token 时才处理。HTTP 和 WebSocket 传 token 的机制**不同**，因为浏览器 API 不同。

**HTTP `/plan`** —— 标准 bearer token：

```python
@app.post("/plan")
async def plan(request: TripRequest, authorization: str = Header(None)):
    if authorization != f"Bearer {settings.DEMO_ACCESS_TOKEN}":
        raise HTTPException(status_code=401)
    ...
```

前端从构建期 env 读 `VITE_DEMO_TOKEN`，每次 `/plan` 调用都带 `Authorization: Bearer <token>`。

**WebSocket `/ws`** —— token 用 query 参数传：

```python
@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    token = ws.query_params.get("demo_token", "")
    if token != settings.DEMO_ACCESS_TOKEN:
        await ws.close(code=1008)
        return
    # Origin 检查；通过后 accept
```

为什么 WS 用 query 而不是 `Authorization` header：浏览器的 `WebSocket` 构造函数签名是 `new WebSocket(url, protocols?)`（见 MDN）。它**没有"传任意 header"的参数**。对纯浏览器客户端来说，在初始握手时带凭据的唯一可用方式就是 query 参数。

### Query 参数传 WS token 的 trade-off

- **Token 可能出现在服务器访问日志或浏览器历史里。** 缓解手段：一旦泄露立刻轮换；生产 `LOG_LEVEL` 保持 `INFO`（不要在 `DEBUG` 下记录原始 URL）；演示设备不要共享浏览器历史。对 demo 可接受；**不适合真实鉴权**，所以这是 demo baseline，不是 Phase 5 的真鉴权。
- **所有 demo 用户共享一个 token。** 一个人泄露等于所有人泄露。这是"小范围信任 demo"的模型。
- **轮换是手动的。** 改 Railway 的 `DEMO_ACCESS_TOKEN`、改 Vercel 的 `VITE_DEMO_TOKEN`、两边都 redeploy。README 的运维手册里会写这步。

### 讨论过但没选的备选

- **Cookie 鉴权 WS**：需要同源或 CORS with credentials；split-origin demo 阶段配起来摩擦大。
- **连接后第一条消息做鉴权**：原理更干净，但 `ws.accept()` 后还得维护"未鉴权"状态拒绝业务消息；代码更多，收益相当。
- **用 `Sec-WebSocket-Protocol` 子协议承载 token**：能做，但语义上是对子协议的滥用，不选。
- **完全不做 token，只靠 Origin 和限流**：一旦后端 URL 泄露就暴露成本滥用面，本阶段不选。

### 这一层明确不做的事

- **不做 per-user 身份**。这是共享密钥的闸门，不是用户身份系统。
- **不做基于角色的访问控制**。只有一个访问级别。
- **不做审计**。"谁发起了哪次请求"这层信息这个设计不提供。

这些归多用户阶段。

## 8. 并发与限流

四层，由应用内到网络边缘。

### A 层：per-connection 串行处理（已有）

`main.py` 的 WebSocket handler 已经在每条消息之间 `await`：

```python
while True:
    raw = await ws.receive_text()
    await _handle_plan(...)   # 必须跑完
    # 跑完才读下一条 receive_text
```

所以**一条连接已经天然串行处理 plan**，不需要额外加锁。正确的产品行为建在这之上：

- 前端在 plan 进行中 disable "Plan" 按钮。
- 如果客户端硬是在第一条 plan 还没返回前发了第二条（比如脚本客户端），第二条就在 socket buffer 里排队，等第一条处理完后跑。不报错、不并发。

这一层不需要新代码改动。早期设计稿里"第二条 plan 立刻被拒"不是当前架构的实际行为，对这个阶段也不是有用行为。B 层的 semaphore 覆盖了真正的风险（跨连接并发）。

### B 层：全局并发上限

模块级 `asyncio.Semaphore(N)` 限制整个后端进程的 `plan_trip` 并发数。`N` 从 `MAX_CONCURRENT_PLANS` env 读，默认 5。

```python
_plan_semaphore = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT_PLANS", "5")))

async def _handle_plan(ws, data, session):
    try:
        async with asyncio.timeout(5):
            await _plan_semaphore.acquire()
    except TimeoutError:
        await ws.send_json({"type": "error", "data": "server busy, try again"})
        return
    try:
        await asyncio.to_thread(plan_trip, data)
    finally:
        _plan_semaphore.release()
```

防止一批突发连接把 Railway 单进程打挂或瞬间抽干 LLM 额度。

### C 层：HTTP 限流（用库）

HTTP `/plan` 用 `slowapi`，按 IP 限（比如每分钟 10 次）：

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/plan")
@limiter.limit("10/minute")
async def plan(request: Request, ...):
    ...
```

选 `slowapi` 而不是自己写，是因为 HTTP 限流是成熟模式，库够用。**但 `slowapi` 当前不支持 WebSocket endpoints**，所以下一层自己写。

### D 层：WebSocket 限流（应用内手写）

因为 `slowapi` 不覆盖 WebSocket，在 WS accept 路径上跑一个小的进程内滑动窗口限流器：

```python
class IPRateLimiter:
    def __init__(self, max_per_window: int, window_seconds: int):
        self.max = max_per_window
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        events = self._events[ip]
        cutoff = now - self.window
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self.max:
            return False
        events.append(now)
        return True

_ws_connect_limiter = IPRateLimiter(max_per_window=20, window_seconds=60)

@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    ip = ws.client.host if ws.client else "unknown"
    if not _ws_connect_limiter.allow(ip):
        await ws.close(code=1008)
        return
    # origin 检查、token 检查，然后 accept
```

这层的**已知限制**写进设计：

- **只在单实例下生效。** 限流器状态在进程内存里。将来后端扩成多 Railway 实例时，各实例各算各的，实际限流会比标称的宽。基于 Redis 的限流器（或挪到 edge 层）是下一步 —— 属于真正的多实例阶段（Phase 5）的事。
- **不做全局并发上限。** 它限的是单 IP 的连接率，总并发由 B 层管。
- **表面最小。** 同 IP 的 plan 消息速率在本阶段不单独限 —— 连接率 + 全局 semaphore 对 demo 已经够。如果单 IP 开 20 连发 20 plan，B 层的 semaphore 会管住执行。

### E 层：payload 大小（已有）

`MAX_WS_MESSAGE_SIZE = 16 * 1024`。不变。超大消息在处理前就拒掉。

## 9. 日志与本地 cache 的生产限制

后端写的两个本地路径 —— log 和 tool cache —— 在开发机上和托管平台上行为差别非常大。

### 文件日志

`backend/logs/backend_YYYY-MM-DD.log` 是磁盘上的文件。在 Railway / Render / Fly 上，容器文件系统是**易丢的**：

- Redeploy 时文件系统重建，日志不跨部署存。
- 重启、自动扩缩容时也会清。
- 多实例部署时（本阶段不是，但未来可能），每个实例写自己的本地文件，没有统一视图。

对本阶段的含义：

- **文件日志只当作进程内短期诊断用。** SSH 或 `railway run` 进容器看最近行为时有用，但**不能替代平台日志聚合**。
- **STDOUT / STDERR 是生产环境的正规日志目的地。** Railway、Fly、Vercel 都抓 STDOUT。每个 `logger.*(...)` 调用通过根 logger 的默认 handler 已经写到 STDOUT，所以平台已经看得到全部。
- **文件 handler 保留** 便利性，不做重构 —— 但它**不是可靠层**。

结构化日志外送（Logtail、Better Stack、自建 Loki）在平台自带日志不够用的时候再考虑，属于后续阶段。

### Tool cache

`backend/tools/.cache/` 存 SerpAPI 和 Firecrawl 结果的时间窗缓存（`_cache.py` 装饰器）。同样是易丢属性：

- Redeploy 缓存全丢。
- 重启也会丢。
- 多实例下各实例缓存不共享。

含义：

- **缓存是 best-effort 性能优化，不是事实源。** Cache miss 就再打 upstream 一次。
- **缓存绝不能当状态或持久层用。** 任何假设缓存能跨部署生存的代码在托管平台上都是错的。
- **多实例缓存一致性不是本阶段目标。** 将来后端跑多个 Railway 实例时，共享缓存（Redis）是对的方向，那一步属于那个阶段。

生产级缓存（Redis 或等价）在缓存命中率真正值得付这个钱时可以加 —— 现在不需要。

## 10. CI/CD 与回滚

### CI（已就位）

`.github/workflows/ci.yml` 每次 push 和 pull request 都跑：

- `backend`：`python -m compileall -q .`
- `frontend`：`npm ci` + `npm run build`

验证发布前必须成立的两件事。未来加测试、lint、安全扫描、deploy 都是新增 step，不重写结构。

### 本阶段不做仓库层 CD

Vercel 和 Railway 都在 `git push` 到配置分支时自动部署。**这就是实际意义上的 CD**，只是不在仓库的 workflow 文件里控制。

本阶段**不**加 deploy job 到 GitHub Actions。理由：

1. Tag-gated deploy、preview 环境、staging 分支、回滚策略都有价值但现在做早了；产品还没有真实使用模式。
2. 靠平台自带 deploy 让失败面更小、更好读。一次 git push、一个平台 build 日志、一次 deploy。
3. 自写 `actions/deploy@…` job 要把平台密钥放到 Actions 环境 —— 多一层密钥管理，当前没有直接收益。

后续阶段可以为具体目标再引入仓库层 deploy workflow：tag 门控的生产部署（只在 `v*.*.*` tag 上 deploy）、PR preview URL、多服务协调部署。这些现在都不需要。

### 运维手册（写在 README 里，写给人看的）

README —— 不是 workflow 文件 —— 记录出货流程：

1. PR 合进 `main` 后 CI 绿。
2. Vercel 自动构建并 promote；新静态 bundle 大约 60 秒内 live。
3. Railway 自动构建并 deploy；新后端大约 2–3 分钟内 live。前一个 revision 在控制台保留，一键回滚。
4. 按 [11.1 节](#111-部署后冒烟验证) 的 smoke 路径验证。

### 回滚

两个平台都暴露 per-revision 回滚按钮。回滚之后：

- 本地 `git checkout <sha>` 拉到该 commit，确认问题确实出在新 commit 而不是配置 / env 问题。
- 针对回滚后的 URL 再跑一遍 [11.1 节](#111-部署后冒烟验证) 的 smoke。
- 如果回滚发生在生产环境，在 `CHANGELOG.md` 的下一个 `[Unreleased]` 里一行记录下，保持历史诚实。

## 11. 验收清单

下面每条在本阶段结束时都要能演示过。

### 11.1 部署后冒烟验证

1. `curl https://<railway-domain>/api/calendar` 带正确的 `Authorization: Bearer <DEMO_ACCESS_TOKEN>` → `200 OK` 返回 2026 GP 列表。
2. 同一个请求**不带** header → `401`。
3. 浏览器打开 `https://<vercel-domain>`，通过 Vercel Deployment Protection 密码后页面渲染；network 里 calendar 请求打到 Railway 且带 bearer token。
4. 从 UI 发起 plan 建立 WebSocket 到 `wss://<railway-domain>/ws?demo_token=…`，3 秒内收到至少一条 `message` 事件，完整跑出 `result → done`，以简单 GP 为例（Italian GP mock 即可）。
5. 非默认 GP（比如 Azerbaijan）带显式 depart/return 日期完整跑通 —— 即便上游 provider（SerpAPI、Firecrawl）限流，三层降级能兜住。

### 11.2 后端直连保护验证

1. `curl https://<railway-domain>/api/calendar` **不带** bearer token → `401`。证明知道 URL 但没有 token 的脚本客户端打不进来。
2. `wscat -c "wss://<railway-domain>/ws"`（不带 `demo_token` query）→ 服务端 code 1008 关闭。证明 WS 闸门不依赖 Vercel 页面保护。
3. `wscat -c "wss://<railway-domain>/ws?demo_token=<WRONG>"` → code 1008 关闭。
4. `wscat -c "wss://<railway-domain>/ws?demo_token=<CORRECT>" --origin https://unknown.example.com` → code 1008 关闭（Origin 检查和 token 独立）。

### 11.3 安全卫生

1. Railway 上设了 `ALLOWED_ORIGINS` env；`CORSMiddleware` 读它；生产没有 `["*"]`。
2. `grep -r "OPENAI_API_KEY\|SERPAPI_API_KEY\|FIRECRAWL_API_KEY\|DEMO_ACCESS_TOKEN" frontend/dist/` 无命中。只有 `VITE_BACKEND_URL`、`VITE_WS_URL`、`VITE_DEMO_TOKEN` 出现在 bundle（设计上公开）。
3. Vercel 项目开启了 Deployment Protection。

### 11.4 并发保护

1. 全局 semaphore：设 `MAX_CONCURRENT_PLANS=2`，同时开 5 条 WebSocket 各自发一次 plan → 任意时刻后端最多 2 个 `plan_trip` 在跑，其他的要么等、要么在 5 秒 acquire 超时后收到"server busy"。
2. HTTP 限流：同一 IP 60 秒内发 12 次 `/plan` → 第 11、12 次返回 `429`。
3. WS 连接率：同一 IP 60 秒内尝试 22 次 WebSocket 连接 → 最后两次 code 1008 关闭。
4. Payload 大小：在已建立的 WS 上发一条 20 KB 消息 → 服务端用已有的超大拒绝错误拒掉。

### 11.5 生产限制确认（无代码，但要验证）

1. Railway redeploy 之后，新 revision 的 `backend/logs/` 空 —— 证明文件日志不跨部署。平台日志查看器里还能看到 STDOUT 的历史。
2. Redeploy 之后 `backend/tools/.cache/` 也是空 —— 证明缓存是纯 best-effort。
3. 这些行为都在 README 的 deploy 手册里写清楚是预期的，不是 bug。

### 11.6 回滚演练

1. 故意部署一个坏 commit（比如某条 status message 语法错）。
2. Railway 控制台回滚到前一个 revision。
3. 对回滚后的 URL 再跑一遍 11.1 全套，全部通过。
4. 把这次演练结果在 `CHANGELOG.md` 的 `[Unreleased]` 下一行一句话记录。

## 12. 不做事项

这个设计不覆盖也不假装覆盖的东西。每条都延期到后续指名的阶段。

- **用户账号、JWT、OAuth、密码登录** —— 多用户阶段。
- **重连后的会话持久化** —— 多用户阶段。当前状态是 per-WebSocket 进程内存，重连从零开始。
- **Per-user 额度 / 归属 / 审计** —— 多用户阶段。
- **Preview / staging 环境** —— 这个阶段一个生产环境够用。
- **自定义域名** —— Vercel / Railway 默认子域名足以支持首次部署；想要 `.com` 将来控制台 15 分钟配完。
- **Tavily / `search_web` provider adapter** —— 单独设计，单独阶段。
- **PWA manifest、移动端响应式、触控优化** —— 单独设计，单独阶段。
- **移动端分发策略** —— 独立产品决策，在后续独立文档评估；本部署设计**不对移动端形态作任何假设**。
- **仓库控制的 CD pipeline** —— tag-gated 部署 / preview URL 真正有需求时再做。
- **结构化日志外送 / APM / 分布式追踪** —— 平台日志查看器目前够用。
- **Redis 或任何共享缓存 / 状态存储** —— 等到真正需要多实例时再回来看。
- **跨实例的生产级 WS 限流** —— 同上。

## 决策汇总

| # | 决策 | 选择 |
|---|---|---|
| 部署目标 | Vercel（前端）+ Railway（后端） | ✅ |
| 备选考虑 | Fly.io 单平台 —— 可行，非首选 | — |
| 拒绝 | 自建 VPS —— 当前阶段运维成本不值得 | ❌ |
| 生产 URL 策略 | `VITE_BACKEND_URL` + `VITE_WS_URL` 构建期注入；`window.location` 只开发期用 | ✅ |
| CORS | `ALLOWED_ORIGINS` env 驱动的白名单；生产绝无 `["*"]` | ✅ |
| WS Origin gate | 握手时读 `Origin` header；advisory，不是鉴权 | ✅ |
| 访问基线 —— 前端 | Vercel Deployment Protection（能力依 plan 而变） | ✅ |
| 访问基线 —— 后端 | `DEMO_ACCESS_TOKEN`：HTTP 用 `Authorization: Bearer`，WS 用 query 参数 | ✅ |
| 单连接行为 | 依赖当前串行 receive loop；前端 disable 重复提交 | ✅ |
| 全局并发上限 | 模块级 `asyncio.Semaphore(N)`，`N` 从 env 读 | ✅ |
| HTTP 限流 | `slowapi` 按 IP 限 `/plan` | ✅ |
| WS 限流 | 应用内手写 per-IP 滑动窗口，挂在 WS accept 上 | ✅ |
| 本阶段的 CD | 不自己做 —— 平台自带 auto-deploy 就是生产路径 | ✅ |
| 回滚 | 平台按 revision 回滚 + README 手册 + 回滚演练 | ✅ |
| 日志 | 文件 handler 便利保留；STDOUT 在平台上是正规源头 | ✅ |
| Tool cache | Best-effort；不是持久层、不是事实源 | ✅ |
| 移动端分发 | 独立产品决策，后续独立文档评估 | — |
