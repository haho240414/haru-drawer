// 하루 보고서 화면 (맥 대시보드와 폰 앱이 같이 씀)
import { catColor, esc, fmtDuration, KIND_ICON, KIND_LABEL } from "./common.js";

const stars = (n) => "★".repeat(Math.max(0, Math.min(5, n || 0)));

export function renderReport(root, data, ctx) {
  const d = data.digest;
  if (!d) {
    root.innerHTML = `<div class="card empty">${data.pending ? `새로 모은 ${data.pending}개를 아직 정리하지 않았어요.<br><br>
      <button class="btn primary" data-act="run">지금 정리하기</button>` : "이날은 모은 게 없어요."}</div>`;
    return;
  }
  const items = d.items || [];
  const byId = Object.fromEntries(items.map((i) => [i.id, i]));
  const cats = d.stats?.categories || [];
  const total = cats.reduce((s, [, n]) => s + n, 0) || 1;
  const style = ctx.style || "A";
  const hours = Array(24).fill(0);
  for (const it of items) hours[Number(it.time.slice(0, 2))]++;
  const maxH = Math.max(1, ...hours);
  const trend = d.trend?.rows || [];
  const maxT = Math.max(1, ...trend.map((r) => Math.max(r.n, r.prev)));

  root.innerHTML = `
    <section class="card hero">
      <h1 class="headline">${esc(d.headline)}</h1>
      <p class="summary">${esc(d.summary)}</p>
      <div class="catbar">${cats.map(([c, n]) => `<span style="width:${(n / total) * 100}%;background:${catColor(c)}" title="${esc(c)} ${n}"></span>`).join("")}</div>
      <div class="legend">${cats.map(([c, n]) => `<span><i class="dot" style="background:${catColor(c)}"></i>${esc(c)} ${n}</span>`).join("")}</div>
    </section>

    <section class="card">
      <h2>잠금화면</h2>
      <div class="lockprev">
        <div class="phone ${style}" id="phonePrev">
          <div class="clock">${esc((d.generated_at || "").slice(11, 16) || "--:--")}</div>
          <div class="date">${esc(d.label)}</div>
          ${data.cards?.[style] ? `<img class="ov" alt="잠금화면 카드" src="${data.cards[style]}">` : ""}
        </div>
        <div class="side">
          <div class="seg" id="styleSeg">
            <button data-style="A" class="${style === "A" ? "on" : ""}">A 카드형</button>
            <button data-style="B" class="${style === "B" ? "on" : ""}">B 큰 글씨</button>
          </div>
          <p class="meta" style="margin-top:12px">${esc(d.lock?.title || "")}<br>${(d.lock?.lines || []).map(esc).join(" · ")}</p>
          ${ctx.lockNote ? `<p class="meta">${ctx.lockNote}</p>` : ""}
          ${ctx.lockActions || ""}
        </div>
      </div>
    </section>

    ${d.highlights?.length ? `<section class="card"><h2>오늘의 핵심</h2>
      ${d.highlights.map((h, i) => {
        const it = byId[h.id];
        return it ? `<div class="hl" data-goto="${esc(h.id)}"><span class="num">${i + 1}</span><div>
          <div class="t">${esc(it.title)}</div><div class="why">${esc(h.why)}</div></div></div>` : "";
      }).join("")}</section>` : ""}

    ${d.todos?.length ? `<section class="card"><h2>할 일</h2>
      ${d.todos.map((t) => `<label class="todo ${t.done ? "done" : ""}">
        <input type="checkbox" data-todo="${esc(t.key)}" ${t.done ? "checked" : ""}>
        <span class="txt" style="flex:1">${esc(t.text)}${t.id && byId[t.id] ? ` <a class="muted" href="#" data-goto="${esc(t.id)}">↗</a>` : ""}</span>
        <span class="when ${t.when === "오늘" ? "today" : ""}">${esc(t.when)}</span></label>`).join("")}
      ${d.tomorrow ? `<p class="meta" style="margin:10px 0 0">내일 아침: ${esc(d.tomorrow)}</p>` : ""}</section>` : ""}

    ${d.themes?.length ? `<section class="card"><h2>주제별 흐름</h2>
      ${d.themes.map((t) => `<div class="theme"><div class="name">${esc(t.name)} <span class="muted">${t.ids.length}</span></div>
        <div class="ins">${esc(t.insight)}</div>
        <div class="chips">${t.ids.map((id) => byId[id] ? `<button class="chip" data-goto="${esc(id)}">${esc(byId[id].title)}</button>` : "").join("")}</div></div>`).join("")}
    </section>` : ""}

    ${d.read_later?.length ? `<section class="card"><h2>나중에 볼 것</h2><div class="chips">
      ${d.read_later.map((id) => byId[id] ? `<button class="chip" data-goto="${esc(id)}">${KIND_ICON[byId[id].kind] || ""} ${esc(byId[id].title)}${byId[id].duration ? ` · ${fmtDuration(byId[id].duration)}` : ""}</button>` : "").join("")}
    </div></section>` : ""}

    <section class="card"><h2>모은 것 ${items.length}개</h2>
      ${items.map((it) => itemHtml(it, ctx)).join("")}
    </section>

    <section class="card"><h2>시간대</h2>
      <div class="hours">${hours.map((n, h) => `<span title="${h}시 ${n}개" style="height:${(n / maxH) * 100}%;opacity:${n ? 0.9 : 0.15}"></span>`).join("")}</div>
      <div class="hours-l"><span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>24시</span></div>
      ${trend.length ? `<h2 style="margin-top:18px">최근 7일 (회색 = 그 전 7일)</h2><div class="trend">
        ${trend.map((r) => `<span>${esc(r.category)}</span>
          <div><div class="bar" style="width:${(r.n / maxT) * 100}%;background:${catColor(r.category)}"></div>
          <div class="bar" style="width:${(r.prev / maxT) * 100}%;background:var(--line);margin-top:3px;height:5px"></div></div>
          <span class="num">${r.n} <span class="muted">/ ${r.prev}</span></span>`).join("")}</div>` : ""}
      <p class="meta" style="margin:12px 0 0">보고서 v${d.version || 1} · ${esc((d.generated_at || "").slice(0, 16).replace("T", " "))} · ${d.llm?.backend === "codex" ? "AI(Codex) 분석" : d.llm?.backend === "heuristic" ? "규칙 기반(AI 실패 시 대체)" : esc(d.llm?.backend || "")}</p>
    </section>`;
}

