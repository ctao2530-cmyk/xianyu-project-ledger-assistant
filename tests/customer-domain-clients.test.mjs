import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const localApiSource = await readFile(new URL("../src/data/localApi.ts", import.meta.url), "utf8");
const apiUrl = `data:text/javascript;base64,${Buffer.from(ts.transpileModule(localApiSource, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText).toString("base64")}`;
async function client(file) {
  const source = await readFile(new URL(`../src/data/${file}.ts`, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText.replace('"./localApi"', JSON.stringify(apiUrl));
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}
const { customerImageClient } = await client("customerImageClient");
const { customerConversationClient } = await client("customerConversationClient");
const { customerAccessClient } = await client("customerAccessClient");
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("image search and all filters are sent to server before pagination", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url) => { requests.push(url); return response({ items: [], total: 201, has_more: true }); });
  const result = await customerImageClient.customerImages({ search: "合成图片 B", conversationId: 9, itemId: "4", dateFrom: "2026-09-01", dateTo: "2026-09-07", offset: 100 });
  const url = new URL(requests[0], "http://isolated.invalid");
  assert.equal(url.searchParams.get("search"), "合成图片 B");
  assert.equal(url.searchParams.get("conversation_id"), "9");
  assert.equal(url.searchParams.get("item_id"), "4");
  assert.equal(url.searchParams.get("offset"), "100");
  assert.equal(result.total, 201);
});

test("group candidates resolve the confirmed customer ID, never a display name", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url) => { requests.push(url); return response(url === "/api/conversations/8" ? { linked_customer_id: "synthetic-a" } : { conversations: [{ id: 8, item_id: 2, customer_name: "同名" }], groups: [] }); });
  const result = await customerConversationClient.conversationGroupCandidates(8);
  assert.equal(requests[1], "/api/customers/synthetic-a/conversation-group-candidates");
  assert.equal(result.customer_id, "synthetic-a");
  assert.equal(result.candidates[0].identity_basis, "confirmed_identity");
});

test("unlinked conversations cannot silently gain a customer identity", async (t) => {
  let requests = 0;
  t.mock.method(globalThis, "fetch", async () => { requests++; return response({ linked_customer_id: null }); });
  await assert.rejects(customerConversationClient.conversationGroupCandidates(8), /确认该渠道身份关联/);
  assert.equal(requests, 1);
});

test("group preview and commit send exact backend fields and same request identity", async (t) => {
  const posts = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (!init?.body) return response({ linked_customer_id: "synthetic-a" });
    posts.push({ url, body: JSON.parse(init.body) });
    return response(url.endsWith("preview") ? { preview_token: "synthetic-preview", effects: { added: [8, 9], removed: [] } } : { id: "group-1", revision: 1, active: true, title: "合并会话", conversation_ids: [8, 9] });
  });
  const payload = { anchor_conversation_id: 8, conversation_ids: [8, 9], expected_revision: 0, title: "UI label", reason: "合成测试", request_id: "synthetic-request" };
  const preview = await customerConversationClient.previewConversationGroup(payload);
  await customerConversationClient.commitConversationGroup({ ...payload, preview_token: preview.preview_token, confirmed: true });
  assert.equal(posts[0].body.request_id, posts[1].body.request_id);
  assert.equal(posts[1].body.preview_token, "synthetic-preview");
  assert.equal("title" in posts[0].body, false);
  assert.equal("anchor_conversation_id" in posts[0].body, false);
  assert.deepEqual(preview.added_ids, [8, 9]);
});

test("group timeline keeps identical text from different conversations", async (t) => {
  t.mock.method(globalThis, "fetch", async () => response({ messages: [{ id: 1, conversation_id: 8, content: "合成消息" }, { id: 2, conversation_id: 9, content: "合成消息" }], total_count: 2, has_more: false }));
  const result = await customerConversationClient.conversationGroupMessages("synthetic-group");
  assert.equal(result.messages.length, 2);
  assert.deepEqual(result.messages.map((row) => row.source_conversation_id), [8, 9]);
});

test("manual history page sends the same fixed page size and opaque continuation", async (t) => {
  let sent;
  t.mock.method(globalThis, "fetch", async (_url, init) => { sent = JSON.parse(init.body); return response({ has_more: true }); });
  await customerConversationClient.previewConversationHistory("synthetic-external", "page", 200, "synthetic-continuation");
  assert.deepEqual(sent, { external_conversation_id: "synthetic-external", history_scope: "page", message_limit: 200, continuation_token: "synthetic-continuation" });
});

test("group image access transmits explicit snapshot, never a model request", async (t) => {
  const urls = [];
  let sent;
  t.mock.method(globalThis, "fetch", async (url, init) => { urls.push(url); sent = JSON.parse(init.body); return response({ id: "synthetic-binding" }); });
  await customerAccessClient.createCustomerContextThreadBinding({ request_id: "synthetic-request", conversation_id: 8, expected_conversation_revision: 0, allow_text: true, allow_images: true, allow_artifacts: false, allow_new_messages: true, expires_in_seconds: 900, authorization_note: "合成测试", confirmed: true, group_id: "group-1", expected_group_revision: 3, selected_conversation_ids: [8, 9] });
  assert.deepEqual(urls, ["/api/customer-context/thread-bindings"]);
  assert.equal(sent.allow_images, true);
  assert.deepEqual(sent.selected_conversation_ids, [8, 9]);
  assert.equal(sent.expected_group_revision, 3);
});
