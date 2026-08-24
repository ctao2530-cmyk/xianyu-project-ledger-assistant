import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const appPath = new URL("../src/App.tsx", import.meta.url);
const launcherPath = new URL("../src/components/GlobalAgentLauncher.tsx", import.meta.url);
const panelPath = new URL("../src/components/GlobalAgentPanel.tsx", import.meta.url);
const settingsPath = new URL("../src/components/GlobalAgentSettingsCard.tsx", import.meta.url);
const stylesPath = new URL("../src/components/global-agent.css", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const agentServicePath = new URL("../backend/app/agents/global_agent/service.py", import.meta.url);
const agentSchemasPath = new URL("../backend/app/global_agent_schemas.py", import.meta.url);

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
  assert.match(panel, /下次提问时更新总结，不自动调用模型/);
  assert.match(panel, /下次核验 200 条/);
  assert.match(panel, /图片完全排除 · 不自动回复/);
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
  assert.match(service, /普通问答必须让 requirement_analysis 和 requirement_blueprint 为 null/);
  assert.match(service, /invalid_customer_confirmed/);
  assert.match(service, /invalid_operator_decisions/);
  assert.match(schemas, /class AgentRequirementBlueprint/);
  assert.match(schemas, /实施阶段存在循环依赖/);
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
