// 잠금화면 카드 그리기 — 맥이 크롬으로 이 화면을 찍어 투명 PNG 를 만들고, 앱 미리보기도 같은 코드를 쓴다.
// 카드 데이터: { label, count, title, lines[], todos, readLater, cats: [[이름, 개수]...], updated }
import { catColor, esc } from "./common.js";

export function renderLockCard(root, card, style = "A") {
  root.className = `lc ${style}`;
  if (!card || !card.count) {
    root.innerHTML = `<div class="empty">하루서랍 · 오늘 모은 게 아직 없어요</div>`;
    return;
  }
  const lines = (card.lines || []).slice(0, 3);
  const cats = (card.cats || []).slice(0, 4);
  if (style === "B") {
    const total = cats.reduce((s, [, n]) => s + n, 0) || 1;
    root.innerHTML = `
      <div class="wrap">
        <div class="kicker">하루서랍 · ${esc(card.label)} · <b>${card.count}개</b></div>
        <div class="title">${esc(card.title)}</div>
        <div class="lines">${lines.map((t, i) =>
          `<div class="line"><span class="n">${String(i + 1).padStart(2, "0")}</span><span class="t">${esc(t)}</span></div>`).join("")}</div>
        <div class="bar">${cats.map(([c, n]) => `<span style="width:${(n / total) * 100}%;background:${catColor(c)}"></span>`).join("")}</div>
        <div class="legend">${cats.map(([c, n]) => `<span><i class="dot" style="background:${catColor(c)}"></i>${esc(c)} ${n}</span>`).join("")}</div>
        ${card.todos ? `<div class="todo">할 일 ${card.todos}개 남음${card.updated ? ` · ${esc(card.updated)} 정리` : ""}</div>` : ""}
      </div>`;
    return;
  }
  root.innerHTML = `
    <div class="panel">
      <div class="top"><span class="brand">하루서랍 · ${esc(card.label)}</span><span class="count">${card.count}개</span></div>
      <div class="title">${esc(card.title)}</div>
      <ul>${lines.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
      <div class="foot">
        ${card.todos ? `<span class="chip todo">할 일 ${card.todos}</span>` : ""}
        ${cats.slice(0, 3).map(([c, n]) => `<span class="chip"><i class="dot" style="background:${catColor(c)}"></i>${esc(c)} ${n}</span>`).join("")}
        ${card.readLater ? `<span class="chip">나중에 볼 것 ${card.readLater}</span>` : ""}
      </div>
    </div>`;
}
