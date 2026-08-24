import assert from "node:assert/strict";
import test from "node:test";

import {
  formatTrafficDateTime,
  formatTrafficPlanDate,
  formatTrafficPlanSlotDateTime,
} from "../src/utils/trafficDateTime.ts";

test("exposure times use the Beijing operation format with minute padding", () => {
  assert.equal(formatTrafficDateTime("2026-08-13T08:20:59Z"), "8月13日16时20分");
  assert.equal(formatTrafficDateTime("2026-08-13T01:05:00Z"), "8月13日9时05分");
});

test("exposure times remain stable across Beijing day, month, and midnight", () => {
  assert.equal(formatTrafficDateTime("2026-08-31T16:05:00Z"), "9月1日0时05分");
  assert.equal(formatTrafficDateTime("2026-12-31T16:00:00Z"), "1月1日0时00分");
});

test("seven-day dates stay compact but concrete operation times are complete", () => {
  assert.equal(formatTrafficPlanDate("2026-08-13"), "8月13日");
  assert.equal(
    formatTrafficPlanSlotDateTime("2026-08-13", "16:20"),
    "8月13日16时20分",
  );
});
