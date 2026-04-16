# 将当前 Debug Trace 收编为正式调试能力

## 背景

当前前端已经有一层临时 `Debug trace`，它来自一次真实排障需求：用户在浏览器里点击 GP 卡片并启动计划后，页面表面上像是“连接失败”或“没有继续”，但后端日志又显示 `/ws plan` 已经收到请求并最终完成。

这次排障证明了一个关键事实：

- 仅看用户描述，不足以判断问题是在前端点击、WebSocket 建连、消息发送、后端执行，还是结果渲染。
- 当前这层临时 trace 已经足以把几个阶段区分开，所以它不应再只是一次性的调试代码。

问题不在于“要不要调试能力”，而在于“如何把它变成项目的一部分，而不是新的临时负担”。

## 当前已知事实

当前代码已经具备这些基础：

- backend 有文件日志：`backend/logs/backend_YYYY-MM-DD.log`
- frontend 会记录一批关键事件：
  - `calendar.fetch.start/response/success/error`
  - `card.click`
  - `plan.run.click`
  - `ws.connect.start`
  - `ws.open`
  - `ws.message`
  - `ws.error`
  - `ws.close`
  - `chat.blocked.no_ws`
  - `chat.send`
- 这些日志已经帮助我们确认：
  - 某些案例不是“连不上 backend”
  - 而是“请求已发送，backend 正在跑，但前端无法清楚呈现长任务状态”

## 当前实现的不足

现有做法已经能用，但还不够稳定，也不够适合作为长期能力：

1. 事件只存在于 `frontend/prototype.jsx` 里，耦合太重。
2. 事件只保存在内存里，刷新页面就丢。
3. 只保留少量文本，缺少结构化字段。
4. 没有 `session_id` 和 `request_id`，无法稳定把前端事件与 backend 日志对应起来。
5. 没有导出能力，协作排障时还要手动复制零散片段。
6. 默认常驻在页面底部，不适合长期保留为普通用户界面。

## 目标

这套能力的目标应该很明确：

1. 让开发者和项目参与者能快速判断问题卡在哪一层。
2. 让一次失败后的上下文可以被复盘，而不是只剩一句“它坏了”。
3. 让 frontend trace 与 backend log 至少能做最小关联。
4. 保持实现轻量，不把当前 demo 项目过早做成重型 observability 平台。

## 非目标

当前阶段不应该做这些事：

1. 不做完整远程 telemetry 系统。
2. 不做用户行为 analytics。
3. 不把 debug 事件混进业务 state。
4. 不引入重型日志 SDK 或 APM。
5. 不把 Hermes 的持久化 memory / registry 体系整套搬进来。

## 建议方案

### 1. 把当前 trace 升级为“可选 debug mode”

建议将当前底部 `Debug trace` 改造成项目内正式的 `debug mode`：

- 默认关闭
- 通过 `?debug=1` 开启
- 或通过前端环境变量开启
- UI 形态建议是 drawer / overlay，而不是永久占据页面底部

这样有几个好处：

- 普通演示不被调试信息污染
- 排障时仍然可以立刻打开
- 不必为“是否让普通用户看到”反复纠结

### 2. 定义最小结构化事件格式

建议前端所有 debug 事件统一成如下结构：

```json
{
  "ts": "2026-04-16T18:08:39.123+08:00",
  "source": "ws",
  "event": "open",
  "phase": "running",
  "session_id": "sess_xxx",
  "request_id": "req_xxx",
  "data": {
    "url": "ws://localhost:3000/ws"
  }
}
```

最小字段建议如下：

- `ts`
- `source`
- `event`
- `phase`
- `session_id`
- `request_id`
- `data`

这里的重点不是字段数量，而是统一格式。现在的问题不是“没有日志”，而是“日志太像临时字符串”。

### 3. 前端建立一个轻量 Trace Store

建议把调试事件从页面组件里抽到一个轻量 store：

- ring buffer，保留最近 100 到 300 条
- 支持：
  - append
  - clear
  - copy text
  - export JSON
- 可选地在 `sessionStorage` 保留当前会话 trace

注意这里推荐 `sessionStorage`，不是长期持久化存储。当前需求是“本次演示/本次排障可复盘”，不是“做跨天记忆系统”。

### 4. 前后端增加最小关联能力

这是当前最值得补的一层，而不是继续堆更多文本：

- 前端生成 `session_id`
- 每次 `plan` / `chat` 生成 `request_id`
- 请求发到 backend 时带上这两个 id
- backend 日志里打印这两个 id
- backend 返回的 `message/result/reply/done/error` 可选回带这两个 id

这样就能把：

- 页面上的一次 `plan.run.click`
- 浏览器里的 `ws.open`
- backend log file 里的 `/ws plan`
- `plan_trip done`

准确串成一个闭环。

### 5. 调试面板展示什么

建议调试面板至少展示这些内容：

- 当前页面 host
- 当前 `API_BASE`
- 当前 `WS_URL`
- 当前 `phase`
- 当前 `session_id`
- 最近一次 `request_id`
- 最近一次 `done/error`
- 本次请求耗时
- 结构化事件列表

同时提供三个交互：

- `Copy`
- `Export JSON`
- `Clear`

### 6. 与 backend 日志的关系

backend 已经有文件日志，这很好，但两边现在是割裂的。

建议目标不是“替代 backend log file”，而是让两边职责更清楚：

- frontend debug mode：告诉我们用户点击后发生了什么
- backend log file：告诉我们服务端收到后做了什么

两者通过 `session_id` / `request_id` 关联，而不是混成一个系统。

## 建议落地顺序

### Step 1：把当前临时 trace 收编

这一步成本最低，收益最大：

- 保留现有事件
- 加开关：`?debug=1`
- 保留 ring buffer
- 增加 `done` / `error` / duration 展示
- 增加 `Copy` 和 `Export JSON`

这一步就已经能把“临时调试代码”变成“项目内可重复使用的调试能力”。

### Step 2：补前后端关联 id

这一步是当前方案真正从“能看”变成“能定位”的关键：

- `session_id`
- `request_id`
- backend 日志上下文
- ws 消息透传

### Step 3：再考虑更进一步的持久化

只有当前两步都真实用起来之后，才有必要评估：

- 是否要跨刷新保留
- 是否要写入本地文件
- 是否要接入部署环境的远程观测

这部分更接近后续 Phase 4.2 / 5，不应在现在提前做重。

## 与当前项目阶段的关系

这项工作不是“锦上添花”，它已经和当前 Phase 4.1 的稳定性直接相关。

原因很简单：

- 我们已经遇到了“看起来像连接失败，实际上不是”的案例
- 我们已经遇到了“后端降级成功，但用户以为坏了”的案例
- 如果没有一套正式的 debug capability，后续 frontend hardening 还会继续依赖口头描述和猜测

所以建议把它放在：

- Phase 4.1：轻量 debug mode + trace 收编
- Phase 4.2：如有需要，再补日志关联和部署环境的更强诊断能力

## 最终建议

当前不应该做的事情是“删掉 trace，等以后再说”。

当前更合理的做法是：

1. 承认当前 trace 已经证明了自身价值。
2. 把它从临时文本列表升级成可选 debug mode。
3. 先做轻量的结构化与导出能力。
4. 再补前后端关联 id。
5. 明确它服务于排障和演示稳定性，而不是服务于分析平台建设。

一句话总结：

当前 `Debug trace` 最值得做的，不是“变复杂”，而是“变正式、变可选、变可关联”。
