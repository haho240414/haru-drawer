// Shared by the app and the saved documents; only appearance is stored locally.
(() => {
  const key = "haru.theme";
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");
  const normalize = value => ["system", "light", "dark"].includes(value) ? value : "system";
  let choice = "system";
  try { choice = normalize(localStorage.getItem(key)); } catch { /* Private storage may be unavailable. */ }

  const apply = () => {
    const resolved = choice === "system" ? (system.matches ? "dark" : "light") : choice;
    root.dataset.theme = resolved;
    root.dataset.themeChoice = choice;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = resolved === "dark" ? "#1b1f20" : "#faf9f6";
    document.querySelectorAll("[data-theme-select]").forEach(select => {
      select.value = choice;
      select.closest(".appearance").hidden = false;
    });
  };
  apply(); // Set the first paint before the body or the application loads.
  document.addEventListener("DOMContentLoaded", apply, { once: true });
  document.addEventListener("change", event => {
    if (!event.target.matches("[data-theme-select]")) return;
    choice = normalize(event.target.value);
    try { localStorage.setItem(key, choice); } catch { /* The current screen still changes. */ }
    apply();
  });
  const followSystem = () => { if (choice === "system") apply(); };
  if (system.addEventListener) system.addEventListener("change", followSystem);
  else system.addListener(followSystem);
  window.addEventListener("storage", event => {
    if (event.key !== key && event.key !== null) return;
    choice = normalize(event.newValue);
    apply();
  });
})();