function itemHtml(it, ctx) {
  const thumb = ctx.thumbUrl(it);
  const host = it.url ? (() => { try { return new URL(it.url).hostname.replace(/^www\./, ""); } catch { return ""; } })() : "";
  return `<article class="item" id="it-${cssId(it.id)}">
    <div>
      <div class="head"><span>${KIND_ICON[it.kind] || ""} ${it.time}</span>
        <span class="cat"><i class="dot" style="background:${catColor(it.category)}"></i>${esc(it.category)}</span>
        ${it.intent ? `<span>· ${esc(it.intent)}</span>` : ""}
        <span class="imp" title="중요도">${stars(it.importance)}</span>
        ${it.source === "share" ? `<span>· 폰 공유</span>` : ""}</div>
      ${it.source === "youtube" ? `<div class="meta">유튜브 ${it.date_basis === "first_observed_at" ? "처음 발견한 날짜 기준" : "저장일 기준"} · ${esc((it.youtube_playlists || []).map(p => p.name).join(" · "))}</div>` : ""}
      <div class="title">${esc(it.title || KIND_LABEL[it.kind])}</div>
      <p class="sum">${esc(it.summary)}</p>
      ${it.key_points?.length ? `<ul class="kp">${it.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>` : ""}
      ${it.actions?.length ? `<div class="acts">${it.actions.map((a) => `<span class="act">→ ${esc(a)}</span>`).join("")}</div>` : ""}
      <div class="links">
        ${it.url ? `<a href="${esc(it.url)}" data-open="${esc(it.url)}">${esc(it.site || host)} 열기 ↗</a>` : ""}
        ${it.duration ? `<span class="muted">${fmtDuration(it.duration)}${it.channel ? ` · ${esc(it.channel)}` : ""}</span>` : ""}
        ${it.note ? `<span class="note">${esc(it.note)}</span>` : ""}
        ${ctx.canHide ? `<button class="chip" data-hide="${esc(it.id)}" title="보고서에서 빼고 다시 정리">빼기</button>` : ""}
      </div>
    </div>
    ${thumb ? `<img class="thumb" src="${thumb}" alt="" data-full="${esc(ctx.fullUrl(it) || thumb)}" loading="lazy">` : ""}
  </article>`;
}

export function cssId(id) { return String(id).replace(/[^a-zA-Z0-9_-]/g, "_"); }
