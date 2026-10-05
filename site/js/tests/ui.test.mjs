// Prochain scan affiché : toutes les 30 min, à hh:05 et hh:35 (heure de Paris).
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextScan } from "../ui.js";

test("prochain scan à hh:05 ou hh:35", () => {
  assert.equal(nextScan(new Date("2026-10-05T10:20:00Z")), "12:31");   // 12:20 à Paris
  assert.equal(nextScan(new Date("2026-10-05T10:40:00Z")), "12:46");   // 12:40
  assert.equal(nextScan(new Date("2026-10-05T10:00:30Z")), "12:01");   // 12:00
  assert.equal(nextScan(new Date("2026-10-05T10:16:00Z")), "12:31");   // 12:16 pile : le suivant
  assert.equal(nextScan(new Date("2026-10-05T10:50:00Z")), "13:01");   // 12:50
  assert.equal(nextScan(new Date("2026-10-05T21:55:00Z")), "00:01");   // 23:55 → minuit passé
});
