# 项目工作区与浅色任务流 Design QA

## 验收目标

- 用户列表参考：`/var/folders/sy/k3k07pxn1g94vr4gr9hsxlq80000gn/T/codex-clipboard-ca979344-6ce5-4f99-9e83-af8596c79ef8.png`。
- 用户详情参考：`/var/folders/sy/k3k07pxn1g94vr4gr9hsxlq80000gn/T/codex-clipboard-c3fbb11e-3481-4a14-a3b0-7c74ea417238.png`。
- 修改前保存截图：`qa/project-workspace-before.png`。
- 项目列表实现截图：`qa/project-workspace-list-1440x900-final.png`。
- 浅色任务流实现截图：`qa/project-workspace-detail-light-default.png`。
- 列表前后对比：`qa/project-workspace-list-comparison.png`。
- 详情前后对比：`qa/project-workspace-detail-comparison.png`。
- 隔离验收地址：`http://127.0.0.1:8990/`，数据库为 `/tmp/xianyu-project-workspace.8c8uKQ/qa.db`，未读取闲鱼 Cookie，也未污染用户真实经营数据。
- 最终交付地址：`http://127.0.0.1:8991/#%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86`。
- 最终同地址可见视口截图：`qa/project-workspace-final-8991-viewport.png`；全页截图的浏览器后端会产生平铺，因此最终视觉证据使用未平铺的可见视口版本。

## 设计结果

- 项目管理已从“混合项目列表”改成一个统一浅色工作区。标题、分类、当前分类指标、阶段筛选、项目卡片、分类洞察、近期节点和组合时间线均位于同一工作区内。
- “个人项目 / 接单项目”是工作区内部的主分类，一次只显示一个类别；切换后指标、筛选、卡片、洞察和时间线同步更新。
- 每个项目使用整张可点击卡片。卡片展示名称、类型、状态、进度、任务、日期以及分类相关数据，点击后默认进入该项目的沉浸任务流。
- 个人项目不显示客户、合同、报价或回款字段；接单项目继续显示合同金额、已收/未收、利润、小时收益、客户沟通和需求报价。
- 项目详情的摘要、工期与进度、分类指标、详情标签和任务流都被收进同一个浅色工作区，不再出现孤立的黑色驾驶舱。
- 沉浸任务流保留阶段列表、空间任务卡、任务时间线、智能详情和本地规则建议；普通卡为白色，当前卡为紫色，进行中为蓝色、完成为绿色、逾期为红色，视觉语言与全站浅色 SaaS 保持一致。

## 对比结论

### Pass 1

- [P1] 原任务流使用整块黑色驾驶舱，与用户要求的全站浅色 UI 不一致。
  - 修复：保留空间交互和数据密度，仅将表面、边框、阴影、状态色和焦点卡重构为白色/浅紫体系。
- [P1] 原项目列表把个人项目和接单项目混在一起，且无法表达两类项目不同的数据语义。
  - 修复：新增工作区内分类切换和分类专属指标、字段与洞察；旧项目缺少分类时按接单项目兼容。
- [P2] 列表卡片只有内部按钮区域可点击，交互目标不够明确。
  - 修复：整张项目卡改为语义化按钮，并补齐 hover、focus、指针和清晰的“进入项目”反馈。

### Pass 2

- [P1] 隔离浏览器中创建个人项目后，任务可在前端显示，但刷新后丢失；后端日志显示个人项目因为没有客户外键而未进入规范化项目表，任务插入触发外键失败。
  - 修复：`business_projects.customer_id` 改为可空，新增 `project_kind` 规范化字段和版本化迁移；旧 SQLite 自动安全重建项目表并执行外键检查。
  - 结果：个人项目、任务、任务状态、实际工时和项目进度均在刷新后保留，规范化表无外键错误。
- [P2] 收入页下拉仍会枚举全部项目。
  - 修复：收入与快速记账只接收接单项目；个人项目不会进入合同、回款和客户消费统计。

### Pass 3

- 未发现剩余 P0、P1 或 P2 视觉与交互问题。
- P3 非阻塞说明：浏览器视口能力的最窄 CSS 宽度会钳制为 480 px，无法生成精确 390 px 截图；同一 `max-width: 560px` 规则已在 480 × 844 验证，文档横向溢出为 0。

## 交互与数据回归

- 分类：个人 / 接单切换、分类计数、分类指标、状态筛选、搜索、排序、近期节点和时间线均可操作。
- 路由：整卡点击进入 `#项目管理/<projectId>/immersive`；刷新保持项目和标签；浏览器后退/前进在项目列表与详情间恢复；页面“返回项目列表”回到正确分类。
- 任务：卡片点击、阶段点击、时间线点击、上一项/下一项、ArrowLeft/ArrowRight、Home/End、水平拖动和滚轮均能改变选中任务并同步右侧详情。
- 滚轮边界：轨道内任务 3 → 4 时页面 `scrollY` 保持不变；到达末项继续向下滚动时，任务保持末项且页面正常从 `1267` 滚动到 `1527`，没有滚动锁或自动跳底。
- 状态推进：任务从待开始 → 进行中 → 已完成后，指标从 `4/0/0/0` 更新为 `3/0/1/0`，个人项目完成度更新为 25%，实际工时更新为 4h，刷新后保持一致。
- 持久化：个人项目在规范化表中的 `customer_id = NULL`、`project_kind = personal`；4 个个人任务均拥有有效项目外键；`PRAGMA foreign_key_check` 无结果。
- 接单项目：合同金额、已收/未收、实际利润、小时收益、客户沟通和需求报价全部保留；旧项目按接单项目兼容。
- 收入页：项目下拉仅显示 `uni-app页面修改`，不包含个人项目 `个人产品增长实验`。
- 浏览器控制台：项目工作区、个人详情、接单详情和收入页均无 error 或 warning。

## 响应式验收

- 1440 × 900：列表使用阶段 / 卡片 / 洞察三段布局；项目卡完整，分类切换与四项指标基线稳定。
- 1024 × 768：任务流为“阶段 + 3D 轨道”两列，时间线和详情移到下方；任务卡保持 CSS 3D，文档横向溢出为 0。
- 768 × 1024：任务流变为单列，任务卡为无透视的 158 px 横向卡片，个人项目不出现客户沟通和需求报价，横向页面溢出为 0。
- 480 × 844：项目卡单列；任务卡变为 368 px 全宽紧凑列表，`position: relative`、`transform: none`；分类按钮和工作区均未溢出。
- `prefers-reduced-motion`：现有媒体查询保留即时透明度反馈，并取消透视位移动画。

## 工程验收

- TypeScript 类型检查通过。
- Vite 生产构建通过，并生成 `dist/client/index.html`、`dist/server/index.js` 与 `dist/.openai/hosting.json`。
- 后端完整测试 79/79 通过，其中包含个人项目无客户、任务外键和快照修订回归。
- Sites Worker 4/4 通过；迁移与后端关键模块均通过 Python 语法编译检查。
- 真实数据库在迁移前备份到 `data/backups/pre-project-workspace-20260806-2110.db`；迁移后 `customer_id` 可空、`project_kind` 已建立，外键违规为 0。
- 最终 8991 仅保留一个真实服务，闲鱼监听状态为 connected；全新标签页从分类切换、整卡进入详情、刷新直达、返回列表到控制台检查全部通过，最终标签停留在交付地址。

final result: passed

---

# 2026-08-23 项目管理简洁工作区 Figma 落地 Design QA

## 目标与视觉真值

- 已确认 Figma 文件：`循营 · 项目管理简洁工作区设计`，页面 `项目管理 · 新方案`，设计板 `循营 · 项目管理新方案 · 全页面设计板`。
- Figma 文件地址：`https://www.figma.com/design/sModtp5AtO4MI1wF2A7XEL`；本地完整设计板源：`/tmp/xunying-project-management-board.svg`。
- 本轮明确移除项目驾驶舱、三维叠卡、前置选中、拖动/滚轮切换和重复 Inspector；项目详情默认进入 `overview`，不再默认进入沉浸任务流。
- 项目—客户—商品关系、真实经营数据、verified 语义、revision/request-id、影响预览和事务确认保持不变。

## 同视口视觉证据

- 修改前桌面 `1440×900`：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/before-desktop-1440x900.png`。
- 修改前移动 `390×844`：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/before-mobile-390x844.png`。
- 最终列表桌面 `1440×900`：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/final-list-desktop-1440x900.png`。
- 最终列表移动 `390×844`：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/final-list-mobile-390x844.png`。
- 详情桌面：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/after-detail-desktop-1440x900.png`；详情移动：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/after-detail-mobile-390x844.png`。
- 编辑桌面：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/after-edit-desktop-1440x900.png`；编辑移动：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/after-edit-mobile-390x844.png`。
- 客户关系影响预览桌面：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/after-relation-preview-desktop-1440x900.png`；商品关系移动底部抽屉：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/final-relation-mobile-390x844.png`。
- Figma 与实现并排比较：`/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/comparison-desktop-list.png` 和 `/Users/chentao/Documents/New project 3/artifacts/project-management-redesign-20260823/comparison-mobile-list.png`。

## 视觉与交互结论

1. 桌面列表改为 Figma 确认的“标题与分类 → 四项紧凑指标 → 搜索/状态/排序 → 项目摘要表”结构；三条真实接单项目直接显示客户、来源商品、状态、真实 verified、交付风险、合同与待收，不再要求先选中项目。
2. `390×844` 使用单列项目摘要卡，保留客户、商品、verified、日期、金额以及“详情/编辑”两个明确入口；顶部全局搜索在项目管理窄屏页隐藏，避免与页面标题重叠。
3. 详情页默认标签为“总览”，可见标签为总览、任务、甘特图、Codex 同步、需求报价、日志、附件、交付核验；沉浸任务流不再出现在主标签中，旧 hash 仍保留只读兼容。
4. 独立编辑页只保存项目自身字段；客户和来源商品各自进入单独关系变更抽屉。商品候选只取 `owned + monitoring_enabled` 的当前本人上架采集商品。
5. 客户关系实测预览从“乐淘5888”到“Za1nny”，影响范围为项目 1、付款记录 2、追加订单 1、异常记录 0；只产生预览，没有点击最终确认。商品关系移动抽屉打开时确认按钮保持禁用，未选择目标、未写入。
6. 关系抽屉支持外部点击、Escape、Tab 焦点闭环和关闭后的焦点返回；桌面为右侧抽屉，移动为底部抽屉。移动抽屉实测 `bottom=844`、文档无横向溢出。
7. 列表、详情和编辑页在桌面与 `390×844` 均为 `scrollWidth <= clientWidth`。列表进入详情得到 `/overview`，进入编辑得到 `/edit`；刷新恢复编辑页，非法项目 ID 自动回到项目列表。
8. 真实三个项目的 verified 均显示 `0%`；实现只读取 `verification.progress.verified_delivery.percent`，读取失败也回落为 `0`，没有再使用 `project.progress`、implemented 或 test_passed 冒充 verified。

## 比较与修复记录

- Pass 1 `[P1 · Structure]`：旧页仍是项目驾驶舱、三维叠卡和右侧 Inspector。修复为直接表格/移动卡片，删除页面内选择、拖动、滚轮、透视和叠卡逻辑。
- Pass 2 `[P1 · Semantics]`：旧详情用 `project.progress` 作为 verification 读取失败时的回退，可能把 legacy 进度展示为 verified。修复为严格回退 `0%`，并把 Codex 同步与交付核验拆成独立标签。
- Pass 3 `[P2 · Responsive]`：首轮移动截图中全局搜索框覆盖项目页标题和编辑标题。修复为仅在项目列表、详情和编辑的窄屏上下文隐藏该全局搜索框；最终 `390×844` 标题、操作和内容无重叠。
- Pass 4：最终 Figma 设计板与列表、详情、编辑和关系抽屉截图并排检查，未发现剩余 P0/P1/P2 视觉差异。全局可拖动小策入口按既有产品要求保留，不属于本轮项目管理重构。

## 工程与单实例证据

- 前端交互测试 `100 passed`；TypeScript 通过；Vite 生产构建通过；Sites Worker `4 passed`；`git diff --check` 通过。构建只保留既有大 chunk 提示。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 完成受控重启，`/api/health` 返回 `{"status":"ok"}`；正式资源为 `index-BJRG6DLg.js` 和 `index-BYEYf6E0.css`，没有启动第二端口或第二服务。
- Ego Lite 网络与运行时检查没有应用 API 失败或 JavaScript exception；仅有既有 `/favicon.ico` 404，按本轮精确修改边界记录但不顺带修复。
- 验收过程没有点击关系最终确认、保存项目修改、创建项目或写入虚假业务数据；未执行 Git 提交、推送、PR、合并或公开部署。

final result: passed

# 第六阶段：证据化样本形成闭环

## 验收目标与真实状态

- 稳定页面：`http://127.0.0.1:8877/?build=20260818-phase6-final6#项目管理/p-1786013284727/codex`，继续使用唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 和唯一端口 `127.0.0.1:8877`。
- 真实生产库仍为 3 个项目、8 个任务、0 个验收点、0 个结果冻结、0 个预测运行、0 个预测评估、0 个校准样本；本阶段没有为了演示写入虚假验收点、冻结或校准记录。
- 三个真实项目的校准候选全部明确排除：两个项目为 `missing_scope`，一个终止合作项目为 `terminal`；`legacy_progress=100%` 的历史项目仍为 verified `0%`，不能形成样本。
- 校准算法版本为 `verified-outcome-calibration-v2-frozen`，样本门槛保持 `0–2 insufficient / 3–4 exploratory / 5+ actionable`，零样本时 MAE、超时比例、区间覆盖和校准倍数均为真实空值。

## 视觉证据

- 已确认桌面设计预览：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-preview-20260818/design-preview-desktop-1470x900.png`。
- 已确认移动设计预览：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-preview-20260818/design-preview-mobile-390x844.png`。
- 最终桌面全页首屏：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-desktop-1470x900.png`。
- 最终桌面样本工作台：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-desktop-sample-workbench-1470x900.png`。
- 最终桌面人工验收抽屉：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-desktop-manual-drawer-1470x900.png`。
- 最终移动全页首屏：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-mobile-390x844.png`。
- 最终移动样本工作台：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-mobile-sample-workbench-390x844.png`。
- 最终移动人工验收抽屉：`/Users/chentao/Documents/New project 3/artifacts/sample-formation-phase6-final-20260818/final-mobile-manual-drawer-390x844.png`。

## 范围、冻结与校准不变量

1. 没有 confirmed Codex 计划的历史项目可选择真实 `BusinessTask`，手工填写稳定 `point_key`、标题和验证类型；UI 明确说明不会从任务标题、legacy 进度或聊天内容猜测标准，也没有 AI 自动生成入口。
2. 人工验收点标记为 `manual_historical`，计划验收点标记为 `codex_plan`；已有 confirmed 计划的项目拒绝通过历史人工接口绕过计划版本。
3. 人工验收点创建和退役使用 revision、request-id 与同一事务；退役保留原记录、状态历史和证据，已使用 key 不复用。
4. 准备度依次检查有效任务与验收范围、verified 证据、预计/实际工时、人工完整性确认和终止状态；任何 active waiver 都会排除决策级样本。
5. 冻结保存完整 outcome、证据摘要、输入哈希、源账本 revision、人工确认、冻结时间、版本和 supersedes 关系；相同事实幂等返回原版本，底层事实变化后旧版本标记 stale，重核验只追加新版本。
6. 第五阶段校准只消费最新、未过期、资格完整的冻结结果；未冻结、stale、legacy 100%、implemented 和 test_passed 均不能进入新样本，历史校准运行与旧样本保持不可变。
7. `GET /verification` 和 `GET /outcome-freezes` 实测不产生写入；正式冻结请求必须同时包含 `confirmed_scope_complete=true`、`confirmed_time_complete=true` 与人工说明。

## 响应式、交互与可访问性

- 桌面 `1470×900` 与移动 `390×844` 均为 `scrollWidth = clientWidth`，没有整体横向溢出；移动两个主要操作实测均为 `44px` 高。
- “核验并冻结结果”在当前真实阻塞状态下禁用；“人工建立验收清单”只打开本地抽屉，没有提交表单或写入业务数据。
- 人工范围抽屉的任务、key、标题、类型和原因均为真实表单；空表单时保存按钮禁用。桌面抽屉实测为右侧 `540×900`，移动抽屉实测为视口底部 `390×706.5`。
- Ego Lite 验收发现项目路由过渡保留的 `transform` 会让嵌套 `position: fixed` 抽屉相对整页定位；三类核验抽屉已通过 React Portal 挂到 `document.body`。修复后抽屉父级为 `BODY`，移动位置 `top=137.5 / bottom=844`，桌面位置 `left=930 / right=1470`。
- Escape 可关闭抽屉，焦点真实返回“人工建立验收清单”按钮；抽屉打开时 body 滚动锁定，操作目标至少 `44×44px`，并保留 reduced-motion 规则。
- Hash 刷新后仍恢复 `#项目管理/p-1786013284727/codex`；项目 verification 与 calibration API 均返回 `200`，Ego Lite 事件队列没有 exception、error 或 failed 网络事件。

## 迁移、数据库与运行证据

- Alembic 唯一 head 为 `20260818_0031`，明确依赖 `20260818_0030`；自动化覆盖完整历史链与 `0030→0031`。
- Alembic 与 startup migration 均接受完整结构、拒绝只有部分表/列的半迁移结构；startup migration 重复执行幂等。
- 迁移前人工 WAL-safe 备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-phase6-manual-20260818-170017.db`，SHA-256 `9fe0055172c4e763bb1636898e235c720d36f0007c24b4ca38b86fdfcc2ce91b`，权限 `0600`。
- startup migration 自动备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-project-outcome-freeze-20260818-170219.db`，SHA-256 `aa8429835fb64ce7ba282c83a26ff60ed98744013b6117f2c84cc115ed98ce6d`，权限 `0600`，备份与迁移后主库 `integrity_check=ok`，`foreign_key_check` 无结果。
- 迁移后 `codex_acceptance_points.source`、`project_outcome_freezes` 和 `project_outcome_freeze_mutation_requests` 均存在；真实业务计数保持不变。
- 唯一 LaunchAgent 完成两次受控恢复（首次迁移、第二次载入抽屉定位修复）；`/api/health` 返回 `ok`，只有一个进程监听 `127.0.0.1:8877`。

## 工程回归与边界

- 后端全量：381 collected，`380 passed, 1 skipped`；跳过项为既有条件跳过，warning 为共享环境的 Starlette/httpx、SQLite datetime、Alembic 配置弃用和一个 pytest 收集提示。
- 第六阶段定向测试覆盖人工范围、任务归属、稳定 key、request-id、revision、confirmed plan 冲突、退役历史、冻结资格、waiver、零工时、终止合作、不可变快照、stale、追加重冻结、校准排除、GET 无写入和半迁移拒绝。
- 前端全量交互 `84 passed`；TypeScript 通过；Vite 生产构建通过；Sites Worker `4 passed`；`git diff --check` 通过。构建只保留既有大 chunk 提示。
- 未执行 Git 提交、推送、PR、合并、公开部署、客户发送、Codex 自动启动或任何真实外部业务动作；没有 reset、checkout、clean 或 `git add .`。

final result: passed

---

# 2026-08-17 商品经营「主动时段实验与预算放量」Design QA

## 验收目标与真实状态

- 路由：`http://127.0.0.1:8877/?build=20260817-traffic-growth-v2#商品经营/exposure`。
- 已为真实候选商品“前端页面美化与功能修改”建立本地增长实验；当前阶段为 T0 干净时段探索，先执行 6 个探索批次，探索完成后再生成 2 个确认批次，总目标 8 批。
- 三个北京时间测试窗为 `12:00–13:59`、`16:00–17:59`、`20:00–21:59`；首个建议测试为 8月19日20时00分。
- 当前周预算上限 ¥24、硬上限 ¥48；按每批约 ¥5.9 估算 8 批总成本 ¥47.2。建立实验只写入本地建议与计划关联，没有购买曝光、开始批次、产生支出或修改闲鱼商品。
- 历史已实现利润 ¥350 仅用于候选商品选择，不被归因为曝光收益；当前实验关联投入、归因咨询、已回款项目与贡献利润均为 0。

## 视觉真值与实现证据

- 桌面确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-145435ca-7a1a-40f7-b802-91ae87718e75.png`，`1487 × 1058`。
- 商业归因抽屉确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-fda7b0a0-f3c4-4ad7-8805-905812e3fda7.png`，`1487 × 1058`。
- 移动确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-8fd0204c-14e9-44d2-a7ad-80d71ab42148.png`，`853 × 1844`。其中“差异 ≥10%”属于生成图误差，正式实现采用已确认的咨询与浏览双门槛。
- 桌面最终实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260817-traffic-growth/desktop-1440x900.png`，CSS 视口与截图均为 `1440 × 900`。
- 商业归因抽屉最终实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260817-traffic-growth/desktop-attribution-drawer-1440x900.png`，`1440 × 900`。
- 移动端工作台最终实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260817-traffic-growth/mobile-growth-390x844.png`，CSS 视口 `390 × 844`、`devicePixelRatio = 2`，截图像素 `780 × 1688`。

## 视觉与信息层级

- 桌面保持确认图的主次结构：左侧增长实验工作台、三时段矩阵与胜出规则，右侧 T0/S1/S2/S3 预算阶梯，底部商业证据条；旧“未来计划”和旧“曝光分析”在活跃实验期间隐藏，避免重复内容，多商品批次追踪继续保留。
- 沿用当前浅色白紫 SaaS、1px 紫灰线、单层玻璃、高亮紫色主操作和 Phosphor 图标，没有引入黑色工作台、厚玻璃、样例经营数据或额外运行时依赖。
- 移动端把三时段矩阵改为三个 44px 时段按钮和单个选中时段详情，预算阶梯改为四列紧凑卡；当前选中时段、详情与桌面数据同步。
- 真实 390px 验收最初发现 CSS Grid 子项保留固有最小宽度，使文档从可用 375px 撑到 407px。修复为商品页顶层 Grid 子项 `min-width: 0` 后，`document.scrollWidth = document.clientWidth = 375`，增长工作台宽 357px，不再产生整体横向滚动。

## 交互与可访问性

1. 桌面和移动端均可切换 12、16、20 三个时段；选中态和单时段详情同步更新，未执行批次不会显示虚构指标。
2. “按计划新建干净批次”只打开人工批次草稿，预选 5 件商品并显示整批约 ¥5.9；弹层明确说明先准备 T0、用户人工购买后才记录实际时间和唯一支出。关闭弹层不写入批次。
3. 键盘聚焦主操作后按 Enter 可打开弹层，Escape 关闭后焦点返回“按计划新建干净批次”。
4. “审查商业归因”在桌面打开右侧抽屉，在窄屏打开底部抽屉；均支持焦点陷阱、Escape、关闭按钮和焦点返回。当前无候选证据时显示真实空状态，不生成案例。
5. 桌面抽屉最终边界为 `520 × 900`，完整落在页面可用宽度内；移动端抽屉使用 `min(82vh, 720px)`，不遮蔽关闭操作。
6. Ego Lite 控制台没有应用来源的 error；仅出现 Ego Lite 浏览器扩展自己的 Built-In AI 信息提示，不属于应用问题。

## 工程、数据与常驻服务

- 后端全量：`328 passed, 1 warning`；warning 为共享环境既有 Starlette/httpx 弃用提示。
- 前端交互：`71 passed`；目标曝光契约复验 `17 passed`；TypeScript 无错误；生产构建通过；Sites Worker `4 passed`；`git diff --check` 通过。
- 生产构建仅保留既有的 Vite 大包体积提示，没有新增构建错误。
- SQLite：`integrity_check = ok`，`foreign_key_check` 无违规；增长实验为 `active / exploration`，6 个探索格均为 `pending`，尚未绑定或开始真实批次。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，`127.0.0.1:8877` 只有一个监听进程，`/api/health` 返回 `ok`，重启后实验状态保持。
- 未执行 Git 提交、推送、合并、公开部署、自动购买曝光、自动修改商品或真实闲鱼写操作。

final result: passed

# 2026-08-17 闲鱼访问验证熔断与 Ego Lite 连接恢复 Design QA

## 验收目标与运行边界

- 修复前 `AdapterAccessVerificationError` 被通用断线分支处理，后端每隔约 2–60 秒再次请求闲鱼；修复后访问验证成为明确的人工闸门，单次失败即进入 `verification_required`。
- 本轮只修改监听状态机、连接恢复提示、Ego Lite 文案和本机代理使用开关；没有读取或输出 Cookie，没有采集商品、导入对话、发送消息或写入业务数据。
- macOS 系统代理已启用，本机服务通过受限 `.env` 显式跟随同一路径；配置文件权限保持 `0600`。

## 真实页面与交互验收

- Ego Lite 任务空间复用既有本机页面，稳定地址：`http://127.0.0.1:8877/?build=20260817-xianyu-verification-fuse#设置中心/渠道连接`，CSS 视口 `1264 × 797`。
- 渠道连接卡显示“闲鱼要求完成人工访问验证，自动重连已暂停”，恢复抽屉显示“等待人工验证”。
- 恢复步骤明确使用现有 Ego Lite，会话凭证输入为空；页面不存在旧 Edge 文案。
- 恢复抽屉说明失败时保持暂停、不覆盖原配置；本轮没有点击提交或重新读取配置。
- 页面无整体横向溢出，控制台 error/warning 为 `0`。

## 熔断与服务验收

- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启，PID `63293`；只有该进程监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`。
- 重启后服务只进行一次连接尝试，于 `15:37:50` 进入 `verification_required`；到 `15:39:09` 仍保持相同状态，跨过旧逻辑最长 60 秒窗口后没有第二次重试。
- SQLite `integrity_check = ok`，`foreign_key_check` 违规数为 `0`。

## 自动化证据

- 后端完整测试：`311 passed`；仅保留共享环境既有 Starlette/httpx 弃用提示。
- 前端交互测试：`69 passed`；新增访问验证提醒契约通过。
- TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 均通过。
- 生产构建保留既有大包体提示，没有新增构建错误。

final result: passed

---

# 2026-08-17 客户消息三栏工作台与历史会话原图归档 Design QA

## 范围与安全边界

- 本轮只调整客户消息会话工作台、闲鱼历史会话导入、客户入站原图归档状态和直接测试；商品经营、项目、账本、客户关系、真实发送、报价转化与 AI 触发逻辑保持不变。
- 历史搜索和预览保持只读；只有用户确认导入后才写入消息并逐张保存该会话的客户入站原图。出站图片不归档，单张原图失败不回滚会话导入，也不会停止剩余图片。
- 图片字节仍进入私有原图目录并执行 SHA-256 校验；Cookie、签名地址、卖家标识和平台原始响应不进入 SQLite、截图、日志或 Git。
- 未执行 Git 提交、推送、合并、公开部署、发送消息、标记已读或模型调用。

## 视觉真值与实现证据

- 源视觉真值：`/Users/chentao/.codex/attachments/ff80616a-909e-488d-aaaf-fe10666aa286/image-1.png`，像素 `2516 × 1630`。源图用于确认会话列表、消息区、需求分析三栏同时可见且各自滚动的结构，不复制其中的浏览器裁切或示例数据。
- Ego Lite 桌面实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-messages-history-images-final/final-v2-1264x797.png`，CSS 视口与截图均为 `1264 × 797`，`deviceScaleFactor = 1`。
- Ego Lite 紧凑桌面实现：`final-v2-1024x768.png`，`1024 × 768`；平板：`final-v2-768x1024.png`，`768 × 1024`；移动端：`final-v2-390x844.png`，`390 × 844`。文件均位于上述证据目录，截图像素与 CSS 视口一一对应，不存在密度缩放。
- 历史导入弹层聚焦证据：`final-v2-history-dialog-1264x797.png`，`1264 × 797`。完整桌面图已能直接阅读三栏比例，弹层图单独覆盖焦点、只读边界、空态、规则和确认操作，因此无需额外裁剪局部图。
- 比较输入同时打开了源视觉真值、最终 1264 桌面、768 平板和 390 移动截图；最终判断基于同一轮可见图像，不以代码或路径代替视觉比较。

## 必查视觉表面

- 字体与层级：沿用循营系统中文字体栈、现有字号和字重；会话标题、客户名、消息正文、需求分析标题、辅助说明和操作按钮保持源图的主次关系。窄屏长客户名和消息摘要使用受控截断，没有重叠或不可读换行。
- 间距与布局：内容宽约 `981px` 时三栏实测为 `203.7 / 294.3 / 481.0px`，工作台 `clientWidth = scrollWidth = 979px`；右侧边界为 `1229.99px`，完整落在视口内。1024px 仍保持三栏，768/390 才顺序堆叠并给每段独立高度和滚动区域。
- 色彩与材质：保持既有白紫浅色 SaaS、1px 紫灰边界、浅紫选中态、克制阴影和绿色人工确认提示；没有新增黑色工作台、厚玻璃、双边框或不透明紫色大面板。
- 图像质量与资产：本轮工作台不需要新增位图；图标继续使用项目已有 Phosphor。历史导入归档保存真实原始字节，不用占位图、CSS 图形、转码图或生成图替代客户原图。
- 文案与内容：导入弹层明确写明“只读查询 · 不发送 · 不标记已读 · 确认前不写入”和“确认后自动保存客户入站原图”；商品详情超时会说明不影响核对与导入。完成提示分别给出消息数、原图成功数与失败数，不把失败描述成成功。

## 比较历史与修复

### Pass 1

- [P1] 旧 `@media (max-width: 1180px)` 按整个浏览器宽度切换两栏，1264 浏览器中的真实内容区只有约 `979px`，但三栏最小宽度合计 `1040px`；外层 `overflow: hidden` 因而裁掉右侧约 `61px`。
  - 修复：页面建立命名 CSS Container；内容宽 `760–1099px` 使用比例轨道，1264 和 1024 都完整显示三栏，消息头操作换到第二行。
- [P1] 旧窄屏规则取消工作台高度并让消息、需求内容无限展开，768/390 页面高度分别约 `10150 / 12024px`。
  - 修复：`<760px` 才堆叠，并为会话列表、消息区和需求分析设置 `270/520/620px`（390px 下列表 `240px`）的明确区域高度；各区域内部滚动。

### Pass 2

- 1264：三栏无裁切，`rootScrollWidth = rootClientWidth = 1249px`；页面高度 `960px`。
- 1024：三栏实测 `202.1 / 291.9 / 477.1px`，无整体横向溢出；页面高度 `960px`。
- 768：页面高度从约 `10150px` 降到 `1732px`，工作台高度 `1412px`；横向宽度 `753 = 753px`。
- 390：页面高度从约 `12024px` 降到 `1706px`，工作台高度 `1382px`；横向宽度 `390 = 390px`。
- 最终没有剩余可执行 P0、P1 或 P2。可选 P3：未来若移动端会话数量显著增加，可评估横向会话切换器；当前独立滚动列表可读且不需要增加另一套导航。

## 交互、可访问性与运行证据

- 历史导入弹层实测：打开后 `body` 锁定，焦点落到“关闭历史对话导入”；Escape 后弹层关闭、锁定解除、焦点返回“导入历史”按钮。弹层宽 `1040px`，没有横向溢出。
- 页面重新加载、四个响应式尺寸、弹层开关期间，应用 `Runtime.exceptionThrown` 与 error/warning Log 事件合计为 `0`。
- 后端全量 `310 passed`；前端交互 `68 passed`；TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过。构建只保留项目既有的大 chunk 建议。
- SQLite `integrity_check = ok`、`foreign_key_check = 0`。唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，PID `54539` 独占 `127.0.0.1:8877`，`/api/health` 返回 `ok`。
- 重启后的闲鱼监听被平台 `AdapterAccessVerificationError` 拦截；使用当前 Ego Lite 登录 Cookie 的候选恢复请求仍返回 409，因此没有继续触发历史读取。该外部验证状态不影响本地 UI、数据库和 Mock Adapter 闭环，但真实平台导入需要用户在闲鱼完成访问验证后再试。

final result: passed

---

# 2026-08-17 客户消息「图片库」原图归档 Design QA

## 视觉真值、实现证据与归一化

