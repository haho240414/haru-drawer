// Shared daily reading view for the Mac dashboard and Capacitor app.
import { catColor, esc, fmtDuration, icon, KIND_ICON, KIND_LABEL } from "./common.js";

export function renderReport(root, data, ctx) {
  const d = data.digest;
  if (!d) {
    root.innerHTML = `<section class="empty"><h1>${data.pending ? "정리를 기다리는 자료가 있어요" : "아직 보고서가 없어요"}</h1>
      <p>${data.pending ? `새로 모은 ${data.pending}개를 정리하면 이곳에서 읽을 수 있어요.` : "이날 모은 자료가 없습니다. 링크나 캡처, 카톡 내보내기 파일을 추가해 보세요."}</p>
      ${data.pending ? '<button class="btn primary" data-act="run">지금 정리하기</button>' : '<a class="btn" href="#/add">자료 추가</a>'}</section>`;
    return;
  }
  const items = d.items || [];
  const byId = Object.fromEntries(items.map(i => [i.id, i]));
  const cats = d.stats?.categories || [];
  const filters = [...new Set(items.map(i => i.category).filter(Boolean))];
  const style = ctx.style || "A";
  const hours = Array(24).fill(0);
  for (const it of items) {
    const hour = Number((it.time || "").slice(0, 2));
    if (Number.isInteger(hour) && hour >= 0 && hour < 24) hours[hour]++;
  }
  const maxH = Math.max(1, ...hours);
  const trend = d.trend?.rows || [];
  const maxT = Math.max(1, ...trend.map(r => Math.max(r.n, r.prev)));

  root.innerHTML = `<div class="report-layout">
    <div class="report-reading">
      <section class="hero">
        <p class="eyebrow">오늘의 서랍</p>
        <h1 class="headline">${esc(d.headline)}</h1>
        <p class="reading-intro">모아둔 ${items.length}개 자료에서 꺼낸 오늘의 이야기.</p>
        ${quickHtml(d)}
        ${d.quick_summary?.length ? `<details class="daily-briefing"><summary>${icon("chevron-right", "disclosure-icon")}오늘의 상세 브리핑</summary><p class="summary">${esc(d.summary)}</p></details>` : `<p class="summary">${esc(d.summary)}</p>`}
        <div class="legend" aria-label="자료 분류">${cats.map(([c, n]) => `<span>${esc(c)} ${n}</span>`).join("")}</div>
      </section>
      <nav class="reading-nav" aria-label="보고서 읽기"><button data-section="collection">${icon("file-text")} 자료별로 읽기</button>${d.highlights?.length ? '<button data-section="highlights">눈여겨볼 이야기</button>' : ''}</nav>

      ${d.highlights?.length ? `<section class="report-section" id="highlights" tabindex="-1"><h2>눈여겨볼 이야기</h2>
        ${d.highlights.map((h, i) => byId[h.id] ? `<button class="hl" data-goto="${esc(h.id)}" aria-label="${esc(byId[h.id].title)} 원본 자료로 이동">
          <span class="num">${String(i + 1).padStart(2, "0")}</span><span><span class="t">${esc(byId[h.id].title)}</span>
          <span class="why">${esc(h.why)}</span></span></button>` : "").join("")}</section>` : ""}

      ${d.todos?.length ? `<section class="report-section"><h2>꺼내두면 좋을 메모</h2><p class="section-caption">시간이 날 때 하나씩 살펴보세요.</p>
        ${d.todos.map((t, i) => `<div class="todo ${t.done ? "done" : ""}">
          <input type="checkbox" id="todo-${i}" data-todo="${esc(t.key)}" ${t.done ? "checked" : ""}>
          <label class="txt" for="todo-${i}">${esc(t.text)}</label>
          ${t.id && byId[t.id] ? `<a href="#" class="todo-source muted" data-goto="${esc(t.id)}" aria-label="${esc(t.text)} 관련 자료로 이동">${icon("external-link")}</a>` : ""}
          ${t.when ? `<span class="when ${t.when === "오늘" ? "today" : ""}">${esc(t.when)}</span>` : ""}</div>`).join("")}
        ${d.tomorrow ? `<p class="meta" style="margin-top:12px">내일 아침: ${esc(d.tomorrow)}</p>` : ""}</section>` : ""}

      <section class="report-section" id="collection" tabindex="-1" aria-label="모은 자료">
        <div class="collection-head"><h2>차곡차곡 모은 자료</h2><div class="filters" aria-label="분류 필터">
          <button class="filter on" data-filter="" aria-pressed="true">전체 ${items.length}</button>
          ${filters.map(c => `<button class="filter" data-filter="${esc(c)}" aria-pressed="false">${esc(c)} ${items.filter(i => i.category === c).length}</button>`).join("")}
        </div></div>
        ${items.map(it => itemHtml(it, ctx)).join("")}
      </section>

      ${d.themes?.length ? `<details class="report-section"><summary>${icon("chevron-right", "disclosure-icon")}주제별 흐름</summary>
        ${d.themes.map(t => `<div class="theme"><div class="name">${esc(t.name)} <span class="muted">${t.ids.length}</span></div>
          <p class="ins">${esc(t.insight)}</p><div class="chips">${t.ids.map(id => byId[id] ? `<button class="chip" data-goto="${esc(id)}">${esc(byId[id].title)}</button>` : "").join("")}</div></div>`).join("")}
      </details>` : ""}

      ${d.read_later?.length ? `<details class="report-section"><summary>${icon("chevron-right", "disclosure-icon")}나중에 볼 것 · ${d.read_later.length}</summary><div class="chips">
        ${d.read_later.map(id => byId[id] ? `<button class="chip" data-goto="${esc(id)}">${icon(KIND_ICON[byId[id].kind] || "file")} ${esc(byId[id].title)}${byId[id].duration ? ` · ${fmtDuration(byId[id].duration)}` : ""}</button>` : "").join("")}
      </div></details>` : ""}

      <details class="report-section"><summary>${icon("chevron-right", "disclosure-icon")}수집 기록과 분석 정보</summary>
        <h3>시간대별 자료 수</h3>
        <div class="hours" role="img" aria-label="${hours.map((n, h) => n ? `${h}시 ${n}개` : "").filter(Boolean).join(", ") || "자료 없음"}">
          ${hours.map((n, h) => `<span title="${h}시 ${n}개" style="height:${(n / maxH) * 100}%;opacity:${n ? .9 : .15}"></span>`).join("")}</div>
        <div class="hours-l"><span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>24시</span></div>
        ${trend.length ? `<h3>최근 7일 / 그 전 7일</h3><div class="trend">
          ${trend.map(r => `<span>${esc(r.category)}</span><div><div class="bar" style="width:${(r.n / maxT) * 100}%;background:${catColor(r.category)}"></div>
            <div class="bar" style="width:${(r.prev / maxT) * 100}%;background:var(--line);margin-top:3px;height:5px"></div></div>
            <span class="num">${r.n} <span class="muted">/ ${r.prev}</span></span>`).join("")}</div>` : ""}
        <p class="meta" style="margin-top:16px">보고서 v${d.version || 1} · ${esc((d.generated_at || "").slice(0, 16).replace("T", " "))} · ${d.llm?.backend === "codex" ? "AI(Codex) 분석" : d.llm?.backend === "heuristic" ? "규칙 기반(AI 실패 시 대체)" : esc(d.llm?.backend || "")}</p>
      </details>
    </div>

    <aside class="report-utilities" aria-label="보고서 활용">
      <section class="utility"><p class="eyebrow">폰에서도 가볍게</p><h2>잠깐 보는 오늘</h2>
        <p class="section-caption">잠금화면에 담을 짧은 요약이에요.</p>
        <p class="lock-title">${esc(d.lock?.title || d.headline)}</p>
        <ul class="lock-lines">${(d.lock?.lines || []).map(l => `<li>${esc(l)}</li>`).join("")}</ul>
        <div class="seg" id="styleSeg" aria-label="잠금화면 카드 모양">
          <button data-style="A" aria-pressed="${style === "A"}" class="${style === "A" ? "on" : ""}">카드형</button>
          <button data-style="B" aria-pressed="${style === "B"}" class="${style === "B" ? "on" : ""}">큰 글씨</button>
        </div>
        <details class="preview-details"><summary>${icon("chevron-right", "disclosure-icon")}미리보기</summary>
          <div class="phone ${style}" id="phonePrev"><div class="clock">${esc((d.generated_at || "").slice(11, 16) || "--:--")}</div>
            <div class="date">${esc(d.label)}</div>${data.cards?.[style] ? `<img class="ov" alt="선택한 잠금화면 카드" src="${esc(data.cards[style])}">` : ""}</div>
          ${!ctx.isNative && data.cards?.[style] ? `<a id="cardFullLink" class="secondary-link" href="${esc(data.cards[style])}" target="_blank" rel="noopener">PNG 크게 보기 ${icon("external-link")}</a>` : ""}
        </details>
        ${ctx.lockActions || ""}${ctx.lockNote ? `<p class="meta">${ctx.lockNote}</p>` : ""}
      </section>

      ${!ctx.isNative ? `<section class="utility"><p class="eyebrow">다시 읽고 싶은 날에</p><h2>노트북에 보관</h2>
        <p class="meta">오늘의 브리핑과 원본 정리를 날짜별 폴더에 담아둡니다.</p>
        <button class="btn block" id="saveFiles">${icon("download")} ${data.archive?.exists ? "파일 갱신" : "파일로 저장"}</button>
        ${data.archive?.exists ? `<a class="secondary-link" href="${esc(data.archive.url)}" target="_blank" rel="noopener">저장한 보고서 보기 ${icon("external-link")}</a>` : ""}
        <details class="path-details"><summary>${icon("chevron-right", "disclosure-icon")}저장 위치</summary><p class="meta">${esc(data.archive?.path || "")}</p></details>
      </section>` : ""}
      ${!ctx.isNative && data.content_enabled ? `<section class="utility"><p class="eyebrow">모아둔 생각을 글로</p><h2>블로그 초안</h2>
        ${data.content ? `<p class="meta">${esc(data.content.title)}</p><p class="meta">${data.content.outdated ? "이전 보고서로 만든 초안이에요. 새 자료 반영을 기다리고 있어요." : data.content.ready ? "글과 대표 이미지가 준비됐어요. 발행 전에 한 번 읽어보세요." : "글은 준비됐어요. 대표 이미지를 기다리고 있어요."}</p>
          <a class="secondary-link" href="${esc(data.content.url)}" target="_blank" rel="noopener">초안 읽기 ${icon("external-link")}</a>` : '<p class="meta">새 보고서가 완성되면 공개 영상에서 글감을 골라 초안과 대표 이미지를 만듭니다.</p>'}
      </section>` : ""}
    </aside>
  </div>`;
}

