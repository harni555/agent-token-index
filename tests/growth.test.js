import test from "node:test";
import assert from "node:assert/strict";
import {
  growthPoints,
  growthDomain,
  windowWeeks,
  heatColor,
} from "../src/growth.js";

const weeks = (values) =>
  values.map((value, i) => ({
    completeWeek: true,
    end: new Date(Date.UTC(2026, 0, 4 + i * 7)).toISOString().slice(0, 10),
    series: { BAWI: { wow: value, fourWeekGrowth: value } },
  }));
test("cooling growth is a percentage-point decline, not contraction", () => {
  const p = growthPoints(weeks([20, 10]), "BAWI", "wow")[1];
  assert.equal(p.value, 10);
  assert.equal(p.change, -10);
});
test("moving mean requires four consecutive nonmissing weeks", () => {
  let p = growthPoints(weeks([10, -10, 20, 0]), "BAWI", "wow");
  assert.equal(p[3].mean, 5);
  assert.equal(p[2].mean, null);
  p = growthPoints(weeks([10, null, 20, 0]), "BAWI", "wow");
  assert.equal(p[3].mean, null);
  assert.equal(p[2].change, null);
  const gap = weeks([10, 20, 30, 40, 50]);
  gap.splice(2, 1);
  assert.equal(growthPoints(gap, "BAWI", "wow")[3].mean, null);
});
test("growth scale includes zero, negative values and full outliers", () => {
  const [lo, hi] = growthDomain([-35, 1200, null]);
  assert.ok(lo < -35);
  assert.ok(hi > 1200);
  assert.ok(growthDomain([4, 9])[0] < 0);
  assert.ok(growthDomain([-4, -9])[1] > 0);
});
test("range filtering preserves real observations and color distinguishes missing from flat", () => {
  const all = weeks(Array(90).fill(1));
  all[0].completeWeek = false;
  assert.equal(windowWeeks(all, "All").length, 89);
  assert.ok(windowWeeks(all, "3M").length < 15);
  assert.notEqual(heatColor(null), heatColor(0));
  assert.equal(heatColor(40), heatColor(4000));
});
