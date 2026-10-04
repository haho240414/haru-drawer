import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const script = readFileSync(new URL("../app/js/theme.js", import.meta.url), "utf8");

function screen({ saved = null, dark = false, unavailable = false } = {}) {
  const events = {}, windowEvents = {}, mediaEvents = {};
  const root = { dataset: {} }, meta = {};
  const appearance = { hidden: true };
  const select = { value: "system", closest: () => appearance, matches: s => s === "[data-theme-select]" };
  let controls = [], preference = saved;
  const media = { matches: dark, addEventListener: (name, callback) => { mediaEvents[name] = callback; } };
  const document = {
    documentElement: root,
    querySelector: () => meta,
    querySelectorAll: () => controls,
    addEventListener: (name, callback) => { events[name] = callback; },
  };
  const localStorage = {
    getItem: () => { if (unavailable) throw new Error("unavailable"); return preference; },
    setItem: (key, value) => { if (unavailable) throw new Error("unavailable"); preference = value; },
  };
  vm.runInNewContext(script, {
    document, localStorage, matchMedia: () => media,
    window: { addEventListener: (name, callback) => { windowEvents[name] = callback; } },
  });
  return {
    root, meta, select, appearance,
    load: () => { controls = [select]; events.DOMContentLoaded(); },
    choose: value => { select.value = value; events.change({ target: select }); },
    system: value => { media.matches = value; mediaEvents.change(); },
    storage: (value, key = "haru.theme") => windowEvents.storage({ key, newValue: value }),
    saved: () => preference,
  };
}

test("explicit choice applies before first paint, appears on load, and survives reload", () => {
  const page = screen({ saved: "dark" });
  assert.equal(page.root.dataset.theme, "dark");
  assert.equal(page.meta.content, "#1b1f20");
  assert.equal(page.appearance.hidden, true);
  page.load();
  assert.equal(page.select.value, "dark");
  assert.equal(page.appearance.hidden, false);
  page.choose("light");
  assert.equal(page.saved(), "light");
  assert.equal(screen({ saved: page.saved(), dark: true }).root.dataset.theme, "light");
});

test("invalid choice follows the system, while explicit light ignores system changes", () => {
  const page = screen({ saved: "invalid", dark: false });
  page.load();
  assert.equal(page.select.value, "system");
  page.system(true);
  assert.equal(page.root.dataset.theme, "dark");
  page.choose("light");
  page.system(false);
  page.system(true);
  assert.equal(page.root.dataset.theme, "light");
  page.choose("system");
  assert.equal(page.root.dataset.theme, "dark");
  page.system(false);
  assert.equal(page.root.dataset.theme, "light");
});

test("other tabs update immediately, unrelated storage events do not, clear follows system", () => {
  const page = screen({ saved: "light", dark: true });
  page.load();
  page.storage("dark");
  assert.equal(page.select.value, "dark");
  assert.equal(page.root.dataset.theme, "dark");
  page.storage("light", "other.preference");
  assert.equal(page.root.dataset.theme, "dark");
  page.storage(null, null);
  assert.equal(page.select.value, "system");
  assert.equal(page.root.dataset.theme, "dark");
});

test("blocked storage still allows appearance changes on the current screen", () => {
  const page = screen({ unavailable: true, dark: true });
  page.load();
  assert.equal(page.root.dataset.theme, "dark");
  assert.doesNotThrow(() => page.choose("light"));
  assert.equal(page.select.value, "light");
  assert.equal(page.meta.content, "#faf9f6");
  page.system(true);
  assert.equal(page.root.dataset.theme, "light");
});