- 已确认桌面图片墙：`/Users/chentao/Documents/New project 3/artifacts/customer-image-library-preview-20260817/desktop-library.png`，`1586 × 992`。
- 已确认桌面灯箱：`/Users/chentao/Documents/New project 3/artifacts/customer-image-library-preview-20260817/desktop-lightbox.png`，`1586 × 992`。
- 已确认移动端图片墙：`/Users/chentao/Documents/New project 3/artifacts/customer-image-library-preview-20260817/mobile-library.png`，`853 × 1844`。
- Ego Lite 桌面图片墙实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-image-library/desktop-gallery-1440x900.png`，CSS 视口与像素均为 `1440 × 900`，`deviceScaleFactor = 1`。
- Ego Lite 桌面灯箱实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-image-library/desktop-lightbox-1440x900.png`，`1440 × 900`。
- Ego Lite 移动图片墙实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-image-library/mobile-gallery-final-390x844.png`，CSS 视口与像素均为 `390 × 844`，`deviceScaleFactor = 1`。
- 真实空态：`/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-image-library/desktop-real-empty-final-1440x900.png` 与 `mobile-real-empty-final-390x844.png`；真实数据库没有归档原图，所以最终页面准确显示 25 条历史图片待人工补录，而没有生成样例卡。
- 全视图并排比较：`desktop-comparison.png` 与 `mobile-comparison.png`；灯箱聚焦比较：`lightbox-comparison.png`，均位于 `/Users/chentao/Documents/New project 3/artifacts/design-qa/customer-image-library/`。桌面源图等比归一到 `1440 × 900`，移动源图等比归一到 `390 × 844` 后与同尺寸实现并列，没有拉伸实现截图。
- 图片墙和灯箱的浏览器验收使用只存在于当前 Ego Lite 页面的临时只读视觉夹具，图片来自项目现有 `public/reference` 静态资源；夹具没有写入 SQLite、图片目录或业务记录。验收后已关闭夹具标签，当前唯一标签恢复到真实空态。

## 必查视觉表面

- 字体与层级：沿用系统中文字体栈和现有循营字号体系；页面标题、一级切换、状态条、工具栏、卡片时间、渠道徽标、弹层标题与元数据形成稳定层次。390px 下没有标题断裂、标签挤压或不可读的小字号。
- 间距与布局：桌面为 5 列紧凑图片墙，移动端为真实 2 列；状态条、筛选区和图片内容按确认预览顺序排列。日期筛选已收敛为一个“全部日期”控件，点击后再展示开始/结束日期，避免桌面工具栏被两个日期输入挤压。
- 色彩与材质：保持浅色白紫 SaaS、单层紫灰边界、克制阴影、紫色主操作、绿色健康状态和黄色历史待补录状态；没有黑色工作区、厚玻璃、双边框或不透明紫色大卡面。
- 图片质量与资产：真实图片使用原始内容端点和 `object-fit: contain`，不裁切、不放大覆盖、不转码。HEIC/HEIF 等浏览器不能显示的原格式展示明确下载空态，不生成转码图或伪预览。所有 UI 图标来自 Phosphor；没有手绘 SVG、CSS 图标、表情或假图片。
- 文案与内容：页面明确写明“原图保存，不压缩、不识别、不进入 AI 分析”；真实历史状态准确显示“有 25 条历史图片尚未取得原图，可人工补录”。图片墙不展示聊天正文，历史补录也不暗示自动读取全部平台历史。

## 比较历史与修复

### 第一轮发现

- [P2] 390px 页头的“当前页面无需搜索”与一级切换在同一纵向区域重叠。修复：只在客户消息窄屏隐藏无用途的页头搜索框，同时保留导航、提醒与账户操作。复验图 `mobile-gallery-final-390x844.png` 和真实图 `mobile-real-empty-final-390x844.png` 已无重叠。
- [P2] 初版桌面工具栏同时展示开始、结束两个日期输入，比确认图拥挤；移动端还直接隐藏日期能力。修复：改为单一“全部日期”摘要控件，弹出完整日期范围选择；桌面和移动都保留功能，Escape 可关闭并返回焦点。
- [P2] 初版移动端“历史图片补录”仍在顶部工具栏，未体现确认图的底部主行动层级。修复：有真实图片时移动端将该入口放在图片墙之后，目标高度实测 `54px`；真实空态继续使用空态中央入口，不产生重复按钮。

### 第二轮结果

- 1440 × 900 桌面实现与确认图在导航、页头、一级切换、状态、筛选、5 列图片墙、轻量卡面和灯箱信息结构上保持一致。
- 390 × 844 实现为 2 列，`scrollWidth = innerWidth`，没有整体横向溢出；移动页头、筛选和卡片不再互相覆盖。
- 桌面灯箱在相同视口下保持主图 / 元数据双列、底部下载 / 回到会话 / 删除三个动作；实现标题改为真实产品文案“原图预览”，不沿用预览阶段的“修改前设计预览”。
- 没有剩余可执行的 P0、P1 或 P2。可选 P3：真实原图逐渐增加后，可再观察超长客户名称是否需要在筛选下拉中增加 Tooltip；当前空态和既有结构不需要提前增加复杂度。

## 交互、响应式与可访问性

- `#客户消息/images` 刷新后保持图片库；点击“返回对应会话”使用 `#客户消息/conversation/{id}`，不丢失浏览器历史。
- 日期筛选实测可打开；Escape 后 `open=false` 且焦点返回日期摘要。
- 历史补录弹层实测显示 25 条真实待补录记录；打开时焦点落到关闭按钮，Escape 关闭并返回触发按钮。移动端弹层没有自身布局溢出。
- 灯箱实测为 `role=dialog`，打开时焦点落到关闭按钮；下载、回到会话和确认后删除本地副本保留独立操作。删除一个关联不会删除其他消息仍引用的同一物理原图。
- 移动端图片墙实测两列，底部补录按钮 `54px`；主要按钮和弹层操作不小于 `44px`。`prefers-reduced-motion` 下关闭卡片位移动画。
- 应用控制台 error / warning 为 `[]`；Ego Lite 自身扩展产生的信息级日志不属于应用错误，已从应用控制台结论中排除。

## 原图、隐私与渠道边界

- 闲鱼只接受可信图片域名和受信 HTTPS 跳转；企业微信只在内存中使用临时 `media_id`，Token 过期时刷新一次后读取二进制原图。签名 URL、`media_id`、Cookie、卖家标识和平台原始响应不会进入 SQLite、API、日志或图片目录。
- 只归档入站图片；消息先入库，图片失败只留下脱敏失败码，不回滚聊天。相同消息重放只产生一个关联，相同字节跨消息复用一个物理文件。
- 原图以 `data/customer-images/<年>/<月>/<SHA-256>.<格式>` 保存；目录 `0700`、文件 `0600`。写入先落在 `data/private/customer-image-tmp`，写前写后校验 SHA-256，再原子替换；图片目录不保存 JSON、日志、元数据或临时文件。
- 历史恢复必须由用户点击并再次确认；恢复过程串行且相同请求 ID 幂等，只重放已经存在的图片占位，不把同一会话中其他历史图片静默导入。企业微信历史和无法远程恢复的图片可以逐条选择本地原文件补录。
- 图片不进入 GPT、Codex、DeepSeek、OCR、需求材料或经营分析；本轮没有调用真实平台历史恢复、发送客户消息、读取全部平台历史或创建测试业务数据。

## 工程、迁移与运行证据

- 后端全量：`305 passed, 1 warning`；warning 为共享环境既有 Starlette/httpx 弃用提示。目标渠道与原图测试为 `35 passed`。
- 前端交互：`67 passed`；TypeScript 无错误；生产构建通过；Sites Worker `4 passed`；`git diff --check` 通过。
- 迁移 `20260817_0024_customer_image_archives` 已应用到真实 SQLite。迁移前自动在线备份为 `/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-customer-images-20260817-105130.db`，权限 `0600`，SHA-256 为 `eec4b254d1c87b0f233824b7ff479cc0b5d4b1e6ae03001142c5270521b1ea8a`，备份 `integrity_check = ok` 且无外键异常。
- 迁移后真实库 `integrity_check = ok`、`foreign_key_check` 无结果；新表为 0 条，原 25 条入站图片占位与 15 条出站图片记录保持不变。没有自动平台读取或假数据回填。
- `data/customer-images` 与 `data/private/customer-image-tmp` 均为 `0700` 且为空；没有 `.part`、元数据或非图片文件。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，当前 PID `49017`；只有该进程监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`，Ego Lite 最终保留一个真实 `#客户消息/images` 标签。
- 未执行 Git 提交、推送、合并、公开部署、自动闲鱼读取或真实客户发送。

final result: passed

---

# 2026-08-16 Prediction Engine 方案 2「未来窗口编排台」Design QA

## 验收范围与安全边界

- 第一阶段 Prediction Engine 已接入首页、经营分析中心、项目管理、客户管理、收入记录和设置中心；预测只读取现有经营数据、运行透明本地规则并保存预测或评估，不自动修改客户、项目、财务、商品或推广状态。
- 本轮视觉真值为用户确认的方案 2“未来窗口编排台”；经营分析中心承载完整预测工作台，其余页面只显示与当前业务对象相关的轻量摘要。
- 项目终止结算问题 `project_cancelled / cooperation_terminated` 被排除在工作负载与延期风险输入之外，避免驾驶舱已经终止的项目继续驱动预测。
- 未执行 Git 提交、推送、PR、合并、公开部署、模型训练、真实闲鱼操作或业务记录改写。

## 视觉真值与最终证据

- 源视觉真值：`/Users/chentao/Documents/New project 3/artifacts/prediction-design-preview-20260816/selected-option-2-future-window.png`，像素 `1667 × 944`。
- 最终桌面实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/prediction-engine-option-2-1667x944-final-verified.png`，Egolite CSS 视口 `1667 × 944`，截图像素 `1667 × 944`，`devicePixelRatio = 1`。
- 完整同视口比较：`/Users/chentao/Documents/New project 3/artifacts/design-qa/prediction-engine-option-2-comparison.png`，像素 `3358 × 944`；左侧为确认预览，右侧为最终真实页面。
- 最终移动端：`/Users/chentao/Documents/New project 3/artifacts/design-qa/prediction-engine-option-2-390x844-final.png`，Egolite CSS 视口与截图均为 `390 × 844`，`devicePixelRatio = 1`。
- 无需额外制作聚焦裁剪：主预测工作台在 `1667 × 944` 完整比较图中已可直接阅读；移动端单独以精确 `390 × 844` 实页验证，避免裁剪掩盖响应式问题。

## 必查视觉表面

- 字体与层级：沿用循营现有系统字体栈、英文眉题、中文标题和轻量辅助说明；“事实 / 预测 / 建议”层级、风险分、数据充分度和主要行动清楚可辨。
- 间距与布局：完整预测台位于经营分析首屏主场，桌面为跑道与今日建议并列、现金流横带、项目与客户清单双列；真实工作台顶部约 `106px`、高度约 `695px`、宽约 `1346px`，没有被旧分析命令条挤出首屏。
- 色彩与令牌：继续使用浅色白紫 SaaS、单层细边、克制阴影和紫色主操作；事实、预测、建议以蓝、紫、橙的低饱和语义区分，没有新增黑色工作台、厚玻璃或高反差噪声。
- 图像与图标：没有新增或替换位图资产；预测内容使用项目已有 Phosphor 图标，顶部品牌和小策入口继续沿用现有透明资产。
- 文案与真实数据：最终页面显示真实规则结果——未来 14 天负载 `0%`、延期风险项目 `0` 个、客户 `Farewell` 优先级 `55 / 100`、未来 30 天已知净现金流 `¥0`；没有复制预览示例数值或为了填满清单伪造项目。

## 比较历史与修复

- Pass 1 `[P2]`：旧经营分析命令条位于预测台之前，使确认方案的核心工作台落到首屏下方。
  - 修复：将“未来窗口编排台”前置为经营分析中心的第一主场；原 GPT / DeepSeek 分析命令条和失败信息完整保留在下方。
- Pass 2 `[P2]`：主要行动按钮实测高度只有 `40px`。
  - 修复：按钮提升到 `44px`，桌面实测 `300 × 44px`，移动实测约 `318 × 44px`。
- Pass 3 `[P2]`：终止合作项目“去除豆包水印”仍由 Prediction 特征层作为待交付项目评分，和项目驾驶舱真实状态冲突。
  - 修复：特征层排除终止结算问题并增加回归测试；最终预测清单不再显示该项目。
- 最终同视口比较未发现剩余可执行 P0、P1 或 P2。正式页面比概念预览更紧凑，并保留循营真实壳层；这是已确认的产品适配，不是内容缺失。

## Egolite 交互、响应式与控制台

- 桌面 `1667 × 944`：页面 `scrollWidth = 1652 < 1667`，预测工作台宽约 `1346px`，无横向溢出；Farewell 建议可见，终止合作项目不在风险清单。
- 移动 `390 × 844`：页面 `scrollWidth = 390`，预测工作台宽约 `372px`，主内容按单列展开，无横向溢出；Farewell 建议和真实空项目风险状态保持可读。
- 在移动实页滚动到主要操作后，点击“前往客户”正确进入 `#客户管理`；客户页保留预测摘要和 Farewell 优先级，浏览器后退恢复 `#经营分析中心` 与“未来窗口编排台”。
- 桌面导航、移动导航和返回过程的 `Runtime.exceptionThrown`、error/warning console 以及 error/warning Log 事件均为 `[]`。
- 首页四项摘要、项目预测摘要、客户优先级详情、收入页现金流摘要和设置中心每日可用工时 `8` 已完成跨页检查；各页面没有整体横向溢出。
- `prefers-reduced-motion`、语义标题、按钮语义和响应式规则由交互契约测试覆盖；没有把截图无法证明的屏幕阅读器完整认证作为通过项。

## 预测口径、数据库与工程验证

- 真实 `/api/predictions` 返回 `record_status = live`、`is_stale = false`；工作负载采用 `deterministic_capacity_ratio_v1`，现金流采用 `known_cashflow_only_v1`，客户优先级采用 `followup_priority_rules_v1`。
- 当前真实数据充分度较低时，页面明确显示“充分度低 / 中”和历史不足，不把规则评分描述为概率，也不生成基线新增收入。
- Prediction 数据表 `prediction_runs`、`prediction_results`、`prediction_evaluations` 已存在。迁移前在线备份为 `/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-prediction-ui-20260816-191255.db`，权限 `0600`，SHA-256 `810d7f803c92a8d2dc3f218b4e33b0e41e176a43a7db891e4f000cf62a0e2d8a`。
- 后端全量 `293 passed, 1 warning`；warning 为共享环境既有 Starlette/httpx 弃用提示。前端交互 `63 passed`，其中 Prediction UI `5 passed`；TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过。
- SQLite `integrity_check = ok`，`foreign_key_check` 无结果。唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 完成受控重启恢复，状态为 running，PID `82375` 独占 `127.0.0.1:8877`，`/api/health` 返回 `{"status":"ok"}`。

final result: passed

---

# 2026-08-15 项目来源商品归属与实时利润 Design QA

## 验收范围与安全边界

- 接单项目可在项目驾驶舱关联、改绑或解除一件本人商品；一件本人商品可以汇总多个项目。
- 商品实际利润统一从账本实时派生：`净确认到账 − 项目支出 − 退款`。合同额和待回款不计入已实现利润，历史商品日快照不追溯改写。
- 只允许关联 `ownership_status = owned` 的本人商品；现有项目不按名称自动猜测商品归属。
- 本轮浏览器只执行选择与影响预览，没有点击最终确认。真实数据库验收结束时 `bound_projects = 0`，没有产生项目商品绑定、改绑或解除绑定写入。
- 未执行 Git 提交、推送、合并、公开部署、商品修改或任何真实闲鱼操作。

## 视觉真值与最终证据

- 项目绑定抽屉确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-093c2f92-626d-49e7-935b-6f87557ac001.png`。
- 商品实时利润确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-a220b837-e97c-40cb-97ad-47e5cb5fbbca.png`。
- 项目驾驶舱桌面默认态：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/project-cockpit-1440x900-final.jpg`。
- 项目绑定及真实影响预览：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/project-binding-preview-1440x900-final.jpg`。
- 移动端抽屉：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/project-binding-mobile-final.jpg`；抽屉列表顶部复验：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/project-binding-mobile-top.jpg`。
- 商品经营雷达桌面态：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/product-profit-1440x900-final.jpg`。
- 商品实际利润构成聚焦态：`/Users/chentao/Documents/New project 3/artifacts/project-product-attribution-final/product-profit-detail-focused.jpg`。
- 内置浏览器响应式覆盖使用 `devicePixelRatio = 0.5`，原始截图会形成 `2 × 2` 重复瓦片。最终证据只截取同一状态左上有效画面并按密度归一化，没有拼接、重绘或替换真实页面数据；桌面内容有效宽度因滚动条为 `1425px`，移动端有效证据为 `375 × 844px`。

## 视觉与信息层级结论

- 绑定抽屉保持确认预览的右侧单层薄玻璃结构：标题、本人商品说明、搜索、商品列表、影响预览、取消和确认操作顺序一致；正式实现继续使用循营现有浅色白紫令牌、1px 紫灰边界和克制遮罩。
- 真实影响预览明确区分当前归属与目标商品，并展示净确认到账、项目支出、退款和归入商品实际利润。选择“前端页面美化与功能修改”时，只读预览得到 `¥280 − ¥0 − ¥0 = ¥280`。
- 项目 Inspector 增加“项目利润”和“来源商品”，未关联时明确显示“未关联商品”；绑定能力由独立操作进入，没有把商品选择塞入卡面或改变现有项目选择/进入交互。
- 商品经营雷达的利润列显示“实际利润、关联项目数、实时账本”三层信息。商品详情把利润公式和关联项目放在同一信息区，并明确历史快照不追溯改写。
- 确认图中的金额和项目均为设计示例；最终页面使用真实账本，所以当前商品显示 `¥0` 和 `0 个关联项目`。这属于正确的数据差异，不以示例数值污染数据库。
- 桌面抽屉宽度、列表密度、影响预览分组、紫色选择态与移动端降级均与确认方向一致；没有发现需要继续修复的 P0、P1 或 P2 视觉问题。

## 交互、数据与可访问性

- 新建接单项目可选来源商品；现有项目从 Inspector 打开“关联来源商品 / 修改来源商品”。列表只展示本人商品并支持名称或 ID 搜索。
- 选择商品后只生成影响预览；绑定、改绑、解除绑定都在最终确认后才提交，并受 revision、preview token、request ID 和载荷哈希保护。
- 抽屉支持遮罩关闭、`Escape` 关闭和焦点返回；移动端使用窄屏抽屉规则，商品列表独立滚动，底部操作保持可见。
- 提交成功后直接采用服务端返回的最新账本快照，避免再次保存造成重复 revision；商品页同时监听 `product_*` 与 `ledger_updated`，到账或归属变化后静默刷新。
- 后端回归覆盖未绑定不计入、多项目聚合同一商品、到账只增加一次、项目支出冲减、改绑利润迁移、幂等与冲突、个人项目和非本人商品拒绝，以及历史快照不变。
- 浏览器验收中 `Escape` 可关闭抽屉，真实页面控制台 error/warning 为 `[]`；没有点击最终确认，数据库绑定数始终为 0。

## 工程、迁移与常驻服务

- 新迁移：`migrations/versions/20260815_0022_project_product_attribution.py`；`business_projects.item_id` 外键和索引已存在。
- 迁移前 SQLite 在线备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-project-product-attribution-20260815-123939.db`，权限 `0600`，SHA-256 `8eb767a63f1d3bc2f3f6dbf7cd61a755607c1d4e1cf01c8fbd7827c950c3f138`。
- 后端全量测试 `278 passed`；前端交互 `57 passed`；TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过。
- 最终 SQLite `integrity_check = ok`、`foreign_key_check = 0`、`bound_projects = 0`。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启；PID `9385` 独占监听 `127.0.0.1:8877`，`/api/health` 返回 `{"status":"ok"}`。

final result: passed

# 2026-08-15 商品修改实验确认预览恢复 Design QA

## 范围与纠错结论

- 本次只更正“商品经营 → 上新与修改 → 商品修改实验”。商品经营指标、上新雷达、市场参考、曝光分析、客户与项目页面均保持现有实现。
- 2026-08-14 的商品实验表验收存在误判：当时的 JSX 让“查看证据”和“建立实验”互斥，响应式 CSS 又在 `1032px` 把固定列表格拆成高卡片；这不是缓存或旧构建造成的回滚。
- 本次恢复确认预览中的四列紧凑表格、圆形流程节点和右侧上下双层操作，同时保留真实商品、实验资格限制和 `launch/product/{itemId}` 精确路由。

## 视觉真值与浏览器证据

- 视觉真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-251d9f0c-9ecb-486f-b1ba-fd828ec9dc98.png`，`1032 × 1523px`。
- 最终同视口页面：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260815-product-modification-restored/implementation-1032x1524.jpg`，CSS 视口 `1032 × 1524`，`devicePixelRatio = 0.5`，归一截图 `1032 × 1524px`。
- 最终组件状态：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260815-product-modification-restored/implementation-focus-final.jpg`，相同 CSS 视口，滚动到商品修改实验区域。
- 全页上下文并排：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260815-product-modification-restored/compare-full.jpg`。确认预览包含其生成时的桌面侧栏与五指标单行外壳；当前真实页面在 `1032px` 使用后续保留的响应式壳层，因此全页图只用于说明上下文，不把非本次范围的壳层差异伪装为一致。
- 组件完整并排：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260815-product-modification-restored/compare-modification-focus.jpg`。左侧为确认预览中的完整实验组件，右侧为最终真实组件；这是本次布局、密度、流程和操作层级的主要对照证据。
- 响应式证据：`implementation-1440x900.jpg`、`implementation-480x844-table.jpg`，均位于上述证据目录。

## 比较历史

- Pass 1：确认上次真实页面使用高行、多行结构，且 JSX 通过互斥分支只显示一个操作按钮；判定为 P1 视觉与操作回归。
- 修复 1：操作区改为同时渲染白色“查看证据”和紫色“建立实验 / 查看实验”；实验资格只禁用紫色主操作，不再隐藏证据入口。
- 修复 2：桌面恢复固定四列；删除 `≤1180px` 的高卡片拆行和旧 `min-width: 1040px` 冲突，只在 `≤980px` 降级为响应式卡片。
- Pass 2：真实 `1032 × 1524` 页面已恢复双层操作，但 6 行高度在 `104–118px` 间波动，组件比确认预览高约 100px；判定为 P2 密度漂移。
- 修复 3：统一桌面行高为约 `92px`，建议正文和市场依据改为克制截断，流程节点和双按钮略微收紧。
- Pass 3：6 行实测均约 `92px`，实验表总高 `592px`；确认预览与最终组件并排后没有剩余可执行 P0、P1 或 P2。

## 必查视觉表面

- 字体与层级：继续使用循营既有系统字体栈、英文眉题、中文标题、9–10.5px 表格信息层级；商品名、置信度、建议标题和辅助数据保持清晰主次，长文案使用单行或受控截断。
- 间距与布局：桌面四列为商品、建议、流程、`104px` 操作区；真实 `1032px` 下列宽为 `224.281 / 318.734 / 254.984 / 104px`，6 行统一约 `92px`，表格 `clientWidth = scrollWidth = 964px`。
- 色彩与令牌：白色证据按钮、紫色主操作、浅紫标签与金色建议标题复用现有浅色 SaaS 令牌；被规则阻止的主操作以低透明度禁用，证据按钮仍可用。
- 图像与资产：该组件不依赖新增位图；流程和操作继续使用项目已有 Phosphor 图标，没有自制 SVG、占位图或装饰性假数据。
- 文案与内容：恢复“查看证据 + 建立实验”的明确双动作；真实有实验时主操作仍显示“评估结果 / 查看实验”，没有为匹配确认图改写商品、咨询、浏览或实验状态。

## 交互、响应式与可访问性

- 点击首行“查看证据”后 URL 为 `#商品经营/launch/product/1063558552024`，“上新与修改”继续为选中页签，恰好 1 行证据展开；再次点击后回到 `#商品经营/launch` 并收起。
- 当前 17 条建议均同时渲染证据按钮和主操作；10 条不满足实验条件的主操作保持 disabled，证据按钮不受影响。验收未点击主操作，没有创建实验或写入业务数据。
- `1440 × 900` 和 `1024 × 768` 使用固定四列；`768 × 1024` 在 `≤980px` 使用可读卡片分区；`480 × 844` 使用单列卡片和两个并排 `44px` 操作按钮。
- 四个验收尺寸的 `document.scrollWidth` 均等于 `clientWidth`，实验表 `scrollWidth` 均不大于自身 `clientWidth`；没有页面横向滚动。
- 浏览器控制台日志为 `[]`；焦点样式、按钮语义、`aria-expanded` 和减少动态效果规则保持。

## 工程与常驻服务

- TypeScript 通过；前端交互 `54 passed`；生产构建通过；Sites Worker `4 passed`；`git diff --check` 通过。构建仅保留既有大 chunk 建议。
- 本轮没有改后端或 SQLite，因此没有迁移，也没有执行真实闲鱼、模型或客户写操作。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启；`/api/health` 返回 `ok`，`127.0.0.1:8877` 只有一个监听进程。
- 没有执行 Git 提交、推送、合并、公开部署或启动第二个服务。

final result: passed

---

# 2026-08-15 项目驾驶舱 Activepieces 式玻璃卡组 Design QA

## 验收目标与保持不变项

- 源视觉真值：`/var/folders/sy/k3k07pxn1g94vr4gr9hsxlq80000gn/T/codex-clipboard-80687472-8dcf-4cd6-8b9f-768e492b384f.png`，原始像素 `2392 × 1360`。
- 只复用参考中的纵向叠卡、后排逐层退开、轻微旋转、悬停提亮和点击后循环前置；保持循营现有浅色产品外壳、真实项目数据、白紫薄玻璃材质和 Phosphor 图标，不复制参考的深紫背景、示例业务数据或不透明白色大面板。
- 点击真实项目卡面只选择并前置；进入详情继续由前景卡或 Inspector 中的明确“进入项目”按钮触发。
- 搜索、分类、状态筛选、排序、创建项目、到账确认、异常记录、Hash 路由、拖动、滚轮、键盘和移动端平面降级均保持。

## 浏览器实现证据与归一化

- 修改前页面：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/01-before-current-viewport.png`；当时内置浏览器真实视口为 `638 × 1494`，触发了既有窄屏卡片规则。
- 桌面默认态：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/03-final-default-css-1440x900-normalized.png`。
- 桌面点击后前置态：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/04-final-after-select-css-1440x900.png`，CSS 视口 `1440 × 900`，截图像素 `1440 × 900`，选中项目为“科研学术数据库的ui修改”。
- 桌面悬停态：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/05-final-hover-default.png`；后排卡实际计算样式为 `brightness(1.035) saturate(1.05)`，同时向上约 `6px`、向前约 `14px`。
- `1024 × 768`：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/06-final-1024x768.png`。
- `768 × 1024`：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/07-final-768x1024.png`。
- 内置浏览器最窄实际 CSS 视口 `480 × 844`：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/08-final-480x844.png`；卡组聚焦态：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/09-final-480x844-focused.png`。
- 内置浏览器显式响应式覆盖使用 `devicePixelRatio = 0.5`，原始截图会形成 `2 × 2` 平铺；归一图只裁取同状态原始画面的左上有效象限，没有缩放、拼接或重绘页面内容。最窄视口被运行时钳制为 `480px`，没有冒充精确 `390px`。

## 同屏与聚焦比较

- 完整同屏比较：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/10-design-qa-full-comparison.png`；左侧为参考，右侧为真实项目驾驶舱。
- 卡组聚焦比较：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-video-reference/11-design-qa-focused-comparison.png`；两侧同时呈现后排薄玻璃托盘、前景展开卡与空间层级。
- 参考是营销页的深色舞台，正式实现是业务系统的浅色工作区，因此背景和业务内容是有意差异；纵向层叠、后排标题可读、逐层旋转与缩小、前景卡完整展开和点击重排关系保持一致。

## 必查视觉表面

- 字体与层级：继续使用循营既有字体栈、英文眉题、中文项目名、辅助信息和状态标签层级；后排托盘仍能读到项目名，前景卡保留进度、任务、交付、已收/未收和明确操作。
- 间距与布局：桌面使用纵向叠卡；选中卡位于前景，后排按约 `22px` 横移、`34px` 上移、`28px` 后退和 `1.2deg` 旋转逐层排列，切换时长 `520ms`，缓动为 `cubic-bezier(.34,1.56,.64,1)`。
- 色彩与视觉令牌：卡片只使用一层 `1px` 紫灰细边、白紫半透明渐变、`16px` 背景模糊、左上高光与克制紫蓝环境光；没有厚侧壁、双边框、黑色舞台、强反射或不透明选中卡。
- 图像与资产：驾驶舱没有需要新增的位图内容；品牌资产继续来自项目现有透明图，图标继续使用 Phosphor，没有以占位图、表情、CSS 插画或自制 SVG 替代参考中的产品卡内容。
- 文案与内容：全部使用真实项目、客户、金额、任务和日期；空卡位明确为“等待新项目”且不计入经营数据，没有复制参考图示例数值或生成假项目。

## 比较历史与修复

- Pass 1 `[P1]`：旧实现是中心轨道与抽出后自动进入详情，未形成参考所示的纵向工作台，也不符合“首次点击只前置”的目标。
  - 修复：改为循环相对距离的纵向卡组，选中项完整展开，其他卡逐层向右上退开；移除自动进入定时器，增加前景卡独立“进入项目”操作。
- Pass 1 `[P2]`：旧控制只覆盖左右方向，项目操作高度不足，窄屏选中卡也不能保证居中。
  - 修复：补齐 ArrowUp/ArrowDown、Home/End，主要项目操作提升到 `44px`，窄屏选择后使用滚动居中并保留触摸与减少动态效果降级。
- Pass 2：打开源图和最终实现同屏、再检查卡组聚焦区域；没有剩余可执行的 P0、P1 或 P2。深色参考与浅色正式系统的背景差异属于已确认的产品约束。
- P3 非阻塞：当前真实分类只有两个项目和一个空卡位，无法在真实数据下展示五层完整卡组；几何函数与交互测试覆盖最多五个可见层，未为截图伪造项目数据。

## 交互、响应式与可访问性

- 鼠标在后排真实卡的可见标题条带点击后，选中项目从 `p-1786679693363` 切换回 `p-1786013284727`，Inspector 同步更新，Hash 仍停留在 `#项目管理`，没有误入详情。
- 点击前景卡的明确“进入项目”后进入 `#项目管理/p-1786013284727/immersive`；浏览器后退恢复驾驶舱。
- Home、End、ArrowUp、ArrowDown、拖动和滚轮均能切换选中项目；可继续切换时滚轮不滚动页面。卡面悬停实际命中后显示微亮、柔和阴影和轻微上提。
- `1024px` 页面宽度 `scrollWidth = clientWidth = 1024`，Inspector 移到下方；`768px` 卡组改为横向 snap，选中卡中心为 `384px`，页面无横向溢出；最窄真实 `480px` 卡组为 `display:grid`、`transform:none` 的可读单列，页面 `scrollWidth = clientWidth = 480`。
- `prefers-reduced-motion` 与粗指针降级由 CSS 媒体查询和自动化断言覆盖；没有把未运行的屏幕阅读器实测宣称为完整无障碍认证。
- 最终浏览器控制台 error/warning 为 `[]`。

## 工程与常驻运行

- 项目驾驶舱专项测试 `4 passed`；前端完整交互 `54 passed`。
- TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过；构建只保留既有大 Chunk 建议。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，PID 从 `56862` 更新为 `65037`；`/api/health` 返回 `{"status":"ok"}`，`127.0.0.1:8877` 只有一个监听进程。
- 本轮没有 Git 提交、推送、合并、公开部署、数据库写入或任何真实闲鱼操作。

final result: passed

---

# 2026-08-14 曝光检查点自动采集与断连恢复 Design QA

## 验收范围与安全边界

- “商品经营 → 曝光分析”新增两种批次级检查点采集方式：`自动采集（推荐）` 与 `到点提醒，我手动记录`；新批次默认自动采集。
- 自动模式以真实 `started_at` 为唯一时间锚点，持久化 `+1h / +6h / +24h / +72h` 四个任务；人工模式到点只进入待人工状态，不读取闲鱼商品详情。
- 断连、普通失败、部分成功、访问验证熔断与服务重启均保留任务和已成功商品结果；只有用户明确点击“恢复连接并补采”才补采未成功商品，不会后台无限重试或重复读取已成功商品。
- 当前真实数据库只有 3 个 `invalidated` 历史批次，因此页面以“等待新批次”的紧凑禁用态验收；没有为了截图创建真实曝光批次、支出、检查点或闲鱼请求。
- 本轮没有 Git 提交、推送、合并、公开部署、购买曝光或修改商品。

## 视觉真值与最终截图

