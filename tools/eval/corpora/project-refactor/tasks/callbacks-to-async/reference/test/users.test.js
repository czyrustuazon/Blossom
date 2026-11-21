import test from "node:test";
import assert from "node:assert/strict";

import { createStore, UserService, resetIds, userReport, countUsers } from "../src/index.js";

test("create stores a user", async () => {
  resetIds();
  const users = new UserService(createStore());
  const user = await users.create("Ada");
  assert.deepEqual(user, { id: "u1", name: "Ada", renames: 0 });
  assert.equal((await users.find("u1")).name, "Ada");
});

test("create rejects an empty name", async () => {
  const users = new UserService(createStore());
  await assert.rejects(users.create(""), { message: "name is required" });
});

test("rename updates the stored user", async () => {
  resetIds();
  const users = new UserService(createStore());
  await users.create("Ada");
  assert.deepEqual(await users.rename("u1", "Ada L."), { id: "u1", name: "Ada L.", renames: 1 });
});

test("rename of an unknown user fails", async () => {
  const users = new UserService(createStore());
  await assert.rejects(users.rename("u99", "x"), { message: "not found: u99" });
});

test("report lists users in order and counts them", async () => {
  resetIds();
  const store = createStore();
  const users = new UserService(store);
  await users.create("Ada");
  await users.create("Grace");
  assert.equal(await userReport(users, ["u2", "u7", "u1"]), "u2: Grace\nu7: (missing)\nu1: Ada");
  assert.equal(await countUsers(store), 2);
});
