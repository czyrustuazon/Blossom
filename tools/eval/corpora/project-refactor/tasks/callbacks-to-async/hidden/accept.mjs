import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import * as api from "../src/index.js";

const isPromise = (v) => v != null && typeof v.then === "function";
const settle = (p) => Promise.resolve(p).catch(() => undefined);

// Same exports as before.
assert.deepEqual(
  Object.keys(api).sort(),
  ["UserService", "countUsers", "createStore", "resetIds", "userReport"]
);

// A callback-style implementation never calls back when no callback is passed; fail fast instead of hanging.
const timer = setTimeout(() => {
  console.error("accept: timed out (a function did not settle its promise)");
  process.exit(1);
}, 5000);

api.resetIds();
const store = api.createStore();
const users = new api.UserService(store);

// No callback parameters left.
assert.equal(store.get.length, 1, "store.get(key)");
assert.equal(store.set.length, 2, "store.set(key, value)");
assert.equal(store.keys.length, 0, "store.keys()");
assert.equal(users.create.length, 1, "create(name)");
assert.equal(users.rename.length, 2, "rename(id, name)");
assert.equal(users.find.length, 1, "find(id)");
assert.equal(api.userReport.length, 2, "userReport(service, ids)");
assert.equal(api.countUsers.length, 1, "countUsers(store)");

// Everything returns a promise, including failures (no synchronous throw).
const p1 = users.create("Ada");
assert.ok(isPromise(p1), "create returns a promise");
assert.deepEqual(await p1, { id: "u1", name: "Ada", renames: 0 });

let threw = false;
let bad;
try {
  bad = users.create("");
} catch {
  threw = true;
}
assert.equal(threw, false, "create('') must reject, not throw synchronously");
await assert.rejects(bad, { message: "name is required" });

await users.create("Grace");
const p2 = users.rename("u1", "Ada L.");
assert.ok(isPromise(p2), "rename returns a promise");
assert.deepEqual(await p2, { id: "u1", name: "Ada L.", renames: 1 });
await assert.rejects(users.rename("u99", "x"), { message: "not found: u99" });

const p3 = users.find("u2");
assert.ok(isPromise(p3), "find returns a promise");
assert.equal((await p3).name, "Grace");
await assert.rejects(users.find("nope"), { message: "not found: nope" });

const p4 = store.get("u2");
assert.ok(isPromise(p4), "store.get returns a promise");
await settle(p4);
assert.ok(isPromise(store.set("k", 1)), "store.set returns a promise");
assert.equal(await store.set("k2", 2), 2);

const p5 = api.userReport(users, ["u2", "u7", "u1"]);
assert.ok(isPromise(p5), "userReport returns a promise");
assert.equal(await p5, "u2: Grace\nu7: (missing)\nu1: Ada L.");
assert.equal(await api.countUsers(store), 4);

// No callback plumbing left in src/.
for (const file of fs.readdirSync("src")) {
  const text = fs.readFileSync(path.join("src", file), "utf8");
  assert.ok(!/\bcb\b|\bcallback\s*[(,)]/.test(text), `${file} still mentions a callback`);
}

clearTimeout(timer);
console.log("accept: ok");