- 正常自动采集确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-6c3f2ecb-33ad-4114-8a57-a100684912e1.png`。
- 断连、部分成功与恢复确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-b30fc5fc-0695-47db-89e0-c82c10572eaa.png`。
- 修改前页面参考：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/13-exposure-final-1440x900-actual.jpg`。
- 最终桌面默认态：`/Users/chentao/Documents/New project 3/artifacts/checkpoint-collection-final/05-final-default-1440x900.png`。
- 最终新建批次弹层：`/Users/chentao/Documents/New project 3/artifacts/checkpoint-collection-final/06-final-new-batch-modal-1440x900.png`。
- 1024 × 768：`/Users/chentao/Documents/New project 3/artifacts/checkpoint-collection-final/02-exposure-auto-empty-1024x768.png`。
- 768 × 1024：`/Users/chentao/Documents/New project 3/artifacts/checkpoint-collection-final/03-exposure-auto-empty-768x1024.png`。
- 内置浏览器最窄实际视口 480 × 844：`/Users/chentao/Documents/New project 3/artifacts/checkpoint-collection-final/07-final-mobile-480x844.png`。
- 内置浏览器在显式响应式覆盖时返回 2 × 2 平铺图；上述最终图只裁取同状态原始画面的左上有效象限，没有缩放、拼接或重绘页面内容。无效的平铺和滚动捕获没有作为验收证据保留。

## 同视口与重点区域比较

- 预览的双选项、绿色通道状态、下一检查点、四阶段时间线与浅色单层容器均已落入现有曝光页顶部；真实数据没有活动批次时，单选项保持可读但禁用，明确显示“新批次默认自动采集 / 等待新批次”。
- 新建批次弹层把两种方式放在费用与商品选择之间，默认选中自动采集；人工模式文案明确“系统只提醒，不访问商品详情”。批次时间继续由服务端确认分钟记录，未恢复计划时间或浏览器自填时间。
- 断连确认预览中的浅琥珀状态、部分成功数量、访问验证保护、恢复补采、人工补齐和安全诊断均已实现；由于真实数据库没有活动任务，本轮只在隔离后端测试与前端结构测试中验证这些状态，没有污染真实业务数据。
- 页面继续使用现有白紫 SaaS 外壳、紫色主操作、绿色正常状态、琥珀风险状态与 Phosphor 图标，没有新增运行时依赖、位图场景或脱离系统的组件材质。

## 响应式、交互与可访问性

- 1440 CSS 视口下 `innerWidth=1440`、内容 `scrollWidth=1410`；1024 下 `scrollWidth=994`，768 下 `scrollWidth=738`，最窄真实 480 下 `scrollWidth=450`，均没有页面横向溢出。
- 1024 下指标卡与经营计划保持两级布局；768 下主区单列但采集方式仍完整可读；480 下顶部指标与主工作区进入同一 `≤560px` 单列规则。
- 内置浏览器不能提供精确 390px CSS 视口，最窄会钳制为 480px；没有把 480px 冒充为 390px。相同 `≤560px` 分支与 390px 目标由 `tests/product-exposure-v24.test.mjs` 和前端交互测试覆盖。
- 新建批次弹层打开后焦点落在“关闭”按钮；`Shift+Tab` 从首个控件循环到最后的“确认已投放并开始记录”；`Escape` 关闭后焦点返回原“新建多商品批次”按钮。
- 第一轮浏览器验收发现新建批次弹层没有响应 `Escape`，也未返回焦点，列为 `[P2]`。最终补齐焦点陷阱、关闭键和触发器焦点恢复，并在生产构建后的真实页面复验通过。
- 最终页面控制台 error/warning 为 `[]`。截图只能证明可见层级、重排与控件状态；屏幕阅读器朗读顺序没有被截图宣称为完整合规，语义由 DOM 与自动化断言补充验证。

## 数据迁移、任务恢复与工程验证

- 新迁移：`migrations/versions/20260814_0021_product_traffic_checkpoint_collection.py`；新增批次采集方式、检查点任务和逐商品任务表。
- 迁移前在线备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-checkpoint-collection-20260814-230243.db`，权限 `0600`；迁移前后 SQLite 完整性和外键检查均通过。
- 最终真实库：批次 `3` 个，全部为 `invalidated`；采集方式兼容为 `auto`；检查点任务 `0`。服务重启没有给历史终止批次重新建任务，也没有产生新的检查点提醒。
- 后端完整测试：`269 passed, 1 warning`；警告为既有 Starlette/httpx 弃用提示。
- 前端交互：`54 passed`；曝光专项：`13 passed`；TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 均通过。构建只保留既有大 Chunk 建议。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，PID 从 `53975` 更新为 `56862`；`http://127.0.0.1:8877/api/health` 返回 `{"status":"ok"}`，8877 只有一个监听进程。

## 结论

双模式采集、按实际开始时间持久调度、断连保留与显式补采、访问验证熔断、部分成功保留、重启恢复、真实库历史隔离、弹层键盘交互、响应式布局和唯一常驻服务均完成并通过验收。没有剩余 P0、P1 或 P2。

final result: passed

---

# 2026-08-14 商品修改、客户三态与客户消息精简 Design QA

## 验收范围与保持不变项

- 商品经营 → 上新与修改：商品修改实验改为紧凑响应式信息区，右侧操作始终可见；“查看证据”使用精确 Hash `#商品经营/launch/product/{itemId}` 并在当前行展开，不再跳回经营总览。
- 客户管理：编辑表单只向用户提供“跟进中 / 已成交 / 已流失”；历史 `new / contacted / proposal` 继续兼容显示为“跟进中”，没有执行数据库迁移或批量改写客户记录。
- 客户消息：默认进入“需求分析”；回复草稿保持可见但禁用，报价转化入口撤下；历史草稿、销售分析、报价、客户、项目和需求材料均保留。
- 验收没有保存客户资料、生成模型草稿、创建报价或项目、发送真实消息，也没有触发闲鱼写操作。

## 视觉真值与实现证据

- 商品修改确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-251d9f0c-9ecb-486f-b1ba-fd828ec9dc98.png`，`1032 × 1523px`。
- 商品修改最终实现：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/product-final-1032x1524.png`，CSS 视口 `1032 × 1524`，归一截图 `1032 × 1524px`。
- 商品确认预览与实现并排证据：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/compare-product-preview-vs-final.png`；左侧确认预览，右侧最终实现。
- 客户三态确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-fc41a578-29af-4e94-b1bf-76d85b7292e9.png`，`1576 × 998px`。
- 客户编辑隐私安全聚焦图：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/customer-status-final-safe.png`，来自 `1536 × 1024` CSS 视口，只保留状态、联系与订单修正区域，不保留客户名称或列表。
- 客户状态确认预览与实现并排证据：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/compare-customer-status-safe.png`；左侧确认预览聚焦区，右侧最终实现聚焦区。
- 客户消息确认预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-4acd59f4-164d-4953-8b3c-3555cd4c9ac7.png`，`1598 × 984px`。
- 客户消息隐私安全聚焦图：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/messages-workbench-final-safe.png`，来自 `1536 × 1024` CSS 视口，只保留禁用草稿、需求分析和导出工作台，不保留会话列表或消息正文。
- 客户消息确认预览与实现并排证据：`/Users/chentao/Documents/New project 3/artifacts/design-qa/20260814-customer-workbench/compare-messages-workbench-safe.png`；左侧确认预览聚焦区，右侧最终实现聚焦区。

## 归一化与隐私边界

- 内置浏览器响应式能力在显式宽屏覆盖时使用 `devicePixelRatio = 0.5` 并输出 2 × 2 平铺图；归一截图只裁取同状态原始画面的左上有效象限，没有缩放、拼接或重绘页面内容。
- 商品截图采用与确认预览近似的 `1032px` CSS 宽度；客户编辑和客户消息采用 `1536 × 1024` CSS 视口。
- 客户消息确认预览使用示例会话；浏览器验收切换到脱敏会话，并只保留右侧工作台聚焦图。包含真实会话列表或消息正文的临时捕获已删除，最终证据只比较信息架构、禁用状态、布局、材质和操作层级。
- 浏览器最窄真实 CSS 视口仍被钳制为 `480 × 844`，没有把它冒充为精确 `390px`；相同 `max-width: 520px` 分支已在 `480px` 真实触发，`390px` 规则由交互测试覆盖。

## 全视图与聚焦对比

- 商品页面保留浅色白紫 SaaS 外壳、五项真实指标、上新雷达和市场参考。此轮当时把确认稿的桌面固定列误做成了 `1032px` 多行结构，并且没有实现右侧双层操作；该差异不是已确认设计，已在 2026-08-15 的更正验收中修复。
- `1032px` 商品页 `document.scrollWidth = 1032`；`1024px` 下文档宽度同为 `1024`，首个“查看证据”按钮右边界为 `1019px`，无需横向拖动即可操作。`768px` 下表格容器 `scrollWidth = clientWidth = 742`。
- `480px` 移动规则下实验操作按钮宽 `410px`、高 `44px`，页面 `scrollWidth = innerWidth = 480`；行内容改为单列卡片，不依赖表格右滑。
- 客户编辑抽屉保持确认稿的右侧浅色抽屉、柔和遮罩、三步结构和单层边界；真实关系状态控件只含“跟进中 / 已成交 / 已流失”。关闭控件在 `1024 / 768 / 480px` 三种规则下均为 `44 × 44px`。
- 客户消息保持三栏工作区；右侧以真实“导出工作台”替代确认稿中的示例卡片，保留需求导出、图片隐私检查、Codex 本地包和 GPT JSON 导入，不恢复草稿或报价转化。

## 交互、路由与功能边界

- 商品证据点击后 URL 为 `#商品经营/launch/product/1063558552024`，`aria-selected` 仍指向“上新与修改”，行内“判断依据”可见；刷新后 Hash、选中页签和证据行均恢复。
- 再次点击同一“查看证据”收起行内证据并回到 `#商品经营/launch`；没有业务数据写入。
- 客户编辑 DOM 的关系状态选项恰好为三项；真实历史 `new` 客户 Farewell 在列表和编辑表单中均显示为“跟进中”。没有点击“保存客户资料”。
- 客户消息“回复草稿”按钮为 disabled，“报价转化”、Sales Agent、模型选择、生成草稿、生成报价和转项目入口数量均为 0；“需求分析导出”和“导入 GPT 分析结果”仍可见。
- 后端 `/api/status` 返回 `customer_reply_drafts_enabled=false` 与 `customer_quote_conversion_enabled=false`；AI 任务没有 pending 或 running，因此重启不会继续执行旧草稿任务。
- `1024 × 768`、`768 × 1024` 和最窄真实 `480 × 844` 下三页文档宽度均等于视口宽度；页面控制台 error/warning 为 `[]`。

## 必查视觉表面

- 字体与层级：沿用循营现有字体栈、标题尺度、英文眉题和辅助文字层级；没有引入新字体或不一致字重。
- 间距与布局：商品行在桌面紧凑、平板分区、移动单列；客户抽屉和客户消息三栏保持现有栅格、圆角、留白与 44px 关键触控目标。
- 色彩与令牌：继续使用白紫背景、紫色主操作、金色提醒和既有语义色；禁用草稿使用低对比锁定态，没有制造可点击错觉。
- 图像与资产：三页继续使用项目已有循营品牌资产和 Phosphor 图标，没有新增位图、占位图、CSS 插画或自制 SVG。
- 文案与内容：状态文案统一为三态；客户消息明确说明“当前仅保留需求分析”，且没有把历史数据删除或伪装为不存在。

## 比较历史与结论

- Pass 1：首次点击证据命中浏览器缓存中的旧前端，仍跳转 `overview`；使用构建查询参数重新加载常驻服务的最新静态资源后，精确 `launch/product` 路由、刷新恢复和行内证据全部通过。该问题没有要求代码修补。
- Pass 2（历史误判）：当时错误地把商品实验表的多行布局与单按钮操作归类为“已批准差异”，因此本段的商品页通过结论无效；客户状态与客户消息结论不受影响。商品实验表已在 2026-08-15 重新以确认图为真值完成对照。
- P3 非阻塞边界：内置浏览器无法提供精确 `390px` CSS 视口；`480px` 已真实触发同一移动规则，自动化继续覆盖 `≤520px`。

## 工程与常驻运行

- 后端完整回归：`265 passed, 1 warning`；警告为既有 Starlette/httpx 弃用提示。
- 前端交互：`53 passed`；TypeScript、生产构建、Sites Worker `4 passed`、`git diff --check`、SQLite `integrity_check` 与 `foreign_key_check` 均通过。生产构建只保留既有大 chunk 建议。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启；最终 PID `22269`，`127.0.0.1:8877` 只有一个监听进程，`/api/health` 返回 `ok`，KeepAlive / RunAtLoad 状态保持。
- 没有执行 Git 提交、推送、合并、公开部署或任何真实客户、模型与闲鱼写操作。

final result: passed

---

# 2026-08-14 曝光批次新建即计时与单批追踪 Design QA

## 验收范围

- “记录已投放批次”在同一后端事务中建立批次并以服务端当前北京时间精确到分钟写入 `created_at` 与 `started_at`；前端不再要求填写计划时间。
- 同一请求 ID 跨分钟重放仍返回第一次写入结果，且只保留一笔 `expense-traffic-{batchId}` 批次级支出。
- 投放前 30 分钟内没有全部商品可靠快照时，真实费用、时间和商品组合继续保存，但批次立即终止观察，不再产生误导性的检查点提醒。
- 多商品批次追踪默认选中最新批次，通过搜索框按建立日期、商品或状态过滤；三批真实记录按建立日期分组，一次只渲染一个所选批次。
- 精确 Hash `#商品经营/exposure/batch/{id}` 支持刷新恢复；鼠标、方向键、Home、End、Enter、空格与 Escape 均保留可操作路径。

## 历史数据修正

- 修正前在线备份：`/Users/chentao/Documents/New project 3/.codex-staging/traffic-new-create-backup.8aFPR8/xianyu_operator-prechange.db`。
- 备份权限为 `600`，SHA-256 为 `126ca4a0446d186f52c0f6d904e1f8d313959f200b18ad4f989d68d359aa3be2`；`integrity_check=ok`，外键检查无异常。
- 8 月 11 日首批建立与开始均属于北京时间 16:00 分钟，不更正。
- 8 月 12 日批次属于历史重叠补录，开始时间早于建立记录，保留原事实。
- 8 月 13 日批次原建立于 16:14、误记开始于 18:06；通过服务层审计方法修正为 `8月13日16时14分`，同步把晚于投放的 T0 标记为 `invalid_baseline_time`，唯一支出时间同步为 16:14。
- 修正后 3 批均为终止观察，运行/观察中批次为 0；三批累计真实投入仍为 `¥18.1`，目标修正审计事件恰好 1 条，SQLite 完整性与外键检查继续通过。

## 真实页面与交互证据

- 桌面 CSS 视口实测为 `1440 × 900`；页面 `scrollWidth == clientWidth == 1410`，无整体横向溢出，文档高度约 `1669px`。
- 默认批次为最新的 `8月13日16时14分`，批次列表 DOM 数量为 1；真实选择器显示 8 月 13、12、11 日三个日期组，每组 1 批。
- 搜索“8月11日”后只保留 1 个匹配批次；点击后下方仍只有 1 个详情，Hash 精确更新到目标批次。
- 精确 Hash 刷新可恢复同一批次与展开状态。Home 将焦点移到最新批次，Enter 能完成选择、关闭浮层并更新 Hash；Escape 关闭后焦点返回触发按钮。
- 键盘验收第一轮发现原生 `role=option` 按钮没有响应 Enter/空格；已增加显式键盘激活处理并在最终构建复验通过。
- 控制台 error/warning 为 `[]`。

## 响应式与截图

- 内置浏览器最窄可用 CSS 视口为 `480 × 844`；对 390px 的请求会被运行时钳制到 480px。本轮没有把 480px 冒充为精确 390px。
- 480px 实测无横向溢出、一次只显示 1 个批次；选择器为底部固定抽屉，左右与底部均为 `0px`，顶部圆角 `20px`，搜索栏高 `48px`，关闭按钮 `44 × 44px`，真实选项数为 3。
- `≤560px`（含 390px）的单列、底部抽屉和触控高度由 `tests/product-exposure-v24.test.mjs` 静态交互回归覆盖。
- 桌面总览：`/Users/chentao/Documents/New project 3/artifacts/traffic-new-create-final/exposure-batch-desktop-cropped.png`，`1410 × 900`。
- 桌面单批详情：`/Users/chentao/Documents/New project 3/artifacts/traffic-new-create-final/exposure-batch-detail-desktop-cropped.png`，`1410 × 900`。
- 原始宽屏截图受内置浏览器 `devicePixelRatio=0.5` 影响形成 2 × 2 平铺；上述桌面图只裁取同一画面的左上有效象限，没有缩放、拼接或改写页面内容。
- 窄屏单批详情：`/Users/chentao/Documents/New project 3/artifacts/traffic-new-create-final/exposure-batch-final-native.png`，`656 × 1429`。

## 工程与常驻运行

- 后端完整回归：`252 passed, 1 warning`；警告为既有 Starlette/httpx 弃用提示。
- 前端交互：`46 passed`；曝光专项：`12 passed`。
- TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过；生产构建只保留既有大包体积提示。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 完成受控停止、恢复和再次重启；最终 PID 为 `139`，`127.0.0.1:8877` 只有一个监听者，`/api/health` 返回 `{"status":"ok"}`。
- 本轮没有访问真实闲鱼写接口、购买曝光、修改商品，也没有执行 Git 提交、推送、合并或公开部署。

## 结论

新建即按服务端确认分钟计时、历史批次安全更正、单批搜索分组追踪、键盘与移动抽屉、数据库完整性、全量工程检查和唯一常驻服务均通过验收。

`final result: passed`

---

# 2026-08-13 项目驾驶舱 1+A Design QA

## 验收目标与边界

- 已确认方向：`1`，采用 Activepieces 风格的纵向轻薄玻璃堆叠工作台；`A`，点击卡面只前置选中，前景卡或右侧 Inspector 的明确按钮才进入项目。
- 同步验收连接状态信息架构：健康状态不占据客户消息工具条；闲鱼、Codex 或 DeepSeek 只有明确异常时才进入全局智能提醒。
- 页面仅使用真实项目、客户、任务、合同和回款数据；没有为了视觉演示创建假项目、写入 SQLite 或修改真实平台状态。

## 视觉真值与实现证据

- 源视觉真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-c21b740d-b3a3-4d05-8bba-1deddb1e9692.png`，原始像素 `1487 × 1058`。
- 最终桌面原始捕获：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-1a/final-after-1440x900.raw.png`，浏览器返回 `2820 × 1800` 的 2 × 2 平铺 JPEG。
- 最终桌面标准分片：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-1a/tiles/q3-1440x900.jpg`，像素 `1410 × 900`，对应相同页面状态的无缩放分片。
- 源视觉与最终实现并排证据：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-1a/reference-vs-final-1440x900.jpg`，两侧均归一为 `1410 × 900`。
- 最终移动端标准分片：`/Users/chentao/Documents/New project 3/artifacts/project-cockpit-1a/tiles/mobile-q3-450x844.jpg`，像素 `450 × 844`。

## 视口、视觉与交互

- 桌面实际 CSS 视口为 `1410 × 900`，`devicePixelRatio=0.5`，`scrollWidth=1410`；1024 × 768 和 768 × 1024 也无整体横向溢出。
- 内置浏览器最窄有效宽度为 `450px`，不能冒充精确 `390px`；`450 × 844` 已进入最终单列规则，`scrollWidth=450`。
- 原始截图存在浏览器运行时的 2 × 2 平铺问题；标准分片来自 JPEG 像素级拆分，没有缩放页面内容。
- 字体与层级沿用循营系统字体栈；四项指标、左侧阶段、中间卡组、右侧 Inspector 与底部时间线保持清晰节奏。
- 卡片使用浅色白紫单层玻璃、1px 紫灰边、16px 模糊和克制光晕；没有厚侧壁、双边框、黑色工作台或不透明选中卡。
- 卡面、Inspector、合同与回款全部来自真实项目；源图的示例连接异常、项目与日期没有写入页面。
- 点击卡面后 URL 保持 `#项目管理`；前景卡和 Inspector 的独立“进入项目”按钮都进入既有 immersive 路由，返回后恢复驾驶舱。
- 后排卡 Hover 实测约上浮 `4.07px` 并提高边框和阴影；Home、End、上下左右键、拖动与滚轮边界行为通过。
- 客户消息页只保留渠道筛选与刷新；三项连接健康时智能提醒没有连接异常，也不会主动执行 Provider 或平台检查。
- 最终控制台日志为 `[]`。

## 比较历史与修复

- 第一轮没有 P0/P1，整体结构、轻玻璃材质、纵向层叠和双入口行为符合源图产品意图。
- `[P2]` 第一轮发现前景卡“进入项目”为 `42px`，Inspector 操作为 `35px`。
  - 修复：两个操作区域统一为 `44px` 最小高度，并更新交互断言。
  - 修复后：最窄有效视口下四个相关操作均实测为 `44px`，页面仍无横向溢出。
- 2026-08-13 最终复验发现 `≤820px` 的粗指针规则会把选中卡缩放到 `0.97`，使卡内 `44px` 按钮实际约为 `42.68px`。
  - 修复：选中卡在窄屏使用 `transform:none !important`，只取消错误继承的缩放，不改变后排卡的轻角度与桌面堆叠动效。
  - 修复后：请求 `390 × 844` 时浏览器实际提供 `780 × 1688` CSS 像素、`devicePixelRatio=0.5`；卡内与 Inspector 四个操作均实测为 `44px`，无横向溢出，控制台为 `[]`。
- 连接状态复验补齐“持续重连”边界：没有错误明细的短暂 `reconnecting` 不进入提醒；一旦后端给出 `ConnectError`、访问验证等明确失败明细，即进入全局智能提醒并可跳转 `#设置中心/渠道连接`。

## 自动化与运行证据

- TypeScript、生产构建和 `git diff --check` 通过；前端交互 `45 passed`；后端完整回归 `249 passed, 1 warning`；Sites Worker `4 passed`。
- 构建仅保留既有大 Chunk 建议，不是本次视觉或交互回归。
- 常驻服务再次完成受控重启，LaunchAgent 为 `running`；最终 PID `78281`，仅一个进程监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`。
- macOS 代理 `127.0.0.1:7892` 正常监听并可访问 Activepieces；本机网络和代理无需改动。闲鱼当前剩余状态为平台访问验证失败，Goofish 登录态检查返回会话已过期；系统已按真实异常显示全局提醒，未绕过验证、未更新 Cookie。
- 没有剩余可执行 P0/P1/P2。P3 边界是精确 390px 视口不可用，以及当前只有一个真实活动项目，不能在不写假数据的情况下真人演示两张真实项目间的 460ms 重排；对应结构和参数已有自动化覆盖。

final result: passed

---

# 2026-08-13 商品经营曝光分析 v2.4 压缩与重叠补录 Design QA

## 验收范围与业务边界

- 曝光页默认压缩当前批次、未来计划、早期观察、成熟分析与批次追踪；完整逐商品曲线只在用户展开某一真实批次后出现。
- 正常新投放继续阻止约 72 小时内的重复商品；“补记已发生投放”只记录用户已经在闲鱼人工购买的事实，并永久标记为归因重叠。
- 归因重叠批次可以保留真实费用、套餐曝光和检查点，但始终排除时段、预算、商品优先级和复投资格结论；页面与自动化测试均保留人工确认闸门。
- 本轮没有点击真实补录确认、开始、取消、重排、采集或投放操作，没有改写当前两笔批次。

## 视觉与交互证据

- 已确认布局真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-51e378e8-afcb-4b2e-8894-658be4ed73b3.png`。
- 默认曝光页：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/19-exposure-final-clean-1072x1494.jpg`。
- 完整页面：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/08-exposure-final-1072x1494-full.jpg`。
- 桌面重叠补录确认态：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/07-overlap-confirmation-final-1072x1494.jpg`。
- 手机重叠补录确认态：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/16-overlap-confirmation-mobile.jpg`。
- 经营总览默认态：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance-final/10-overview-final-1072x1494-full.jpg`。

## 页面压缩与跨页审查结果

- `1072 × 1494` 默认曝光页高度为 `2038px`，由修改前约 `3017px` 降低约 32%，满足不超过 `2250px` 的目标；`scrollWidth = clientWidth = 1072`。
- 顶部 Grid 使用自然高度，未来计划不再被当前批次完整曲线等高拉伸；无成熟批次时只显示紧凑状态摘要。
- 批次追踪首次进入全部收起；展开真实批次时完整曲线数量恰好为 1，收起后回到 0；计划批次显示“尚未开始，没有真实曲线”。
- 经营总览默认显示 3 条优先策略，展开到前 5 条后可收起；商品雷达默认 8 件，仍可展开全部 17 件。
- 上新与修改默认 6 条建议，可展开全部 17 条；市场参考在当前真实数据下保持一屏紧凑结构。
- 未打开的快速记账抽屉不再暴露 `role=dialog`；打开时原有对话框语义保持不变。

## 时间、计划和数据一致性

- 当前批次展示“计划 08/12 16:00”“实际投放 08/11 16:00”“较计划早 23 小时 59 分钟”；不再显示难读的 1439 分钟。
- 所有 `+1h / +6h / +24h / +72h` 继续以实际开始时间为唯一锚点。
- 未到期计划统一显示“继续观察，+72h 将于 08/14 16:00 到期”，不再与“补录 +72h”动作冲突。
- 真实库仍为 2 个批次、10 个批次商品、15 个检查点、0 个批次事件；5 笔支出合计 ¥1078.10，账本修订号 46，证明验收未写入补录事实。

## 响应式、可访问性与控制台

- 实测 `1440 × 900`、`1024 × 768`、`768 × 1024` 和浏览器可达到的最窄 `480 × 844` CSS 视口均无页面整体横向溢出；未来计划在窄屏保留自身水平滚动，不挤压整页。
- 当前浏览器的响应式能力在请求 390px 时实际提供 480px CSS 视口，因此不能把 390px 声称为真实浏览器视口；`≤560px` 规则和交互自动化覆盖仍通过。
- 窄屏重叠补录弹层为底部全宽布局，三项底部操作均为 `44px`；确认框默认未勾选，提交按钮禁用。
- Escape 关闭补录弹层后，焦点返回“补记已发生投放”；未打开页面没有可见或隐藏的错误 dialog 语义。
- 最终浏览器控制台日志为 `[]`，没有新增 error 或 warning。

## 数据迁移、自动化与常驻运行

- 迁移前备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-product-traffic-overlap-20260813-004617.db`，权限 `0600`，SHA-256 `69774b45f5e8f5e2ed36009e83f1a877936a77887598449b74c90aa298b6ef8e`。
- SQLite `PRAGMA integrity_check = ok`，`foreign_key_check` 无异常。
- 后端完整回归：`241 passed, 1 warning`；警告为既有 Starlette 依赖弃用提示。
- 前端交互：`35 passed`；TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 均通过。构建仅保留既有大 chunk 警告。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 最终 PID `10741`，`127.0.0.1:8877` 单一监听，`/api/health` 返回 `ok`，受控重启恢复通过。
- 外部状态仍有 `AdapterAccessVerificationError`：闲鱼监听需要用户在现有 Edge 完成人工验证后再恢复；本轮没有更新 Cookie、绕过验证或触发真实采集。

## 结论

- 曝光分析页面密度、重叠事实补录边界、计划时间语义、批次图表折叠、商品经营其余页面压缩、响应式与常驻运行均通过。
- 没有执行 Git 提交、推送、合并、公开部署或真实闲鱼业务动作。

final result: passed

---

# 2026-08-12 商品经营曝光分析 v2.4 最终验收

## 源真值、实现截图与归一化

- 用户确认的视觉真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-51e378e8-afcb-4b2e-8894-658be4ed73b3.png`，1571 × 1001 px。
- 最终桌面截图：`/Users/chentao/Documents/New project 3/data/private/v24-qa/exposure-v24-final-1440x900.jpg`。浏览器 CSS 视口为 1440 × 900；内置浏览器以约 2× 像素密度输出 2820 × 1800，比较时按 CSS 像素归一化。
- Edge 目标宽度截图：`/Users/chentao/Documents/New project 3/data/private/v24-qa/exposure-v24-final-1344x768.jpg`，CSS 视口 1344 × 768，输出 2628 × 1536。
- 中等与竖屏截图：`exposure-v24-final-1024x768.jpg`、`exposure-v24-final-768x1024.jpg`，均位于 `data/private/v24-qa/`。
- 最窄可测截图：`exposure-v24-final-narrow-480x844.jpg`。内置浏览器将请求的 390 × 844 CSS 视口钳制为 480 × 844；因此没有把 480 冒充为精确 390，但同一 `max-width: 560px` 分支已实际触发并验收。
- 三栏同屏对照图：`/Users/chentao/Documents/New project 3/artifacts/v24-acceptance/exposure-v24-reference-before-final.png`，依次展示确认效果图、修改前 v2.3 与最终 v2.4；仅做等比缩放和排版，没有重绘业务内容。
- 完整视图对照：参考图和最终桌面页均采用浅色 SaaS、一个主要滚动经营面、当前批次 / 未来计划的清晰分栏以及紫色克制主操作。最终实现保留真实导航、真实五项指标、真实批次与真实检查点，不复制效果图中的示例数字或假状态。
- 重点区域对照：当前批次内嵌逐商品曲线；未来计划与当前观察语义分离；跨批次分析只保留成熟投入、长尾平均和时段比较；历史批次用聚合迷你图与可展开完整曲线，不与当前批次重复制造大图。

## 视觉与响应式结果

- 1440 × 900：内容区使用当前批次与未来计划两列，当前真实曲线直接可见；页面横向溢出为 0。
- 1344 × 768：Container Query 命中两列布局，当前批次宽 359 px、未来计划宽 594 px，早期观察完整下移为 964 px 横向指标带；右侧未被三列强行压缩，页面横向溢出为 0。
- 1024 × 768：当前批次宽 357 px、未来计划宽 546 px，早期观察下移；未来七天只在自身容器内横向浏览，页面横向溢出为 0。
- 768 × 1024：当前批次、未来计划和早期观察改为单列，容器宽 670 px；页面横向溢出为 0。
- 480 × 844：逐商品图表一次只展示一个商品，上一件 / 下一件均为 44 × 44 px，四个指标按钮均可操作；点击下一件后从“前端页面美化与功能修改”切换到“MySQL/建表/SQL/ER图/连接”。页面横向溢出为 0。
- `prefers-reduced-motion`：曝光页现有媒体查询将过渡压缩到 0.01 ms、动画只执行一次，并取消旋转加载动画；没有持续视差或必须依赖动画才能完成的操作。

## 时间、计划与图表语义

- 当前真实批次显示“实际投放 08/11 16:00”和“计划 08/12 16:00 · 较计划早 1439 分钟”，并明确声明所有检查点从实际开始时间计算。
- 当前页显示“当前批次 · 跟进 +72h”；未来计划显示“补录 08/11 批次 +72h / 跟进观察”，没有把昨天已购买的批次伪装成今天再次投放。
- 当前历史 T0 批次保留 `T0 / +1h / +6h / +24h` 真实记录和等待中的 `+72h`，且明确标记不能进入成熟结论或获得商品复投资格。
- 逐商品曲线只绘制真实检查点，T0 固定为 0，缺失的 +72h 不插值。切换“咨询”后当前商品值同步为 +0；当前 +24h 排名与商品切换保持一致。
- 待开始批次显示“尚未开始，没有真实曲线”，没有使用效果图示例数据或占位曲线。
- 真实观察批次卡显示聚合浏览增量迷你曲线与“咨询 +0”；“展开完整曲线 / 收起完整曲线”均已在浏览器实际操作通过。

## 只读交互、安全边界与修正历史

### Pass 1：v2.4 主布局与真实图表

- [P1] 旧版在约 1344 宽度仍尝试容纳三列，早期观察和右侧内容被压缩。
  - 修复：曝光工作区改为 CSS Container Query；1344 与 1024 均为两列，早期观察移动到下一行。
- [P1] 计划批次、观察批次和跨批分析出现信息重复，用户难以判断“今天是否又要投放”。
  - 修复：观察槽通过 `source_batch_id` 明确绑定实际批次；新付费与继续观察分别标记；跨批分析删除重复的逐商品大图。
- [P1] 缺少逐批次真实图表。
  - 修复：当前批次内嵌完整逐商品曲线；每个已开始批次提供真实聚合迷你图和可展开完整曲线；计划批次不画假图。

### Pass 2：重排预览费用一致性

- [P1] 浏览器只读打开重排预览时，卡片总费用为 ¥5.9，但弹窗把 `fee_impact=0` 误显示成“费用不变 ¥0”。
  - 修复：弹窗改为“总费用保持 ¥5.9（增量 ¥0）”，明确区分原批次总费用与重排增量；未点击确认重排。
  - 修复后重新通过 TypeScript、曝光定向测试、30 项交互测试、生产构建、Sites Worker 与 `git diff --check`，并经唯一 LaunchAgent 重启后在真实页面复验。

### Pass 3：最终验收

- 没有剩余 P0、P1 或 P2 视觉、语义或安全问题。
- 只执行了指标切换、商品前后切换、历史图表展开 / 收起、重排预览打开 / 关闭等安全交互；没有远程刷新 T0、开始批次、确认重排、取消计划、新建批次、记录检查点、重新评估或购买曝光。
- 浏览器控制台 error / warning 均为空。

## 工程、数据库与常驻服务

- 后端全量测试：233 passed；商品经营定向：47 passed；前端交互：30 passed；Sites Worker：4 passed；TypeScript、生产构建与 `git diff --check` 通过。仅保留既有 Starlette/httpx 弃用警告和 Vite 大包提示。
- 真实数据库迁移后保持 2 个批次、10 个批次商品、15 个检查点、2 个项目、2 个付款节点、Ledger revision 46；`product_traffic_batch_events=0`，证明浏览器验收没有执行 v2.4 批次写操作。
- 当前观察批次仍为 `traffic-batch-1b46d3a7-5070-46be-8998-c87e7d378c73`；待开始批次仍为 `traffic-batch-c8749369-fe89-4f1f-80ec-d3956f7e2c35`，费用均为 ¥5.9，待开始批次未自动取消、替换或准备 T0。
- SQLite `integrity_check=ok`、`foreign_key_check=0`。最终私有快照位于 `data/private/v24-milestones/20260812-migration-complete/` 与 `data/private/v24-milestones/20260812-final-runtime/`，目录权限 0700、数据库 0600，SHA-256 均为 `9694091cb96b45cbe4b2d5bf90cffb52b714fa7424cd4e63981f6a85f3984ab3`。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后由 PID 89973 唯一监听 `127.0.0.1:8877`；`/api/health` 返回 `status: ok`。
- 本轮没有 Git 提交、推送、PR、合并或公开部署，也没有自动投流或自动修改商品。

final result: passed

---

# 2026-08-12 商品经营曝光方案 v2.3 最终验收

## 验收范围

- 取消独立“目标计划”导航和页面；首页月度目标卡与设置字段继续保留。
- 将曝光页分为当前真实批次、未来七天计划和早期观察三种语义，不再把观察任务误解为新投放。
- 规则使用实际开始时间计算 `T0 → +1h → +6h → +24h → +72h`；+1h/+6h 只作过程信号，合格 T0 的 +24h/+72h 才能进入成熟结论。
- 同一商品的 72 小时归因窗口由后端硬保护；前端按钮禁用只是额外提示。没有自动取消旧计划、自动投流、自动补录检查点或修改商品。

## 当前真实数据与结论

- 当前观察批次：2026-08-11 16:00 北京时间开始，5 件商品，批次总费用 ¥5.9，套餐总曝光 9,200。
- 已记录 `+1h / +6h / +24h`，成熟度 3/4；+24h 为浏览 +54、想要 +3、咨询 +0。
- T0 距实际开始约 434 分钟，超过 30 分钟门槛，因此保留真实轨迹但不纳入时段、预算或商品优先级结论。
- 下一检查点为 2026-08-14 16:00 的 +72h，当前未到期；成熟有效批次仍为 0。
- 当前第 7 版计划：08/12 补录当前批次 +72h，08/13–08/14 冷却观察，08/15 才考虑下一批，08/16 优化，08/17 候选批次，08/18 优化。
- 本周已投入 ¥5.9、未来计划 ¥11.8、周上限 ¥24、剩余额度 ¥6.3；因成熟有效批次为 0，系统没有给出追加预算或优先时段结论。

## 安全修正与界面证据

- 真实数据库中原有一个待开始批次与当前观察批次重叠 2 件商品。接口现在返回 `start_blocked=true`，最早时间为 2026-08-14 16:00；即使绕过前端，启动接口也返回 409，且不会新增曝光支出。
- 页面明确显示“1 个观察中 · 1 个待开始”，不再笼统写成“2 个进行中”。
- 默认选中今天 08/12 的观察计划，不再默认跳到未来第一个投放日。
- 单批排名显示“批次内观察，不进入时段 / 预算 / 商品优先级结论”。旧 T0 的 +1h/+6h/+24h 显示“已有记录 · 因 T0 或归因质量未纳入”，不再误写成等待记录。
- 桌面单幅证据：`/Users/chentao/Documents/New project 3/artifacts/exposure-analysis-v23-desktop-final.jpg`；原始捕获为 `artifacts/exposure-analysis-v23-1440x900.png`。
- 窄屏单幅证据：`/Users/chentao/Documents/New project 3/artifacts/exposure-analysis-v23-mobile-final.jpg`；原始捕获为 `artifacts/exposure-analysis-v23-390x844.png`。
- 浏览器截图后端会按设备缩放重复平铺；单幅证据仅从原始捕获裁取左上真实页面，没有重绘或改变页面内容。

## 浏览器与响应式

- 同一内置浏览器标签使用无缓存构建地址恢复最新资源，没有开启第二个网站或第二个服务。
- 目标计划导航计数为 0；今天的计划卡为选中态。
- 待开始重叠批次按钮处于 disabled，原因文案和后端返回一致。
- 桌面与窄屏均无页面横向溢出；未来七天卡仅在自身容器内横向浏览。
- 浏览器控制台 error/warning 均为空。

## 自动化、数据库与常驻运行

- 后端完整回归：228 passed；仅有既有 FastAPI/Starlette 弃用警告。
- 前端交互：25 passed；TypeScript 通过；Sites Worker 4 passed；生产构建通过；`git diff --check` 通过。
- 生产构建仅保留既有大包体积提示，不是构建失败。
- 重启前后计划保持同一 ID、v2.3 第 7 版；连续 GET 的计划语义哈希一致，Ledger 修订号保持 46，证明浏览页面不会写业务数据或制造计划噪声版本。
- SQLite `integrity_check=ok`，`foreign_key_check=0`。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后自动恢复；最终只有 PID 72745 监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`。
- 本轮没有提交、推送、合并或公开部署。

