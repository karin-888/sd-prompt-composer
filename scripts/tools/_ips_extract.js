// Helper: load a list of INFINITE PROMPT STUDIO data .js files (each assigns to
// `window.SOMETHING = …`) and dump the resulting window state as JSON.
// Usage: node _ips_extract.js <file1.js> <file2.js> ... > out.json
"use strict";

const fs = require("fs");
const path = require("path");

const win = {};
const out = {};

// Silence console.log/info/warn from the loaded files (some IPS files log).
const noop = () => {};
const silentConsole = {
  log: noop, info: noop, warn: noop, error: noop, debug: noop, trace: noop,
  group: noop, groupEnd: noop, time: noop, timeEnd: noop, assert: noop,
  dir: noop, table: noop, count: noop, countReset: noop,
};

const files = process.argv.slice(2);
for (const f of files) {
  try {
    const src = fs.readFileSync(f, "utf-8");
    const before = new Set(Object.keys(win));
    // Run in a sandboxed function so `window` is the only global the file sees.
    new Function("window", "console", src)(win, silentConsole);
    const after = Object.keys(win).filter(k => !before.has(k));
    out[path.basename(f)] = after; // record which keys this file introduced
  } catch (e) {
    process.stderr.write(`ERR ${path.basename(f)}: ${e.message}\n`);
    out[path.basename(f)] = [];
  }
}

process.stdout.write(JSON.stringify({ window: win, file_keys: out }));
