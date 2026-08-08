# 咸鱼个人开发者经营助手

本项目把项目记账、客户关系、收支利润、沉浸任务流、商品经营策略与闲鱼/微信客服整合为一个本机经营平台。React 前端保留浅色 SaaS 设计；FastAPI 与 SQLite 负责统一数据、消息监听、每日商品快照、DeepSeek 快速草稿与线索识别、Codex 深度草稿、GPT 人工需求蓝图导入、规则报价和人工确认后的项目转化。

## 本机运行

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
pnpm install
pnpm run dev:local
```

浏览器打开 Vite 显示的本机地址。开发服务器会代理 `/api`、`/events` 与微信 Mock 回调到 FastAPI。构建本机单端口版本：

```bash
pnpm run build
pnpm run local
```

`pnpm run local` 由 FastAPI 托管 `dist/client`，默认仅监听 `127.0.0.1:8877`。当前 Mac 通过用户级 LaunchAgent `com.chentao.xianyu-ledger-assistant` 在登录后自动启动，并在进程异常退出时自动恢复。Sites 构建仍可用，但客户消息、Cookie、Codex CLI 与发送能力只在本机后端连接时启用。

## 数据与安全

- 主数据库：`data/xianyu_operator.db`（已加入忽略规则）。
- 原回复助手数据库在复制前生成本机备份，源仓库不会被修改。
- `.env`、Cookie、企业微信密钥和 Codex 登录凭证不会进入前端、SQLite、日志或导出文件。
- `DEEPSEEK_API_KEY` 只写入未跟踪的本机 `.env`；网页只显示是否配置、模型名和脱敏健康状态。
- 真实发送默认必须人工确认；自动化测试只使用 Mock 渠道。
- 商品经营每天最多进行一次只读远程采集；系统只生成策略和记录人工动作，不会修改、发布、下架商品或产生推广费用。
- 旧浏览器记账数据可在“设置中心 → 数据迁移”先预览冲突，再确认导入 SQLite。

## 项目异常结算

- 接单项目可从项目驾驶舱、项目详情或收入记录页记录客户不满意、退款、取消、拒付、终止合作、需求范围争议和其他异常。
- `净到账 = 累计实际入账 - 实际退款`；`可收余额 = 合同额 - 累计实际入账 - 确认无法收回`。退款只减少净到账和利润，不会再生成一笔支出。
- 全额核销会复用原待收节点并标记为“已核销”；部分核销会保留剩余待收金额。异常记录不会自动改变项目交付状态。
- 所有异常与到账写入都携带账本修订号和请求 ID，防止多浏览器覆盖与网络重试产生重复记录。数据库升级前会自动创建时间戳备份。

## AI 分工

- 新消息优先使用 DeepSeek 生成三条快速草稿；回复区可明确改用 Codex 深度草稿，失败时不会静默切换 Provider。
- DeepSeek 线索分析只给出需求信号、缺失信息和转化建议，只有用户确认后才保存为销售线索。
- 需求分析采用“脱敏导出 → 用户交给自己的 GPT → 粘贴严格 JSON → 校验预览 → 人工保存”的流程；系统不会读取 ChatGPT 登录态或自动调用 ChatGPT API。
- 客户需求以独立案例和不可变版本保存在 SQLite，并通过浅色四层蓝图展示目标、功能、实施阶段和交付验收。
- 新版需求蓝图自带阶段工时，报价金额由本地规则计算，不再额外调用慢速模型。

### DeepSeek 本机配置

DeepSeek 密钥只保存在项目根目录的 `.env`。将 `.env.example` 中的以下配置复制到 `.env`，填入自己的 Key 后重启本机 `8877` 服务：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_REPLY_MODEL=deepseek-v4-flash
DEEPSEEK_LEAD_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=12
```

后端通过 `POST https://api.deepseek.com/chat/completions` 生成草稿和线索分析，通过 `GET https://api.deepseek.com/models` 检测 Key 与连接状态。网页中的入口为“设置中心 → AI与回复”，这里只显示非敏感状态、模型和实际请求路径，不会读取或回显 API Key。
