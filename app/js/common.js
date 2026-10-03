// 폰 앱·맥 대시보드·잠금화면 카드가 같이 쓰는 작은 도구들

export const CAT_COLORS = {
  "부동산": "#f59e0b",
  "재테크·투자": "#10b981",
  "AI·테크": "#818cf8",
  "업무": "#38bdf8",
  "콘텐츠·SNS": "#f472b6",
  "쇼핑": "#fb923c",
  "건강·운동": "#4ade80",
  "맛집·여행": "#facc15",
  "생활·정보": "#2dd4bf",
  "기타": "#94a3b8",
};
const SPARE = ["#a78bfa", "#f87171", "#34d399", "#60a5fa", "#fbbf24", "#e879f9"];

export function catColor(name) {
  if (CAT_COLORS[name]) return CAT_COLORS[name];
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return SPARE[h % SPARE.length];
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const KIND_LABEL = { link: "링크", image: "캡처", text: "메모", video: "동영상", file: "파일", audio: "음성" };
export const KIND_ICON = { link: "link", image: "image", text: "file-text", video: "square-play", file: "file", audio: "mic" };

// Official Lucide geometry is bundled locally, including its license.
export function icon(name, cls = "") {
  return `<svg class="icon ${esc(cls)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="vendor/lucide.svg#${esc(name)}"></use></svg>`;
}

export function fmtDuration(sec) {
  if (!sec) return "";
  const m = Math.round(sec / 60);
  return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분`;
}

// 다이제스트 → 잠금화면 카드 데이터 (맥 렌더러와 폰 미리보기가 같은 규칙을 쓰게 한 곳에)
export function cardFromDigest(d) {
  if (!d) return null;
  const lock = d.lock || {};
  const lines = (lock.lines && lock.lines.length ? lock.lines : (d.highlights || []).map((h) => {
    const it = (d.items || []).find((x) => x.id === h.id);
    return it ? (it.lock_line || it.title) : "";
  })).filter(Boolean).slice(0, 3);
  return {
    day: d.day,
    label: d.label,
    count: (d.stats && d.stats.count) || (d.items || []).length,
    title: lock.title || d.headline || "",
    lines,
    todos: (d.todos || []).filter((t) => !t.done).length,
    readLater: (d.read_later || []).length,
    cats: (d.stats && d.stats.categories) || [],
    updated: d.generated_at ? d.generated_at.slice(11, 16) : "",
  };
}
