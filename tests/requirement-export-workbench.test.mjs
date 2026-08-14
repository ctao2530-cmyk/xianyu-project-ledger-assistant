import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const workbenchPath = new URL("../src/components/RequirementExportWorkbench.tsx", import.meta.url);
const stylesPath = new URL("../src/components/requirement-export-workbench.css", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);

test("requirement analysis keeps the existing import flow and adds the selected export workbench", async () => {
  const source = await readFile(pagePath, "utf8");

  assert.match(source, /汇总完整材料/);
  assert.match(source, /<RequirementExportWorkbench/);
  assert.match(source, /交给 GPT \/ Codex 分析/);
  assert.match(source, /选择 GPT 返回的 JSON 文件/);
  assert.match(source, /校验并生成可视化预览/);
  assert.match(source, /人工确认绑定客户、商品并保存蓝图/);
});

test("export workbench exposes image review, missing-state, local package, and legacy text actions", async () => {
  const source = await readFile(workbenchPath, "utf8");

  assert.match(source, /导出工作台/);
  assert.match(source, /补充参考图片/);
  assert.match(source, /确认隐私/);
  assert.match(source, /缺失图片/);
  assert.match(source, /预览并导出给 Codex/);
  assert.match(source, /我确认导出不完整材料包/);
  assert.match(source, /下载 Markdown/);
  assert.match(source, /复制纯文字/);
  assert.match(source, /本地生成，不自动上传/);
  assert.match(source, /不会自动上传、调用 GPT、读取 Cookie 或发送客户消息/);
  assert.match(source, /packageDialogRef\.current\?\.focus/);
  assert.match(source, /event\.key !== "Tab"/);
  assert.match(source, /剪贴板不可用/);
  assert.match(source, /uploadedIds\.push/);
  assert.match(source, /loadPreview\(uploadedIds\)/);
});

test("client uses scoped preview, multipart upload, privacy, delete, and package APIs", async () => {
  const source = await readFile(servicePath, "utf8");

  assert.match(source, /requirementExportPreview/);
  assert.match(source, /requirement-export-preview/);
  assert.match(source, /uploadRequirementAttachment/);
  assert.match(source, /new FormData\(\)/);
  assert.match(source, /updateRequirementAttachmentPrivacy/);
  assert.match(source, /deleteRequirementAttachment/);
  assert.match(source, /createRequirementExportPackage/);
  assert.match(source, /requirement-export-package/);
  assert.match(source, /!\(init\?\.body instanceof FormData\)/);
});

test("confirmed workbench layout keeps source hierarchy and practical narrow-screen targets", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.requirement-material-grid \{[\s\S]*grid-template-columns: minmax\(0, 1\.3fr\) minmax\(168px, \.78fr\)/);
  assert.match(styles, /\.requirement-package-primary \{[\s\S]*linear-gradient/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.requirement-material-grid \{ grid-template-columns: 1fr/);
  assert.match(styles, /@media \(max-width: 480px\)[\s\S]*\.requirement-image-select,[\s\S]*min-width: 44px/);
  assert.match(styles, /\.requirement-package-dialog > header button \{ width: 44px; height: 44px; \}/);
  assert.match(styles, /\.requirement-package-backdrop/);
  assert.match(styles, /\.requirement-image-card img \{[\s\S]*object-fit: contain/);
  assert.match(styles, /button:focus-visible/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});
