// 데이터 출처: 맥 대시보드(Flask API) 또는 폰 앱(네이티브 플러그인 'Haru').
// 화면 코드는 어느 쪽인지 몰라도 되게 같은 모양의 함수를 준다.
import { Capacitor, registerPlugin } from "../vendor/capacitor/core.js";

export const isNative = Capacitor.isNativePlatform();
const Haru = isNative ? registerPlugin("Haru") : null;

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok && r.status !== 409) {
    const body = await r.text();
    let msg = body;
    try { msg = JSON.parse(body).msg || body; } catch { /* 일반 오류 응답 */ }
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

export const MacSource = {
  kind: "mac",
  async days() { return api("/api/days"); },
  async day(day) {
    const j = await api(`/api/day/${day}`);
    return { ...j, cards: { A: `/api/card/${day}/A.png?v=${j.digest?.version || 0}`, B: `/api/card/${day}/B.png?v=${j.digest?.version || 0}` } };
  },
  thumbUrl(item) { return item.thumb ? `/media/${item.thumb}` : null; },
  fullUrl(item) { return item.media ? `/media/${item.media}` : null; },
  async run(opts = {}) { return post("/api/run", opts); },
  async status(withLlm = false) { return api(`/api/status${withLlm ? "?llm=1" : ""}`); },
  async setTodo(key, done) { return post("/api/todo", { key, done }); },
  async hide(id) { return post(`/api/item/${encodeURIComponent(id)}/hide`); },
  async importFiles(files) {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    return api("/api/import", { method: "POST", body: fd });
  },
  async pairing() { return api("/api/pairing"); },
  async resetPairing() { return post("/api/pairing/reset"); },
  async publish(day) { return post(`/api/publish/${day}`); },
  async exportDay(day) { return post(`/api/archive/${day}`); },
  async settings() { return api("/api/settings"); },
  async saveSettings(patch) { return post("/api/settings", patch); },
  async youtube() { return api("/api/youtube"); },
  async youtubeClient(document) { return post("/api/youtube/client", document); },
  async youtubeConnect() { return post("/api/youtube/connect"); },
  async youtubeDisconnect() { return post("/api/youtube/disconnect"); },
  async youtubePlaylists() { return api("/api/youtube/playlists"); },
  async youtubeSelection(playlists, enabled) { return post("/api/youtube/selection", { playlists, enabled }); },
  openUrl(url) { window.open(url, "_blank", "noopener"); },
};

export const PhoneSource = {
  kind: "phone",
  async days() { return Haru.listDigests(); },
  async day(day) {
    const j = await Haru.getDigest({ day });
    this._thumbs = j.thumbs || {};
    return { day, digest: j.digest || null, items: [], pending: j.pending || 0, cards: j.cards || {} };
  },
  thumbUrl(item) { return (this._thumbs || {})[item.id] || null; },
  fullUrl(item) { return (this._thumbs || {})[item.id] || null; },
  async run() { return Haru.requestRefresh(); },
  async status() { return Haru.getStatus(); },
  async setTodo(key, done) { return Haru.setTodo({ key, done }); },
  async hide() { return { ok: false }; },
  async sync() { return Haru.syncNow(); },
  async takeReportRoute() { return Haru.takeReportRoute(); },
  async pair(code) { return Haru.pair({ code }); },
  async unpair() { return Haru.unpair(); },
  async scanQr() { return Haru.scanQr(); },
  async outbox() { return Haru.getOutbox(); },
  async retryOutbox() { return Haru.retryOutbox(); },
  async settings() { return Haru.getSettings(); },
  async saveSettings(patch) { return Haru.setSettings(patch); },
  async pickBackground() { return Haru.pickBackground(); },
  async applyLockscreen() { return Haru.applyLockscreen(); },
  async previewLockscreen(style) { return Haru.previewLockscreen({ style }); },
  async requestNotifications() { return Haru.requestNotifications(); },
  async openBatterySettings() { return Haru.openBatterySettings(); },
  openUrl(url) { Haru.openUrl({ url }); },
  addListener(name, fn) { return Haru.addListener(name, fn); },
};

export const Source = isNative ? PhoneSource : MacSource;