function itemHtml(it, ctx) {
  const thumb = ctx.thumbUrl(it);
  const hasBriefing = it.briefing?.length || it.quick_summary?.length;
  const host = it.url ? (() => { try { return new URL(it.url).hostname.replace(/^www\./, ""); } catch { return ""; } })() : "";
  let chapter = 0;
  const chapters = (it.transcript_sections || []).flatMap(s => s.sections || []);
  const chapterId = n => `chapter-${cssId(it.id)}-${n}`;
  return `<article class="item" id="it-${cssId(it.id)}" data-category="${esc(it.category || "")}">
    <div class="item-icon">${icon(it.source === "youtube" ? "square-play" : KIND_ICON[it.kind] || "file")}</div>
    <div><h3 class="title">${esc(it.title || KIND_LABEL[it.kind])}</h3>
      <div class="head"><span>${esc(KIND_LABEL[it.kind] || "자료")} · ${esc(it.time)}</span><span>${esc(it.category)}</span>
        ${it.intent ? `<span>· ${esc(it.intent)}</span>` : ""}
        <span class="sr-only">중요도 ${esc(it.importance || 0)} / 5</span>
        ${it.source === "share" ? "<span>· 폰 공유</span>" : ""}</div>
      ${it.source === "youtube" ? `<p class="item-origin">${esc(it.channel || "유튜브")} ${it.duration ? `· ${fmtDuration(it.duration)}` : ""} · ${esc((it.youtube_playlists || []).map(p => p.name).join(" · "))}</p>` : ""}
      ${quickHtml(it) || `<p class="sum">${esc(it.summary)}</p>`}
      ${hasBriefing || it.key_points?.length || it.actions?.length ? `<details class="item-extra briefing"><summary>${icon("chevron-right", "disclosure-icon")}${hasBriefing ? "상세 브리핑" : "핵심 내용과 실행 메모"}</summary>
        ${it.briefing?.length ? it.briefing.map(s => `<h4>${esc(s.heading)}</h4><p class="sum">${esc(s.body)}</p>`).join("") : hasBriefing ? `<p class="sum">${esc(it.summary)}</p>` : ""}
        ${it.key_points?.length ? "<h4>기억할 포인트</h4>" : ""}
        ${it.key_points?.length ? `<ul class="kp">${it.key_points.map(k => `<li>${esc(k)}</li>`).join("")}</ul>` : ""}
        ${it.actions?.length ? `<div class="acts">${it.actions.map(a => `<span class="act">${esc(a)}</span>`).join("")}</div>` : ""}</details>` : ""}
      ${it.transcript_sections?.length ? `<details class="item-extra source-notes"><summary>${icon("chevron-right", "disclosure-icon")}원본 내용 정리 · 시간 순서대로</summary>
        <p class="note">음성·자막을 풀어 쓴 정리본입니다. 반복·광고는 축약했으며, 전사 전문은 노트북에 보관합니다.</p>
        ${chapters.length ? `<details class="chapter-index"><summary>${icon("chevron-right", "disclosure-icon")}목차 · ${chapters.length}개 이야기</summary><ol>${chapters.map((ch, n) => `<li><button data-section="${chapterId(n + 1)}"><span>${esc(ch.time)}</span>${esc(ch.heading)}</button></li>`).join("")}</ol></details>` : ""}
        ${it.transcript_sections.map(s => `${s.sections?.length ? s.sections.map(ch => `<h4 id="${chapterId(++chapter)}" tabindex="-1">${esc(ch.heading)}</h4><p class="chapter-time">${esc(ch.time)}</p><p class="sum">${esc(ch.body)}</p>`).join("") : `<h4>구간 ${esc(s.part)}/${esc(s.total)}</h4><p class="sum">${esc(s.summary)}</p><ul class="kp">${(s.points || []).map(p => `<li>${esc(p)}</li>`).join("")}</ul>`}
          ${(s.uncertain || []).map(p => `<p class="note">확인 필요: ${esc(p)}</p>`).join("")}`).join("")}</details>` : ""}
      <div class="links">
        ${it.url ? `<a href="${esc(it.url)}" data-open="${esc(it.url)}">${esc(it.site || host)} 열기 ${icon("external-link")}</a>` : ""}
        ${it.duration && it.source !== "youtube" ? `<span class="muted">${fmtDuration(it.duration)}${it.channel ? ` · ${esc(it.channel)}` : ""}</span>` : ""}
        ${ctx.canHide ? `<button class="chip" data-hide="${esc(it.id)}" title="${esc(it.title || "자료")}를 보고서에서 빼고 다시 정리">빼기</button>` : ""}
      </div>
      ${it.note || it.source === "youtube" ? `<details class="item-provenance"><summary>${icon("chevron-right", "disclosure-icon")}수집·분석 정보</summary>${it.source === "youtube" ? `<p class="meta">유튜브 ${it.date_basis === "first_observed_at" ? "처음 발견한 날짜 기준" : "저장일 기준"}</p>` : ""}${it.note ? `<p class="meta">${esc(it.note)}</p>` : ""}</details>` : ""}
    </div>
    ${thumb ? `<button class="thumb-button" data-full="${esc(ctx.fullUrl(it) || thumb)}" aria-label="${esc(it.title || "이미지")} 크게 보기"><img class="thumb" src="${esc(thumb)}" alt="" loading="lazy"></button>` : ""}
  </article>`;
}

function quickHtml(data) {
  return data.quick_summary?.length ? `<div class="quick-summary"><h4>3줄 요약</h4><ol>${data.quick_summary.map(s => `<li>${esc(s)}</li>`).join("")}</ol></div>` : "";
}

export function cssId(id) { return String(id).replace(/[^a-zA-Z0-9_-]/g, "_"); }