final result: passed

---

# 2026-08-12 独立「目标计划」取消 Design QA

## 验收范围

- 删除左侧独立「目标计划」入口、对应页面元数据、页面路由分支、示例数据页面和专用样式。
- 保留首页「本月目标」卡片、设置中心「月度目标金额」、`monthlyIncomeGoal` 以及旧 `goalRemindersEnabled` 数据兼容字段。
- 设置中心不再显示没有真实提醒来源的「月度目标进度提醒」开关；没有修改 SQLite 经营数据。

## 页面与运行证据

- 商品经营曝光页：`/tmp/xianyu-goal-removal-audit-2026-08-12/01-exposure-after-goal-removal-1440x900.png`。
- 设置中心月度目标：`/tmp/xianyu-goal-removal-audit-2026-08-12/02-settings-monthly-goal-1440x900.png`。
- 左侧导航顺序为「数据统计 → 经营分析中心 → 小策 · 今日判断 → 设置中心」，不存在「目标计划」。
- 打开旧 `#目标计划` 地址后安全显示首页；首页「本月目标」卡仍存在。
- 设置中心「记账设置」保留可用的「月度目标金额」输入和「首页月度目标卡会实时读取」说明。
- 浏览器控制台 error / warning 为 `[]`。

## 工程与常驻服务

- TypeScript 类型检查通过。
- 生产构建通过；仅保留既有的大包体积提示。
- Sites Worker：`4 passed`。
- 关键前端交互：`25 passed`。
- `git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后从 PID `55737` 恢复为 PID `62570`；`127.0.0.1:8877` 只有一个监听，`/api/health` 返回 `{"status":"ok"}`。

## 结论

独立目标页面已取消，同时保留了首页月度目标与旧数据兼容，导航、旧地址回退、构建和唯一常驻服务均通过。

final result: passed

---

# 2026-08-12 历史导入遮挡与 Codex 深度超时修复

## 修复结果

- 历史对话导入弹层改用 React Portal 挂载到 `document.body`；真实页面测得遮罩从视口左上角覆盖完整页面，左侧导航位于遮罩下方，横向溢出为 0。
- 保留既有浅色单层玻璃、双栏桌面布局、窄屏底部抽屉、Escape、遮罩关闭、焦点闭环与焦点返回，不通过隐藏侧栏或堆叠更高局部 `z-index` 规避问题。
- Codex 模型生成新增 Provider 级有效超时下限。销售分析传入 15 秒、经营分析传入 20 秒时均提升到 Codex 独立配置；任务明确需要更长时间时保留更长值。
- 本机唯一 `8877` 服务的 `CODEX_TIMEOUT_SECONDS` 已设为 300；DeepSeek 继续使用 12 秒快速通道。安装、登录、帮助和模型目录等非生成探针继续使用短诊断超时。
- 页面中既有的“Codex 生成超时（15 秒）”失败记录不会改写数据库，而是标注为历史记录，并明确说明当前重试改用 Codex 独立长时限；本机当前配置为 300 秒。

## 验收证据

- 后端全量测试：`215 passed, 1 warning`；前端交互测试：`21 passed`。
- TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 全部通过。
- 真实桌面页：遮罩父级为 `BODY`，左侧命中元素为 `.history-import-backdrop`，全局“立即记账”隐藏，关闭按钮自动获得焦点。
- 真实窄屏页：弹层保持在视口内，确认区无覆盖，页面无横向溢出。
- Escape 和关闭按钮均可退出，焦点返回“导入历史”；浏览器控制台无 error 或 warning。
- 本轮自动化与浏览器验收没有点击查询或确认导入，没有调用真实模型、发送客户消息或标记消息已读。最终数据库验收前已经存在 1 条历史导入提交审计记录，创建于 2026-08-12 02:44（北京时间 10:44），服务日志对应一次成功提交；来源无法仅凭安全日志归因，因此本轮保留该用户数据且未新增第二条记录。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后为 running，`127.0.0.1:8877` 只有一个监听进程，`/api/health` 返回 ok。

final result: passed

---

# 2026-08-12 闲鱼历史对话导入 Design QA

## 源真值、实现与归一化

- 用户确认的源效果图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-12dce56c-00dd-4334-83bb-8e7d62bdeebb.png`，1487 × 1058 px。
- 桌面实现截图：`/tmp/xianyu-history-import-2026-08-12/01-desktop-default.png`，5760 × 3600 px；浏览器测试视口设置为 1440 × 900，内置浏览器以 4× 像素密度输出。比较时以弹层内容区和源图中的同一默认空状态为准。
- 窄屏实现截图：`/tmp/xianyu-history-import-2026-08-12/02-mobile-default.png`，1560 × 3376 px；浏览器测试视口设置为 390 × 844，内置浏览器以 4× 像素密度输出。
- 状态：客户消息页打开“导入闲鱼历史对话”，尚未查询或提交；待回复复选框保持默认关闭，确认按钮不可用。
- 全视图比较：源图与桌面实现均为居中的浅色单层玻璃弹层、白紫雾化背景、双栏会话选择/消息预览、底部规则和人工确认区。实现保留当前循营侧栏、真实品牌、现有页面密度和紫色令牌，没有照搬源图里的演示客户内容。
- 聚焦比较：标题、安全边界、搜索栏、时间范围、双栏空状态、规则说明、待回复选项和底部按钮在最终截图中均可直接判读，因此不需要额外拆分局部截图。

## 必查视觉面

- 字体与排版：沿用全站中文无衬线字体；英文 eyebrow、25px 主标题、12px 辅助说明和 9–11px 密集业务标签形成清晰层级，长文不溢出弹层。
- 间距与布局：桌面 1040px 双栏弹层、26px 圆角和 24px 外围节奏与源图相近；窄屏切为 94dvh 底部面板和单列内容，不产生页面横向溢出。
- 颜色与令牌：使用白紫半透明单层玻璃、1px 冷灰紫细边、柔和蓝紫光晕、绿色只读安全提示和紫色主操作；没有黑色界面、厚玻璃侧壁或高反射材质。
- 图像与图标：本功能只复用现有 Phosphor 图标，不需要新增位图资产；未使用 emoji、手写 SVG、CSS 插画或与品牌不一致的图标族。
- 文案与内容：明确写明“只读查询、不发送、不标记已读、确认前不写入”，并说明平台消息 ID 去重、历史消息不增加未读、默认不生成草稿。
- 交互与可访问性：已验证查询、自动只读预览、Escape、关闭按钮、遮罩关闭、焦点闭环与焦点返回；默认待回复复选框未勾选。窄屏打开时隐藏全局“立即记账”，避免遮挡导入按钮；减少动态效果媒体查询会取消弹层位移。

## 比较与修正历史

### Pass 1：默认轻薄玻璃与只读流程

- 实现与确认图保持相同的信息骨架，同时替换为当前循营真实品牌、真实接口状态和空状态内容。
- 真实只读查询返回历史会话，并自动完成一条会话的差异预览；没有点击“确认导入”，数据库中的历史导入提交记录保持 0。

### Pass 2：窄屏全局操作遮挡

- [P1] 390 × 844 窄屏下，全局“立即记账”悬浮按钮压住历史导入确认区域，可能造成误点或核心操作不可达。
  - 修复：`body.history-import-open` 时隐藏全局 `.floating-add`，不改变其他页面或弹层关闭后的状态。
  - 修复后证据：`/tmp/xianyu-history-import-2026-08-12/02-mobile-default.png`；页面横向溢出为 0，待回复默认仍为关闭，确认区域完整可见。

## 运行与安全证据

- 真实搜索和预览只读执行成功；未提交导入、未发送消息、未标记已读、未生成草稿。
- 控制台 error / warning 为 0；焦点始终停留在弹层内并在关闭后返回“导入历史”入口。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后继续运行，只有一个进程监听 `127.0.0.1:8877`，`/api/health` 返回 `status: ok`。
- 桌面和窄屏最终实现均无剩余 P0、P1 或 P2 视觉与交互问题。

final result: passed
---

# 2026-08-10 项目追加订单 Design QA

## 验收范围与证据

- 正常项目追加订单最终页面：`/tmp/xianyu-change-order-qa-2026-08-10/change-order-modal-final.png`。
- 终止合作项目保护：`/tmp/xianyu-change-order-qa-2026-08-10/terminated-project-guard.png`。
- 追加订单保留在原项目内，原合同、原付款节点和历史收入不被覆盖；新增金额通过独立追加订单记录及关联付款节点审计。
- “追加订单”与“拆分现有未收余额”继续是两个独立入口；保存追加订单不会改变项目状态或完成订单数。

## 视觉与交互验收

- 弹层沿用现有浅色 SaaS 设计：白紫表面、单层圆角卡片、紫色主操作和清晰的合同变化预览，没有引入深色工作区或新视觉依赖。
- 表单完整展示追加内容、追加金额、客户确认日期、已到账 / 单笔待收 / 分期计划、备注和保存结果预览。
- 在真实已结清项目 `uni-app页面修改` 中填写“验收演示（不保存）”和 ¥120，切换分期计划后自动生成 ¥60 + ¥60 两期；预览正确显示合同总额 ¥230 → ¥350、已确认入账保持 ¥230、可收余额 ¥0 → ¥120。
- 点击取消后弹层关闭，未触发保存。页面控制台 error / warning 为 0。
- `去除豆包水印` 已存在终止合作记录：收入页顶部显示不可用的“已终止，请新建项目”，空付款计划显示“原合作已经终止”，且不再提供新增追加订单入口；后端同时以 `project_terminated` 拒绝绕过前端的请求。
- 正常项目的“追加订单”按钮仍可用；项目详情合同卡、付款计划区和收入页入口使用同一业务边界。

## 数据与接口边界

- 新增 `project_change_orders` 审计表，`payment_nodes.change_order_id` 可关联追加订单；迁移后 `PRAGMA foreign_key_check` 为 0，完整性为 `ok`。
- `POST /api/ledger/change-orders` 使用 `request_id` 防重复提交，并使用 `expected_revision` 防止覆盖其他浏览器的新版本。
- 支持已到账、单笔待收和金额合计严格等于追加金额的分期计划；部分到账拆分继续保留追加订单关联。
- 浏览器验收前后 SQLite 均为 revision 33、2 个项目、1 个付款节点、0 个追加订单，证明预览与取消没有写入经营数据。

## 工程与运行验收

- 后端完整测试：174 passed，1 条既有 Starlette/httpx2 弃用提醒；其中追加订单 6 项针对性测试通过。
- TypeScript 类型检查通过。
- Vite 生产构建通过，并生成 `dist/client/index.html`、`dist/server/index.js` 与 `dist/.openai/hosting.json`；仅保留既有大分包体积提示。
- Sites Worker 4/4 通过；`git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启恢复，`/api/health` 返回 `status: ok`，最终只有一个进程监听 `127.0.0.1:8877`。
- 未提交、推送、合并或公开部署，没有启动第二端口或第二个真实后端。

final result: passed

---

# 2026-08-10 经营浏览口径与项目任务编辑补充 Design QA

## 范围与源真值

- 本轮是“三张确认效果图最终实现”之后的补充收口，不改变上节三张确认图的布局、视觉方向或业务边界。
- 商品经营修改前基线：`/tmp/xianyu-self-view-task-editor-20260810/02-task-before.png`，1521 × 1500 px。文件名沿用验收过程编号，实际内容是商品经营页，不作为任务页证据。
- 商品经营最终实现：`/tmp/xianyu-self-view-task-editor-20260810/09-product-browse-accounting.png` 与 `10-product-radar-accounting.png`，均为 1521 × 1500 px。
- 任务驾驶舱实现基线：`/tmp/xianyu-self-view-task-editor-20260810/03-task-cockpit-after.png`，1521 × 1500 px。
- 任务编辑桌面状态：`/tmp/xianyu-self-view-task-editor-20260810/04-task-editor-desktop.png`，1521 × 1500 px。
- 任务驾驶舱数据恢复后的最终状态：`/tmp/xianyu-self-view-task-editor-20260810/11-task-final-restored.png`，1521 × 1500 px。
- 最终浏览器实时截图：`/tmp/xianyu-self-view-task-editor-20260810/12-task-final-live-browser.png`，2560 × 1440 px；CSS 视口为 2560 × 1440，device scale 1。
- 任务编辑器没有独立的新概念图；其视觉源真值是当前系统已确认的浅色 SaaS 表面、紫色主操作、白紫细边卡面与既有弹层/抽屉模式。它不替换三张确认效果图中的任何页面结构。

## 归一化与同屏比较

- 驾驶舱同状态全屏对照：`/tmp/xianyu-self-view-task-editor-20260810/13-task-cockpit-stability.png`，3048 × 1554 px；左右原图均为 1521 × 1500，未缩放，仅增加 54 px 标题区和 6 px 分隔。
- 移动端缺陷修复对照：`/tmp/xianyu-self-view-task-editor-20260810/14-task-editor-mobile-fix.png`，3048 × 1554 px；左右原图均为 1521 × 1500，内部同源 iframe CSS 视口均为 480 × 844，density 1。
- 商品口径全屏对照：`/tmp/xianyu-self-view-task-editor-20260810/15-product-accounting-overview.png`，3048 × 1554 px；左右原图均为 1521 × 1500。
- 驾驶舱聚焦对照：`/tmp/xianyu-self-view-task-editor-20260810/16-task-cockpit-focus.png`，2386 × 824 px；裁切真实驾驶舱、轨道、Inspector 与时间线区域。
- 移动编辑器聚焦对照：`/tmp/xianyu-self-view-task-editor-20260810/17-task-editor-mobile-focus.png`，1246 × 984 px；裁切 480 × 844 iframe 的编辑器区域。
- 商品经营指标聚焦对照：`/tmp/xianyu-self-view-task-editor-20260810/18-product-accounting-focus.png`，1816 × 854 px；裁切今日策略的真实指标文案。
- 驾驶舱基线与最终图的平均 RGB 绝对差为 0.0000；仅浏览器顶部通知像素存在 8 × 4 px 的不可见级差异，任务区域没有视觉漂移。

## 最终实现

- 商品采集每次成功读取保留 `raw_browse_count`，并累计 `collection_views_excluded`；所有趋势、转化、建议和实验统一使用 `browse_count = max(0, raw_browse_count - collection_views_excluded)`。
- 商品雷达和选中商品详情同时显示“经营浏览”“平台原始”“已排除”，避免把采集自身产生的访问误判为自然流量。最终浏览器证据中 MySQL 商品为经营浏览 70、平台原始 73、已排除 3，公式一致。
- “新增任务”现在打开空白编辑器，不会直接生成默认业务记录；Inspector 与普通任务列表均提供明确的“编辑任务”入口。
- 编辑器支持名称、状态、开始/截止日期、预计/实际工时；保存后沿用既有修订写入路径，同步任务轨道、状态指标、工时和项目进度。
- 项目已过交付日时，新任务默认截止日不再早于默认开始日；日期、名称与工时均在保存前校验。
- 编辑器通过 `createPortal(..., document.body)` 挂载到页面最外层，避免长页面过渡容器影响 `position: fixed`；桌面显示居中弹层，窄屏显示视口内底部抽屉。

## 必查视觉面

- 字体与排版：继续使用现有中文无衬线字体栈和系统字阶。标题、字段标签、单位、状态与辅助说明形成清楚层级；桌面和 480 px 模式均无截断、异常换行或过密文本。
- 间距与布局：桌面弹层宽度、表单两列和底部 44 px 操作区与系统弹层一致；窄屏改为单列表单和底部抽屉，页面横向溢出为 0。
- 颜色与令牌：保留白紫卡面、1 px 浅边、紫色主操作、蓝色进行中、绿色完成和橙红风险；没有黑色工作区、厚重玻璃或额外大色块。
- 图像与资产：只使用现有品牌资产及 Phosphor 图标；没有新增位图背景、占位图、表情符号、手写 SVG、Canvas、WebGL 或运行时依赖。
- 文案与内容：编辑器文案说明保存后影响，经营浏览文案明确解释原始量与排除量；商品、项目和任务值都来自真实本机数据，没有写入效果图示例数据。
- 图标与控件：任务状态、日期、工时、关闭、保存和编辑图标来自同一 Phosphor 家族，尺寸和笔画一致；按钮均有明确 hover/focus/selected 状态。
- 无障碍：编辑器使用 `role="dialog"`、`aria-modal`、标题和说明关联；打开后首字段获得焦点，Escape、关闭按钮和遮罩均可退出，按钮和表单可键盘到达，减少动态效果时取消位移动画。

## 比较历史

### Pass 1：任务创建默认日期

- [P1] 已过项目交付日时，新增任务曾把项目交付日直接作为截止日，导致默认开始日为 08/10、截止日为 08/09，用户无法直接保存合理任务。
  - 修复：默认开始日取今天或项目开始日中的较晚值；默认截止日取项目交付日与默认开始日中的较晚值。
  - 修复后证据：`04-task-editor-desktop.png` 和 `08-task-editor-mobile-fixed.png` 均显示 2026/08/10 — 2026/08/10。

### Pass 2：移动端弹层定位

- [P1] 480 × 844 长页面中，弹层最初受页面过渡容器影响落到可见视口下方；遮罩存在但表单不可操作，阻断移动端核心流程。
  - 修复前证据：`07-task-editor-mobile-before-fix.png`。
  - 修复：使用 React Portal 挂到 `document.body`，窄屏由正式媒体查询显示为底部抽屉。
  - 修复后证据：`08-task-editor-mobile-fixed.png`、`14-task-editor-mobile-fix.png` 和 `17-task-editor-mobile-focus.png`；表单、取消和创建任务均在视口内。

### Pass 3：真实任务增改与数据恢复

- 新建临时任务后，驾驶舱指标、轨道、Inspector、任务列表、工时和项目进度同步；随后在 Inspector 和普通任务列表中各完成一次编辑验证。
- 验收前修订号 25，交互验收结束修订号 28，使用正常修订接口恢复到修订号 29；恢复后的快照与验收前完全一致，没有残留临时任务，也没有直接修改 SQLite。
- `03-task-cockpit-after.png` 与 `11-task-final-restored.png` 的同屏与聚焦对照未发现任务区域漂移。

### Pass 4：经营浏览口径

- [P1] 采集商品详情会让平台原始浏览增加，原规则可能把系统自身读取误判为自然流量，影响趋势、咨询转化和曝光策略。
  - 修复：数据库保留原始值和累计排除量，服务端只将真实成功的远程商品详情采集计为一次保守自访问；缓存、测试历史和人工观察不增加排除量。
  - 修复后证据：`09-product-browse-accounting.png`、`10-product-radar-accounting.png`、`15-product-accounting-overview.png` 和 `18-product-accounting-focus.png`。
- 最终页面保留原有信息架构和卡片节奏，只替换经营指标口径并增加一行可审计说明；未发现 P2 以上的密度或可读性回归。

## 交互、响应式与运行证据

- 已验证新增、空名称校验、编辑、推进入口、Inspector/普通列表同步、Escape 关闭、首字段聚焦、遮罩退出与弹层打开时隐藏全局“立即记账”。
- 当前实时复验只打开并关闭空白编辑器，没有再次保存业务数据；`body` 滚动锁定，编辑器层为视口固定定位，页面横向溢出 0。
- 480 × 844 同源 iframe 命中 `max-width: 560px` 规则，表单改为单列；修复后取消和创建任务按钮均完整可见。
- 商品页最终 DOM 同时出现经营浏览、平台原始与已排除字段；推荐、雷达、趋势和转化漏斗均使用经营浏览。
- 浏览器控制台 error / warning 为 0。
- 现有历史任务仍保留一条 08/10 — 08/09 的原始业务日期，本轮未擅自改动用户数据；再次编辑保存时会由新校验要求用户修正。这是历史数据质量说明，不是本轮新增任务默认值回归。

## 工程、数据库与服务验收

- 后端完整测试：168 passed，1 条既有 Starlette/httpx2 弃用提醒。
- TypeScript 类型检查、生产构建、Sites Worker 4/4 与 `git diff --check` 均通过；构建只保留既有大分包体积提示。
- 数据升级前生成 WAL 安全备份 `data/backups/xianyu_operator-before-browse-accounting-20260810-113053.db`；备份和当前数据库完整性均为 `ok`，外键违规 0。
- 新增列 `raw_browse_count`、`collection_views_excluded` 已存在；快照总数保持 55，今日采集批次保持 1，重启没有触发第二次真实闲鱼采集。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 保持 RunAtLoad/KeepAlive；最终只由一个进程监听 `127.0.0.1:8877`，`/api/health` 返回 `status: ok`。
- 未提交、推送、合并或公开部署；没有启动第二个端口、第二个后端或第二个浏览器标签页，也没有触发真实采集、发送、商品修改或投流。

## 最终判断

- 已修复所有本轮发现的 P0、P1 和 P2；无剩余阻断项。
- 补充功能沿用三张已确认效果图所在的浅色产品体系，没有破坏原有页面层级、驾驶舱空间轨道或真实数据边界。

final result: passed

---

# 2026-08-09 顶部「智能提醒」丰富版 Design QA

## 源真值、实现与归一化

- 用户确认的源效果图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-a7f7c3bf-6690-4f54-af94-8315845c6438.png`，1330 × 1183 px。
- 浏览器桌面原始截图：`/tmp/xianyu-reminder-rich-2026-08-09/final-reminder-rich-qa-raw.png`，2660 × 2368 px，浏览器 CSS 视口 1330 × 1184，`devicePixelRatio = 2`。
- 桌面归一化截图：`/tmp/xianyu-reminder-rich-2026-08-09/final-reminder-rich.png`，1330 × 1183 px；原始截图按 50% 缩小，并按源图高度裁去底部 1 px，没有改色、重排或补帧。
- 手机实现：`/tmp/xianyu-reminder-rich-2026-08-09/mobile-reminder.png`，480 × 844 px；原始 960 × 1688 px 截图按 50% 归一化。
- 全视图同屏证据：`/tmp/xianyu-reminder-rich-2026-08-09/final-comparison-source-vs-implementation.png`，左侧源图、右侧最终实现。
- 浮层聚焦证据：`/tmp/xianyu-reminder-rich-2026-08-09/final-comparison-reminder-focused.png`；提醒标题、状态、内容卡和底部操作均可直接判读，因此不需要再拆分更小的局部证据。
- 比较状态均为数据统计页、铃铛角标 1、提醒浮层打开；最终实现使用当前 SQLite 和商品经营接口中的真实状态，不复刻效果图里的示例回款事项。

## 数据边界与内容真实性

- 顶部提醒只聚合客户未读/待回复，以及商品经营中的到期更新、逐商品最新采集失败、市场关键词更新、上新建议或计划、曝光检查点、修改实验复盘和中高优先级经营建议。
- 项目异常、交付日期、合同余额、待回款和结算状态不再进入顶部提醒或首页同名提醒卡。
- 采集失败读取每个本人商品的最新状态；当天较早的失败批次不会覆盖随后成功的逐商品手动刷新，因此不会产生“旧失败仍在提醒”的误报。
- 最终真实状态为 1 条经营建议：`Django校园二手平台完整源码`；界面没有新增演示提醒，也没有为了贴图修改客户、项目、商品、任务、收款或经营数据。
- 打开、关闭、浏览和跳转提醒只改变前端显示与路由；没有经营数据写入。

## 必查视觉面

- 字体与排版：沿用全站中文无衬线体系；标题、副标题、状态胶囊、类别、商品名、说明、时间和操作形成清晰层级，桌面长文单行收敛，手机说明可读且不重叠。
- 间距与布局：桌面使用 390 px 单层玻璃浮层，右缘与铃铛/头像区域对齐；手机转为贴底抽屉并锁定背景滚动。标题、提醒卡与底部操作之间由克制分隔线组织。
- 颜色与令牌：使用浅紫白玻璃、1 px 紫灰边和柔和阴影；客户为蓝、采集和曝光为橙、关键词及上新为紫、实验为靛蓝、经营建议为绿。没有黑色界面、厚重玻璃或不透明色块。
- 图像与图标：本轮没有需要新增的位图资产；全部操作图标复用现有 Phosphor 体系，没有表情符号、占位图、手写 SVG 或与系统不一致的图标族。
- 文案与内容：副标题明确为“客户消息、商品更新与经营建议”；经营建议显示真实商品、真实规则说明和“看建议”动作，不把本地规则伪装成官方闲鱼排名或远程 AI 结论。
- 响应式与可访问性：480 × 844 下页面无横向溢出，关闭与主操作达到至少 44 px；对话框具有标题关系、焦点闭环、Escape 关闭和焦点返回，`prefers-reduced-motion` 下取消大幅位移。

## 比较与修正历史

### Pass 1：提醒来源审查

- [P1] 旧规则把项目异常、交付和回款混入顶部提醒，与用户确认的客户沟通和商品经营入口不一致。
  - 修复：顶部与首页提醒共用新的客户/商品经营派生模型，并删除项目异常、交付和回款分支。
- [P2] 只读取每日任务汇总会让早上的失败批次覆盖稍后成功的逐商品刷新。
  - 修复：失败提示改读每个本人商品的最新采集状态和当日快照；较新的成功结果会消除旧失败提示。

### Pass 2：丰富版视觉与操作

- [P2] 普通弹层缺少真实事项层级、语义图标、独立动作和手机抽屉体验。
  - 修复：实现浅紫白玻璃表面、独立提醒卡、类别状态色、时间、明确操作、底部双入口，以及窄屏遮罩抽屉。
- [P2] 原交互缺少完整的键盘与焦点收口。
  - 修复：增加外部点击、Escape、焦点返回、焦点闭环、头像菜单互斥和移动端滚动锁定。

### Pass 3：最终同状态比较

- 全视图与浮层聚焦对照确认：浮层位置、宽度、圆角、材质、信息密度、状态胶囊、提醒卡层级与确认稿的视觉意图一致；真实提醒内容不同是有意的数据真实性约束。
- “看建议”进入 `#商品经营`；“查看全部提醒”回到首页同一套提醒卡；“提醒设置”进入既有设置入口。
- 桌面 Escape 关闭后焦点返回铃铛；手机背景滚动锁定、横向溢出为 0；控制台 error / warning 为 0。
- 未发现剩余 P0、P1 或 P2；浮层宽度与确认稿存在少量像素差异，属于适配现有页头宽度的可接受 P3。

## 工程与运行验收

- TypeScript 类型检查、Vite 生产构建、Sites Worker 4/4、商品 `access_verification` 针对性后端测试和 `git diff --check` 均通过。
- 常驻 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，`/api/health` 返回 `status: ok`；继续只使用唯一 `127.0.0.1:8877` 服务。
- 最终继续复用原内置浏览器标签，没有打开第二端口、第二后端或第二标签页。

final result: passed

---

# 2026-08-09 数据统计第 3 案同尺寸最终 QA

## 源真值与浏览器证据

- 用户最终选择的第 3 张效果图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-2f81c02e-6c83-49e5-89db-2a025419b9e7.png`，1487 × 1058 px。
- 最终浏览器实现：`/tmp/new-project-3-statistics-final-wide-2.png`，1487 × 1058 px；CSS 视口为 1488 × 1058，`devicePixelRatio = 0.5`。
- 全视图同屏比较：`/tmp/new-project-3-statistics-comparison-final.png`，2976 × 1058 px；左侧为源真值，右侧为最终实现。
- 顶部指标与经营洞察聚焦比较：`/tmp/new-project-3-statistics-comparison-final-top.png`，2500 × 505 px。
- 项目收益排行与利润结构聚焦比较：`/tmp/new-project-3-statistics-comparison-final-bottom.png`，2500 × 563 px。
- 响应式证据：`/tmp/new-project-3-statistics-1024.png`、`/tmp/new-project-3-statistics-768.png`、`/tmp/new-project-3-statistics-480.png`。
- 本机浏览器在显式视口下会把同一可见画面返回为 2 × 2 平铺位图；所有最终证据只提取左上角完整 CSS 视口瓦片，没有拉伸、改色、补帧或重排页面。

## 必查视觉面

- 字体与排版：沿用全站中文无衬线字体、现有标题字重和紫色英文眉题。宽屏项目名、金额、指标说明与图表标签均达到可读尺寸，长客户名继续单行省略。
- 间距与布局：1488 × 1058 下侧栏为 238 px，主内容依次为 154 px 四指标、198 px 经营洞察横条、约 688/510 px 的排行与利润结构；页面 `scrollWidth = innerWidth = 1488`、`scrollHeight = innerHeight = 1058`，准确在一屏内完成。
- 颜色与令牌：保留白色轻卡、浅紫背景、紫色品牌、绿色收入、橙色支出与红色负利润。效果图把负利润率显示为绿色，正式实现按系统语义使用红色，这是防止误读的有意差异。
- 图像与资产：沿用现有透明鸭子、行星和沙漏位图，以及现有 Phosphor 图标；没有新增占位图、手写 SVG、表情符号或带底色位图。
- 文案与内容：效果图中的示例来源标签和通用客户名没有写入系统。正式实现展示 SQLite 当前项目、客户、收入、支出与工时，并明确标注“按真实支出分类”。
- 交互与无障碍：排行使用语义表格、七个列标题、真实数据行、分页按钮、禁用态、焦点样式和 `aria-label`；利润结构图具有完整读屏摘要。窄屏菜单打开与关闭均已验证。

## 比较历史

### Pass 1：已有紧凑实现对照第 3 张效果图

- [P2] 原紧凑实现的四指标、洞察条和底部面板只占页面上半部，与确认图的纵向节奏和信息可读性不一致。
  - 修复：桌面专属尺寸调整为 154 / 198 / 512 px 三段结构，项目行高度、标题间距和图表绘图区同步放大；主内容现在与源图具有相同顶线、分区和底线。
- [P2] 原利润结构按线性比例显示时，¥230 收入柱过短，无法复现确认图中“低值仍可比较”的视觉意图。
  - 修复：桌面非零柱设置 136 px 可读下限，最高柱保持 288 px；零值继续只有 4 px，不会伪造收入或支出。
- [P2] 原全局侧栏和页头比例比确认图偏宽，导致标题、行星和主内容起点错位。
  - 修复：只在数据统计宽屏页使用 238 px 侧栏、确认图对应的导航节奏、搜索框和资料按钮宽度；其他页面不受影响。

### Pass 2：响应式与交互复验

- [P1] 首次 768 px 截图中，移动到页头下方的搜索框与第一行指标重叠。
  - 修复：`max-width: 820px` 下为统计页预留 55 px 搜索区；复验中搜索框底部为 134 px、指标顶部为 143 px，不再覆盖。
- 1024 × 768 保留两列指标与双栏下部；768 × 1024 保留两列指标并把排行和图表改为单列；浏览器最窄可用视口为 480 × 844，进入两列紧凑指标和单列内容。三个视口均无页面横向溢出。
- 窄屏“打开导航 / 关闭导航”状态正确；分页在当前只有一页时准确禁用；浏览器控制台 error / warning 为 0。

### Pass 3：最终同图复验

- 全视图和两个聚焦比较确认侧栏宽度、页头、四指标、洞察与成本横条、排行卡片、分页基线、四根利润柱和页面底线与第 3 张效果图一致。
- 剩余差异仅来自真实数据映射、负值语义色和现有品牌资产透明留白，均为产品约束下的预期结果；未发现剩余 P0、P1 或 P2。
- P3 非阻塞说明：本机浏览器最窄 CSS 视口被钳制为 480 px，无法直接保存 390 px 截图；同一 `max-width: 480px` 规则已在 480 × 844 验证，且代码在 360 px 以下会把四指标改为单列。

## 工程与运行

- TypeScript 类型检查通过；Vite 生产构建通过并生成 `dist/client/index.html`、`dist/server/index.js` 与 `dist/.openai/hosting.json`；Sites Worker 4/4 通过；`git diff --check` 通过。
- 最终页面继续使用 `http://127.0.0.1:8877/#数据统计`，没有启动第二端口、第二后端或第二标签页。
- 本轮只修改前端派生展示和持久设计约束，没有写入、修改或删除 SQLite 经营数据。

