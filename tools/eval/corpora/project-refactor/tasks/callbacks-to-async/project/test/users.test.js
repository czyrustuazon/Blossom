import test from "node:test";
import assert from "node:assert/strict";

import { createStore, UserService, resetIds, userReport, countUsers } from "../src/index.js";

test("create stores a user", (t, done) => {
  resetIds();
  const store = createStore();
  const users = new UserService(store);
  users.create("Ada", (err, user) => {
    assert.equal(err, null);
    assert.deepEqual(user, { id: "u1", name: "Ada", renames: 0 });
    users.find("u1", (err2, found) => {
      assert.equal(err2, null);
      assert.equal(found.name, "Ada");
      done();
    });
  });
});

test("create rejects an empty name", (t, done) => {
  const users = new UserService(createStore());
  users.create("", (err) => {
    assert.equal(err.message, "name is required");
    done();
  });
});

test("rename updates the stored user", (t, done) => {
  resetIds();
  const users = new UserService(createStore());
  users.create("Ada", () => {
    users.rename("u1", "Ada L.", (err, user) => {
      assert.equal(err, null);
      assert.deepEqual(user, { id: "u1", name: "Ada L.", renames: 1 });
      done();
    });
  });
});

test("rename of an unknown user fails", (t, done) => {
  const users = new UserService(createStore());
  users.rename("u99", "x", (err) => {
    assert.equal(err.message, "not found: u99");
    done();
  });
});

test("report lists users in order and counts them", (t, done) => {
  resetIds();
  const store = createStore();
  const users = new UserService(store);
  users.create("Ada", () => {
    users.create("Grace", () => {
      userReport(users, ["u2", "u7", "u1"], (err, text) => {
        assert.equal(err, null);
        assert.equal(text, "u2: Grace\nu7: (missing)\nu1: Ada");
        countUsers(store, (err2, n) => {
          assert.equal(n, 2);
          done();
        });
      });
    });
  });
});
