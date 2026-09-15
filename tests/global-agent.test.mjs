import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const appPath = new URL("../src/App.tsx", import.meta.url);
const launcherPath = new URL("../src/components/GlobalAgentLauncher.tsx", import.meta.url);
const panelPath = new URL("../src/components/GlobalAgentPanel.tsx", import.meta.url);
const chatGPTAccessPath = new URL("../src/components/ChatGPTConversationAccessCard.tsx", import.meta.url);
const settingsPath = new URL("../src/components/GlobalAgentSettingsCard.tsx", import.meta.url);
const stylesPath = new URL("../src/components/global-agent.css", import.meta.url);
const otherPagesPath = new URL("../src/pages/OtherPages.tsx", import.meta.url);
const otherStylesPath = new URL("../src/pages/other-pages.css", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const agentServicePath = new URL("../backend/app/agents/global_agent/service.py", import.meta.url);
const agentSchemasPath = new URL("../backend/app/global_agent_schemas.py", import.meta.url);
const agentApiPath = new URL("../backend/app/global_agent_api.py", import.meta.url);

test("small strategy partner is globally mounted and home insight opens it", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /import \{ GlobalAgentLauncher \} from "\.\/components\/GlobalAgentLauncher"/);
  assert.match(app, /<GlobalAgentLauncher onNavigate=\{navigateFromGlobalAgent\} \/>/);
  assert.match(app, /new CustomEvent\("xunying:global-agent-open"\)/);
  assert.match(app, /target === "settings"[\s\S]*openSettings\("AI与回复"\)/);
  assert.match(app, /products: "商品经营"/);
  assert.match(app, /customers: "客户管理"/);
  assert.match(app, /projects: "项目管理"/);
  assert.match(app, /"business-analysis": "经营分析中心"/);
  assert.match(app, /AI经营助手: \{ title: "小策 · AI 技术与商业合伙人"/);
});

