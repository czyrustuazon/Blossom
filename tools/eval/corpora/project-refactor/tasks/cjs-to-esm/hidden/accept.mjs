// Run from the project root: node _acceptance/accept.mjs
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const pkg = JSON.parse(readFileSync("package.json", "utf8"));
assert.equal(pkg.type, "module", 'package.json needs "type": "module"');

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
for (const file of [...walk("src"), ...walk("test")].filter((f) => /\.[cm]?js$/.test(f))) {
  const src = readFileSync(file, "utf8");
  assert.ok(!/\brequire\s*\(/.test(src), `${file} still uses require()`);
  assert.ok(!/\bmodule\.exports\b|\bexports\.\w+\s*=/.test(src), `${file} still uses CommonJS exports`);
}

const mod = await import(pathToFileURL(join(process.cwd(), "src", "index.js")).href);
mod.resetIds();
const list = new mod.TaskList();
const t = list.add("ship it", "high");
list.add("later", "low");
list.complete(t.id);
assert.equal(list.render(), "[x] !!ship it\n[ ] ~later");
assert.equal(mod.formatTask({ title: "y", done: true, priority: "low" }), "[x] ~y");
const fmt = await import(pathToFileURL(join(process.cwd(), "src", "lib", "format.js")).href);
assert.equal(fmt.PRIORITY_MARK.high, "!!");
console.log("acceptance ok");
