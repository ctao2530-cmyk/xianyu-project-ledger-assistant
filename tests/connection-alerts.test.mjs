import assert from "node:assert/strict";
import test from "node:test";

import { buildConnectionAlerts } from "../src/data/connectionAlerts.ts";

const healthyStatus = {
  listener: "connected",
  model: "connected",
  codex_installed: true,
  codex_logged_in: true,
};

const healthyProviders = [
  { provider: "codex_cli", configured: true, status: "connected", detail: null },
  { provider: "deepseek", configured: true, status: "connected", detail: null },
];

test("healthy cached connection state stays out of smart reminders", () => {
  assert.deepEqual(buildConnectionAlerts(healthyStatus, healthyProviders), []);
});

test("unknown and checking states are not treated as failures", () => {
  assert.deepEqual(buildConnectionAlerts({ listener: "reconnecting", model: "checking" }, [
    { provider: "codex_cli", configured: true, status: "checking", detail: null },
    { provider: "deepseek", configured: true, status: "checking", detail: null },
  ]), []);
  assert.deepEqual(buildConnectionAlerts(null, [
    { provider: "codex_cli", configured: false, status: "checking", detail: null },
    { provider: "deepseek", configured: false, status: "unknown", detail: null },
  ]), []);
});

test("reconnecting only becomes actionable after the backend reports a concrete failure", () => {
  assert.deepEqual(buildConnectionAlerts({
    listener: "reconnecting",
    listener_detail: null,
    model: "connected",
    codex_installed: true,
    codex_logged_in: true,
  }, healthyProviders), []);

  const alerts = buildConnectionAlerts({
    listener: "reconnecting",
    listener_detail: "连接中断（ConnectError），稍后重试",
    model: "connected",
    codex_installed: true,
    codex_logged_in: true,
  }, healthyProviders);

  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].id, "connection-xianyu-error");
  assert.equal(alerts[0].settingsSection, "渠道连接");
});

test("explicit failures produce independent settings reminders", () => {
  const alerts = buildConnectionAlerts({
    listener: "login_required",
    model: "login_required",
    codex_installed: true,
    codex_logged_in: false,
  }, [
    { provider: "codex_cli", configured: true, status: "login_required", detail: "需要登录" },
    { provider: "deepseek", configured: true, status: "error", detail: "DeepSeek 鉴权失败" },
  ]);

  assert.deepEqual(alerts.map((item) => item.target), ["xianyu", "codex_cli", "deepseek"]);
  assert.equal(alerts[0].settingsSection, "渠道连接");
  assert.equal(alerts[1].settingsSection, "AI与回复");
  assert.equal(alerts[2].settingsSection, "AI与回复");
});

test("access verification is actionable and clearly reports that retries stopped", () => {
  const alerts = buildConnectionAlerts({
    listener: "verification_required",
    listener_detail: "闲鱼要求完成人工访问验证，自动重连已暂停",
    model: "connected",
    codex_installed: true,
    codex_logged_in: true,
  }, healthyProviders);

  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].id, "connection-xianyu-verification");
  assert.match(alerts[0].description, /Ego Lite/);
  assert.match(alerts[0].description, /自动重连已经暂停/);
});

test("one recovered provider disappears without hiding remaining failures", () => {
  const alerts = buildConnectionAlerts(healthyStatus, [
    healthyProviders[0],
    { provider: "deepseek", configured: false, status: "not_configured", detail: null },
  ]);
  assert.deepEqual(alerts.map((item) => item.target), ["deepseek"]);
  assert.equal(alerts[0].id, "connection-deepseek-config");
});