final result: passed

---

# 2026-08-09 数据统计紧凑首屏 Design QA

## 源真值、实现与归一化

- 用户确认的第 3 张设计预览：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-2f81c02e-6c83-49e5-89db-2a025419b9e7.png`，1487 × 1058 px。
- 修改前真实页面：`/tmp/statistics-compact-audit-2026-08-09/02-current-viewport.jpg`，2530 × 1423 px；用于确认超长排行行与异常高利润柱的真实基线。
- 最终桌面实现：`/tmp/statistics-compact-qa-2026-08-09/18-verified-desktop-1440x1024.png`，1440 × 1024 px，CSS 视口 1440 × 1024，浏览器 `devicePixelRatio = 0.5`。
- 全视图同屏比较：`/tmp/statistics-compact-qa-2026-08-09/22-reference-verified-comparison.png`，2904 × 1024 px。
- 下方排行与利润结构聚焦比较：`/tmp/statistics-compact-qa-2026-08-09/23-focused-lower-comparison.png`，2384 × 460 px。
- 响应式证据：`19-verified-1024x768.png`、`20-verified-768x1024.png`、`21-verified-480x844.png`，均位于 `/tmp/statistics-compact-qa-2026-08-09/`。
- 源图长宽比与 1440 × 1024 的差值小于 0.1%；比较时只等比级别归一到 1440 × 1024，没有裁掉源图内容或改色。浏览器原始截图因本机 0.5 像素比返回 2 × 2 平铺位图，最终证据只提取左上角完整 CSS 视口瓦片，没有缩放或重排实现页面。
- 页面状态为 SQLite 修订 23：2 个项目、2 位客户、4 条支出、1 个付款节点和3项任务。显示内容均来自真实快照，没有添加预览图中的演示客户、收入来源或虚构数据。

## 必查视觉面

- 字体与排版：沿用当前系统中文无衬线字体栈、标题字重与紫色英文眉题。统计页正文提升到约 10–13 px，项目名与金额保持 11–13 px，不再使用修改前难以阅读的 7–8 px 级信息密度；真实长客户名使用单行省略，不破坏列宽。
- 间距与布局：桌面依次为 112 px 四项指标、158 px 横向洞察条、约 58/42 的排行与利润结构。统计主体高度 718 px，1440 × 1024 首屏完整显示核心信息；项目行只在排行卡内延伸，底部两卡拥有统一顶线与底线。
- 颜色与视觉令牌：继续使用全站浅紫背景、白色轻卡面、紫色品牌操作、绿色收入和利润、橙色支出与红色负利润；没有黑色区块、厚玻璃、强阴影或新的材质体系。
- 图像与资产：本轮没有新增图片、占位图、手写 SVG、CSS 插画或表情符号。页头行星、侧栏装饰与现有透明位图保持原样；功能图标继续使用现有 Phosphor 图标库，尺寸和底色与系统一致。
- 文案与内容：保留“经营洞察、利润率、成本结构、项目收益排行、月度与年度利润结构”信息层级。预览中的假“收入来源”和通用“客户名称”没有进入正式实现，改为真实项目类型与真实客户；成本说明明确为“按真实支出分类”。
- 图标与交互：分页按钮保留按钮语义、禁用态、`aria-label` 与 `focus-visible`；当前只有一页，因此上一页和下一页均按真实状态禁用。排行容器使用 `role=table`、7 个列标题和 2 个真实数据行。
- 无障碍与动效：负利润不只依赖颜色，还保留带符号数值；利润结构提供完整 `aria-label`。窄屏结构仍按“指标 → 洞察 → 排行 → 图表”阅读，`prefers-reduced-motion` 下取消页面进入和进度位移动画。

## 比较历史

### Pass 1：修改前页面与确认预览

- [P1] 修改前项目排行主面板约 1925 px 宽，两个项目被拉成长横线，项目、收入、成本和工时之间缺少可扫描的局部分组。
  - 修复：改为最大 5 项分页的局部语义表格，桌面展示 7 列，平板改为双层行，窄屏改为可读卡片网格；进度条只停留在项目单元格中。
- [P1] 修改前支出柱按“支出 / 收入 × 150”放大，当前 1072 / 230 会生成约 699 px 高度，把利润结构卡拉到约 858 px。
  - 修复：四项收入与支出统一按全局最大值缩放，最高柱固定为 210 px；最终四柱高度为 45、210、45、210 px，图表卡稳定为 396 px。
- [P2] 修改前洞察和成本结构位于窄右栏，主体纵向层级失衡，1440 级视口无法同时看完洞察、排行和结构。
  - 修复：把洞察、利润率和四类成本合并为 158 px 横向摘要条，下方采用约 58/42 双栏，核心信息在 1440 × 1024 同屏完成。

### Pass 2：浏览器实现复验

- 全视图与聚焦对照确认卡片顺序、四指标语义、洞察分区、排行字段和四柱结构与第 3 张预览一致；正式页面因真实系统侧栏更宽、且不使用演示来源字段而更紧凑，属于数据和既有外壳约束下的有意差异。
- 1024 × 768 保留洞察摘要与 58/42 双栏；768 × 1024 和 480 × 844 改为单列下方内容。四个视口的页面横向溢出均为 0。
- [P2] 首次响应式截图中，全局“立即记账”浮层在 1024 与 768 宽度遮挡利润柱或图表标题。
  - 修复：统计页与现有项目驾驶舱、商品经营页保持一致，隐藏该页面上的全局浮层；移动端仍可通过顶部菜单进入侧栏“立即记账”，最终截图不再遮挡统计内容。

### Pass 3：最终收口

- 最终 1440、1024、768 和 480 截图再次从最新生产构建捕获；利润柱上限、表格语义、真实行数、无横向溢出和响应式结构均保持正确。
- 控制台 error / warning 为 0；未发现剩余 P0、P1 或 P2。没有需要阻塞交付的 P3 项。

## 工程、运行与数据边界

- TypeScript 类型检查、`git diff --check`、Vite 生产构建和 Sites Worker 4/4 均通过。生产构建仅保留已有的大包体积提示，不影响本轮页面运行或功能正确性。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 最终受控重启到 PID 91548；`/api/health` 返回 `status: ok`，只有一个进程监听 `127.0.0.1:8877`。
- 最终精确地址为 `http://127.0.0.1:8877/?build=20260809-statistics-compact-v3#数据统计`；复用同一浏览器标签，没有启动第二端口或第二后端。
- 本轮只读取真实经营快照并修改前端派生展示；SQLite 修订仍为 23，没有新增、修改或删除项目、客户、任务、收支或付款记录。

final result: passed

---

# 2026-08-09 项目卡原位 Z 轴抽出 Design QA

## 确认范围

- 本轮采用用户确认的方案 B：项目卡首次点击后保持原槽位 X 坐标不变，只沿 Z 轴向观察者方向抽出约 150px；不再通过悬停、点击或重排把卡片横向轮播到舞台中央。
- 默认状态没有项目卡处于抽出态；悬停只增强边缘高光。时间线、方向键、Home、End、拖动和滚轮仍可选择项目，但不会触发抽出。
- 抽出后才显示“进入项目 / 确认到账 / 记录异常”操作；窄屏和减少动态效果模式保留平面可读降级。

## 视觉证据

- 参考图裁切：`/tmp/project-card-extraction-qa-2026-08-09/reference-deck-focus.png`。
- 默认状态全页：`/tmp/project-card-extraction-qa-2026-08-09/01-default-full.png`。
- 默认状态舞台：`/tmp/project-card-extraction-qa-2026-08-09/02-default-scene.png`。
- 点击抽出全页：`/tmp/project-card-extraction-qa-2026-08-09/03-clicked-full.png`。
- 点击抽出舞台：`/tmp/project-card-extraction-qa-2026-08-09/04-clicked-scene.png`。
- 同屏对照：`/tmp/project-card-extraction-qa-2026-08-09/08-reference-default-clicked-comparison.png`。
- 响应式证据：`05-responsive-css-1024x768.png`、`06-responsive-css-768x1024.png`、`07-responsive-css-480x844.png`，均位于同一证据目录。

## 交互与空间验证

- 默认卡 transform 的平移量为 `X=-146px, Y=6px, Z=-8px`；点击后为 `X=-146px, Y=-16px, Z=142px`。X 完全不变，Z 精确增加 150px，证明是原位抽出而不是滑到中央。
- 悬停 520ms 前后 transform 完全一致；点击才设置 `data-extracted=true` 并开放操作区。点击时间线后抽出状态清除，卡片恢复原槽位。
- 只绘制选中项附近最多五张卡片；抽出时其他卡片不补位、不重排，只轻微降低透明度与饱和度，保留卡槽关系。
- 抽出卡轻微转正并缩放至约 1.045，同时增加局部紫色光场和独立地面软影；卡面仍是单层 1px 细边的浅色薄玻璃，没有厚侧壁、双边框、黑色底板或不透明紫色填充。
- 点击后的屏幕中心横向变化仅约 1.83px，来自透视投影，不属于横向轮播。

## 响应式、无障碍与运行验收

- 1024×768 保留弱化 3D 与原位抽出；768×1024 使用容器内横向卡片；480×844 使用单列平面卡片并清除 3D transform。三种状态页面横向溢出均为 0。
- 项目卡保留按钮语义、键盘激活、`aria-current` 与焦点样式；抽出前的操作区为 `aria-hidden=true`，抽出后才进入可见和可操作状态。
- `prefers-reduced-motion` 下取消大幅透视位移；粗指针和窄屏不启用持续视差。
- TypeScript 类型检查、Vite 生产构建、Sites Worker 4/4 和 `git diff --check` 均通过；浏览器控制台 error / warning 为 0。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后继续只监听 `127.0.0.1:8877`，`/api/health` 返回 `status: ok`，未启动第二端口、第二后端或第二标签页。
- 本轮未修改 SQLite、LocalStorage 或经营数据，未提交、推送或部署。

final result: passed

---

# 2026-08-09 项目轨道空卡位 Design QA

## 源真值、实现与归一化

- 页面基线：`/tmp/project-placeholder-preview-2026-08-09/01-current-page.jpg`，1220 × 1500 px；用于确认除中央轨道外的真实页面结构、排版、颜色、指标、Inspector 与时间线必须保持不变。
- 已确认的材质与交互预览：`/tmp/project-card-hover-preview-2026-08-09/05-preview-hover-centered.png` 与 `/tmp/project-card-hover-preview-2026-08-09/06-preview-click-locked.png`；沿用薄玻璃、侧卡后退、悬停抽出和正面聚焦语言。
- 最终默认状态：`/tmp/project-placeholder-implementation-2026-08-09/09-final-cropped-1220x1500.png`，1220 × 1500 px；接单项目为 1 张真实卡加 2 张空卡。
- 最终悬停状态：`/tmp/project-placeholder-implementation-2026-08-09/12-hover-cropped-1410x900.png`，1410 × 900 px；左侧空卡抽出到中央并完整显示新建入口。
- 最终空分类状态：`/tmp/project-placeholder-implementation-2026-08-09/13-personal-empty-cropped-1410x900.png`，1410 × 900 px；个人项目为 0 时显示 3 张明确的空卡。
- 全视图同屏比较：`/tmp/project-placeholder-implementation-2026-08-09/10-before-after-1220x1500.png`，2464 × 1500 px。
- 中央轨道聚焦比较：`/tmp/project-placeholder-implementation-2026-08-09/11-stage-before-after.png`，964 × 525 px。
- 浏览器最终 CSS 视口为 1220 × 1500，`devicePixelRatio = 0.5`。截图后端把同一可见内容平铺成 2440 × 3000；最终证据只提取左上角完整 1220 × 1500 瓦片，没有缩放、改色或重排。响应式几何检查分别使用 1024 × 768、768 × 1024 和 480 × 844 CSS 视口。
- 状态：默认“接单项目 → 当前合作”，真实 SQLite 数据为 1 个当前项目；空卡完全由前端派生，不是项目记录。

## 必查视觉面

- 字体与排版：真实项目卡的项目名称、状态、任务、日期和财务层级保持不变；空卡只显示分类、`EMPTY SLOT`、`等待新项目`、简短说明和“点击新建”，没有虚构名称、客户、金额、任务或进度。
- 间距与布局：1 个真实项目时真实卡继续位于中央，两个空位均匀退到左右后方；默认仅露出必要识别信息，悬停后空卡以现有 360 ms 轨道动效抽到中央并完整可读。其他页面区域与基线位置一致。
- 颜色与视觉令牌：空卡复用浅紫白半透明渐变、单条 1 px 紫灰边、14 px 模糊和柔和阴影；没有黑色背景、双边框、厚侧壁、底座或实心不透明卡面。
- 图像与资产：没有新增位图、占位图片、手写 SVG 或表情符号；加号与箭头继续使用现有 Phosphor 图标。空位本身是可操作的产品 UI，不作为装饰素材或业务卡伪装。
- 文案与内容：轨道标题明确显示“1 个真实项目 · 2 个待启用卡位”，控制区显示“1 / 1 个项目 · 2 个空位”；0 项目时为 3 个空位。指标、右侧 Inspector 和时间线仍只读取真实项目。
- 图标与操作：空卡整卡为按钮语义，焦点轮廓沿用项目工作区品牌色；点击或键盘激活只打开当前分类的既有新建项目弹层，不提供会误写数据的独立操作。

## 交互、数据边界与响应式

- 接单项目实际验证为 1 张真实卡加 2 张空卡；个人项目实际验证为 0 张真实卡加 3 张空卡。
- 侧空卡悬停前为后退角度，稳定悬停后获得 `hover-preview` 并抽到中央；边界框从约 253 × 270 变为约 328 × 339，正面信息和按钮完整可见。
- 点击空卡打开“新建项目”弹层，接单分类保持预选；随后关闭弹层，没有点击“保存记录”。个人空卡打开时预选个人分类。
- 切换“已完成”等非当前筛选后空卡数量为 0，并恢复原有无结果状态；输入无结果搜索词时同样不显示空卡，清空后恢复。
- 空卡不进入上一项/下一项的真实项目计数，不更新正式选中项目、Inspector 或时间线，也不参与项目数、进度、合同额和回款指标。
- 1024 × 768 保留三卡弱透视；768 × 1024 改为容器内横向卡片；480 × 844 改为 374 px 宽的单列卡片。三个视口的页面横向溢出均为 0。
- 代码派生规则覆盖 0/1/2/3+：分别补 3/2/1/0 张空卡；新建真实项目后无需迁移或写入占位记录即可自动减少第一张空卡。
- 最终账本仍为修订 23、2 个项目、3 项任务、1 个付款节点，数据库 `PRAGMA quick_check` 返回 `ok`；本轮没有新增、修改或删除经营记录。

## 比较历史

### Pass 1：基线与最终实现

- 全视图比较确认页面外壳、指标、阶段筛选、真实项目卡、Inspector 和时间线没有视觉漂移；唯一结构变化位于中央轨道。
- 聚焦比较确认真实卡仍保持中心焦点，左右空卡提供可见的空间层次且没有压住搜索、排序、控制区或右侧 Inspector。
- 默认状态中空卡正文被中央真实卡适度遮挡是扇形景深的预期结果；悬停后会转正并完整显示，因此不构成可用性问题。
- 未发现剩余 P0、P1 或 P2；没有为提升视觉密度伪造业务数据。

## 工程与运行验收

- TypeScript 类型检查通过；Vite 生产构建通过并生成 Sites 所需产物；Sites Worker 4/4 通过；`git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启到 PID 86204，`/api/health` 返回 `status: ok`，端口 8877 只有一个监听进程。
- 最终页面控制台 error / warning 为 0，文档横向溢出为 0；继续复用原有 8877 标签页，没有打开第二个端口或第二个标签页。

final result: passed

---

# 2026-08-09 市场规则 V2 与两态预览最终 Design QA

## 对照目标与证据

- 系统推荐源真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-50de0a2c-742b-44a1-ba40-93b031519ba1.png`，1672 × 941 px。
- 自定义关键词源真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-55b19f1e-3516-4af3-a4d7-51cf395b57c6.png`，1672 × 941 px。
- 最终系统推荐状态：`/tmp/xianyu-market-v2-qa-2026-08-09/08-final-system-recommendation.jpg`，1339 × 1500 px。
- 最终自定义关键词状态：`/tmp/xianyu-market-v2-qa-2026-08-09/09-final-custom-keyword.jpg`，1339 × 1500 px。
- 系统推荐全视图同屏对照：`/tmp/xianyu-market-v2-qa-2026-08-09/10-final-system-full-comparison.jpg`，3368 × 993 px。
- 自定义关键词全视图同屏对照：`/tmp/xianyu-market-v2-qa-2026-08-09/11-final-custom-full-comparison.jpg`，3368 × 993 px。
- 系统推荐聚焦对照：`/tmp/xianyu-market-v2-qa-2026-08-09/12-final-system-market-card-comparison.jpg`，1464 × 702 px。
- 自定义关键词聚焦对照：`/tmp/xianyu-market-v2-qa-2026-08-09/13-final-custom-market-card-comparison.jpg`，1464 × 702 px。
- 浏览器 CSS 视口为 1340 × 1500、`devicePixelRatio = 1`；截图宽度的 1 px 差值来自浏览器可见内容区。
- 全视图比较把最终截图顶部按 1672:941 比例裁成 1339 × 754，再等比归一化为 1672 × 941；没有改色或重排页面内容。聚焦比较分别截取两侧真实“市场参考”卡片并以 `contain` 放入相同画布，没有拉伸。

## 最终状态

- 页面使用真实 SQLite 数据：16 件本人商品、4 件已排除商品、0 个市场样本；没有为了接近预览写入示例结果。
- 上新结论为 `observe`，页面明确显示“继续观察 / 继续积累证据”，而不是在证据不足时强行建议发布。
- 每日生成 3 个技术实现类候选关键词；用户有明确方向时可切换“我的关键词”，并选择只验证一次或加入常用关键词。
- 上新雷达同时显示建议商品类型、标题结构、公开价格参考、差异化重点、发布时间依据和市场验证状态。
- 商品修改建议同时区分“内部表现 / 高可见市场参考”，并显示具体修改内容、主题匹配、市场差距、价格区间与置信度依据。
- 系统不自动搜索闲鱼，不自动发布、修改、下架或购买曝光；市场参考仍由用户在现有 Edge / Goofish 搜索后人工导入。

## 必查视觉面

- 字体与排版：沿用全站中文无衬线字体栈。第二轮把关键说明、关键词、提醒、置信度和修改依据从过细的 7–9 px 调整为 8.5–11.5 px，标题与正文层级更接近确认预览；长商品名继续受控省略或换行。
- 间距与布局：保持“上新雷达 + 市场参考 + 商品修改实验”的确认结构。运行页面保留现有全局页头和真实数据密度；1340 px 视口下 `scrollWidth === innerWidth === 1340`，无页面横向溢出。
- 颜色与令牌：白色卡面、浅紫背景、紫色主操作、橙色提醒、绿色完成和灰紫次级信息与当前系统一致；没有引入黑色区域或新的材质体系。
- 图像与资产：该功能区不依赖新增位图；现有透明装饰资产与 Phosphor 图标保持不变，没有占位图、表情符号、手写 SVG 或位图文字。
- 文案与内容：推荐明确来自咨询需求、本人商品覆盖、历史参考和交付容量；公开结果只称为“高可见市场参考”，不伪装成闲鱼官方热门，也不复制竞品完整标题。
- 图标与交互：工作区标签、关键词来源、候选词、导入、提醒、证据按钮均有清晰选中、禁用、hover 与 `focus-visible` 状态；按钮和标签使用语义化角色。

## 比较历史

### Pass 1

- [P2] 初版功能结构已经对齐，但市场卡和修改建议内部多处使用 7–9 px 文本，实际运行时比预览更细密，右侧卡片的有效信息显得偏轻。
- 修复：仅调整已确认功能区的文字层级、按钮高度和表格说明密度；未改变布局方向、数据、接口或业务行为。

### Pass 2

- 重新构建、重启唯一常驻服务并重新捕获系统推荐、自定义关键词、全视图和聚焦对照。
- 字体、间距、紫色选中态、橙色提醒、输入焦点、按钮密度和卡片边界均达到确认预览的视觉意图。
- 预览中的示例数量与运行页面的真实 16 件商品、2 个相关咨询不同，属于禁止伪造业务数据的预期差异。
- 运行页面为避免重叠保留了当前系统的完整页头和自然文档流；这是现有产品结构约束，不是未实现的视觉缺陷。
- 未发现剩余 P0、P1 或 P2。右侧卡片在证据为空时保留少量呼吸空间，列为可接受的 P3，不阻塞交付。

## 交互、响应式与运行检查

- 实际点击并验证“系统推荐 / 我的关键词”；输入 `uni-app 页面修改` 后“使用我的关键词更新”变为可用，但未提交，因此没有写入市场样本。
- 实际切换“市场参考”页面并确认 0 样本空状态；实际点击商品“查看证据”，选中商品和证据详情可见。
- “继续积累证据”在 `observe` 状态保持禁用；提醒文案明确“只提醒，不会自动搜索或打开新网站”。
- 最终重新加载期间监听 `pageerror` 与 `console` 事件，均未收到 error 或 warning；关键标签切换后页面仍可操作。
- 当前内置浏览器固定为 1340 × 1500，源真值也是桌面状态；本轮浏览器截图在该真实视口完成。既有 1280、980、720 和 520 px 媒体规则仍保留，分别处理指标、双栏、标签、关键词面板、实验卡和弹层，未新增固定宽度或页面级横向滚动。
- `prefers-reduced-motion` 规则保持原有无位移动画行为，本轮只调整静态文字与控件尺寸。

## 工程与数据验收

- 后端完整测试 136/136 通过；仅有既有 Starlette 弃用警告。
- TypeScript 类型检查通过；Vite 生产构建通过；Sites Worker 4/4 通过；`git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后 PID 更新为 80971，`8877` 只有 1 个监听进程，`/api/health` 返回 `status: ok`。
- `/api/products/intelligence` 返回 `market-v2`、3 个推荐关键词、`recommended_action = observe` 和 0 个市场样本日。
- 正式 SQLite 的 `product_market_samples = 0`、`product_market_sample_results = 0`，`PRAGMA integrity_check` 返回 `ok`。
- 没有启动第二个端口或浏览器标签，没有自动搜索闲鱼，没有提交导入、创建上新计划、创建修改实验、发布、改品或投流。

final result: passed

---

# 2026-08-09 每日关键词、市场参考与上新修改 Design QA

## 对照目标与最终证据

- 系统推荐状态源真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-50de0a2c-742b-44a1-ba40-93b031519ba1.png`，1672 × 941 px。
- 自定义关键词状态源真值：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-55b19f1e-3516-4af3-a4d7-51cf395b57c6.png`，1672 × 941 px。
- 最终系统推荐状态：`/tmp/xianyu-market-reference-design-qa-20260809/final-system-recommendation-1340x1500.png`，1339 × 1500 px；浏览器 CSS 视口为 1340 × 1500、`devicePixelRatio = 1`。
- 最终自定义关键词状态：`/tmp/xianyu-market-reference-design-qa-20260809/final-custom-keyword-1340x1500.png`，1339 × 1500 px。
- 最终导入弹层：`/tmp/xianyu-market-reference-design-qa-20260809/final-import-dialog-1340x1500.png`，1339 × 1500 px。
- 系统推荐全视图同屏对照：`/tmp/xianyu-market-reference-design-qa-20260809/comparison-system-full-final.png`，2698 × 814 px。
- 自定义关键词全视图同屏对照：`/tmp/xianyu-market-reference-design-qa-20260809/comparison-custom-full-final.png`，2698 × 814 px。
- 系统推荐聚焦对照：`/tmp/xianyu-market-reference-design-qa-20260809/comparison-system-focus-final.png`，1320 × 585 px。
- 自定义关键词聚焦对照：`/tmp/xianyu-market-reference-design-qa-20260809/comparison-custom-focus-final.png`，1320 × 585 px。
- 状态：唯一常驻地址 `http://127.0.0.1:8877/#商品经营`，默认内部标签为“上新与修改”，关键词来源默认“系统推荐”。验收只浏览、切换和开关弹层，没有导入市场样本、建立上新计划或创建商品实验。

## 尺寸与归一化

- 源图按原始宽高比缩放为 1339 × 754；最终页面从 1339 × 1500 可见截图顶部提取 1339 × 754，不缩放页面内容，以相同宽度和纵横比完成全视图比较。
- 聚焦比较分别使用源图和最终页面中真实的“市场参考”区域；两侧均使用 `contain` 放入 650 × 525 面板，没有拉伸或改色。
- 两张源图是确认过的桌面设计预览。最终实现保留现有产品全局页头、真实 16 件本人商品以及真实咨询数量，因此全视图中的页头高度和数据密度与预览不同；功能区的信息层级、材质、色彩和交互状态按源图实现，没有为了截图伪造数据。

## 必查视觉面

- 字体与排版：继续使用全站中文无衬线字体栈。上新结论、市场提醒、关键词、置信度、实验建议和按钮层级清晰；真实商品长标题使用受控省略或换行，没有压住操作区。
- 间距与布局：顶部五项经营指标、四个内部标签、上新雷达、市场参考和商品修改实验形成与预览一致的阅读顺序。1340 px 桌面视口无页面横向溢出；市场参考内部在较窄宽度下仍保持清晰分组。
- 颜色与视觉令牌：白色卡面、浅紫背景、紫色主操作、橙色提醒和绿色完成状态沿用现有系统令牌。没有加入黑色工作区、强反射或与全站不一致的材质。
- 图像与资产：本轮核心界面不依赖新增位图素材；装饰、图标和状态图形继续使用现有透明资产与 Phosphor 图标体系，没有占位图、表情符号或手写 SVG 替代。
- 文案与真实内容：推荐词明确说明来源于真实咨询、本人商品覆盖、历史参考和交付容量，不称为“闲鱼官方热门”。自定义词明确区分“仅本次验证”和“加入常用关键词”。导入弹层明确限制公开字段并排除 Cookie、卖家身份、平台 ID、原始页面和 HTML。
- 图标与操作：系统推荐、自定义关键词、导入、提醒、上新计划、实验查看和关闭操作使用同一图标家族，按钮有 hover、focus-visible、disabled 和选中态。

## 交互、数据与安全回归

- 已实际验证“系统推荐 / 我的关键词”双状态切换；自定义输入为空时提交按钮保持禁用，切换本身不写入经营数据。
- 已实际打开导入弹层并检查三步说明、JSON Schema 示例、公开字段边界、说明输入和确认按钮；没有提交任何测试结果。
- 已实际验证“经营总览、曝光分析、上新与修改、市场参考”四个内部标签；原有多商品曝光批次、经营计划和策略功能仍可访问。
- 同一天同一关键词的市场样本由后端唯一约束和覆盖写入实现，不会形成重复趋势点；API Schema 禁止未知字段，结果位置必须唯一。
- 页面交互后控制台新增 error / warning 为 0，页面 `scrollWidth - clientWidth = 0`。
- 当前真实数据库保持 1 个今日关键词计划、0 个市场样本、0 个上新计划、0 个修改实验；`PRAGMA integrity_check` 返回 `ok`。
- 响应式规则在 1280、980、720 和 520 px 分别重排指标、主栏、标签、关键词面板、实验卡和导入弹层；本轮源图只有桌面状态，精确窄屏截图未作为像素源真值。现有 CSS 保持容器内横向浏览、单列弹层和无页面横向溢出约束。

## 比较历史

### Pass 1：预览与最终结构对照

- 源图和实现的核心功能区均采用“上新雷达 + 市场参考 + 商品修改实验”结构；系统推荐和自定义关键词两种状态、提醒横幅、关键词操作以及导入入口位置一致。
- 预览中只显示 2 个示例商品，最终实现展示 16 个真实本人商品；这是禁止伪造业务数据的预期差异，不构成视觉缺陷。
- 最终保留现有全局页头和固定侧栏，避免商品经营成为独立外壳；聚焦对照确认卡片圆角、边框、紫色选中态、橙色提醒和操作密度与预览一致。

### Pass 2：键盘关闭修复

- [P2] 首次交互复验发现导入弹层可点“取消”和右上角关闭，但按 Escape 不会退出。
- 修复：只在市场参考导入弹层的遮罩层补充 Escape 键处理，不修改表单数据、其他弹层或业务流程。
- 复验：打开弹层后在 JSON 输入区按 Escape，`dialogCount` 从 1 变为 0；随后重新打开、点“取消”同样关闭，控制台无 error / warning。

### Pass 3：最终服务与工程收口

