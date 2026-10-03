// 하루서랍 화면 — 맥 대시보드(브라우저)와 폰 앱(Capacitor)이 같은 코드를 쓴다.
import { Source, isNative } from "./source.js";
import { showYoutube } from "./youtube.js";
import { renderReport, cssId } from "./report.js";
import { esc, icon } from "./common.js";

const $view = document.getElementById("view");
const $tabs = document.getElementById("tabs");
const $desktopTabs = document.getElementById("desktopTabs");
const $run = document.getElementById("runBtn");
const state = { days: [], today: null };
document.querySelector(".skip-link").onclick = (event) => {
  event.preventDefault();
  $view.focus();
  $view.scrollIntoView({ block: "start" });
};

const pref = {
  get(k, d) { try { return localStorage.getItem("haru." + k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("haru." + k, v); } catch { /* 저장 못 해도 화면은 동작 */ } },
};

const TABS = [["#/", "calendar-days", "보고서", "오늘 보고서"], ["#/days", "file-text", "기록", "기록"],
  ["#/add", "circle-plus", "자료", isNative ? "보낼 자료" : "자료 추가"],
  ["#/link", isNative ? "monitor" : "smartphone", "연결", isNative ? "맥 연결" : "폰 연결"], ["#/settings", "settings", "설정", "설정"]];

function toast(msg, ms = 2600) {
  const t = Object.assign(document.createElement("div"), { className: "toast", textContent: msg });
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

function drawTabs(route) {
  const draw = (tabs, mobile) => tabs.map(([href, ic, short, full]) => {
    const on = href === "#/" ? (route === "" || route.startsWith("day/")) : route.startsWith(href.slice(2)) || (mobile && href === "#/settings" && route === "youtube");
    return `<a href="${href}" class="${on ? "on" : ""}" ${on ? 'aria-current="page"' : ""}><span class="ic">${icon(ic)}</span>${mobile ? short : full}</a>`;
  }).join("");
  $tabs.innerHTML = draw(TABS, true);
  const desktop = [...TABS];
  if (!isNative) desktop.splice(3, 0, ["#/youtube", "square-play", "유튜브", "유튜브"]);
  $desktopTabs.innerHTML = draw(desktop, false);
}

async function loadDays() {
  try {
    const j = await Source.days();
    state.days = j.days || [];
    state.today = j.today || state.days[0]?.day || null;
  } catch (e) {
    state.days = [];
  }
}

// ---------------- 하루 보고서 ----------------
async function showDay(day) {
  await loadDays();
  if (!day) day = state.days[0]?.day || state.today;
  if (!day) {
    $view.innerHTML = `<section class="empty"><h1>첫 보고서를 기다리고 있어요</h1><p>${isNative
      ? "링크나 캡처를 공유 → 하루서랍으로 보내면 맥에서 정리한 보고서가 여기에 도착합니다."
      : "링크나 캡처, 카톡 ‘나와의 채팅’ 내보내기 파일을 추가해 보세요. 모은 자료를 하루 단위로 정리합니다."}</p><a class="btn" href="#/add">자료 추가</a></section>`;
    return;
  }
  const idx = state.days.findIndex((d) => d.day === day);
  const prev = state.days[idx + 1]?.day;
  const next = idx > 0 ? state.days[idx - 1]?.day : null;
  $view.innerHTML = `<div class="daynav">
      <button class="arrow" ${prev ? `data-day="${prev}"` : "disabled"} aria-label="이전 날">${icon("chevron-left")}</button>
      <span class="label" id="dayLabel">${esc(day)}</span>
      <button class="arrow" ${next ? `data-day="${next}"` : "disabled"} aria-label="다음 날">${icon("chevron-right")}</button>
    </div><div class="meta" id="dayMeta"></div><div id="report"><div class="card empty">불러오는 중…</div></div>`;
  let data;
  try {
    data = await Source.day(day);
  } catch (e) {
    document.getElementById("report").innerHTML = `<div class="card empty">불러오지 못했어요: ${esc(e.message)}</div>`;
    return;
  }
  const d = data.digest;
  document.getElementById("dayLabel").textContent = d?.label || day;
  document.getElementById("dayMeta").textContent = d
    ? `자료 ${d.stats?.count || 0}개 · ${(d.generated_at || "").slice(11, 16)} 정리${data.pending ? ` · 새로 ${data.pending}개 대기` : ""}`
    : "";
  let style = pref.get("style", "A");
  if (isNative) {
    try { style = (await Source.settings()).style || style; } catch { /* 기본값 */ }
  }
  const ctx = {
    style,
    isNative,
    canHide: !isNative,
    thumbUrl: (it) => Source.thumbUrl(it),
    fullUrl: (it) => Source.fullUrl(it),
    lockNote: isNative ? "잠금화면 배경과 알림은 설정에서 켤 수 있어요." : '폰 연결 후 사용할 수 있어요. 배경과 알림은 폰에서 설정합니다.',
    lockActions: isNative
      ? `<button class="btn block" data-act="apply">${icon("smartphone")} 잠금화면에 적용</button>`
      : `<button class="btn block" data-act="publish">${icon("smartphone")} 폰으로 보내기</button>`,
  };
  const rep = document.getElementById("report");
  renderReport(rep, data, ctx);
  if (d && !isNative) {
    document.getElementById("saveFiles").onclick = async (ev) => {
      const button = ev.currentTarget;
      button.disabled = true;
      try {
        await Source.exportDay(day);
        toast("노트북에 파일로 저장했어요");
        await showDay(day);
      } catch (e) { toast("파일 저장 실패: " + e.message); button.disabled = false; }
    };
  }
  const filterItems = (category) => {
    rep.querySelectorAll("[data-filter]").forEach(b => {
      const on = b.dataset.filter === category;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    rep.querySelectorAll(".item").forEach(item => { item.hidden = !!category && item.dataset.category !== category; });
  };
  rep.onclick = async (ev) => {
    const t = ev.target.closest("[data-goto],[data-open],[data-style],[data-act],[data-hide],[data-filter],[data-full]");
    if (!t) return;
    if ("filter" in t.dataset) { filterItems(t.dataset.filter); return; }
    if (t.dataset.hide) {
      if (!confirm("이 항목을 보고서에서 뺄까요? (그날 보고서를 다시 정리해요)")) return;
      await Source.hide(t.dataset.hide);
      t.closest(".item").style.opacity = 0.35;
      toast("뺐어요 — 보고서를 다시 정리할게요");
      runNow({ day });
      return;
    }
    if (t.dataset.goto) {
      ev.preventDefault();
      filterItems("");
      const el = document.getElementById("it-" + cssId(t.dataset.goto));
      if (el) { el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1500); }
    } else if (t.dataset.open) {
      ev.preventDefault();
      Source.openUrl(t.dataset.open);
    } else if (t.dataset.style) {
      pref.set("style", t.dataset.style);
      if (isNative) await Source.saveSettings({ style: t.dataset.style });
      rep.querySelectorAll("[data-style]").forEach(b => {
        const on = b.dataset.style === t.dataset.style;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(on));
      });
      const phone = document.getElementById("phonePrev");
      phone.className = `phone ${t.dataset.style}`;
      const image = phone.querySelector("img");
      if (image && data.cards?.[t.dataset.style]) image.src = data.cards[t.dataset.style];
      const full = document.getElementById("cardFullLink");
      if (full) full.href = data.cards?.[t.dataset.style] || "#";
    } else if (t.dataset.full) {
      const v = Object.assign(document.createElement("dialog"), { className: "viewer" });
      v.setAttribute("aria-label", "이미지 크게 보기");
      v.innerHTML = `<button class="btn close">닫기</button><img src="${esc(t.dataset.full)}" alt="${esc(t.getAttribute("aria-label") || "선택한 자료")}">`;
      v.querySelector("button").onclick = () => v.close();
      v.onclick = (event) => { if (event.target === v) v.close(); };
      v.onclose = () => { v.remove(); t.focus(); };
      document.body.append(v);
      v.showModal();
    } else if (t.dataset.act === "run") {
      runNow({ day });
    } else if (t.dataset.act === "apply") {
      const r = await Source.applyLockscreen();
      toast(r.ok ? "잠금화면에 적용했어요" : (r.msg || "적용하지 못했어요"));
    } else if (t.dataset.act === "publish") {
      const r = await Source.publish(day);
      toast(r.ok ? "폰으로 보냈어요" : (r.msg || "폰과 연결돼 있지 않아요"));
    }
  };
  rep.onchange = async (ev) => {
    const cb = ev.target.closest("input[data-todo]");
    if (!cb) return;
    cb.closest(".todo").classList.toggle("done", cb.checked);
    try { await Source.setTodo(cb.dataset.todo, cb.checked); }
    catch (e) { cb.checked = !cb.checked; cb.closest(".todo").classList.toggle("done", cb.checked); toast("할 일 저장 실패: " + e.message); }
  };
  document.querySelectorAll(".daynav [data-day]").forEach((b) => (b.onclick = () => (location.hash = `#/day/${b.dataset.day}`)));
}

// ---------------- 기록 ----------------
async function showDays() {
  await loadDays();
  $view.innerHTML = `<div class="page-heading"><h1>기록</h1><p>모아 둔 자료와 보고서를 날짜별로 읽어보세요.</p></div>
    <div class="card list">${state.days.length ? state.days.map((d) => `<a class="row" href="#/day/${d.day}">
      <span class="d">${esc(d.day)}</span><span class="n">${d.count}개</span>
      <span class="spacer" style="flex:1"></span><span class="meta">${d.digest_version ? "정리 완료" : "정리 전"}</span>${icon("chevron-right")}</a>`).join("")
      : `<div class="empty">아직 기록이 없어요</div>`}</div>`;
}

// ---------------- 넣기 (맥) / 보낼 것 (폰) ----------------
async function showAdd() {
  if (isNative) return showOutbox();
  const st = await Source.status().catch(() => ({}));
  $view.innerHTML = `<div class="page-heading"><h1>자료 추가</h1><p>나에게 보낸 링크와 캡처를 한곳에 모으세요.</p></div>
    <div class="card">
      <button class="drop" id="drop" style="width:100%" type="button">${icon("circle-plus")}<br><b>파일을 선택하거나 여기에 끌어다 놓으세요</b><br><span class="meta">카톡 내보내기 TXT·CSV·ZIP, 이미지, PDF</span></button>
      <input type="file" id="file" multiple hidden accept=".txt,.csv,.zip,image/*,.pdf">
      <div id="impResult" style="margin-top:12px"></div>
    </div>
    <details class="card"><summary>${icon("chevron-right", "disclosure-icon")}카톡 ‘나와의 채팅’ 내보내는 법</summary>
      <ol class="steps">
        <li><b>폰(안드로이드)</b>: 나와의 채팅 → 오른쪽 위 ≡ → ⚙ 설정 → <b>대화 내용 내보내기</b> → '텍스트 메시지만 보내기'를 누르고 공유 창에서 <b>하루서랍</b> 선택 (사진까지: '모든 메시지 내부 저장소에 저장')</li>
        <li><b>맥 카톡</b>: 나와의 채팅 → 메뉴(≡) → 대화 내용 내보내기 → 저장 위치를 <code>${esc(st.inbox || "~/하루서랍")}</code> 로 고르면 자동으로 들어가요</li>
        <li>같은 대화를 여러 번 넣어도 겹치지 않아요 (이미 넣은 메시지는 건너뜀)</li>
        <li>다른 사람이 있는 대화방은 받지 않아요 — 나와의 채팅만</li>
      </ol>
    </details>
    <div class="card"><h2>최근 넣은 것</h2>${(st.imports || []).map((i) => `<div class="meta">${esc(i.at?.slice(0, 16).replace("T", " "))} · ${esc(i.name)} · 새 ${i.stats?.new ?? 0}개 / 중복 ${i.stats?.dup ?? 0}</div>`).join("") || `<div class="meta">아직 없어요</div>`}</div>`;
  const drop = document.getElementById("drop");
  const file = document.getElementById("file");
  const send = async (files) => {
    if (!files.length) return;
    document.getElementById("impResult").innerHTML = `<div class="meta">넣는 중…</div>`;
    const j = await Source.importFiles(files);
    document.getElementById("impResult").innerHTML = j.results.map((r) => r.ok
      ? `<div><span class="ok">✓</span> ${esc(r.file)} — ${r.new != null ? `새 항목 ${r.new}개 (중복 ${r.dup}, ${esc((r.days || []).join(", "))})` : `${esc(r.kind)} ${esc(r.result)}`}</div>`
      : `<div><span class="bad">✗</span> ${esc(r.file)} — ${esc(r.error)}</div>`).join("")
      + `<div style="margin-top:10px"><button class="btn primary small" id="runAfter">지금 정리하기</button></div>`;
    document.getElementById("runAfter").onclick = () => runNow();
  };
  drop.onclick = () => file.click();
  file.onchange = () => send([...file.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); send([...e.dataTransfer.files]); };
}

async function showOutbox() {
  const j = await Source.outbox().catch(() => ({ items: [] }));
  const items = j.items || [];
  $view.innerHTML = `<div class="page-heading"><h1>보낼 자료</h1><p>노트북에서 정리할 링크와 캡처입니다.</p></div>
    <div class="card"><p class="meta" style="margin:0 0 10px">아무 앱에서 <b>공유 → 하루서랍</b>을 누르면 여기 담겼다가 맥으로 갑니다 (맥이 받으면 사라짐).</p>
      ${items.length ? items.map((it) => `<div class="todo"><span>${icon(it.kind === "image" ? "image" : it.kind === "export" ? "message-square" : "link")}</span>
        <span style="flex:1">${esc((it.text || it.name || "").slice(0, 80))}<br><span class="meta">${esc(it.ts?.slice(5, 16).replace("T", " "))} · ${esc(it.state)}</span></span></div>`).join("")
        : `<div class="empty" style="padding:20px">모두 맥으로 보냈어요</div>`}
      <div class="row2" style="margin-top:12px"><button class="btn small" id="sync">지금 보내기·받기</button>
      ${items.length ? `<button class="btn small" id="retry">다시 보내기</button>` : ""}</div></div>
    <div class="card"><h2>카톡 '나와의 채팅'도 넣으려면</h2>
      <ol class="steps"><li>카톡 나와의 채팅 → ≡ → ⚙ → 대화 내용 내보내기</li><li>'텍스트 메시지만 보내기' → 공유 창에서 <b>하루서랍</b></li><li>이미 넣은 메시지는 겹치지 않아요</li></ol></div>`;
  document.getElementById("sync").onclick = async () => { toast("맥과 주고받는 중…"); await Source.sync(); showOutbox(); };
  const r = document.getElementById("retry");
  if (r) r.onclick = async () => { await Source.retryOutbox(); toast("다시 보낼게요"); showOutbox(); };
}

// ---------------- 연결 ----------------
async function showLink() {
  if (isNative) return showLinkPhone();
  const j = await Source.pairing();
  const ph = j.phone;
  $view.innerHTML = `<div class="page-heading"><h1>폰 연결</h1><p>노트북에서 정리한 보고서를 폰에서도 읽어보세요.</p></div>
    <div class="card"><div class="lockprev">
      <img src="${j.qr}" alt="연결 QR" style="width:220px;height:220px;border-radius:12px;background:#fff;padding:6px">
      <div class="side"><ol class="steps">
        <li>폰에 하루서랍 앱 설치</li><li>앱 → 맥 연결 → <b>QR 찍기</b></li><li>끝! 폰이 맥에 인사하면 아래에 표시돼요</li></ol>
        <p class="meta">QR 이 안 되면 아래 코드를 카톡 '나에게 보내기'로 폰에 보내서 앱에 붙여 넣어도 돼요.</p></div></div>
      <div class="code" style="margin-top:12px">${esc(j.code)}</div>
      <div class="row2" style="margin-top:10px"><button class="btn small" id="copy">코드 복사</button>
        <button class="btn small" id="reset">새 코드 만들기 (기존 폰 연결 끊김)</button></div></div>
    <div class="card"><h2>폰 앱 설치</h2><div class="lockprev">
      <img src="${j.apk_qr}" alt="앱 받기 QR" style="width:150px;height:150px;border-radius:12px;background:#fff;padding:5px">
      <div class="side"><ol class="steps"><li>폰 카메라로 이 QR 을 찍어 <b>haru-drawer.apk</b> 받기</li>
        <li>설치할 때 '출처를 알 수 없는 앱' 허용</li><li>앱을 열고 위의 연결 QR 찍기</li></ol>
        <a class="meta" href="${esc(j.apk_url)}" target="_blank">${esc(j.apk_url)}</a></div></div></div>
    <div class="card"><h2>연결 상태</h2>${ph ? `<div><span class="ok">● 연결됨</span> ${esc(ph.dev?.model || "")} · ${ph.dev?.w}×${ph.dev?.h} · 마지막 ${esc((ph.seen || "").slice(0, 16).replace("T", " "))}</div>`
      : `<div class="muted">아직 폰이 인사하지 않았어요</div>`}
      <p class="meta">중계: ${esc(j.server)} (내용은 맥·폰만 아는 키로 암호화돼서 중계 서버는 못 읽어요)</p></div>`;
  document.getElementById("copy").onclick = async () => { await navigator.clipboard.writeText(j.code); toast("복사했어요"); };
  document.getElementById("reset").onclick = async () => {
    if (!confirm("새 코드를 만들면 지금 연결된 폰은 다시 연결해야 해요. 계속할까요?")) return;
    await Source.resetPairing(); showLink();
  };
}

async function showLinkPhone() {
  const st = await Source.status().catch(() => ({}));
  $view.innerHTML = `<div class="page-heading"><h1>맥 연결</h1><p>분석할 노트북과 연결해 보고서를 받아보세요.</p></div>
    <div class="card">${st.paired ? `<div><span class="ok">● 연결됨</span> ${esc(st.macName || "맥")}</div>
        <p class="meta">마지막으로 맥 소식: ${esc(st.lastHb || "아직 없음")}<br>다음 정리 예정: ${esc(st.macNext || "-")}</p>`
      : `<p>맥의 하루서랍 대시보드 → <b>폰 연결</b> 화면의 QR 을 찍으세요.</p>`}
      <div class="row2"><button class="btn primary" id="scan">QR 찍기</button><button class="btn" id="paste">코드 붙여 넣기</button>
      ${st.paired ? `<button class="btn" id="unpair">연결 끊기</button>` : ""}</div></div>`;
  document.getElementById("scan").onclick = async () => {
    try { const r = await Source.scanQr(); if (r.code) await doPair(r.code); } catch (e) { toast("QR 을 읽지 못했어요: " + e.message); }
  };
  document.getElementById("paste").onclick = async () => {
    const code = prompt("맥에서 받은 연결 코드 (HARU1. 로 시작)");
    if (code) await doPair(code);
  };
  const u = document.getElementById("unpair");
  if (u) u.onclick = async () => { if (confirm("연결을 끊을까요?")) { await Source.unpair(); showLinkPhone(); } };
}

async function doPair(code) {
  try {
    const r = await Source.pair(code.trim());
    toast(r.ok ? "맥과 연결했어요 — 곧 오늘 정리가 도착해요" : (r.msg || "연결하지 못했어요"));
  } catch (e) { toast("연결 실패: " + e.message); }
  showLinkPhone();
}

// ---------------- 설정 ----------------
async function showSettings() {
  if (isNative) return showSettingsPhone();
  const s = await Source.settings();
  const st = await Source.status(true).catch(() => ({}));
  $view.innerHTML = `<div class="page-heading"><h1>설정</h1><p>수집과 보고서를 내 생활에 맞춰 설정하세요.</p></div>
    <div class="card"><h2>유튜브 저장 영상</h2><p class="meta">경제·AI·휴식 재생목록의 새 저장분을 하루 보고서에 넣어요.</p><a class="btn small" href="#/youtube">유튜브 연결·수집 설정</a></div>
    <div class="card settings-form">
      <div class="field"><label for="schedule">정리 시각 (쉼표로)</label><input type="text" id="schedule" value="${esc((s.schedule || []).join(", "))}">
        <div class="hint">이 시각마다 새로 모은 걸 정리해 폰으로 보내요. 폰에서 공유하면 잠잠해진 뒤(3분) 바로 정리해요 (최소 ${s.min_run_gap_min || 20}분 간격).</div></div>
      <div class="field"><label for="boundary">하루가 바뀌는 시각</label><input type="number" id="boundary" min="0" max="8" value="${s.day_boundary_hour}">
        <div class="hint">새벽 이 시각 전에 보낸 건 전날로 칩니다.</div></div>
      <div class="field"><label for="tz">시간대</label><input type="text" id="tz" value="${esc(s.timezone)}">
        <div class="hint">폰이 연결되면 폰 시간대로 자동으로 맞춰요. (이 맥의 시스템 시간대와 따로)</div></div>
      <div class="field"><label for="profile">나에 대한 소개 (분석할 때 참고)</label><textarea id="profile">${esc(s.profile)}</textarea></div>
      <div class="field"><label for="cats">카테고리 (쉼표로)</label><input type="text" id="cats" value="${esc((s.categories || []).join(", "))}"></div>
      <div class="field"><label for="backend">AI</label><select id="backend">
        ${["codex", "ollama", "fake"].map((b) => `<option value="${b}" ${s.llm.backend === b ? "selected" : ""}>${{ codex: "Codex (ChatGPT 구독, 기본)", ollama: "ollama (이 맥 로컬 모델)", fake: "규칙 기반 (AI 없이 시험용)" }[b]}</option>`).join("")}
      </select><div class="hint">${st.llm ? (st.llm.ok ? `<span class="ok">사용 가능</span> ${esc(st.llm.msg || "")}` : `<span class="bad">사용 불가</span> ${esc(st.llm.msg || "")}`) : ""}</div></div>
      <div class="field"><label for="relay">중계 서버</label><input type="text" id="relay" value="${esc(s.relay?.server || "")}">
        <div class="hint">기본 ntfy.sh (무료·계정 없음). 직접 띄운 ntfy 주소로 바꿀 수 있어요. 바꾸면 폰을 다시 연결하세요.</div></div>
      <button class="btn primary" id="save">저장</button>
    </div>
    <div class="card"><h2>상태</h2>
      <div class="meta">상시 실행(데몬) 마지막 확인: ${esc(st.daemon_tick?.slice(0, 19).replace("T", " ") || "안 돌고 있음")}</div>
      <div class="meta">받은편지함: ${esc(st.inbox || "")}</div>
      <div class="log" style="margin-top:10px">${(st.events || []).map((e) => `${e.at.slice(5, 16).replace("T", " ")} ${e.kind} ${e.msg}`).map(esc).join("\n")}</div></div>`;
  document.getElementById("save").onclick = async () => {
    const split = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);
    await Source.saveSettings({
      schedule: split(document.getElementById("schedule").value),
      day_boundary_hour: Number(document.getElementById("boundary").value),
      timezone: document.getElementById("tz").value.trim(),
      profile: document.getElementById("profile").value.trim(),
      categories: split(document.getElementById("cats").value),
      llm: { backend: document.getElementById("backend").value },
      relay: { server: document.getElementById("relay").value.trim() },
    });
    toast("저장했어요");
    showSettings();
  };
}

async function showSettingsPhone() {
  const s = await Source.settings();
  $view.innerHTML = `<div class="page-heading"><h1>설정</h1><p>수집과 보고서를 내 생활에 맞춰 설정하세요.</p></div>
    <div class="card"><h2>잠금화면</h2>
      <label class="todo"><input type="checkbox" id="wall" ${s.wallpaper ? "checked" : ""}><span style="flex:1">잠금화면 배경에 오늘 정리 카드 넣기</span></label>
      <label class="todo"><input type="checkbox" id="notif" ${s.notify ? "checked" : ""}><span style="flex:1">잠금화면 알림으로도 보여 주기 (조용히, 소리 없음)</span></label>
      <div class="field"><label>카드 모양</label><div class="seg" id="seg">
        <button data-style="A" class="${s.style === "A" ? "on" : ""}">A 카드형</button><button data-style="B" class="${s.style === "B" ? "on" : ""}">B 큰 글씨</button></div></div>
      <div class="field"><label>배경</label><div class="row2">
        <button class="btn small" id="bgPick">내 사진 고르기</button><button class="btn small" id="bgDefault">기본 그라데이션</button>
        <span class="meta">${s.bg === "photo" ? "내 사진 사용 중" : "기본 그라데이션"}</span></div></div>
      <div id="prev" style="margin-top:10px"></div>
      <div class="row2" style="margin-top:10px"><button class="btn primary small" id="apply">지금 적용</button></div>
    </div>
    <div class="card"><h2>잘 돌게 하려면</h2>
      <div class="row2"><button class="btn small" id="perm">알림 허용</button><button class="btn small" id="batt">배터리 최적화 끄기</button></div>
      <p class="meta">삼성 폰은 절전 때문에 백그라운드 확인이 늦어질 수 있어요. '배터리 최적화 끄기'를 권해요.</p></div>`;
  const save = async (patch) => { await Source.saveSettings(patch); showSettingsPhone(); };
  document.getElementById("wall").onchange = (e) => save({ wallpaper: e.target.checked });
  document.getElementById("notif").onchange = (e) => save({ notify: e.target.checked });
  document.querySelectorAll("#seg [data-style]").forEach((b) => (b.onclick = () => save({ style: b.dataset.style })));
  document.getElementById("bgPick").onclick = async () => { await Source.pickBackground(); showSettingsPhone(); };
  document.getElementById("bgDefault").onclick = () => save({ bg: "gradient" });
  document.getElementById("apply").onclick = async () => { const r = await Source.applyLockscreen(); toast(r.ok ? "적용했어요" : (r.msg || "아직 받은 정리가 없어요")); };
  document.getElementById("perm").onclick = async () => { await Source.requestNotifications(); toast("알림 권한을 확인했어요"); };
  document.getElementById("batt").onclick = () => Source.openBatterySettings();
  try {
    const p = await Source.previewLockscreen(s.style);
    if (p.image) document.getElementById("prev").innerHTML = `<img src="${p.image}" alt="미리보기" style="width:160px;border-radius:16px;box-shadow:0 0 0 4px #0b0b0d">`;
  } catch { /* 받은 정리 없음 */ }
}

// ---------------- 정리하기 버튼 ----------------
async function runNow(opts = {}) {
  if (isNative) {
    const r = await Source.run();
    toast(r.ok ? "맥에 정리를 부탁했어요 (몇 분 걸려요)" : (r.msg || "맥과 연결돼 있지 않아요"));
    return;
  }
  const r = await Source.run({ force: false, ...opts });
  if (!r.ok) return toast(r.msg || "정리를 시작하지 못했어요");
  $run.disabled = true;
  $run.textContent = "정리 중…";
  let last = "";
  for (let i = 0; i < 600; i++) {
    await new Promise((res) => setTimeout(res, 2000));
    const st = await Source.status().catch(() => null);
    if (!st) continue;
    const line = (st.run_log || []).slice(-1)[0] || "";
    if (line && line !== last) { last = line; $run.textContent = line.trim().slice(0, 18) || "정리 중…"; }
    if (!st.running) break;
  }
  $run.disabled = false;
  $run.innerHTML = `${icon("list")} 정리하기`;
  toast("정리했어요");
  route();
}
$run.onclick = () => runNow();
$run.innerHTML = `${icon("list")} 정리하기`;

// ---------------- 길 찾기 ----------------
async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  drawTabs(h);
  window.scrollTo(0, 0);
  $view.innerHTML = '<p class="empty meta" role="status">불러오는 중…</p>';
  try {
    if (h.startsWith("day/")) return await showDay(h.slice(4));
    if (h === "days") return await showDays();
    if (h === "add") return await showAdd();
    if (h === "link") return await showLink();
    if (h === "settings") return await showSettings();
    if (h === "youtube" && !isNative) return await showYoutube($view, toast, runNow);
    return await showDay(null);
  } catch (e) {
    $view.innerHTML = `<section class="empty"><h1>화면을 불러오지 못했어요</h1><p>${esc(e.message)}</p><button class="btn" id="retryView">다시 불러오기</button></section>`;
    document.getElementById("retryView").onclick = route;
  }
}
window.addEventListener("hashchange", route);

// 폰 앱 첫 실행: 맥과 연결 전이면 '맥 연결' 화면부터, 알림 권한은 한 번만 묻는다
async function firstRun() {
  if (!isNative) return;
  try {
    const st = await Source.status();
    if (!st.paired && !location.hash) location.hash = "#/link";
    if (!st.notifications && pref.get("askedNotif", "") !== "1") {
      pref.set("askedNotif", "1");
      await Source.requestNotifications();
    }
  } catch { /* 네이티브 준비 전이면 다음에 */ }
}

if (isNative) {
  // 새 정리가 도착하면 (네이티브가 알려 줌) 화면 갱신
  Source.addListener("digest", () => { if (!location.hash || location.hash === "#/" || location.hash.startsWith("#/day")) route(); });
  Source.addListener("shared", () => { if (location.hash === "#/add") route(); });
  Source.addListener("paired", () => { toast("맥과 연결했어요"); route(); });
}
firstRun().finally(route);
