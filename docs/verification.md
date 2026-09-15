# 发布验证记录 · 2026-09-15

本记录针对招聘展示版的独立源码副本，不使用本机真实客户数据库、渠道凭证或客户图片。

## 后端

环境：macOS ARM64、Python 3.12.14；从 `pyproject.toml` 新建虚拟环境安装。

- 依赖安装成功，`pip check` 通过。
- 完整 `pytest backend/tests`：**688 通过、1 跳过、5 失败**。
- 五项失败都发生在历史迁移测试的最终版本号断言：期待 `20260907_0045`，实际迁移到 `20260908_0046`。这不等于全套测试通过，后续应同步维护测试预期并重新验证。
- 为避免 editable 安装下仓库脚本与 `backend/scripts` 同名冲突，补充 `scripts/__init__.py`；没有改变业务处理逻辑。

失败用例所在文件：

- `backend/tests/test_business_analysis_persistence.py`
- `backend/tests/test_business_recommendation_feedback.py`
- `backend/tests/test_customer_item_migration.py`
- `backend/tests/test_prediction_engine.py`
- `backend/tests/test_traffic_growth.py`

## 前端

环境：Node.js 24.19.0，使用与当前 `pnpm-lock.yaml` 匹配的已有前端依赖。尝试全新 pnpm 10 安装时，最后一个 esbuild 二进制包下载反复断线，因此未将全新前端安装计为通过。

- `npm run typecheck` 通过。
- `npm run build` 通过，并生成 Sites 所需文件；仍有大于 500 kB 的 bundle 提示。
- 经营记录历史、页面控件、客户控件、信息架构、消息时间线、时区及 Sites 的 45 项回归全部通过。
- README 中隔离演示服务器能够启动，页面、脚本、样式和品牌图片请求均为 HTTP 200；本次未重复进行完整浏览器视觉验收。

## 证据范围

合成数据截图仅展示当前界面；不代表真实客户验收。后端自动化结果不代表第三方账号登录、远程渠道、付费模型或生产部署完成。

本次公开树不包含本地数据库、原始客户图片、凭证、内部验收截图或本机运行日志。此记录不宣称对仓库既有公开历史进行了独立安全审计。