- 后端完整测试 132/132 通过；仅保留既有 Starlette 弃用警告。
- TypeScript 类型检查通过；Vite 生产构建和 Sites Worker 4/4 通过，`git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后恢复为单一 8877 监听进程，`/api/health` 返回 `status: ok`。
- 未发现剩余 P0、P1 或 P2。P3 非阻塞说明：当前浏览器可见面板宽度与 1672 px 设计源不同，因此全视图比较按相同宽度和纵横比归一化；聚焦功能区另做无拉伸对照。

## Implementation Checklist

- [x] 每个北京时间自然日生成 3 个技术实现类候选关键词。
- [x] 支持系统推荐与用户自定义关键词，并可选择是否加入常用关键词。
- [x] 北京时间 20:00 未更新提醒、延后 2 小时、今日跳过和有效导入后自动完成。
- [x] 仅导入公开搜索字段，同日同词覆盖而不重复。
- [x] 上新建议、手动上新计划和单变量商品修改实验保持人工控制。
- [x] 两张确认预览状态、导入弹层、四个内部标签和 Escape 键盘关闭均通过。
- [x] 真实数据未被测试污染，唯一 8877 常驻服务恢复健康。

final result: passed

---

# 2026-08-08 多商品曝光经营计划与本地规则 V2.1 Design QA

## 验收范围与真实状态

- 经营方案使用真实 SQLite 数据：16 件本人商品、4 件已排除商品、3 个快照日、0 个真实曝光批次。
- 当前规则阶段为“基线学习”，周预算为 ¥24；未来 7 天安排 3 个多商品曝光日，每批 5 件商品，批次总费用约 ¥5.9，非曝光日用于自然流量或长尾观察。
- 数据库只生成了 1 份当前经营计划与 7 个计划槽位；浏览器验收前后 `product_traffic_batches` 均为 0，没有创建真实批次、费用或闲鱼操作。
- 实施前备份：`data/backups/xianyu_operator-before-exposure-v2-20260808-211014.db`；升级后 `PRAGMA foreign_key_check` 无结果。

## 本地规则与安全边界

- 规则 V2.1 同时使用 24h、7d、28d 滚动窗口，并按快照实际日期间隔计算日均变化；少于 3 个快照日、采集失败或数据陈旧时降低置信度并阻止放大投流。
- 计划同时考虑 72 小时商品冷却、商品修改观察期、交付容量、每周预算、已有/未来批次重叠和今明两天锁定。
- 0–5 个有效批次保持基线学习；6 个起进入受控学习；30 个起使用探索/利用组合。历史效果使用贝叶斯平滑，避免一次咨询把排序推到极端。
- 批次效果以商品 T0、+1h、+6h、+24h、+72h 的累计浏览、想要、收藏和咨询差值评估；套餐总曝光只保存为批次总量，不虚构分摊到单件商品。
- 本地提醒仅提醒投放前和检查点到期；不会请求闲鱼、购买曝光、自动修改商品、自动发布或自动投流。
- 发布时间建议按去重后的首次咨询计算；当前真实依据为近 90 天 11 个首次咨询样本，不再把同一客户的连续追问重复计数。

## 视觉与交互证据

- 最终桌面：`/tmp/xianyu-exposure-v2-qa-2026-08-08/final-desktop-1440x900.jpg`，对应 CSS 视口 1440 × 900、可见内容 1410 × 900。
- 最终移动：`/tmp/xianyu-exposure-v2-qa-2026-08-08/mobile-480x844-final.jpg`，对应 CSS 视口 480 × 844、可见内容 450 × 844。
- 桌面批次弹层：`/tmp/xianyu-exposure-v2-qa-2026-08-08/batch-modal-desktop-1440x900-final.jpg`；显示北京时间、批次总费用、商品多选、隐私/自动化边界和保存操作。
- 浏览器截图后端会把同一可见视口平铺为 2 × 2；上述证据仅机械提取左上方完整瓦片，没有缩放、改色或重新生成页面内容。
- 日期切换已实际验证：切换到 08/09 后焦点卡、5 件组合、约 ¥5.9 和锁定状态同步更新，页面不跳转也不写入经营数据。
- 多选已实际验证：弹层提供 16 件本人商品，默认选中计划中的 5 件；点击商品卡可替换组合，并稳定保持最多 5 件。关闭后真实批次仍为 0。
- 批次创建、开始、完成、取消与检查点写入由后端专项测试覆盖；浏览器真实数据验收只打开、选择、关闭，不点击“保存批次计划”。

## 响应式与无障碍

- 1440 × 900：采集说明、7 天计划焦点卡、规则阶段、批次组合与周预算在同一首屏层级内；文档横向溢出为 0。
- 1024 × 768：计划仍保持焦点/规则双列，7 天日期在组件内部横向浏览；文档横向溢出为 0。
- 768 × 1024：计划焦点转为单列，商品组合保持可读，经营主栏和规则栏依次排列；文档横向溢出为 0。
- 浏览器响应式后端最窄可用 CSS 宽度为 480 px，因此使用 480 × 844 验证 `max-width: 520px` 移动规则：顶部操作、指标和商品选择均为单列，弹层 `scrollWidth === clientWidth`，页面横向溢出为 0。
- 复验发现 1024 与 768 宽度的全局“立即记账”悬浮按钮会遮住经营计划。[P2] 已只在商品经营页隐藏该重复入口；侧栏/移动菜单中的记账入口保留，其他页面行为不变。
- 商品选择使用原生 checkbox 与完整 label，日期使用按钮和 `aria-pressed`，弹层关闭、取消及保存按钮均可由语义定位；`prefers-reduced-motion` 下取消 Hover 位移和旋转动画。

## 工程与运行验收

- 后端完整测试 122/122 通过；其中商品经营专项覆盖窗口、归属、计划、预算、冷却、批次幂等、检查点和提醒。
- TypeScript 类型检查通过。
- Vite 生产构建通过，生成 `dist/client/index.html`、`dist/server/index.js` 和 `dist/.openai/hosting.json`。
- Sites Worker 4/4 通过；`git diff --check` 通过。
- 最终页面无 console error / warning，图片加载失败为 0；1440、1024、768 和 480 四个断点均无页面横向溢出。
- 唯一常驻服务仍为 `http://127.0.0.1:8877`；LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启后恢复，`/api/health` 返回 `status: ok`，且只有一个 8877 监听进程。

final result: passed

---

# 2026-08-08 项目异常结算与净回款 Design QA

## 验收范围

- 新增客户不满意、退款、项目取消、客户拒付、终止合作、需求范围争议和其他异常的统一记录入口。
- 统一首页、收入页、项目驾驶舱、项目详情、客户累计消费、目标页和支出页的净到账口径。
- 明确区分累计入账、实际退款、确认核销、可收余额、净到账、净回款率和结算完成度。
- 所有写入使用 SQLite 修订号与请求 ID；异常记录不自动改变项目交付状态，退款不重复生成支出。

## 隔离数据验收

- 使用临时数据库 `/tmp/xianyu-settlement-qa.T2p19Y/qa.db` 和临时 `127.0.0.1:8994` 完成写流程；真实 `8877` 数据未被写入。
- 仅记录风险：需求范围争议写入原因和备注，净到账与可收余额不变。
- 全额核销：待收 ¥4,000 节点变为“已核销”，可收余额同步减少 ¥4,000。
- 部分核销：无付款计划项目核销 ¥2,500，可收余额从 ¥10,000 调整为 ¥7,500，并保留原项目状态。
- 退款并核销剩余款：累计入账 ¥3,000、实际退款 ¥1,000、剩余尾款核销 ¥3,000；项目净到账为 ¥2,000，可收余额为 ¥0，结算完成度为 100%。
- 最终隔离汇总为净到账 ¥2,000、可收余额 ¥7,500、退款 ¥1,000、核销 ¥9,500；三个项目仍分别保持 `in_progress`、`delivered`、`delivered`。
- 并发冲突：在弹层打开后把后端修订从 5 更新为 6，再提交会显示“经营数据已在其他浏览器更新”，保留弹层并提供“刷新最新数据”，没有静默覆盖。

## 视觉、响应式与无障碍

- 1440 × 900、1024 × 768、768 × 1024 和浏览器可用最窄 480 × 844 均无文档横向溢出。
- 桌面保持四项财务指标和主内容/提醒侧栏；平板切为两列指标与单列工作区；窄屏操作按钮、财务拆分和异常历史自动折叠。
- 异常界面继续使用白色圆角、浅紫品牌色与橙色风险提示，没有引入深色工作区。
- 异常弹层在 480 × 844 下宽 443 px、内部 `scrollWidth === clientWidth`；三项影响预览切为单列，金额字段和原因字段保持可读。
- 弹层打开后原因字段自动获得焦点，Escape 可以关闭；修订冲突错误使用 `role=alert`，刷新与关闭按钮均可键盘操作。
- 首页“累计净收入”、净收入趋势、当日退款净额、当前项目异常类型和智能提醒均读取同一财务派生模型。
- 浏览器控制台新增 error / warning 为 0。

## 工程验收

- 后端完整测试 106/106 通过，其中统一账本套件覆盖仅风险、全额/部分核销、退款、退款与核销组合、超额拒绝、个人项目拒绝、请求幂等、修订冲突、退款后再次到账上限和数据库约束。
- TypeScript 类型检查通过。
- Vite 生产构建通过，并生成 `dist/client/index.html`、`dist/server/index.js` 与 `dist/.openai/hosting.json`。
- Sites Worker 4/4 通过，`git diff --check` 通过。

final result: passed

---

# 2026-08-08 项目驾驶舱中心扇形空间场景 Design QA

## 对照目标与证据

- 设计源真值：`/tmp/project-cockpit-reference-latest-landscape.png`，2400 × 1080 px。该图只作为“中心扇形、轻薄玻璃、前后景深与选中卡抽出”的空间和材质参考；按用户确认，不复刻其黑色系统外壳、独立侧栏、手机状态栏或绿色主题。
- 修改前证据：`qa/project-cockpit-before-20260808.png`，1188 × 1500 px，用于确认原来的普通项目网格与右侧洞察结构。
- 最终实现证据：`qa/project-cockpit-final-1440x900.jpg`，1410 × 900 px；浏览器 CSS 视口为 1440 × 900，30 px 差值来自浏览器可见内容宽度。
- 任务级轻玻璃证据：`qa/task-flow-light-final-1440x900.jpg`，1410 × 900 px。
- 全视图同屏对照：`qa/project-cockpit-comparison-full-20260808.jpg`。参考图与最终实现被放在同一个比较画布的等宽面板中，参考图按比例居中，不拉伸。
- 中央轨道聚焦对照：`qa/project-cockpit-comparison-focus-20260808.jpg`。该图用于检查卡片角度、前后层级、玻璃边缘、中心焦点和文字可读性。
- 状态：`#项目管理`，默认“接单项目”，按当前 SQLite 真实数据显示 2 个项目，选中“去除豆包水印”；没有创建装饰性假项目。

## 尺寸与密度归一化

- 浏览器响应式能力在本机后端请求 720 × 450 后暴露为 `innerWidth: 1440`、`innerHeight: 900`、`devicePixelRatio: 0.5`。
- 浏览器原始截图 `qa/project-cockpit-final-1440x900@2x.png` 为 2820 × 1800 px，并将同一 1410 × 900 可见内容平铺为 2 × 2；这是浏览器截图后端现象，不是页面 DOM 重复。
- 最终证据从原始截图提取一个 1410 × 900 完整可见瓦片，未缩放、未改变颜色，因而与 CSS 可见内容保持 1:1。
- 参考图是独立宽屏概念图，不能与本产品完整外壳形成严格像素级同视口匹配；全视图比较用于判断信息架构，聚焦比较用于判断用户明确指定的中心空间场景。

## Findings

- 未发现剩余 P0、P1 或 P2 问题。
- [P3] 当前真实分类只有 2 个项目，因此最终静态截图只能看到 1 张选中卡和 1 张后退卡，扇形密度低于参考图。该差异是“不生成假项目卡”的数据约束，不影响 3 个以上项目时前后各两张的正式布局，也不应通过伪造数据修正。

## 必查视觉面

- 字体与排版：沿用全站现有中文无衬线栈、字号、字重和行高。选中项目名称、状态、金额、任务和日期在半透明阅读层内清晰；侧卡仍可辨识项目名称，没有使用参考图中过窄、过暗的小字。长名称使用受控换行或省略，不压住操作按钮。
- 间距与布局节奏：顶部分类和四项指标、左侧阶段、中间轨道、右侧 Inspector、底部时间线形成稳定三列层级。1440 × 900 首屏可完整看到驾驶舱主任务，页面横向溢出为 0；选中卡没有遮住 Inspector 或筛选控件。
- 颜色与视觉令牌：保留现有浅色 SaaS 的白、浅紫、紫蓝品牌色，橙色只用于待回款风险。卡面为单层半透明白紫渐变、1 px 紫灰边、轻 blur 和柔和光晕；没有黑色驾驶舱、双边框、厚侧壁、玻璃底座或实心紫色选中面。
- 图像与资产质量：中央空间由 DOM、CSS 透视、渐变光场和低对比点阵组成，没有新增位图背景、WebGL 或占位图；参考图本身没有需要迁入的独立产品图片资产。全站既有透明装饰素材未被本轮改坏，项目与任务图标继续使用既有 Phosphor 图标体系。
- 文案与真实内容：项目名称、客户/类型、状态、任务、交付日、合同额、已收和未收均来自现有数据。空分类展示真实空状态；界面没有参考图的虚构任务、人员或数值。
- 图标与操作可见性：分类、筛选、排序、上一项/下一项、进入项目、新建项目和 Inspector 操作使用同一图标家族，按钮对齐一致；“首次点击选择”和“进入项目”是两个视觉上分离的动作。

## 交互、响应式与无障碍

- 已实际验证：未选中项目卡点击后只抽出并更新 Inspector，URL 不变；“进入项目”进入 `#项目管理/<projectId>/immersive`。
- 已实际验证：上一项/下一项、Home、End、方向键、水平拖动和滚轮切换；轨道首尾恢复页面滚动，不产生自动跳底。
- 已实际验证：分类切换、阶段筛选、搜索、排序和空个人项目；分类切换不写入 SQLite 或 LocalStorage。
- 任务轨道已实际验证卡片点击和前后切换；选中任务前移、相邻任务保持约 9° 的可读轻透视，没有深色或不透明紫色卡面。
- 响应式：1024 × 768 为阶段与轨道两列且 Inspector 下移；768 × 1024 为平面横向卡；480 × 844 触发 `max-width: 560px` 单列模式并取消 3D。三个尺寸的文档横向溢出均为 0。
- 可访问性：项目卡使用按钮语义、`aria-current`、明确 `focus-visible`；粗指针、窄屏和 `prefers-reduced-motion` 关闭持续视差和大幅位移。

## 比较历史

### Pass 1：结构与主题

- [P1] 修改前为普通项目卡网格，中心没有明确焦点和空间纵深。
  - 修复：`#项目管理` 直接改为驾驶舱，新增中心扇形轨道、左侧阶段、右侧 Inspector 和底部时间线。
- [P1] 项目详情任务流仍混有深色基础样式和实心选中卡，与确认的浅色全站方向冲突。
  - 修复：合并为正式浅色样式，并统一为薄玻璃材质；项目层空间最强、任务层角度和景深减半。

### Pass 2：点击与可读性

- [P2] 3D 父平面会吞掉后退卡片的指针命中，视觉上能看到但无法可靠点击。
  - 修复：轨道父层设为 `pointer-events: none`，可见项目卡恢复 `pointer-events: auto`；随后实际点击侧卡确认会抽出并更新 Inspector。
- [P2] 任务相邻卡过于侧向且露出宽度不足，项目名称/任务名称难以辨认。
  - 修复：项目卡保持面向中心但选中卡只约 4°，任务相邻卡收敛到约 9°，任务横向距离调整为 92 px。
- [P2] 首页只筛选 `in_progress`，导致待开始和已交付待回款项目被错误显示为空。
  - 修复：首页改为“当前项目”，纳入待开始、进行中、逾期及已交付待回款，并让项目行直达沉浸任务流。

### Pass 3：最终同屏对照

- 全视图与聚焦对照确认中心焦点、卡面抽出、后退景深、细边玻璃和浅色产品一致性均已建立。
- 当前 2 项真实数据限制了静态扇形数量，但不存在需要用假卡补齐的 P0/P1/P2 问题。
- 项目列表、项目详情、首页入口、桌面/平板/窄屏及键盘焦点均通过最终回归。

### Pass 4：常驻服务与控制台

- [P2] 常驻服务重启后的首次快速 Hash 导航会让被跳过的原生 View Transition `ready` Promise 产生未处理的 `InvalidStateError`，虽然页面和数据没有异常，但控制台不干净。
  - 修复：`runPageTransition` 同时观察 `ready`、`updateCallbackDone` 和 `finished`，将快速导航导致的预期动画取消安全收口。
  - 结果：在同一 8877 标签中执行“重新加载 → 首页概览 → 项目管理”的快速连续切换后，新增 error / warning 为 0，最终 URL 保持精确的 `#项目管理`。

## Implementation Checklist

- [x] 项目管理默认进入浅色驾驶舱。
- [x] 个人 / 接单分类、筛选、搜索和排序驱动同一套真实数据。
- [x] 中央项目卡支持选择抽出与独立进入项目动作。
- [x] 任务轨道复用轻玻璃材质并降低动态强度。
- [x] 首页当前项目纳入待开始、逾期和已交付待回款。
- [x] 响应式、键盘、滚轮边界和减少动态效果通过。
- [x] 同屏全视图和中央轨道聚焦比较无 P0/P1/P2。
- [x] LaunchAgent 受控重启恢复，快速导航后控制台无新增错误或警告。

final result: passed

---

# 2026-08-08 轻薄玻璃收口复验

## 对照证据与归一化

- 设计源真值：`/tmp/xianyu-cockpit-qa-2026-08-08/reference-landscape.png`，2400 × 1080 px；只提取中心扇形、前后景深、薄玻璃和选中卡抽出，不复刻其黑色外壳。
- 最终桌面：`/tmp/xianyu-cockpit-qa-2026-08-08/14-final-desktop.jpg`，1410 × 900 px；对应浏览器 CSS 视口 1440 × 900，30 px 差值来自浏览器可见内容区。
- 最终移动：`/tmp/xianyu-cockpit-qa-2026-08-08/13-final-mobile.jpg`，450 × 844 px；对应浏览器 CSS 视口 480 × 844，同样按可见内容区 1:1 提取，没有缩放。
- 任务轨道：`/tmp/xianyu-cockpit-qa-2026-08-08/06-task-flow-top.jpg`，1410 × 900 px。
- 全视图同屏对照：`/tmp/xianyu-cockpit-qa-2026-08-08/15-reference-vs-final.jpg`，2822 × 900 px；参考与最终桌面按同高面板并排，不拉伸。
- 中央焦点同屏对照：`/tmp/xianyu-cockpit-qa-2026-08-08/16-focus-reference-vs-final.jpg`，1602 × 520 px；用于判断卡面角度、玻璃边缘、名称可读性和抽出层级。
- 当前数据状态：接单项目 2 个，使用真实 SQLite 数据；没有为增加扇形密度伪造项目。

## 必查视觉面

- 字体与排版：沿用全站中文无衬线字体体系；正面项目名称、状态、任务、交付日和财务信息清晰，侧卡仍可辨认名称。
- 间距与布局：桌面保持左侧阶段、中间场景、右侧 Inspector 和底部时间线；移动端转为单列，页面横向溢出为 0。
- 颜色与令牌：卡面使用低不透明白紫渐变、单条 1 px 紫灰边、14 px 背景模糊和柔和紫蓝光晕；没有黑色工作区、双边框、厚侧壁或玻璃底座。
- 图像与资产：场景由现有 DOM、CSS 透视、径向光场和点阵构成，没有新增位图背景、WebGL 或占位素材；Phosphor 图标体系保持一致。
- 文案与数据：项目卡、Inspector、阶段和时间线均读取真实项目、任务与回款派生数据；个人项目空状态不制造示例内容。

## 比较历史

### Pass 1

- [P2] 480 × 844 下，全局悬浮记账按钮压住项目驾驶舱的移动卡片和底部操作区。
- 修复：只在项目驾驶舱内隐藏这个重复的全局悬浮入口；移动侧栏中的“立即记账”仍保留，功能没有丢失。

### Pass 2

- 修复后桌面、移动和任务轨道重新截图，并与参考图完成全视图及中央焦点同屏比较。
- 未发现剩余 P0、P1 或 P2；当前仅有 2 个真实项目造成静态扇形数量少于参考图，属于真实数据约束，不应通过假卡片修正。
- 滚轮边界复验：第一项向下滚动会切到第二项且 `scrollY` 保持 90；在末项再次向下滚动后选中项保持不变、页面 `scrollY` 从 90 变为 152，确认首尾恢复正常页面滚动。
- 页面控制台新增 error / warning 为 0；图片加载失败为 0。

## Implementation Checklist

- [x] 中心扇形、轻薄玻璃、选择抽出和独立进入项目操作完成。
- [x] 任务轨道使用同材质并降低透视与位移强度。
- [x] 1440 × 900、1024 × 768、768 × 1024 和 480 × 844 响应式通过。
- [x] 点击、键盘、拖动、滚轮首尾、分类切换和空状态通过。
- [x] 移动端无遮挡、无横向页面滚动，减少动态效果保持可读。

final result: passed

---

# 2026-08-09 项目卡悬停旋转与点击锁定 Design QA

## 源真值、实现与归一化

- 悬停居中源真值：`/tmp/project-card-hover-preview-2026-08-09/05-preview-hover-centered.png`，1738 × 454 px。
- 点击锁定源真值：`/tmp/project-card-hover-preview-2026-08-09/06-preview-click-locked.png`，1738 × 454 px。
- 四状态分镜：`/tmp/project-card-hover-preview-2026-08-09/07-hover-rotation-storyboard.png`，2370 × 942 px。
- 浏览器悬停居中：`/tmp/project-hover-implementation-2026-08-09/07-qa-hover-centered.jpg`，1220 × 1500 px。
- 浏览器点击锁定：`/tmp/project-hover-implementation-2026-08-09/08-qa-click-locked.jpg`，1220 × 1500 px。
- 最终恢复页面：`/tmp/project-hover-implementation-2026-08-09/09-final-restored-page.jpg`，1220 × 1500 px。
- 悬停卡面聚焦对照：`/tmp/project-hover-implementation-2026-08-09/10-compare-hover-focus.jpg`，750 × 415 px。
- 点击锁定卡面聚焦对照：`/tmp/project-hover-implementation-2026-08-09/11-compare-click-focus.jpg`，750 × 415 px。
- 全视图同屏对照：`/tmp/project-hover-implementation-2026-08-09/12-compare-full-view.jpg`，1220 × 2041 px。
- 浏览器 CSS 视口为 1220 × 1500，`devicePixelRatio = 1`。两张源图是宽舞台设计预览，运行页面受现有三列驾驶舱约束；聚焦比较从源图和浏览器截图各提取 360 × 375 px 的真实卡面区域并排，没有拉伸、改色或重排。
- 双卡交互验收使用 SQLite 中现有的 `去除豆包水印` 与 `uni-app页面修改` 两张真实项目卡。只在测试构建中临时让两者同屏，没有创建项目、修改 SQLite 或写入经营数据；最终源码、构建与页面均已恢复“当前合作 / 已终止”正式筛选。

## 必查视觉面

- 字体与排版：卡片业务内容、中文无衬线字体、项目名称、状态、进度、任务、日期和财务层级保持不变；悬停与锁定只改变空间位置和层级，不让文字重排或截断。
- 间距与布局：悬停目标卡前移到中央，原锁定卡向另一侧后退；中心卡和源预览的宽高、正面角度、操作区密度及留白一致。运行页面保留左侧阶段、中央舞台、右侧 Inspector 和底部时间线，这是现有产品结构约束。
- 颜色与令牌：继续使用浅紫白单层玻璃、1 px 紫灰边、柔和紫蓝光晕和当前系统阴影；没有加入黑色背景、厚侧壁、双边框或不透明选中卡。
- 图像与资产：本轮不需要新增位图或装饰素材；现有 Phosphor 图标、背景光场和点阵保持不变，没有占位图、表情符号或手写 SVG。
- 文案与内容：轨道说明更新为“悬停预览 · 点击锁定 · 拖动、滚轮或键盘切换”，明确区分临时预览和正式选中；客户、金额、日期和状态均来自真实数据。
- 无障碍：正式选中继续由 `aria-pressed`、`aria-current` 和键盘焦点表达；悬停预览不伪装成已选中。点击后操作按钮才进入可聚焦状态；触摸、窄屏和减少动态效果条件下不启动悬停旋转。

## 比较历史

### Pass 1：现有行为与确认预览

- [P1] 原实现只有边框 Hover，侧卡不会转正、居中或抽出，无法达到确认分镜的核心空间交互。
  - 修复：新增独立的临时悬停焦点，按焦点索引重排卡组；悬停目标使用约 2° 正面角度、104 px 前移和 1.065 缩放，其他卡恢复扇形景深。
- [P2] 直接依赖移动卡片的 `pointerleave` 会在卡片离开鼠标后立即复位，容易反复闪烁。
  - 修复：使用约 140 ms 停留判定、舞台级悬停锁定和约 120 ms 离场恢复；预览激活后需真实移动至少 12 px 才允许换轨。

### Pass 2：浏览器交互复验

- 90 ms 时两卡 class 保持不变；180 ms 时目标卡获得 `hover-preview`，验证停留阈值生效。
- 约 360 ms 动画完成后，目标卡为接近正面的中心焦点，原锁定卡退向左后方；Inspector 仍显示原锁定项目，没有被 Hover 静默改写。
- 鼠标移到舞台空白区并等待 220 ms，悬停预览仍保持；移出舞台 75 ms 时仍保持，155 ms 时恢复正式选中，未出现闪烁。
- 点击悬停卡后，`data-previewing` 清除，目标卡 `aria-pressed=true`、`aria-current=true`，Inspector 同步为 `uni-app页面修改`；原卡恢复未选中。
- ArrowLeft 与 End 均可在两张真实卡之间正式切换，验证新增 Hover 状态没有破坏键盘路径。

### Pass 3：视觉与响应式收口

- 聚焦对照确认源图和实现的卡片尺寸、轻薄玻璃、正面角度、按钮区、紫色层级与柔和阴影达到相同视觉意图；真实项目内容不同属于源图使用两张真实卡演示的预期差异。
- 1024 × 768 保留 3D 卡轨并把 Inspector 移到下方；768 × 1024 改为容器内横向卡片；浏览器最窄可用宽度钳制为 480 × 844，并进入单列卡片规则。三种状态的页面横向溢出均为 0。
- 点击锁定截图中的紫色细线来自自动化点击留下的 `focus-visible` 可访问性轮廓，不会改变卡面布局，列为可接受的 P3。
- 未发现剩余 P0、P1 或 P2。

## 工程与运行验收

- TypeScript 类型检查通过；Vite 生产构建通过；Sites Worker 4/4 通过；`git diff --check` 通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 最终受控重启到 PID 84676，`/api/health` 返回 `status: ok`，继续只使用唯一 `127.0.0.1:8877` 服务。
- 最终页面重新加载后只显示 1 个当前合作项目，“已终止”仍单独归档；控制台 error / warning 为 0。
- 最终浏览器标签保持原地址和原项目管理 Hash，没有打开第二个端口或第二个标签页，没有修改真实项目、任务、回款或客户数据。

final result: passed

---

# 2026-08-09 项目轨道空卡位最终收口

- 详细视觉、交互、数据边界与响应式证据见本文件“2026-08-09 项目轨道空卡位 Design QA”。
- 最终状态保持 1 张真实接单项目卡加 2 张前端派生空卡；个人项目空分类为 3 张空卡。
- 空卡点击只打开既有新建项目弹层，筛选和搜索时隐藏，不进入指标、Inspector、时间线或持久化。
- 最终浏览器控制台无 error / warning，8877 单实例健康，类型检查、生产构建与 Sites Worker 测试通过。

final result: passed

---

# 2026-08-09 顶部智能提醒最终收口

- 提醒来源已统一为客户未读/待回复与商品经营动作；不再包含项目异常、交付、回款或结算事项，旧失败批次也不会覆盖较新的逐商品成功结果。
- 完整视觉、数据边界、三轮比较和交互证据见本文件“2026-08-09 顶部「智能提醒」丰富版 Design QA”。
- 最终桌面对照：`/tmp/xianyu-reminder-rich-2026-08-09/final-comparison-source-vs-implementation.png`；浮层聚焦对照：`/tmp/xianyu-reminder-rich-2026-08-09/final-comparison-reminder-focused.png`。
- 最终手机抽屉：`/tmp/xianyu-reminder-rich-2026-08-09/mobile-reminder.png`；横向溢出 0，触控目标达到至少 44 px。
- TypeScript、生产构建、Sites Worker 4/4、商品采集针对性测试、`git diff --check`、8877 单实例健康检查和浏览器控制台检查均通过。

final result: passed

---

# 2026-08-10 三张确认效果图最终实现 Design QA

## 验收范围与源真值

- 商品采集日志确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-6fc775b3-2119-4dac-b3f3-f16fa103f28a.png`，1672 × 941 px。
- 需求蓝图编辑确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-cf5cd598-ab44-4222-83dc-35f2b54a4e43.png`，1672 × 941 px。
- 客户分类确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-75480dac-c37e-4f7f-87fe-28cf0205bc62.png`，1672 × 941 px。
- 商品最终实现：`/tmp/xianyu-ledger-three-previews-final/17-product-collection-log-1672x941-final.jpg`，1672 × 941 px。
- 蓝图编辑最终实现：`/tmp/xianyu-ledger-three-previews-final/01-blueprint-editor-1440x900-final.jpg`，实际可见内容 1410 × 900 px，对应 CSS 视口 1440 × 900。
- 蓝图 V2 预览：`/tmp/xianyu-ledger-three-previews-final/02-blueprint-version-preview-1440x900-final.jpg`，实际可见内容 1410 × 900 px，对应 CSS 视口 1440 × 900。
- 客户分类最终实现：`/tmp/xianyu-ledger-three-previews-final/03-customer-classification-1440x900-final.jpg`，1440 × 900 px。
- 移动蓝图编辑最终实现：`/tmp/xianyu-ledger-three-previews-final/06-blueprint-editor-mobile-fixed-480x844.jpg`，480 × 844 px。

## 归一化与同屏比较

- 商品最终比较：`/tmp/xianyu-ledger-three-previews-final/18-compare-product-final.png`，3348 × 941 px；左侧是 1672 × 941 源图，右侧是 CSS 1672 × 942 页面截图裁去底部 1 px 后的 1672 × 941 实现，中间保留 4 px 分隔，没有改色或重排。
- 蓝图编辑比较：`/tmp/xianyu-ledger-three-previews-final/08-compare-blueprint.png`，3348 × 941 px。
- 客户分类比较：`/tmp/xianyu-ledger-three-previews-final/09-compare-customer.png`，3348 × 941 px。
- 浏览器截图原始输出包含重复画面；证据只提取左上真实可见象限，再按目标 CSS 视口归一化。商品图原始输出为 3284 × 1884，真实象限为 1642 × 942，归一化到 1672 × 942 后仅裁去底部 1 px。
- 三张源图本身已经分别聚焦商品操作区、蓝图编辑抽屉和客户分类表；同屏图中文字、卡片、按钮及状态均可直接判读，因此不再重复裁切桌面局部。移动端底部操作的独立聚焦证据用于补充响应式判断。

## 最终实现结果

- 商品采集：自动、手动全量和单商品采集均形成批次及逐商品日志；历史成功、失败和保护跳过保留。展开区固定为 156 px 并在内部滚动，不删除历史，也不会把“今日优先策略”继续推离首屏。
- 需求蓝图：目标、功能、阶段和验收四层均可编辑；预览后只能追加新版本，旧版本保持只读。真实案例仅完成 V1 → V2 预览，没有点击最终保存。
- 客户转移：验收需求案例已独立归属脱敏客户 `示例客户`，只移动案例、来源身份和商品关联；项目、任务、付款、收入及原客户其他历史不随之移动。
- 客户管理：新增“跟进中 / 已成交 / 已流失”生命周期分类和“全部 / 闲鱼 / 微信”渠道筛选；`示例客户` 位于跟进中，切换已成交或微信时不会错误出现。

## 必查视觉面

- 字体与排版：沿用现有中文无衬线和产品字阶。商品主标题、采集状态、历史批次、蓝图字段、客户状态和金额层级清晰；没有为了贴图缩小到不可读字号。
- 间距与布局：商品操作区保持左侧经营说明、右侧采集面板和下方策略；三个商品操作同排。蓝图使用右侧编辑抽屉；客户页使用主表加 Inspector，均保持现有浅色 SaaS 外壳。
- 颜色与令牌：紫色主操作、绿色成功、橙色失败或风险、浅紫白卡面与柔和阴影延续全站令牌；没有黑色工作区、厚重玻璃或新的不透明大色块。
- 图像与资产：继续使用项目已有品牌图片与 Phosphor 图标；本轮没有增加位图背景、占位图、表情符号、手写 SVG、Canvas、WebGL 或新的运行时依赖。
- 文案与内容：全部商品、采集批次、客户、需求版本和分类计数来自真实本机数据；没有把效果图示例值写入业务数据。
- 无障碍：日志开关使用按钮和 `aria-expanded`；客户生命周期使用 tab 语义，渠道按钮使用 pressed 状态；抽屉、关闭按钮和底部操作可由键盘到达，焦点样式延续现有体系。

## 比较历史

### Pass 1：主体功能与真实数据

- [P1] 原系统缺少可审计的多日采集批次、不可变蓝图编辑和客户生命周期分类。
  - 修复：新增采集批次及逐商品结果、蓝图追加版本编辑、需求案例独立客户转移，以及客户生命周期和渠道筛选。
- [P1] 需求案例原先无法在不移动项目和财务历史的前提下独立归属客户。
  - 修复：建立独立转移边界并完成一次真实转移；案例当前客户为 `c-transfer-795c719c3386ac0f73b02150`，当前版本仍为 1。

### Pass 2：响应式操作区

- [P2] 480 × 844 蓝图编辑器中，全局“立即记账”悬浮按钮遮挡底部“预览新版本”。
  - 修复前证据：`/tmp/xianyu-ledger-three-previews-final/05-blueprint-editor-mobile-480x844.jpg`。
  - 修复：蓝图编辑抽屉或客户转移弹层打开时隐藏重复的全局悬浮入口；正常页面记账入口不受影响。
  - 修复后证据：`/tmp/xianyu-ledger-three-previews-final/06-blueprint-editor-mobile-fixed-480x844.jpg`；`floatingDisplay = none`，按钮可见且无重叠。

### Pass 3：商品首屏密度与点击稳定性

- [P2] 5 条真实采集历史全部展开时占用 286 px，商品卡高度达到约 691 px，“今日优先策略”落到首屏下方，明显偏离确认图的信息密度。
  - 修复：日志可视高度收紧到 156 px并保留内部滚动；商品管理、添加商品和手动采集全部改为桌面单行三列。
- [P2] 自动化点击日志开关时，`overflow: hidden` 让整张商品卡成为可编程滚动容器，卡片内部会滚动约 66 px并裁掉主标题。
  - 修复：装饰裁切改为 `overflow: clip`，日志继续由自己的滚动容器承担历史浏览。
  - 结果：卡片 `scrollTop = 0`、日志高度 156 px、优先策略在 1672 × 942 首屏可见，页面横向溢出为 0。

### Pass 4：最终同屏复验

- 商品源图与最终实现的结构、白紫表面、采集状态、展开日志和三项操作一致；正式页面保留 5 条真实历史而不是效果图的 2 条示例，因此以滚动窗口表达，是有意的数据差异。
- 蓝图编辑保留四层结构、不可变版本说明、客户转移入口和预览操作；正式数据字段比效果图更完整，不影响层级和操作路径。
- 客户页的四指标、生命周期分类、渠道筛选、主表和右侧客户资料结构一致；正式页面只显示当前真实分类结果。
- 未发现剩余 P0、P1 或 P2。现有系统字号和外壳尺寸比效果图的概念缩放略大，属于保持全站一致性的可接受 P3，不再为单页破坏全局设计令牌。

## 交互、响应式与数据边界

- 商品：采集日志开合正常，全部历史可滚动访问；商品管理、添加商品和手动采集按钮可聚焦。验收没有触发任何真实采集、商品修改、发布、下架或投流。
- 蓝图：编辑抽屉可打开，四层字段和预览按钮可见；“确认创建 V2”只在预览后的下一步出现。本轮未点击确认，版本数保持 1。
- 客户：点击已成交后 `示例客户` 不出现；返回跟进中并筛选微信时不出现；恢复全部渠道后重新出现，选择状态与表格同步。
- 1024 × 768、768 × 1024 和 480 × 844 的商品页均无页面横向溢出；日志保持独立滚动，商品卡 `scrollTop = 0`。480 × 844 蓝图编辑器无横向溢出，底部按钮位于视口内。
- 内置浏览器最窄可控 CSS 宽度为 480 px，无法生成精确 390 px 证据；480 px 已命中同一个 `max-width: 560px` 规则。
- SQLite 快照修订号保持 24；真实案例当前客户 ID为 `c-transfer-795c719c3386ac0f73b02150`，`current_version = 1`、版本数 1。浏览和切换没有产生第二次转移或新增 V2。

## 工程与运行验收

- 后端完整测试：166 passed，1 条既有 Starlette/httpx2 弃用提醒。
- TypeScript 类型检查通过。
- 生产构建通过，生成 `dist/client/index.html`、`dist/server/index.js` 和 `dist/.openai/hosting.json`；仅保留既有大分包体积提示。
- Sites Worker：4/4 通过；`git diff --check` 通过。
- 浏览器商品页、蓝图页和客户页控制台 error / warning 为 0。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控重启恢复，`/api/health` 返回 `status: ok`，最终只有一个进程监听 `127.0.0.1:8877`。
- 未提交、推送、合并或公开部署；没有启动第二端口或第二个真实后端。

final result: passed

---

# 2026-08-10 商品增长复盘与任务删除 Design QA

## 验收范围与源真值

- 商品增长复盘确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-442e5842-8478-4582-98ff-7eeb9754bf90.png`，1263 × 1246 px。
- 任务编辑确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-46fb05fa-4f84-44a3-979c-196402206105.png`，1262 × 1246 px。
- 删除确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-52ad60a7-55a6-474b-99d7-088116813c3a.png`，1263 × 1246 px。
- 商品增长复盘最终实现：`/tmp/xianyu-growth-statistics-20260810/14-growth-statistics-pass2-fresh-crop.png`，1263 × 1246 px。
- 任务编辑最终实现：`/tmp/xianyu-growth-statistics-20260810/18-task-editor-crop.png`，1263 × 1246 px。
- 删除确认最终实现：`/tmp/xianyu-growth-statistics-20260810/20-task-delete-confirm-crop.png`，1263 × 1246 px。