test("launcher separates dragging from clicking and persists position only", async () => {
  const source = await readFile(launcherPath, "utf8");

  assert.match(source, /const POSITION_KEY = "xunying\.global-agent\.launcher\.v1"/);
  assert.match(source, /Math\.hypot\(dx, dy\) > 5/);
  assert.match(source, /suppressClickRef\.current = true/);
  assert.match(source, /if \(suppressClickRef\.current\)[\s\S]*return;/);
  assert.match(source, /setPointerCapture/);
  assert.match(source, /releasePointerCapture/);
  assert.match(source, /window\.setTimeout\(\(\) => \{ suppressClickRef\.current = false; \}, 0\)/);
  assert.match(source, /onPointerCancel=\{\(\) => \{ dragRef\.current = null; suppressClickRef\.current = false; \}\}/);
  assert.match(source, /localStorage\.setItem\(POSITION_KEY, JSON\.stringify\(safe\)\)/);
  assert.doesNotMatch(source, /localStorage\.setItem\([^P]/);
  assert.match(source, /"\.floating-add", "\.xunying-mobile-nav"/);
  assert.match(source, /ArrowLeft[\s\S]*ArrowRight[\s\S]*ArrowUp[\s\S]*ArrowDown[\s\S]*Home/);
});

test("opening is read-only and sending explicitly creates a persisted run", async () => {
  const panel = await readFile(panelPath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(panel, /if \(!open\) return;[\s\S]*void loadBootstrap\(\)/);
  assert.match(panel, /globalAgentBootstrap\(\)/);
  assert.match(panel, /const submit = async/);
  assert.match(panel, /createGlobalAgentThread/);
  assert.match(panel, /sendGlobalAgentMessage/);
  assert.doesNotMatch(panel, /useEffect\([\s\S]{0,240}sendGlobalAgentMessage/);
  assert.match(panel, /分析可读 · 客户写入需人工确认/);
  assert.match(panel, /globalAgentCustomerContextOptions/);
  assert.match(panel, /updateGlobalAgentThreadContext/);
  assert.match(panel, /持续分析未开启时不会自动调用模型/);
  assert.match(panel, /新消息先写入 SQLite，再于 30 秒静默窗口或 60 秒最长等待后自动增量分析/);
  assert.match(panel, /下次核验 200 条/);
  assert.match(panel, /图片按授权/);
  assert.match(panel, /不自动回复/);
  assert.match(panel, /消息 #\$\{reference\.slice/);
  assert.match(panel, /event\.type === "customer_context_updated"/);
  assert.match(panel, /thread\?\.customer_context\?\.conversation_id === Number\(event\.conversation_id\)/);
  assert.match(panel, /\[open, thread\?\.id, thread\?\.customer_context\?\.conversation_id\]/);
  assert.doesNotMatch(panel, /购买推广|发送客户消息|修改商品|变更项目状态/);
  assert.match(service, /"\/api\/global-agent\/bootstrap"/);
  assert.match(service, /"\/api\/global-agent\/customer-context-options"/);
  assert.match(service, /\/api\/global-agent\/threads\/\$\{encodeURIComponent\(threadId\)\}\/context/);
  assert.match(service, /\/api\/global-agent\/threads\/\$\{encodeURIComponent\(threadId\)\}\/messages/);
  assert.match(service, /method: "POST"/);
});

test("user messages omit the self label and stay right aligned", async () => {
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(panel, /<article className="agent-user-message" key=\{message\.id\}><p>\{message\.content\}<\/p><\/article>/);
  assert.doesNotMatch(panel, /agent-user-message" key=\{message\.id\}><span>你<\/span>/);
  assert.match(styles, /\.agent-user-message \{[\s\S]*width: fit-content;[\s\S]*max-width: min\(86%, 470px\);[\s\S]*align-self: flex-end;/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.agent-user-message \{ max-width: 92%; \}/);
});

test("answers expose evidence chain confidence period limits and one next step", async () => {
  const panel = await readFile(panelPath, "utf8");

  assert.match(panel, />事实</);
  assert.match(panel, />原因</);
  assert.match(panel, />建议</);
  assert.match(panel, /answer\.confidence/);
  assert.match(panel, /answer\.observation_period/);
  assert.match(panel, /限制与反证/);
  assert.match(panel, /message\.citations/);
  assert.match(panel, /citation\.relative_path/);
  assert.match(panel, /message\.tool_references/);
  assert.match(panel, /answer\.next_step/);
  assert.match(panel, /answer\.target_page/);
  assert.match(panel, /不会静默切换其他模型/);
});

test("execution trace shows persisted safe steps and tool calls without hidden reasoning", async () => {
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const api = await readFile(agentApiPath, "utf8");
  const assistantMessageSource = panel.slice(
    panel.indexOf("function AssistantMessage"),
    panel.indexOf("export function GlobalAgentPanel"),
  );

  assert.match(service, /globalAgentRunTrace:[\s\S]*\/api\/global-agent\/runs\/\$\{encodeURIComponent\(runId\)\}\/trace/);
  assert.match(api, /"\/runs\/\{run_id\}\/trace"[\s\S]*response_model=AgentRunTraceView/);
  assert.match(panel, /event\.type !== "global_agent_run"[\s\S]*event\.type !== "global_agent_tool"[\s\S]*event\.type !== "global_agent_step"/);
  assert.match(panel, /if \(eventRun\) void refreshRunTrace\(eventRun\)/);
  assert.match(panel, /if \(event\.type === "global_agent_run"\) void refreshThread\(eventThread\)/);
  for (const label of ["上下文", "证据", "工具", "生成", "校验", "保存"]) assert.match(panel, new RegExp(`"${label}"`));
  assert.match(panel, /本次工具调用/);
  assert.match(panel, /读取原因/);
  assert.match(panel, /查看全部 \$\{trace\.total_steps\} 个步骤/);
  assert.match(panel, /旧记录未保存节点轨迹/);
  assert.match(panel, /仅显示可审计摘要 · 不展示隐藏思维、原始 Prompt 或敏感数据/);
  assert.match(panel, /function toolProvenance/);
  assert.match(panel, /formatObservedAt\(tool\.observed_at\)/);
  assert.match(panel, /revision \$\{tool\.revision\}/);
  assert.match(panel, /tool\.read_only \? "只读"/);
  assert.match(panel, /agent-tool-provenance/);
  assert.doesNotMatch(panel, /tool\.sensitivity/);
  assert.match(panel, /function AgentLiveProgress/);
  assert.match(panel, /activeTool\?\.summary[\s\S]*activeStep\?\.summary/);
  assert.match(panel, /role="status" aria-live="polite"/);
  assert.match(panel, /agent-run-duration/);
  assert.match(panel, /`用时 \$\{formatElapsedDuration\(elapsedMs\)\}`/);
  assert.match(panel, /message\.run_elapsed_ms/);
  assert.match(panel, /<CaretRight size=\{16\} \/>/);
  assert.match(panel, /traceExpanded && \(trace[\s\S]*<AgentExecutionTrace/);
  assert.match(assistantMessageSource, /return <>[\s\S]*agent-trace-history[\s\S]*<article className="agent-answer-card">/);
  assert.doesNotMatch(assistantMessageSource, /<article className="agent-answer-card">[\s\S]*agent-trace-history/);
  assert.doesNotMatch(panel, /arguments_json|result_json|detail_json|system_prompt/);
  assert.match(styles, /\.agent-trace-step-toggle[\s\S]*min-height: 44px/);
  assert.match(styles, /\.agent-execution-trace \{[\s\S]*width: 100%;[\s\S]*flex: 0 0 auto;/);
  assert.match(styles, /\.agent-live-progress \{[\s\S]*min-height: 64px;[\s\S]*grid-template-columns: 32px minmax\(0, 1fr\) 44px;/);
  assert.match(styles, /\.global-agent-conversation > \.agent-trace-history \{[\s\S]*width: 100%;[\s\S]*justify-items: center;/);
  assert.match(styles, /\.agent-trace-history > \.agent-run-duration \{[\s\S]*min-height: 44px;[\s\S]*border-radius: 999px;/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.agent-trace-summary \{ grid-template-columns: repeat\(2/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-trace-state > i\.is-active[\s\S]*\.agent-live-progress > i/);
  assert.match(service, /run_elapsed_ms: number \| null/);
  assert.match(service, /source: string;[\s\S]*observed_at: string \| null;[\s\S]*revision: number \| null;[\s\S]*read_only: boolean;[\s\S]*sensitivity: string;/);
});

test("the original chat renders requirement analysis and four-layer blueprints only when returned", async () => {
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const service = await readFile(agentServicePath, "utf8");
  const schemas = await readFile(agentSchemasPath, "utf8");

  assert.match(panel, /answer\.requirement_analysis && <RequirementAnalysisCard/);
  assert.match(panel, /answer\.requirement_blueprint && <RequirementBlueprintCard/);
  assert.match(panel, /客户已确认/);
  assert.match(panel, /经营者补充/);
  assert.match(panel, /项目目标/);
  assert.match(panel, /功能能力/);
  assert.match(panel, /实施阶段/);
  assert.match(panel, /交付验收/);
  assert.match(panel, /estimated_hours === null \? " · 工时待核验"/);
  assert.match(styles, /\.agent-blueprint-grid \{ display: grid; grid-template-columns: repeat\(4/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.agent-blueprint-grid \{ grid-template-columns: repeat\(2/);
  assert.match(service, /operator-note:/);
  assert.match(service, /普通问答必须让 requirement_analysis、requirement_blueprint 和[\s\S]*execution_plan 为 null/);
  assert.match(service, /invalid_customer_confirmed/);
  assert.match(service, /invalid_operator_decisions/);
  assert.match(schemas, /class AgentRequirementBlueprint/);
  assert.match(schemas, /实施阶段存在循环依赖/);
});

test("explicit execution plans expose bounded stages, workspaces, tests, acceptance and stop gates", async () => {
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(service, /export interface GlobalAgentExecutionPlanStage/);
  assert.match(service, /task_key: string;[\s\S]*workspace_key: string;[\s\S]*dependency_task_keys: string\[\];/);
  assert.match(service, /process_tests: string\[\];[\s\S]*acceptance_criteria: string\[\];[\s\S]*stop_conditions: string\[\];/);
  assert.match(service, /execution_plan\?: GlobalAgentExecutionPlan \| null/);
  assert.match(panel, /answer\.execution_plan && <ExecutionPlanCard/);
  for (const label of ["允许修改", "必须保持", "不在范围", "过程测试", "验收标准", "停止条件"]) assert.match(panel, new RegExp(label));
  assert.match(panel, /stage\.task_key/);
  assert.match(panel, /stage\.workspace_key/);
  assert.match(panel, /stage\.dependency_task_keys/);
  assert.match(styles, /\.agent-plan-boundaries \{[\s\S]*grid-template-columns: repeat\(3/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.agent-plan-boundaries,[\s\S]*\.agent-plan-stage-grid \{ grid-template-columns: 1fr; \}/);
});

test("ChatGPT short-lived reads use an independent settings path while persistent analysis stays explicit", async () => {
  const panel = await readFile(panelPath, "utf8");
  const accessCard = await readFile(chatGPTAccessPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const otherPages = await readFile(otherPagesPath, "utf8");
  const otherStyles = await readFile(otherStylesPath, "utf8");
  const service = await readFile(servicePath, "utf8") + await readFile(new URL("../src/data/customerAccessClient.ts", import.meta.url), "utf8");

  assert.match(service, /export type CustomerContextAudience = "openai_chatgpt" \| "openai_api" \| "codex_cli"/);
  assert.match(service, /customerConversationAccess:[\s\S]*\/api\/customer-context\/conversations\/\$\{conversationId\}\/access/);
  assert.match(service, /export interface CustomerContextThreadBinding/);
  assert.match(service, /customerContextThreadBindings:[\s\S]*"\/api\/customer-context\/thread-bindings"/);
  assert.match(service, /createCustomerContextThreadBinding:[\s\S]*"\/api\/customer-context\/thread-bindings"/);
  assert.match(service, /revokeCustomerContextThreadBinding:[\s\S]*\/api\/customer-context\/thread-bindings\/\$\{encodeURIComponent\(bindingId\)\}\/revoke/);
  assert.match(otherPages, /<ChatGPTConversationAccessCard onToast=\{onToast\} \/>/);
  assert.match(accessCard, /独立路径 · 不创建小策对话 · 不调用模型/);
  assert.match(accessCard, /globalAgentCustomerContextOptions\(\)/);
  assert.match(accessCard, /customerConversationAccess\(targetId\)/);
  assert.match(accessCard, /createCustomerContextThreadBinding\(/);
  assert.match(accessCard, /customerContextThreadBindings\(\)/);
  assert.match(accessCard, /conversation_id: selected\.conversation_id/);
  assert.match(accessCard, /expected_conversation_revision: access\.revision/);
  assert.match(accessCard, /allowText.*useState\(true\)/);
  assert.match(accessCard, /allowImages.*useState\(false\)/);
  assert.match(accessCard, /allowArtifacts.*useState\(false\)/);
  assert.match(accessCard, /expiresInSeconds.*useState\(3600\)/);
  assert.match(accessCard, /navigator\.clipboard\.writeText\(oneTimeKey\.instruction\)/);
  assert.match(accessCard, /线程绑定说明仅显示一次/);
  assert.match(accessCard, /多个对话可同时有效/);
  assert.match(accessCard, /同一客户授权续期时，请继续在原 ChatGPT 对话中使用本说明/);
  assert.match(accessCard, /以本次 context_key 替换旧密钥/);
  assert.doesNotMatch(accessCard, /请在一个全新的 ChatGPT 对话中使用本说明/);
  assert.match(accessCard, /不得省略、替换或猜测 context_key/);
  assert.doesNotMatch(accessCard, /capabilityToken/);
  assert.doesNotMatch(accessCard, /createGlobalAgentThread|sendGlobalAgentMessage|createCustomerContextGrant/);
  assert.doesNotMatch(accessCard, /deepseek[A-Z]|DeepSeekProvider|createDeepSeek/);
  assert.doesNotMatch(accessCard, /localStorage|sessionStorage|console\./);
  assert.doesNotMatch(accessCard, /\{capabilityToken\}/);

  assert.doesNotMatch(panel, /createOpenAIGrant|revokeOpenAIGrant|copyCapabilityOnce|capabilityToken/);
  assert.doesNotMatch(panel, /OpenAI 双层权限|>创建短时读取<|>替换短时读取</);
  assert.match(panel, /ChatGPT 网页读取不经过小策，也不会因为创建授权而调用模型/);
  assert.match(panel, /onNavigate\("settings"\)/);
  assert.match(panel, /DeepSeek 不可授权/);
  assert.match(panel, /原始文字/);
  assert.match(panel, /增量关联原图/);
  assert.match(panel, /仅明确绑定的客户会话/);
  assert.match(panel, /自动分析新消息/);
  assert.match(panel, /不自动回复/);
  assert.match(styles, /\.global-agent-context-access > button,[\s\S]*\.global-agent-openai-grant button \{[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.global-agent-context-card\.has-openai-grant \{ max-height: 48vh; \}/);
  assert.match(otherStyles, /\.chatgpt-conversation-access button \{ min-height: 44px; \}/);
  assert.match(otherStyles, /@media \(max-width: 720px\)[\s\S]*\.chatgpt-access-flow,[\s\S]*grid-template-columns: 1fr/);
  assert.match(otherStyles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("customer creation stays a reviewable proposal with a separate human write boundary", async () => {
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const agentService = await readFile(agentServicePath, "utf8");
  const schemas = await readFile(agentSchemasPath, "utf8");

  assert.match(panel, /answer\.customer_create_proposal && <CustomerCreateProposalCard/);
  assert.match(panel, /客户资料提案/);
  assert.match(panel, /仅为待确认草稿，尚未写入客户列表/);
  assert.match(panel, /customerIntakeCandidates\(\)/);
  assert.match(panel, /confirmGlobalAgentCustomerCreate/);
  assert.match(panel, /assistant_message_id: message\.id/);
  assert.match(panel, /expected_revision: latest\.revision/);
  assert.match(panel, /确认加入客户列表/);
  assert.match(panel, /返回修改/);
  assert.match(panel, /分析可读 · 客户写入需人工确认/);
  assert.match(styles, /\.agent-customer-proposal/);
  assert.match(service, /\/customer-create\/confirm/);
  assert.match(agentService, /def confirm_customer_create/);
  assert.match(agentService, /customer_create_proposal[\s\S]*if customer_create_requested[\s\S]*else None/);
  assert.match(schemas, /class AgentCustomerCreateProposal/);
  assert.match(schemas, /A reviewable proposal only/);
});

test("desktop anchor and mobile drawer preserve practical access", async () => {
  const launcher = await readFile(launcherPath, "utf8");
  const panel = await readFile(panelPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(launcher, /Math\.min\(760, window\.innerWidth - 48\)/);
  assert.match(launcher, /Math\.min\(790, window\.innerHeight - 48\)/);
  assert.match(styles, /\.global-agent-panel \{[\s\S]*width: var\(--agent-panel-width\);[\s\S]*height: var\(--agent-panel-height\)/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.global-agent-panel \{[\s\S]*bottom: env\(safe-area-inset-bottom, 0px\)/);
  assert.match(styles, /\.global-agent-root\.has-mobile-nav \.global-agent-panel \{[\s\S]*bottom: calc\(72px \+ env\(safe-area-inset-bottom, 0px\)\)/);
  assert.match(launcher, /setHasMobileNav\(Boolean\(document\.querySelector\("\.xunying-mobile-nav"\)\)\)/);
  assert.match(styles, /border-radius: 24px 24px 0 0/);
  assert.match(styles, /min-width: 44px;[\s\S]*min-height: 44px/);
  assert.match(panel, /document\.body\.classList\.add\("global-agent-open"\)/);
  assert.match(panel, /document\.body\.classList\.remove\("global-agent-open"\)/);
  assert.match(styles, /body\.global-agent-open \{ overflow: hidden; \}/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(panelPath.href, /GlobalAgentPanel/);
});

test("settings manage multiple non-secret profiles and approved knowledge only", async () => {
  const settings = await readFile(settingsPath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(settings, /新增模型/);
  assert.match(settings, /Codex 本机 CLI/);
  assert.match(settings, /DeepSeek/);
  assert.match(settings, /OpenAI Compatible/);
  assert.match(settings, /createGlobalAgentProfile/);
  assert.match(settings, /updateGlobalAgentProfile/);
  assert.match(settings, /globalAgentProviderModels/);
  assert.match(settings, /reindexGlobalAgentKnowledge/);
  assert.match(settings, /10-Projects、20-Decisions、30-Patterns、40-Cross-Domain 和 60-Playbooks/);
  assert.match(settings, /不会读取 00-Inbox、客户图片或密钥内容/);
  assert.doesNotMatch(settings, /API Key|password|secret/i);
  assert.match(service, /\/api\/global-agent\/providers\/\$\{encodeURIComponent\(provider\)\}\/models/);
});
