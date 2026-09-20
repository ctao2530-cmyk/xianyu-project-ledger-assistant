# 开发与验证

## 环境

- Node.js 22、pnpm 10，前端依赖由 `pnpm-lock.yaml` 固定。
- Python 3.11+（建议 3.12）。Python 依赖在 `pyproject.toml` 中使用版本区间，目前没有独立锁文件。
- macOS / Linux；启动脚本使用 `.venv/bin/python`，Windows 需适配路径。

按 README 安装依赖后，`pnpm run dev:local` 启动 `8877` 后端和 `5173` Vite。后端已有实例时，使用 `pnpm run dev` 只启动前端。不要同时执行多套启动命令占用同一端口。

`pnpm run build` 生成 `dist/client/`、`dist/server/` 和 Sites 配置；本地完整应用由 FastAPI 提供服务。生成静态产物并不等于已部署业务后端。

## 自动化检查

```bash
pnpm run check
.venv/bin/python -m pytest backend/tests
```

`check` 按顺序执行类型检查、构建、交互回归、收支与排序行为测试、Sites 产物测试，任一步失败即停止。仓库提供前后端 GitHub Actions 作业，`pnpm run check:all` 串行执行本地前后端检查。远端结果需以实际运行记录为准。

范围较小的授权与数据回归：

```bash
.venv/bin/python -m pytest backend/tests/test_customer_context_expiry.py backend/tests/test_customer_context_thread_bindings.py backend/tests/test_customer_context_timeline.py backend/tests/test_customer_message_search.py
node --test tests/operating-records-history.test.mjs tests/customer-controls.test.mjs tests/message-timeline.test.mjs tests/customer-timezones.test.mjs
```

部分历史前端测试直接断言源码结构，UI 演进后可能与当前界面不一致；失败需判断是行为回归还是旧断言，不应通过删除断言来制造通过结果。页面验收还需检查桌面/手机布局、键盘操作、控制台与截图。

本次发布的实际结果与已知失败项见 [发布验证记录](verification.md)。

## 可选集成

| 集成 | 配置入口 | 使用约束 |
| --- | --- | --- |
| 闲鱼 / 企微 | `.env.example` 与设置中心 | 仅使用本人授权账号；无凭证时不构成渠道接通 |
| Codex CLI | `CODEX_COMMAND` | 改为本机已安装的命令路径，登录由使用者完成 |
| DeepSeek | `DEEPSEEK_API_KEY` | 显式调用；失败不静默改用其他模型 |
| OpenAI 分析 | `backend/app/config.py` 中 `openai_*` 配置 | 需 API 凭证和单独的客户分析订阅，可能产生费用 |
| ChatGPT MCP | `customer_context_*` 配置 | 配置 OAuth 或 tunnel 身份边界，再显式选择会话与权限 |

真实凭证只保存在未跟踪的本地配置。不要把 `.env`、数据库、客户图片或调试响应加入提交。

## 演示截图

README 首页、项目与收支图片来自 `demo.localhost:8877` 的独立虚构 SQLite 场景，与当前 Aurora UI 对应。项目、客户、金额和消息均为演示数据；既有经典界面截图仍保留用于历史说明。截图不代表实际经营成果。

完整本地应用启动后可访问演示入口，初始化与录屏说明见 [HR 演示指南](HR演示数据与录屏脚本.md)。`pnpm run demo` 仍用于只读经典界面夹具，与完整后端演示入口不同。

离线恢复工具与授权边界见 [备份恢复](local-recovery.md)。当前模块边界见 [重构记录](refactor-20260916.md)。