## 归一化与同屏比较

- 商品增长复盘最终比较：`/tmp/xianyu-growth-statistics-20260810/15-growth-statistics-comparison-pass2-fresh.jpg`；左侧源图、右侧最新构建，均为 1263 × 1246 px。
- 任务编辑最终比较：`/tmp/xianyu-growth-statistics-20260810/19-task-editor-comparison.jpg`；源图仅横向归一化 1 px 到 1263 × 1246，未改色或重排。
- 删除确认最终比较：`/tmp/xianyu-growth-statistics-20260810/21-task-delete-confirm-comparison.jpg`；两侧均为 1263 × 1246 px。
- 桌面 CSS 视口为 1294 × 1246；浏览器截图输出包含重复画面。商品页原始输出 2528 × 2492，任务弹层原始输出 2588 × 2492，均提取左上真实可见象限，并将商品页右侧多出的 1 px裁去以匹配源图。
- 三张源图都已聚焦目标页面或中央弹层，原尺寸同屏图中文字、按钮和状态可判读；同时单独以原始细节打开最终商品页、任务编辑器和删除确认，因此不再制作会重复信息的局部裁切。

## 必查视觉面

- 字体与排版：继续使用现有中文无衬线字体、标题字重和紧凑数据字阶。商品增长、转化、贡献和归因层级清楚；任务名、项目名与不可撤销警告均可直接读出。
- 间距与布局：统计页按“四项指标 → 趋势/贡献 → 漏斗 → 五行比较 → 待归因收入”排列，最新构建已在同一 1263 × 1246 证据中完整呈现。任务编辑和删除确认保持居中、清晰分区与足够按钮间距。
- 颜色与令牌：紫色用于统计与主操作，绿色用于咨询、橙色用于想要，红色只用于删除风险；卡面继续使用浅紫白表面和柔和阴影，没有新增黑色工作区。
- 图像与资产：继续使用现有品牌资产与 Phosphor 图标；本轮没有增加占位图、表情符号、手写 SVG、Canvas、WebGL 或新运行时依赖。
- 文案与内容：统计页全部数值来自真实商品采集和经营快照；确认收入与商品归因差额只显示为“待归因收入”，没有猜测分摊。删除确认明确显示真实任务和所属项目。
- 无障碍：周期按钮使用 `aria-pressed`；商品跳转和任务删除均为按钮语义。删除确认使用 `alertdialog`、`aria-modal`、标题和说明关联，Escape、遮罩、关闭和“返回编辑”都能安全退出。

## 比较历史

### Pass 1：统计页首屏密度

- [P2] 初版重复了一条完整白色工具栏，指标和图表卡偏高，1263 × 1246 视口中第五行商品与待归因说明落在首屏下方。
  - 修复前证据：`/tmp/xianyu-growth-statistics-20260810/09-growth-statistics-comparison-pass1.jpg`。
  - 修复：工具栏改为透明紧凑行；指标卡收紧；趋势和贡献卡的目标高度收至 300 px，图表高度收至 193 px；漏斗同步压缩但保留四阶段关系。

### Pass 2：最新构建复验

- 初次重载仍命中旧静态资源 `index-BQklOScw.css`，因此先前样式看似未生效；使用新的构建查询标识重新加载同一标签后，确认页面使用最新 `index-CDtpzTs5.css`。
- 修复后证据：`/tmp/xianyu-growth-statistics-20260810/15-growth-statistics-comparison-pass2-fresh.jpg`。
- 第五行商品与“待归因收入 ¥230”已进入同一首屏；趋势、贡献和漏斗仍保留可读刻度与层级。未发现剩余 P0、P1 或 P2。
- 当前正式外壳的侧栏、顶部搜索和字号比例与生成式参考图有轻微差异，属于保持全站现有设计令牌的可接受 P3，不为单页修改全局导航。

### Pass 3：任务删除双重确认

- 现有任务编辑器显示红色描边“删除任务”；新增任务模式不出现该操作。
- 删除确认显示任务“交付检查任务 2”、项目“uni-app页面修改”、进度/工时/项目状态重算说明及不可撤销警告。
- Escape、遮罩点击和“返回编辑”均回到编辑器；关闭编辑器时没有保存修改。验收从未点击“确认删除”。
- 同屏比较显示卡片结构、浅色材质、红色风险层级和操作排列与两张确认图一致，未发现 P0、P1 或 P2。

## 交互、响应式与数据边界

- 7、14、30、90 天按钮逐项点击后，选中态和“新增咨询 / 新增想要”周期文案同步更新；只改变前端派生窗口。
- 从比较表第一行点击“查看商品经营”，精确打开 `#商品经营/overview/product/1063498329657` 并聚焦“Django校园二手平台完整源码”；浏览器返回恢复同一统计页。
- 1024 × 768：四指标同排，趋势与贡献并排，页面横向溢出为 0。
- 768 × 1024：指标两列，趋势和贡献纵向排列；980 px 比较表只在卡片内部横向浏览，页面横向溢出为 0。
- 内置浏览器最窄可控 CSS 宽度为 480 × 844：命中移动布局，比较表改为卡片式，页面横向溢出为 0。精确 390 px 受浏览器最小宽度限制未生成截图；代码中的 `max-width: 460px` 单列指标规则保留。
- 响应式证据：`/tmp/xianyu-growth-statistics-20260810/22-resp-1024x768-crop.png`、`/tmp/xianyu-growth-statistics-20260810/23-resp-768x1024-crop.png`、`/tmp/xianyu-growth-statistics-20260810/24-resp-480x844-crop.png`。
- 验收结束时 SQLite 修订号仍为 31、任务总数仍为 5；选择周期、打开商品详情、打开/取消删除都没有写入经营数据。

## 工程与运行验收

- TypeScript 类型检查通过。
- Vite 生产构建通过，并生成 `dist/client/index.html`、`dist/server/index.js` 与 `dist/.openai/hosting.json`；仅保留既有大分包体积提示。
- 后端完整测试 168 passed，1 条既有 Starlette/httpx2 弃用提醒。
- Sites Worker 4/4 通过；`git diff --check` 通过。
- 浏览器控制台 error / warning 为 0。
- 常驻服务受控重启后 `/api/health` 返回 `status: ok`，继续使用唯一 `127.0.0.1:8877`。
- 未提交、推送、合并或公开部署，没有启动第二端口或第二个真实后端。

final result: passed

---

# Project cockpit design QA

## Comparison target

- Source visual truth: `/Users/chentao/.codex/generated_images/019feaab-cbe5-7c53-8ea3-e240d651b48b/exec-08c60802-ac5c-444b-b30b-acb6ac88d36d.png`
- Source pixels: `1402 × 1122`. The source is a three-state interaction storyboard rather than one browser viewport: project-card extraction, desktop task centering, and narrow-screen task centering.
- Combined comparison input: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/qa-comparison-master-v2.png`
- Focus comparisons:
  - project extraction: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/qa-compare-project-extraction.png`
  - desktop centered task: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/qa-compare-desktop-task-centered.png`
  - narrow centered task: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/qa-compare-mobile-task-centered.png`

## Rendered implementation evidence

- Project extraction: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/02-project-card-extracted-final.png`, `3668 × 2174` PNG. The browser viewport override exposed `3668 × 2928` CSS pixels at reported DPR `0.5`; the visible page capture was kept at native PNG size and then focus-cropped for the combined comparison. The timer was extended only in a temporary verification build so the browser could save the transient frame; the final source and served build were restored to `220 ms`. A separate final-build DOM check confirmed the same extracted transform, placeholder slot, and one-click route transition.
- Desktop centered task: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/07-final-desktop-1250x1400-task2-raw.png`, `1280 × 1400` PNG from a `1280 × 1400` CSS viewport. The reported DPR was `0.5`, but this capture was already one PNG pixel per CSS pixel and required no resampling.
- Narrow full render: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/06-mobile-min-450x1840-task2-normalized.png`, normalized from the browser's duplicated `900 × 3680` raw capture to one `450 × 1840` CSS view.
- Narrow task focus: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/project-cockpit-final/06-mobile-min-450x840-task-focus.png`, `450 × 840` focused crop.
- The in-app Browser clamps its minimum visual viewport to `450 px`, so a literal `390 px` browser capture was unavailable. The `max-width: 560px` layout branch was active at `450 px`; its flat snap rail, controls, width containment, and centering behavior were verified. The same branch therefore covers `390 px`, and its presence is also enforced by the interaction contract test.

## States and behavior checked

- One project-card click enters `p-1786013284727/immersive`; the intermediate extracted state has `data-extracted="true"`, an origin-slot outline, full opacity, and the intended pull-forward transform.
- Clicking either task face selects it, moves its center to the rail center with a measured `0 px` delta, and synchronizes the inspector title.
- The middle previous/next controls are `46 × 46 px` and work in both directions.
- `ArrowLeft`, `ArrowRight`, `Home`, and `End` select the expected task.
- A large drag changes one spatial selection without opening an editor or project; a sub-threshold drag does not change selection.
- Browser back/forward and refresh preserve the valid immersive hash; an invalid project ID returns to the project cockpit.
- At the narrow breakpoint the task rail is `display:flex`, `overflow-x:auto`, `scroll-snap-type:x mandatory`; the selected card is flat, centered with a `0 px` delta, and the document has no horizontal overflow (`450 px` client and scroll widths).
- Reduced-motion source paths use `0 ms` project-entry delay, `auto` rail scrolling, and reduced CSS transitions. The in-app Browser does not expose media-feature emulation, so this was verified through source and contract tests rather than a simulated screenshot.
- Browser console after the tested flow: no page logs or errors.

## Required fidelity surfaces

- Fonts and typography: the implementation keeps the product's existing system sans stack and the storyboard's compact hierarchy. Project/task names remain the strongest labels; metadata, status, and dates retain smaller optical weights without clipping in the compared states.
- Spacing and layout rhythm: the extracted project card visibly separates from its slot without an extra scale jump; the center task is front-facing; side cards remain readable; the inspector and timeline keep the existing light workspace proportions. Narrow cards use a flat horizontal snap rail instead of collapsing to a vertical list.
- Colors and visual tokens: white and soft lavender surfaces, restrained purple outlines, green completion states, and low-opacity shadows match the selected direction and the existing product tokens. No dark cockpit or opaque selected card was introduced.
- Image quality and asset fidelity: the interaction states do not require new raster imagery. Existing product artwork remains untouched, and visible UI symbols use the installed Phosphor icon family rather than handcrafted SVG/CSS substitutes.
- Copy and content: real project and task names are preserved. The source storyboard's fake third task slot is intentionally not inserted into the data rail; the existing explicit “新增任务” control remains the honest action for creating one.
- Icons and controls: icon weight and rounded control treatment remain consistent with the current design system. Arrow hit targets meet the `46 px` measured size.
- Accessibility: semantic buttons, current-state attributes, focus-visible styling, keyboard navigation, touch/drag fallbacks, and reduced-motion branches remain present.

## Findings and iteration history

### Iteration 1 — blocked

- `[P2] Narrow task selection moved the whole document vertically.`
  - Evidence: `selectedCard.scrollIntoView(...)` centered the rail but also changed the document scroll position during narrow-screen selection.
  - Impact: a task selection could pull the page header and project context out of view, making the interaction feel like a page jump.
  - Fix: replaced document-wide `scrollIntoView` with a centered `orbit.scrollTo({ left, behavior })` calculation scoped to the horizontal task container.

### Iteration 2 — passed

- Post-fix evidence: at the minimum supported `450 px` visual viewport, the selected task center delta is `0 px`, orbit scroll position changes to the selected card, document `scrollY` remains `0` under native clicks/arrows, and document client/scroll widths are both `450 px`.
- The combined source/implementation input shows no remaining actionable P0, P1, or P2 mismatch. The selected visual's essential behaviors are present: a clear card extraction before entry, a centered front-facing task, readable neighboring cards, working directional controls, and a flat narrow-screen rail.

## Open questions and follow-up polish

- No blocking design questions remain.
- P3: if a future project has three or more real tasks, re-check the far-side opacity cadence at the same desktop viewport. This is optional polish and does not block the current two-task acceptance state.

## Implementation checklist

- [x] Card extraction state matches the selected interaction direction.
- [x] One click enters the correct immersive project.
- [x] Task-card click and both middle arrows center the selected task.
- [x] Keyboard, drag, history, invalid route, responsive, reduced-motion contract, and console checks completed.
- [x] P2 narrow-screen page jump fixed and re-captured.
- [x] No actionable P0/P1/P2 finding remains.

final result: passed

---

# 循营 · 小策证据工作台 Design QA

## Comparison target

- Source visual truth, desktop default: `/Users/chentao/.codex/generated_images/019feaab-cbe5-7c53-8ea3-e240d651b48b/exec-64f793e9-1187-4444-b2b4-0846261b5538.png` (`1487 × 1058`).
- Source visual truth, mobile default: `/Users/chentao/.codex/generated_images/019feaab-cbe5-7c53-8ea3-e240d651b48b/exec-34dfa809-bdb6-412c-b447-be9f932ad8e1.png` (`853 × 1844`).
- Source visual truth, desktop evidence drawer: `/Users/chentao/.codex/generated_images/019feaab-cbe5-7c53-8ea3-e240d651b48b/exec-fd59fbf2-4356-4db1-9649-7a808923a5ad.png` (`1487 × 1058`).
- Implementation URL and state: `http://127.0.0.1:8877/#AI经营助手`, light theme, real local ledger snapshot, workflow panel collapsed by default.
- Browser-rendered implementation, desktop default: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/xunying-desktop-1440x1024.png` (`1440 × 1024`).
- Browser-rendered implementation, desktop drawer with challenge checklist open: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/xunying-desktop-drawer-1440x1024.png` (`1440 × 1024`).
- Browser-rendered implementation, narrow default: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/xunying-mobile-480x844.png` (`450 × 844` visible page crop from a `480 × 844` CSS viewport).

## Viewport and density normalization

- Desktop: the in-app browser viewport override was set to `720 × 512`; the page reported `1440 × 1024` CSS px with `devicePixelRatio = 0.5`. The browser capture backend returned a repeated `2880 × 2048` image, so the verified top-left `1440 × 1024` frame was extracted without rescaling.
- Mobile: the browser clamps its override to a minimum physical width of `240`, which produced a `480 × 844` CSS viewport with `devicePixelRatio = 0.5`. The capture backend returned `900 × 1688`; the verified top-left `450 × 844` visible-page frame was extracted without rescaling. This viewport activates the same `(max-width: 480px)` rules used at the requested `390px` width.
- Desktop references were proportionally contained in a `1440 × 1024` comparison frame. The mobile reference was resized to the implementation width and cropped to the same first-viewport height.

## Full-view comparison evidence

- Desktop default, source on the left and implementation on the right: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/comparison-desktop-default.png`.
- Desktop drawer, source on the left and implementation on the right: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/comparison-desktop-drawer.png`.
- Mobile first viewport, source on the left and implementation on the right: `/Users/chentao/.codex/worktrees/c376/New project 3/artifacts/ui-qa/comparison-mobile-default.png`.
- Focused-region comparison was not needed: the source and implementation were opened at original pixel detail, and the judgment typography, fact rows, brand raster assets, drawer sections, icons and action labels are all legible in the full-resolution comparison inputs.

## Required fidelity surfaces

- Fonts and typography: the implementation keeps the source's compact Chinese sans-serif hierarchy, dark navy judgment headline, purple eyebrow labels and lighter explanatory copy. Dynamic evidence rows are intentionally denser than the empty-state mock but remain legible and do not truncate the primary judgment.
- Spacing and layout rhythm: the three-column desktop evidence composition, audit strip, single-action band and three workflow entries match the selected hierarchy. Desktop and narrow layouts have no horizontal overflow. The narrow layout preserves the judgment-first order and a fixed bottom navigation.
- Colors and visual tokens: white-purple surfaces, violet primary actions, blue evidence, green knowledge and amber counterargument accents remain consistent with the source. Contrast and focus outlines remain visible.
- Image quality and asset fidelity: the orbit mark and Xiaoce avatar are project-owned transparent RGBA raster assets, rendered with `object-fit: contain`; no placeholder, emoji, CSS illustration or handcrafted SVG substitutes are used. Phosphor supplies the standard UI icons.
- Copy and content: sample numbers from the visual mock were not copied. The implementation shows the authoritative local snapshot: 2 projects, 1 confirmed receipt, 4 expenses, 4 actual hours, and no delivery log or attachment evidence. The missing knowledge state is explicit rather than fabricated.
- Existing-shell constraints: the shared header, existing navigation order and live-data detail are retained for product compatibility. The evidence drawer is deliberately wider than the concept image so four real evidence categories and their provenance remain readable without truncation.

## States, interactions and accessibility checked

- Default workflow content is absent; each of 需求分析、规则报价 and 项目复盘 expands only after its entry is clicked and remains connected to its real local service.
- Evidence drawer: open, outside-click close, Escape close, body scroll lock, Tab focus containment, focus return, and challenge checklist expanded/collapsed state all passed.
- Desktop fixed-layer geometry after the final fix: backdrop `1440 × 1024`, drawer `480 × 1024` at `x = 960`, and `rightGap = 0`.
- Narrow fixed navigation after the final fix: `y = 772`, height `72`, `bottomGap = 0` in an `844px`-high viewport. Four navigation targets are `111 × 57`; primary and secondary actions are `48px` high.
- Project regression: one semantic click on the real project card navigated directly to `#项目管理/p-1786013284727/immersive`. The rail next arrow selected task 2; clicking task 1 returned it to the exact rail center (`activeCenter = 807`, `orbitCenter = 807`, delta `0px`) and synchronized the inspector.
- Browser console warnings and errors: none.

## Comparison history

### Pass 1 — P2: workflow input leaked into the evidence-first home

- Earlier evidence: the requirements textarea rendered immediately under the three workflow entries, making the first screen read like a chat/input tool rather than a decision workbench.
- Fix: added a default-collapsed `workflowExpanded` state; the selected workflow now renders only after an entry click, with `aria-expanded`, `aria-selected` and a named tab panel.
- Post-fix evidence: desktop and mobile default captures contain only the three workflow entries; DOM verification returned `workflowPanelCount = 0` and `textareaVisible = false` before interaction.

### Pass 2 — P1: fixed navigation and drawer were anchored to page content

- Earlier evidence: the inherited `business-enter` transform remained on `.xunying-workbench`, creating a containing block for fixed descendants. At the narrow viewport the bottom navigation reported `y = 1867.64` instead of the viewport bottom.
- Fix: replaced the transform-based entrance on this page with an opacity-only `xunying-workbench-enter` fade.
- Post-fix evidence: `.xunying-workbench` reports `transform: none`; the mobile navigation is fixed at the viewport bottom, and the desktop backdrop/drawer cover and align to the viewport exactly.

## Findings

- No actionable P0, P1 or P2 findings remain.
- Expected deviation: real evidence replaces the source mock's empty fact state, increasing mobile content height while preserving order, readability and scroll access.

## Open questions

- Residual P3 verification gap: the in-app browser enforces a `480px` minimum CSS width in this environment. The exact `390 × 844` capture should be repeated when that clamp is unavailable; the tested viewport already activates the same final `max-width: 480px` rule set and showed no overflow.

## Implementation checklist

- [x] Preserve real-data decision derivation and explicit knowledge boundary.
- [x] Keep the three existing local-service workflows, collapsed by default.
- [x] Verify drawer dismissal, focus handling and challenge state.
- [x] Verify desktop, narrow layout, fixed navigation and no horizontal overflow.
- [x] Verify the original project-card, rail-arrow and exact task-centering regressions.
- [x] Verify console, TypeScript, interaction tests, production build, Sites output and backend suite.

## Follow-up polish

- P3: capture the same narrow state at an exact `390 × 844` CSS viewport when the browser override permits it.
- P3: split the approximately `1.315 MB` main JavaScript chunk in a separate performance pass; it is not a visual or interaction blocker for this implementation.

final result: passed

---

# AI经营分析中心设计验收记录

## 验收范围

- 已确认方向：方案 3「证据链优先」。
- 核心结构：`业务指标 / 数据来源 → AI发现与原因 → 人工行动建议`。
- 本次只验收 AI经营分析中心；没有调整现有客户、项目、商品和财务业务逻辑。
- 所有建议仍为人工决策与人工执行，浏览器验收没有触发真实 DeepSeek 请求。

## 视觉来源与截图

- 修改前设计预览（视觉参考，不代表已经运行）：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/ai-business-analysis-source-1440x1024.png`
- 第一轮真实实现：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/ai-business-analysis-implementation-pass1-1440x1024.png`
- 第二轮真实实现：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/ai-business-analysis-implementation-pass2-1440x1024.png`
- 第二轮同画面对照（左侧设计预览，右侧真实实现）：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/ai-business-analysis-comparison-pass2.png`
- 移动端真实实现：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/ai-business-analysis-mobile-480x844.png`

## 视口与密度归一化

### 桌面端

- 目标 CSS 视口：`1440 × 1024`。
- 浏览器能力设置值：`720 × 512`。
- 页面实际报告：`innerWidth=1440`、`innerHeight=1024`、`devicePixelRatio=0.5`。
- 浏览器原始截图为 `2880 × 2048` 的 2 × 2 平铺；验收图取左上角 `1440 × 1024`，没有缩放页面内容。

### 移动端

- 浏览器当前最窄可用 CSS 视口为 `480 × 844`，`devicePixelRatio=0.5`；对 `195px` 的设置请求会被运行时钳制到 `480px`。
- 实测 `scrollWidth=480`，无横向溢出。
- 证据链与指标区均为单列；采纳按钮和“查看依据”按钮实测高度均为 `44px`。
- `390px` 使用同一组 `@media (max-width: 620px)` 规则，并由 `tests/business-analysis-center.test.mjs` 对单列布局、触控高度和减少动效约束做静态回归。

## 第一轮发现与修复

1. 财务卡第二金额 `¥1,072.20` 被省略。
   - 修复：双列改为等宽，减少分隔区占宽，并为财务金额使用更稳妥的字号。
   - 第二轮实测两个金额均 `scrollWidth == clientWidth`，没有截断。
2. 页面纵向密度偏高，第三条证据链被截断，历史区域不在首屏。
   - 修复：命令条压缩到 `60px`、指标区压缩到 `128px`、证据链首行压缩到 `158px`，同步减少不必要内边距和间距。
   - 第二轮历史区域顶部为 `961px`，已经进入 `1024px` 首屏；证据链三条内容仍完整可读。
3. 历史表“问题数”错误复用建议数。
   - 修复：后端历史 DTO 新增 `insight_count`，从对应分析记录的 `result_json.insights` 计算；前端改用该字段。
4. 历史表“观察周期”错误复用当前正在查看记录的周期。
   - 修复：按每条历史记录自己的 `snapshot_time`，以 `Asia/Shanghai` 时区显示快照月份。

## 交互与运行证据

- “查看依据”展开：`aria-expanded=true`，对应依据面板可见；再次点击后为 `false`，面板数量回到 0。
- 领域筛选：选择“收入 / 财务”后只显示 2 条财务证据链。
- 建议展开：默认 3 条，可展开为 5 条，再收起为 3 条。
- Hash 直达与刷新：`#经营分析中心` 刷新后恢复同一页面。
- 顶部导航继续沿用项目既有的 `replaceState` 规则；本功能没有扩大范围重写全局路由。
- 浏览器控制台日志：`[]`，没有错误或警告。
- 真实数据为空历史状态：页面明确显示“还没有历史分析”；没有为了截图向 SQLite 插入样例记录。
- 真实 `POST /api/business-analysis/runs` 未触发，避免未经确认产生模型费用；AI 成功、失败回退和历史详情由自动化测试覆盖。

## 自动化与服务验收

- 后端完整回归：`186 passed, 1 warning`（既有 Starlette 弃用警告）。
- 前端交互约束：`13 passed`。
- TypeScript：通过。
- 生产构建：通过；仅保留既有大包体积警告。
- Sites 交付测试：`4 passed`。
- `git diff --check`：通过。
- SQLite 新表存在：`business_analysis_records`、`business_analysis_recommendations`。
- 常驻服务：LaunchAgent 自动恢复检查通过；旧进程退出后拉起新进程，`8877` 保持单一监听，`/api/health` 返回 `ok`。

## 结论

设计方向、真实数据边界、核心交互、响应式、API、数据库兼容、构建和常驻运行均通过本阶段验收。

`final result: passed`

---

# 2026-08-11 客户编辑、关系修正与模型选择补充 Design QA

## 验收范围

- 客户资料编辑：基础资料、状态、等级和标签可在抽屉内修改，使用 revision 防止覆盖较新的浏览器会话，并使用 request-id 保证重复请求幂等。
- 订单关系修正：必须先生成影响预览，再由用户人工确认；确认后在同一事务内同步项目、付款节点与追加订单的客户关系，不移动需求案例或渠道身份，也不改变合同、到账、待收和交付状态。
- 经营分析模型：GPT 为默认提供方，可显式切换 GPT / DeepSeek 及具体模型；选中模型失败时保留规则分析并显示错误，不静默切换提供方。
- 本轮没有触发真实模型生成，避免额外费用与分析记录；真实关系修正已经按用户确认的预览映射执行一次，后续浏览器验收只调用预览接口，没有再次写入。

## 视觉来源与证据边界

- 已确认的修改前设计预览：
  `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/customer-model-correction-preview.html`
- 内置浏览器安全策略禁止打开本地 `file://` 源文件，也不允许通过其他浏览器或间接方式绕过，因此无法在同一受控浏览器中并排打开源视觉与正式实现。
- 客户页包含真实经营与客户资料；在无法稳定裁切脱敏区域的情况下，没有保留全页实现截图，避免将客户隐私作为验收附件。
- 浏览器响应式能力的最窄真实 CSS 视口为 `480px`，无法生成精确 `360px` 的运行截图。`480px` 实测无横向溢出，客户抽屉为全屏布局，模型下拉框与关键操作点击高度均为 `44px`；`360px` 仅有媒体查询和自动化回归证据，不能等同于真实视口截图。

## 功能、数据与运行验收

- 客户编辑抽屉可直接打开；字段、焦点约束、Escape 关闭和窄屏全屏状态通过浏览器验收。
- 关系修正必须先预览，预览影响与用户确认映射一致；事务完成后，目标项目的付款节点与追加订单同步更新，其他项目及其争议、终止合作历史保持不变。
- 真实 SQLite 修订号由 `36` 递增至 `40`；审计表记录三次客户更新和一次关系修正；`PRAGMA integrity_check = ok`，`PRAGMA foreign_key_check` 无异常。
- 修正前 WAL 安全备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator.pre-customer-rebind-20260811-163853.db`；完整性为 `ok`。
- GPT 默认选中；DeepSeek 可切换后再切回 GPT；具体模型列表和“失败不自动切换”提示正常。
- 后端完整测试、14 项前端交互测试、4 项 Sites 测试、TypeScript、生产构建和 `git diff --check` 均通过。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启；最终只有一个进程监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`，运行中的 OpenAPI 已包含新客户关系接口。
- 浏览器已恢复到 `#经营分析中心`，临时 viewport override 已重置；控制台无错误。

## 结论

功能、事务数据修正、自动化回归、构建和常驻服务均已通过。正式视觉 QA 仍缺少可在同一受控环境打开的源预览图，以及隐私安全的精确 `360px` 实现截图；按 Product Design 验收规则，本补充项不能标记为视觉通过。

`final result: blocked`

---

# Design QA — 需求材料导出工作台

## Comparison target

- Source visual truth: `/Users/chentao/.codex/generated_images/019feaab-cbe5-7c53-8ea3-e240d651b48b/exec-bb909f85-c4af-4911-bf67-5b5c7f7b1d22.png`
- Current-page safe reference: `/Users/chentao/.codex/visualizations/2026/08/10/019feaab-cbe5-7c53-8ea3-e240d651b48b/requirement-export-current-safe-reference.png`
- Source pixels: `1132 × 1389`; safe reference pixels: `560 × 360`.
- Runtime route: `http://127.0.0.1:8877/#客户消息` → “需求分析”.
- Privacy-safe implementation detail: `/Users/chentao/Documents/New project 3/artifacts/requirement-image-handoff-qa/desktop-workbench-safe-detail.png`, pixels `793 × 1450`.
- Privacy-safe generated-package state: `/Users/chentao/Documents/New project 3/artifacts/requirement-image-handoff-qa/desktop-workbench-safe.png`, pixels `793 × 1000`.
- The approved visual used three reviewed sample thumbnails and one missing slot. The live conversation exposed twelve real image placeholders; QA added one project-owned decorative PNG, leaving eleven missing slots. This is a real-data state difference, not a layout substitution, and no sample business record was inserted.

## Evidence captured

- Branch commit `0b17648` was merged into local `main` by merge commit `ba1981e`; the narrow-screen touch-target fix is commit `e6649f5`.
- LaunchAgent `com.chentao.xianyu-ledger-assistant` was restarted in place. The final process is PID `15750`, the working directory remains `/Users/chentao/Documents/New project 3`, only one process listens on `127.0.0.1:8877`, and `/api/health` returns `ok`.
- Runtime OpenAPI contains all five new requirement-material endpoint paths, and SQLite contains the `message_attachments` table.
- Backend tests: `263 passed, 1 warning`; interaction tests: `50 passed`; Sites tests: `4 passed`. TypeScript, production build, `git diff --check`, SQLite `integrity_check`, and `foreign_key_check` passed.
- The warning is the existing Starlette/httpx deprecation warning from the shared test environment, not a requirement-material failure.
- Pre-restart WAL-safe backup: `/Users/chentao/Documents/New project 3/data/backups/xianyu_operator.pre-requirement-image-handoff-20260814-130559.db`; backup integrity is `ok` and file permissions are owner-only.

## Full-view comparison

The customer-message page contains real names and conversation text, so no full-page screenshot was retained. Browser DOM and interaction checks covered the full flow, while the two retained crops contain only the export workbench, safe QA artwork, missing-message numbers, counts, controls, and the local package state. Temporary over-wide crops that included real conversation content were deleted immediately and are not delivery artifacts.

