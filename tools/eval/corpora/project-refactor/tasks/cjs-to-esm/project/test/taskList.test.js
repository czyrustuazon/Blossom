const test = require("node:test");
const assert = require("node:assert/strict");
const { TaskList, formatTask, resetIds } = require("../src/index");

test("add, complete, render", () => {
  resetIds();
  const list = new TaskList();
  const a = list.add("write docs", "high");
  list.add("nap", "low");
  list.complete(a.id);
  assert.equal(a.id, "t1");
  assert.equal(list.pending().length, 1);
  assert.equal(list.render(), "[x] !!write docs\n[ ] ~nap");
});

test("formatTask and errors", () => {
  assert.equal(formatTask({ title: "x", done: false, priority: "normal" }), "[ ] x");
  assert.throws(() => new TaskList().complete("nope"), /no task nope/);
});
