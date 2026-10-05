// Prochain scan affiché : toutes les 30 min, à hh:05 et hh:35 (heure de Paris).
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextScan } from "../ui.js";

test("prochain scan à hh:05 ou hh:35", () => {
  assert.equal(nextScan(new Date("2026-10-05T10:20:00Z")), "12:35");   // 12:20 à Paris
  assert.equal(nextScan(new Date("2026-10-05T10:40:00Z")), "13:05");   // 12:40
  assert.equal(nextScan(new Date("2026-10-05T10:02:00Z")), "12:05");   // 12:02
});