## Focused-region comparison

- The implementation preserves the approved hierarchy: safety note → three-step flow → image library plus material summary → dominant Codex export action → Markdown/plain-text fallbacks → local-only footer.
- Thin lavender boundaries, white/light-purple surfaces, Phosphor icons, restrained type scale, green reviewed state, orange incomplete state, and the purple primary action match the selected direction.
- Live data naturally produced more missing slots than the visual source. Desktop uses the approved image-grid/summary split; the narrow layout stacks the image library, summary, actions, and bottom-sheet confirmation without horizontal overflow.
- Uploaded images use `object-fit: contain`; the safe `80 × 120` PNG stayed complete and was not cover-cropped.

## Findings

- Pass 1 blocker resolved: the feature is now served by the maintained local `8877` LaunchAgent and is reachable in the in-app browser.
- Pass 2 found one P2 accessibility issue: the narrow-screen dialog close target measured `38 × 38px`, below the approved `44px` target.
- Fix: `e6649f5` raises the narrow close control to `44 × 44px` and adds an interaction-contract assertion. Post-restart browser measurement confirmed the fix.
- No remaining P0, P1, or P2 findings.

## Required fidelity surfaces

- Fonts, spacing, colors, borders, icons, reviewed/pending/incomplete states, action hierarchy, and safe-image rendering passed focused visual inspection.
- Browser console errors remained empty throughout upload, privacy changes, export, copy, download, deletion, reload, and responsive checks.
- The in-app viewport capability bottoms out at a real CSS viewport of `480 × 844`; it cannot produce a truthful `390px` CSS viewport. At `480 × 844`, `scrollWidth = clientWidth = 450`, the dialog is a bottom sheet, focus is inside it, and the close, primary, and footer controls all measure `44px` high or square.
- Reduced-motion rules and keyboard focus styles remain in CSS and interaction-contract coverage.

## Interaction and cleanup checks

1. Clicking a missing slot before accepting the manual privacy boundary was blocked with the expected notice.
2. One safe project-owned PNG was uploaded through the multi-file chooser. The image was pending by default; review → revoke → review succeeded, and pending review blocked export.
3. The incomplete-package dialog started with its confirm action disabled; explicit acknowledgement enabled it. Escape closed the dialog and returned focus to the export button.
4. The package contained `README.md`, `conversation.json`, `manifest.json`, `images/`, and `contact-sheet-01.png`; its manifest exposed only the approved aggregate keys and contained one image.
5. Automatic and explicit Codex-prompt copy, plain-text copy, and Markdown download all produced their expected success state. The original clipboard was restored afterward.
6. The QA attachment was deleted through the UI confirmation. The message count never changed, all twelve missing slots returned, the attachment row count became zero, and the generated QA package was permanently removed by its exact path.

## Comparison history

- Pass 1: source artifacts opened; implementation capture blocked before a same-state comparison could begin. No visual fixes were claimed from code inspection alone.
- Pass 2: merged runtime flow passed; the `38px` mobile close target was found and fixed.
- Pass 3: rebuilt and restarted runtime passed desktop/narrow interactions, privacy-safe visual review, service recovery, database integrity, and cleanup verification.

final result: passed

# 2026-08-12 商品经营「单品增量轨迹」Design QA

## 验收目标与状态

- 路由：`http://127.0.0.1:8877/#商品经营/exposure`。
- 状态：真实曝光批次 `08/11 16:00`，5 件商品，观察中；选择“浏览”指标与第一件商品。
- 当前真实数据已经记录 `+1h` 与 `+6h`。确认图制作时只有 `+1h`，所以确认图合计 `+24`、正式页面当前合计 `+30`；该差异来自真实检查点推进，不是视觉漂移，也没有为了匹配确认图改写业务数据。
- 组件只绘制 T0 和已保存的真实检查点，不补点、不插值、不生成样例经营数据。

## 视觉真值与实现证据

### 源视觉

- 桌面确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-22160eee-c28b-40e5-8943-c146c1000f3f.png`，原始像素 `1146 × 1372`。
- 移动确认图：`/Users/chentao/.codex/generated_images/019fcc4f-dc58-7ee1-92e8-93b53ebea504/exec-898af2b5-5a37-4c8e-88c6-4c7574c6dda9.png`，原始像素 `853 × 1844`。

### 浏览器实现截图

- 桌面最终实现：`/tmp/product-exposure-delta-qa-20260812/desktop-final-pass2-clean.jpg`，像素 `1122 × 804`。
- 移动最终实现：`/tmp/product-exposure-delta-qa-20260812/final-live-480x844-settled.jpg`，浏览器 CSS 视口与截图均为 `480 × 844`，`devicePixelRatio = 1`。
- 桌面完整区域并排对比：`/tmp/product-exposure-delta-qa-20260812/desktop-comparison-pass2.jpg`，像素 `2244 × 804`；源图与实现均裁切并归一到 `1122 × 804` 后同屏比较。
- 桌面图表聚焦对比：`/tmp/product-exposure-delta-qa-20260812/chart-comparison-pass2.jpg`，像素 `1800 × 440`；两侧各使用 `900 × 440` 的同状态图表区域。
- 移动聚焦对比：`/tmp/product-exposure-delta-qa-20260812/mobile-comparison-final-nofocus.jpg`，像素 `900 × 656`；源图与当时的实现截图均归一为 `450px` 宽的同区域裁切。最终又在未缩放的 `480 × 844` 视口复核一次，结果保持一致。
- 桌面捕获使用临时响应式视口覆盖以取得宽屏完整表面；交付前已重置，最终浏览器保持正常 `480 × 844`、`devicePixelRatio = 1`。

## 必查视觉表面

- 字体与层级：沿用当前浅色 SaaS 的系统字体栈。英文眉题、中文标题、说明、指标切换、坐标轴与排名的字号和字重层次与确认图一致；真实长商品名采用单行截断，未出现挤压或错行。
- 间距与布局：桌面为图表与排名并列，指标切换只占图表列；移动端为批次、四项指标、单商品切换器、曲线和排名依次堆叠。卡片圆角、边界、内边距与纵向节奏保持现有页面体系；最终 `scrollWidth = clientWidth = 480`，无页面横向溢出。
- 色彩与视觉令牌：紫色用于主要曲线与选中态，蓝、绿、橙、浅紫用于其他商品，早期信号与经营结论采用低对比区域底色；没有引入黑色工作台或脱离产品体系的高饱和背景。
- 图像与资产：该区域是数据可视化，不包含需要生成或替代的位图资产。曲线、点、坐标轴与提示浮层由现有 Recharts 运行时绘制，图标继续使用项目已有 Phosphor 图标，没有用占位图片、表情或自制插画代替确认图内容。
- 文案与内容：保留“单品增量轨迹”“早期信号 / 经营结论”“当前 +6h 排名”和批次合计；补充“只绘制真实检查点”及“观察增量不等同于平台因果归因”的数据边界说明。页面展示真实批次、真实商品与真实检查点，不复刻确认图中的旧数值。

## 第一轮比较：发现与修复

- `[P2]` 指标标签宽度越过图表列，视觉上侵入右侧排名区域。
  - 第一轮证据：`/tmp/product-exposure-delta-qa-20260812/desktop-comparison.jpg` 与 `/tmp/product-exposure-delta-qa-20260812/chart-comparison.jpg`。
  - 修复：将四项指标切换限制在曲线列宽度内，把“只绘制真实检查点”作为独立提示；移动端继续保持四项等宽，并在窄屏隐藏提示以避免拥挤。
- 第一轮没有 P0/P1。除动态数据推进外，其余差异均为可接受的真实产品约束。

## 第二轮比较：最终结果

- 第二轮完整对比与聚焦对比均确认指标区、曲线、图例、排名和下方分析卡的层级接近确认图。
- 没有剩余可执行的 P0/P1/P2。
- 字体、布局节奏、颜色令牌、数据图表质量、文案与交互状态全部通过；动态数值差异明确归类为真实数据状态差异。
- 可选 P3：未来若商品数明显超过 8 件，可进一步增加桌面图例折叠；当前 5 件真实商品不需要该处理。

## 交互、响应式与可访问性

- 桌面端同时显示 5 条真实商品曲线；指标切换、图例选择、排名选择和 Tooltip 均与当前商品同步。
- Tooltip 展示累计值、相对 T0 增量和北京时间记录时间。
- 移动端只绘制 1 条选中商品曲线；“上一件商品”和“下一件商品”实测均为 `44 × 44px`，从 `1 / 5` 切换到 `2 / 5` 后，图例与排名同步选中第二件商品，再恢复第一件商品。
- 移动端“只绘制真实检查点”提示隐藏；四项指标保持等宽；排名行实测高度 `44px`。
- 键盘语义、`aria-current`、`aria-label` 与焦点样式保留；`prefers-reduced-motion` 下关闭曲线动效。
- 最终浏览器控制台日志为 `[]`，没有 error 或 warning。

## 数据、自动化与运行边界

- 后端完整测试：`199 passed, 1 warning`；警告为既有依赖弃用提示。
- 前端交互测试：`16 passed`。
- TypeScript、生产构建、Sites Worker `4 passed` 与 `git diff --check` 均通过。
- 本轮没有改 SQLite 结构，不需要迁移；没有触发采集、投流、检查点记录或其他真实经营数据写入。
- 常驻服务由唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 运行，工作目录为 `/Users/chentao/Documents/New project 3`；`127.0.0.1:8877` 单一监听，`/api/health` 返回 `ok`。

final result: passed

---

# 2026-08-15 商品经营「未来 7 天经营方案」v2.4.3 Design QA

## 验收目标与真实状态

- 路由：`http://127.0.0.1:8877/?build=20260815-product-plan-v243#商品经营/exposure`。
- 真实计划：8月15、17、19、21日为多商品曝光；8月16、18、20日为商品表达优化。8月15日展示 5 件真实推荐商品、批次费用 ¥5.9、`24h内 · 计划固定`，且冷却冲突为 0。
- 最近实际投放为 8月13日16时14分、5 件商品、¥6.1；该批次因基线无效终止观察，但投放事实与同商品冷却保留，不再驱动未来观察日。
- 本轮只重算本地可解释经营建议并验证批次草稿预填；没有购买曝光、采集闲鱼、提交批次、修改商品或写入测试经营数据。

## 视觉真值与实现证据

- 8月15日确认预览：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-preview-20260815/01-8月15日曝光详情态.png`，`1440 × 1440`。
- 8月16日确认预览：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-preview-20260815/02-8月16日优化详情态.png`，`1440 × 1440`。
- 浏览器 8月15日实现：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-v243-final/desktop-viewport.png`，`2530 × 1423`；浏览器 CSS 视口 `2560 × 1440`，`devicePixelRatio = 1`。
- 浏览器 8月16日实现：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-v243-final/desktop-aug16-optimize.png`，`2530 × 1423`。
- 全视图并排证据：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-v243-final/reference-vs-implementation.png`，`2880 × 1510`。
- 经营方案聚焦对比：`/Users/chentao/Documents/New project 3/artifacts/product-operating-plan-v243-final/focused-plan-comparison.png`，`2800 × 1030`。源图与实页分别按各自经营方案可见区域裁切并等比装入等宽面板；没有拉伸图片。
- 确认图是去除应用外壳的 `1440px` 设计预览，当前内置浏览器固定为更宽的真实应用视口，所以实现保持相同信息层级、材质和交互，但利用额外宽度压缩纵向高度；这属于响应式产品约束，不是内容缺失。

## 必查视觉表面

- 字体与层级：继续使用产品系统字体栈；英文眉题、中文主标题、日期、商品名、原因、角色、费用和操作形成与确认图一致的六级层次。长商品名保持单行截断，实际 5 件商品没有被遮挡。
- 间距与布局：最近批次状态条、七日轨道、左侧当天详情、右侧计划依据和底部图例顺序与确认图一致。当前宽屏使用约 `70/30` 的详情与依据分栏；页面 `scrollWidth = clientWidth = 2530`，没有整体横向溢出。
- 色彩与令牌：沿用现有浅色白紫 SaaS、1px 紫灰边界、克制阴影、紫色主操作、绿色安全状态和橙色优化语义；没有增加黑色工作台、厚玻璃或不透明紫色大面板。
- 图像与资产：该组件只有真实业务信息和 Phosphor 图标，不需要新增位图。没有使用表情、占位图、手绘 SVG 或截图文字替代可访问 UI。
- 文案与内容：页面明确区分“24h内计划固定”“手动固定”“商品冷却中”；七个日期都显示动作、商品数和费用边界，选中日展示真实商品名、角色和原因。没有把计划固定写成禁用或冷却，也没有复用确认图示例数据替换真实数据。

## 交互与可访问性

1. 选择8月16日后，只有一张日期卡保持选中；详情标题变为“8月16日 · 先优化商品表达”，展示“校园二手平台完整源码”和“Excel批量处理｜公式图表代做”，主操作为“查看 2 件商品修改建议”。
2. 点击修改建议后，Hash 路由进入 `#商品经营/launch/product/1063498329657`，上新与修改页面的“上新雷达”真实可见。
3. 返回曝光页并选择8月15日，点击“按这 5 件建立批次”只打开人工确认草稿；弹层预选 5 件计划商品，整批费用为 `5.9`，关闭弹层后没有写入批次。
4. 当前视口没有横向溢出；窄屏堆叠、44px 操作目标和减少动态效果由响应式 CSS 与 `product-exposure-v24` 交互契约覆盖。本次内置浏览器没有可用的视口模拟能力，因此没有把静态断点检查冒充 390px 浏览器截图。
5. 页面控制台日志为 `[]`；日期切换、Hash 路由、批次草稿打开与关闭期间没有新增 error 或 warning。

## 比较历史与发现

- 第一轮规则验收发现 8月16日仍显示“观察长尾效果”。根因是已终止批次的商品冷却仍被旧分支当作观察来源；修复后冷却只保留真实防重叠作用，已终止批次不再生成观察日。
- 第二轮真实 API 重算得到规则 `v2.4.3` 第 4 版：15/17/19/21曝光，16/18/20优化；旧版 `locked=true` 已清除，只有8月15日准确落在未来24小时稳定窗口。
- 视觉对比确认状态条、七日轨道、当天商品详情、依据卡、安全提示和主操作全部出现。宽屏比确认图更紧凑，是为了利用真实 `2560px` 视口并避免恢复过长页面。
- 没有剩余可执行的 P0、P1 或 P2。可选 P3：若未来内置浏览器提供固定视口模拟，可再补一张完全同尺寸的 `1440 × 900` 对比截图，不影响当前功能与视觉验收。

## 工程与运行证据

- 后端：`273 passed, 1 warning`；warning 为共享环境既有 Starlette/httpx 弃用提示。
- 前端交互：`55 passed`；TypeScript 无错误；生产构建通过；Sites Worker `4 passed`；目标文件 `git diff --check` 通过。
- SQLite：`integrity_check = ok`，`foreign_key_check` 无结果。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 已受控重启，当前 PID `98250`；只有该进程监听 `127.0.0.1:8877`，`/api/health` 返回 `ok`。
- 未执行 Git 提交、推送、合并、公开部署或真实闲鱼操作。

final result: passed

# 第四阶段：验收、真实进度和经营闭环

## 验收范围与视觉证据

- 验收页面：`http://127.0.0.1:8877/#项目管理/p-1786013284727/codex`，使用既有唯一 LaunchAgent 服务与 Ego Lite 任务空间，没有启动第二端口或第二个后端实例。
- 修改前桌面基线：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/baseline-desktop-1470x833.png`。
- 修改前移动基线：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/baseline-mobile-390x844.png`。
- 已确认桌面设计预览：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/design-preview-desktop-1470x900.png`。
- 已确认移动设计预览：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/design-preview-mobile-390x844.png`。
- 最终桌面实现：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/implementation-desktop-final-1470x833.png`。
- 最终移动实现：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/implementation-mobile-final-390x844.png`。
- 桌面并排比较：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/comparison-desktop-source-vs-final.png`。
- 移动并排比较：`/Users/chentao/Documents/New project 3/artifacts/codex-verification-phase4-preview-20260818/comparison-mobile-source-vs-final.png`。
- 源视觉与最终实页按各自真实视口等比比较；桌面以 `1470 × 833` 实页为准，移动以 `390 × 844` 实页为准，没有拉伸截图或把静态预览冒充运行页面。

## 视觉、内容与响应式检查

- 字体与层级：继续使用产品既有字体和浅色 SaaS 层级；项目标题、正式工时、三种进度、验收点、证据、Git 与交付清单的主次关系清楚。三种进度各自占用独立卡片，没有合并成一条模糊进度。
- 布局与密度：桌面在原 Codex 实时事件与托管运行工作台上方增加验收工作台；右侧核验详情抽屉不遮挡主列表。移动端将进度卡、空状态和操作区压缩为适合 `390px` 的纵向节奏，并为既有全局浮动记账按钮保留底部安全区；两个视口均无整体横向溢出。
- 色彩与令牌：沿用浅白紫背景、单层细边界、克制阴影和既有状态语义；没有引入黑色工作台、厚玻璃、双层边界或与项目系统冲突的新令牌。
- 图像与资产：本阶段工作台只使用结构化数据、现有图标和文字状态，不需要新增装饰位图，也没有嵌入截图文字、占位业务数据或不透明图片背景。
- 文案与真实性：正式运行徽标为“当前真实项目 · 实时更新”；真实项目当前显示 Codex 执行、已实现、已验证交付均为 `0%`，历史手工进度 `100%` 被明确隔离。空验收计划显示事实性空状态，不用示例任务伪造已接入结果。
- 历史兼容：项目头部使用“已验证交付进度”；旧项目原手工值保存在 `legacy_progress` 并单独解释，不再冒充验收进度。项目详情刷新后仍恢复同一项目和 Codex 标签。

## 交互、接口与可访问性

1. 桌面与移动页面都可读取三种进度、验收点、工时、Git 和交付清单；无确认计划时展示真实空状态。
2. 移动端人工工时表单可以打开，四个字段真实存在，空表单时提交按钮禁用；验收过程中没有提交表单，因此没有向真实数据库写入测试业务记录。
3. 核验详情在桌面使用右侧抽屉、窄屏使用底部抽屉；操作目标、焦点顺序、Escape/关闭路径与 reduced-motion 适配由组件及交互回归覆盖。
4. 页面读取的项目、Codex 同步、验收和交付接口均返回 `200`；浏览器没有捕获 JavaScript error 或 unhandled rejection。
5. Hash 刷新后仍回到 `#项目管理/p-1786013284727/codex`，没有因无验收计划跳转到其他项目或标签。

## 两轮视觉修复与比较结论

- 第一轮发现设计预览阶段的“修改前设计预览”标记仍出现在正式运行语境；正式实现改为“当前真实项目 · 实时更新”，避免把已运行页面误写成预览稿。
- 第二轮发现 `390 × 844` 下进度卡和空状态纵向节奏偏松，且既有浮动记账按钮可能侵入末端内容；随后压缩移动间距、保持可读点击区，并增加底部安全留白。
- 最终并排比较确认核心层级、浅色材质、三卡结构、空状态和核验抽屉与已确认方向一致。真实项目数值和正式运行文案与设计预览不同，是事实数据和产品化状态，不是视觉漂移。
- 最终没有剩余可执行的 P0、P1 或 P2 视觉问题。

## 工程、数据与运行证据

- 后端全量：`358 passed, 1 skipped`；跳过项为既有条件跳过，warning 为共享环境的 Starlette/httpx、SQLite datetime 与 Alembic 配置弃用提示，以及一个 Pydantic 测试输入类的 pytest 收集提示。
- 前端交互：`80 passed`；TypeScript `tsc --noEmit` 通过；Vite 生产构建通过；Sites Worker `4 passed`。构建仅保留项目既有的大 chunk 提示。
- 0029 迁移与完整链覆盖 `0001 → … → 0017–0025 → 0026 → 0027 → 0028 → 0029`；旧项目兼容、历史进度保留和 0028→0029 数据迁移均有自动化测试。
- 最终对抗性回放发现“新计划确认后可能短暂沿用上一版已验证进度”；现已让计划确认在同一事务内调用唯一 `ProjectProgressService`，新增、退役或重权重任务会立即重算，稳定 ID 对应的已验证验收点仍保留。聚焦回归与后端全量均通过。
- 真实数据库迁移前备份：`/Users/chentao/Documents/New project 3/data/backups/xianyu_operator-before-phase4-live-20260818-024616.db`，SHA-256 `0f1f6ab96435f1ecb79c778bbedf306bbbb495c12f43594e3b36feb5c9aaced0`。
- 本阶段没有 Git 提交、推送、PR、合并、公开部署、客户发送或真实外部业务动作。

final result: passed

---

# 2026-08-19 全局「小策 · AI 技术与商业合伙人」Agent Design QA

## 验收目标与来源

- 目标：在现有「循营 · 一人经营台」中提供全局可拖动的小策入口；点击后打开只读 AI 对话面板，可选择人工配置的多模型 Profile，基于批准知识库与本地客户、商品、项目、财务和经营分析数据回答问题，并只给出人工执行的下一步建议。
- 已确认设计预览：`/Users/chentao/.codex/generated_images/01a01006-1f66-74d3-8bb1-0c47c5bb13ba/exec-e29603d6-145e-44c3-8814-f6b21ace5ca8.png`。
- 最终视觉证据目录：`/Users/chentao/Documents/New project 3/artifacts/global-agent-final-20260819/`。
- 主要实现：`src/components/GlobalAgentLauncher.tsx`、`src/components/GlobalAgentPanel.tsx`、`src/components/GlobalAgentSettingsCard.tsx`、`src/components/global-agent.css`、`src/App.tsx`、`backend/app/agents/global_agent/`、`backend/app/global_agent_api.py`、`backend/app/global_agent_schemas.py`、`migrations/versions/20260819_0033_global_agent.py`。

## 实页与像素证据

- 桌面修改前：`desktop-before.png`，`1470 × 900`。
- 桌面面板：`desktop-open-fixed.png`，`1470 × 900`；实页面板约 `600 × 650px`。
- 桌面真实回答：`desktop-answer-complete.png` 与 `desktop-answer-evidence.png`，均为 `1470 × 900`。
- 移动首页抽屉：`mobile-home-open-settled.png`，`390 × 844`；当前页面无底部导航时抽屉贴底。
- 移动小策页面抽屉：`mobile-partner-open-fixed.png`，`390 × 844`；真实存在 `72px` 底部导航时精确避让。
- 设置中心：`desktop-settings.png` 与 `desktop-settings-editor.png`，均为 `1470 × 900`。
- 全视图与聚焦同图对照：`design-qa-comparison.png`，`2990 × 1058`；左侧为最终桌面与移动回答态，右侧为已确认桌面与移动预览。截图均按原比例排列，没有把预览冒充实页或用示例值替换真实数据。

## 视觉、交互与可访问性

- 桌面使用锚定式浅色面板，移动使用底部抽屉；保持现有白紫 SaaS、单层细边界、克制阴影和小策独立丝带头像，没有恢复机器人、鸭子或黑色聊天工作台。
- 入口可在视口内自由拖动并左右吸附；拖动只持久化坐标，不创建线程或运行。点击与拖动阈值分离，拖动不会误开面板。
- 打开面板默认只读取 bootstrap；新对话、历史对话、Profile 选择、取消运行、事实/原因/建议、证据来源、观察周期、置信度、限制与唯一人工下一步均有清晰层级。
- 桌面关闭后焦点返回头像；Escape、焦点陷阱、至少 `44 × 44px` 的操作目标和 `prefers-reduced-motion` 均覆盖。桌面与 `390 × 844` 均无横向溢出。
- 设置中心显示多个模型 Profile、模型目录和人工知识索引更新；不提供密钥输入框，未把 Secret 写入浏览器、SQLite、页面或截图。

## 两次实页修复历史

- 第一轮发现：拖动头像后，如果浏览器未派发尾随 click，下一次正常点击会被残留抑制状态吞掉。修复为在拖动结束后零延迟复位，并覆盖 `pointercancel`；复测确认拖动不打开、下一次点击正常打开。
- 第二轮发现：首页移动视图没有底部导航却固定预留 `72px`，同时标题栏和快捷建议的部分控件不足 `44px`。修复为仅在页面真实存在 `.xunying-mobile-nav` 时避让 `72px`，并统一移动操作目标；首页贴底、小策页与导航顶边精确衔接。
- 最终对照没有剩余可执行的 P0、P1 或 P2；与预览的文案和数据差异来自真实 Provider、知识索引与经营数据，不属于视觉漂移。

## 真实性与安全边界

- 真实 DeepSeek 问答完成，使用 `finance_summary` 与 `business_analysis` 两个只读工具，引用 1 条批准知识路径与 2 个本地业务来源，并展示中置信度、观察周期、限制与唯一人工下一步。
- 模型、线程、消息、运行和工具调用均持久化；工具调用与消息遵循先持久化再进入 EventHub。Provider 失败不静默降级，模型引用只能来自实际检索或工具白名单。
- 知识索引只读取批准的 `10-Projects`、`20-Decisions`、`30-Patterns`、`40-Cross-Domain`、`60-Playbooks`，不读取 `00-Inbox`、客户图片或明显密钥内容。
- 本阶段没有执行客户触达、商品修改、项目变更、账本修改、投流或其他真实业务动作，也没有启动或控制外部 Codex 任务。

## 工程、数据库与单实例证据

- 后端全量：`392 passed, 1 skipped`；全局 Agent 聚焦测试：`7 passed`。保留项均为既有 Starlette/httpx、SQLite datetime、Alembic 配置弃用提示和一个 Pydantic 测试输入类收集提示。
- 前端交互：`90 passed`；TypeScript 通过；Vite 生产构建通过并生成 Sites 交付结构；Sites Worker `4 passed`；`git diff --check` 通过。构建仅保留既有的大 chunk 提示。
- LaunchAgent `com.chentao.xianyu-ledger-assistant` 为 `running`，PID `5782`；只有该进程监听 `127.0.0.1:8877`，`/api/health` 返回 `{"status":"ok"}`。
- 生产 SQLite `integrity_check=ok`、外键违规 `0`，0033 的 9 个全局 Agent 核心表齐全；当前为 3 个模型 Profile、16 篇有效知识文档、124 个知识分块和 124 条 FTS 记录。
- 生产库保留 1 个真实只读问答线程、1 个完成运行和 2 个完成工具调用，没有为了验收伪造额外业务数据。迁移前人工备份与 startup 自动备份均为 mode `0600`，分别位于 `data/backups/xianyu_operator-before-global-agent-manual-20260819-125038.db` 和 `data/backups/xianyu_operator-before-global-agent-20260819-125053.db`。
- 未执行 Git 提交、推送、PR、合并或公开部署。

final result: passed

---

# 2026-08-19 客户消息精简与原小策对话框延续 Design QA

## 源视觉、实页证据与归一化

- 源视觉真值目录：`/Users/chentao/Documents/New project 3/artifacts/customer-message-xiaoce-preview-20260819/`。
- 客户消息桌面源图：`customer-messages-two-column-desktop.png`，`1470 × 833`；最终实页：`/Users/chentao/Documents/New project 3/artifacts/customer-message-xiaoce-final-20260819/customer-messages-desktop-1470x833.png`，CSS 视口与截图均为 `1470 × 833`，`deviceScaleFactor = 1`。
- 客户消息移动源图：`customer-messages-two-column-mobile.png`，`390 × 844`；最终实页：`/Users/chentao/Documents/New project 3/artifacts/customer-message-xiaoce-final-20260819/customer-messages-mobile-390x844.png`，CSS 视口与截图均为 `390 × 844`，`deviceScaleFactor = 1`。
- 小策桌面源图：`xiaoce-requirement-analysis-desktop.png` 与 `xiaoce-requirement-blueprint-desktop.png`，均为 `1470 × 833`；最终原对话框空态：`xiaoce-dialog-desktop-1470x833.png`，历史普通回答态：`xiaoce-history-desktop-1470x833.png`，均为 `1470 × 833`。
- 小策移动源图：`xiaoce-requirement-analysis-mobile.png` 与 `xiaoce-requirement-blueprint-mobile.png`，均为 `390 × 844`；最终原对话框空态：`xiaoce-dialog-mobile-390x844.png`，CSS 视口与截图均为 `390 × 844`，`deviceScaleFactor = 1`。
- 源图和实现截图已在同一比较输入中按相同像素尺寸打开；全页已能清晰核对字体、间距、表面、控件与内容层级，因此无需额外裁切聚焦图。需求分析/蓝图源图的产物区只用于核对已实现组件的布局约束；生产实页未调用模型生成新产物，也未把静态预览冒充真实回答。

## 必查视觉表面

- 字体与层级：继续使用循营现有中文字体栈、字号、字重和浅色 SaaS 层级；客户消息页保留“筛选 → 会话 → 消息”顺序，小策保留标题、对话/上下文/模型选择、对话区和输入区。用户消息不再显示“你”，并在历史实页中实测 `align-self: flex-end`。
- 间距与布局：桌面工作台为两列，会话区约 `273.45px`、消息区约 `873.55px`；移动端会话列表 `292px` 在上、消息区 `540px` 在下。桌面小策面板实测 `760 × 785px`，移动抽屉修复后为完整 `390 × 590px`，两端均无整体横向溢出。
- 色彩与令牌：保持白紫表面、单层细边界、克制阴影、紫色选中态和小策丝带头像；没有恢复黑色聊天工作台、机器人、鸭子或新的视觉体系。
- 图像与资产：继续使用项目已有透明循营标识和小策头像，图标继续来自现有 Phosphor 图标库；没有新增占位图、CSS 图形、手工 SVG 或生成图片来替代产品资产。
- 文案与内容：客户消息副标题与确认预览一致，明确“分析与判断统一由小策按需完成”。页面没有需求分析、回复草稿、报价转化、客户绑定、导出工作台或 GPT 导入入口；真实客户名、消息和提醒数量与预览示例不同，属于真实数据差异。

## 交互、响应式与安全边界

1. 桌面和 `390 × 844` 均可查看真实会话与消息；移动端顺序实测为会话列表在上、消息记录在下，`scrollWidth = clientWidth`。
2. 原可拖动小策图标保留。Ego Lite 使用单次原生指针事件实测点击打开原对话框；Escape 关闭后焦点返回“打开小策全局助手；可拖动位置”。
3. 原对话框继续提供历史对话、客户上下文、多模型、新对话、输入框和发送按钮。只打开面板读取 bootstrap；选择既有历史对话只执行 GET，没有发送问题、触发模型或创建新线程。
4. 移动抽屉关闭按钮和发送按钮均为 `44 × 44px`；打开时 `body.global-agent-open` 锁定背景滚动，关闭后移除，抽屉占满 `390px` 视口宽度。
5. 历史普通回答仍显示事实、原因、建议、证据、置信度与限制；两条既有用户消息均靠右。历史普通回答没有错误附带需求分析或蓝图产物。
6. 需求分析和四层蓝图只在模型返回严格结构时按需渲染；本轮安全边界禁止生产模型调用，因此没有为了截图创建假客户产物。相关条件渲染、四层布局、移动两列和后端证据引用由自动化测试覆盖。
7. Hash 刷新后仍恢复 `#客户消息`；页面、会话、全局 Agent bootstrap 与客户上下文接口均返回 `200`。Ego Lite 事件队列没有 exception、error、failed 或 `loadingFailed`。

## 比较历史与修复

- Pass 1 `[P2 · Copy]`：实页标题副文案仍写“完成可追溯的需求分析”，与已确认“客户消息页只保留会话与消息，分析交给小策”不一致。修复为“集中查看客户咨询与历史记录，分析与判断统一由小策按需完成”；同视口重建和截图确认。
- Pass 2 `[P2 · Responsive/Behavior]`：移动端打开小策后背景纵向滚动条仍存在，抽屉实际只有 `375px`，与 `390px` 源图不一致且背景可继续滚动。修复为打开时添加 `global-agent-open` 滚动锁，关闭时清理；重建后实测抽屉 `left=0 / right=390 / width=390`、背景不可滚动、关闭后焦点与 body 状态恢复。
- Pass 3：桌面、移动、空态与历史普通回答态复核未发现新的 P0/P1/P2。源图中专门的需求分析/蓝图产物态因禁止真实模型调用未做生产同态截图；该限制已明确记录，不影响客户消息精简和原对话框延续的实页结论。

## 工程、数据库与单实例证据

- 后端全量在本轮主体实现后为 `407 passed, 1 skipped`；最终视觉修复仅涉及前端副文案、面板滚动锁和对应前端契约测试，没有改动后端。
- 前端全量交互 `88 passed`；TypeScript 通过；Vite 生产构建与 Sites 结构生成通过；Sites Worker `4 passed`；`git diff --check` 通过。构建只保留既有大 chunk 提示。
- 生产 SQLite `integrity_check=ok`、外键违规 `0`；验收前后仍为 `global_agent_threads=2`、`global_agent_messages=5`、`global_agent_runs=3`、`global_agent_conversation_summaries=0`，没有创建测试对话、消息、运行或客户总结。
- 唯一 LaunchAgent `com.chentao.xianyu-ledger-assistant` 受控恢复后 PID 为 `28590`；只有该进程监听 `127.0.0.1:8877`，`/api/health` 返回 `{"status":"ok"}`。
- 未执行 Git 提交、推送、PR、合并、公开部署、客户发送、报价、项目变更、商品操作或真实模型调用。

final result: passed
