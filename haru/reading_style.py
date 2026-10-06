"""저장 보고서와 원본 자료가 공유하는 오프라인 읽기 스타일."""

from .appearance import theme_css

READING_CSS = theme_css() + """
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Apple SD Gothic Neo',sans-serif;font-size:16px;line-height:1.9;word-break:keep-all}
main{max-width:800px;margin:auto;padding:40px 36px 88px}header{padding-bottom:28px;margin-bottom:28px;border-bottom:1px solid var(--line)}
.document-tools{display:flex;align-items:center;justify-content:space-between;gap:20px}.document-tools .appearance{line-height:1.4}
.brand{font-size:20px;font-weight:600;letter-spacing:-.7px}.eyebrow{font-size:12px;color:var(--accent);letter-spacing:.04em;margin:24px 0 6px}
h1{font-size:clamp(26px,4vw,34px);font-weight:550;line-height:1.5;letter-spacing:-1px;margin:6px 0 8px;text-wrap:balance}h2{font-size:22px;font-weight:600;line-height:1.5;margin:0 0 16px}h3{font-size:19px;font-weight:550;line-height:1.65;margin:12px 0 8px}h4{font-weight:600;line-height:1.65}
p{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 20px}.meta,small,.reading-intro{color:var(--text-3);font-size:13px}small{display:block;margin-left:24px}
a{color:var(--accent);overflow-wrap:anywhere;text-underline-offset:5px;text-decoration-thickness:1px}a:hover{text-decoration:none}:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
section{margin:32px 0;padding-bottom:28px;border-bottom:1px solid var(--line);scroll-margin-top:24px}ul,ol{padding-left:24px}li{padding:5px 0}li::marker{color:var(--accent)}
.checklist{list-style:none;padding:0}.checklist li{padding:10px 0;border-bottom:1px solid var(--line)}.checklist li:last-child{border-bottom:0}.grid{display:block}
article{border-top:1px solid var(--line);padding:32px 0;min-width:0;scroll-margin-top:80px}article:first-child{border-top:0;padding-top:0}
.tag{font-size:12px;padding:5px 11px;border-radius:20px;background:var(--accent-soft);color:var(--accent)}img{max-width:100%;max-height:340px;object-fit:contain;border-radius:12px}
nav{display:flex;flex-wrap:wrap;gap:8px 20px;margin-top:20px;font-size:13px}nav a{display:inline-flex;align-items:center;min-height:44px}.downloads{border-top:1px solid var(--line);padding-top:12px;margin-top:28px}
footer{margin-top:32px;padding-top:8px}summary{cursor:pointer;min-height:44px;padding:10px 0;color:var(--accent);font-size:14px;font-weight:500}
.quick h4{font-size:12px;color:var(--text-3);margin:16px 0 8px}.quick ol{margin:0 0 20px;font-size:15px}.quick li{padding:6px 0 6px 4px}.quick li::marker{font-size:13px;font-weight:600}
header>.quick{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 24px;margin:24px 0 8px}header>.quick h4{margin:0 0 8px;color:var(--accent)}header>.quick ol{margin:0}
details h4{margin:28px 0 8px;font-size:17px}details p{font-size:16px}.briefing{border-top:1px solid var(--line);margin-top:18px}.caption{font-size:13px;color:var(--text-3);margin-top:-8px}
.reading-bar{position:sticky;top:0;z-index:1;background:var(--bg);border-bottom:1px solid var(--line);margin:0;max-width:none;padding:8px max(20px,calc((100vw - 728px)/2));align-items:center;justify-content:space-between}
.source-intro{border-bottom:1px solid var(--line);padding-bottom:24px}.notice{font-size:13px;color:var(--text-3);padding-left:16px;border-left:2px solid var(--accent);line-height:1.8}
.contents{display:block;padding:20px 24px;background:var(--surface);border:1px solid var(--line);border-radius:12px;margin:28px 0 36px;scroll-margin-top:80px}.contents h2{font-size:16px;margin-bottom:8px}.contents ol{margin:0;font-size:15px}.contents a{display:inline-block;min-height:44px}
.chapter-index{background:var(--surface-2);border-radius:12px;padding:8px 18px;margin:20px 0 28px}.chapter-index ol{font-size:14px}.chapter-index a{display:inline-block;min-height:44px;padding:5px 0}.chapter-index span{font-size:12px;display:block;color:var(--text-3)}
.source-chapter{margin-top:32px}.source-chapter h3{scroll-margin-top:80px}.chapter-time{font-size:12px;color:var(--accent);font-variant-numeric:tabular-nums;margin:0 0 14px}
.source-chapter p:not(.chapter-time){color:var(--text-2)}.back-to-contents{display:inline-block;min-height:44px;font-size:13px;margin-top:20px}
@media(max-width:600px){body{font-size:15px}main{padding:24px 20px 60px}h2{font-size:21px}h3{font-size:18px}header>.quick{padding:16px 18px}.quick ol{font-size:14px}details p{font-size:15px}.reading-bar{font-size:12px;gap:8px;padding:4px 20px}.contents{padding:16px 18px}.chapter-index{padding:8px 14px}}
@media print{body{background:white;color:#000}main{max-width:none;padding:0}.reading-bar,nav,.chapter-index,.back-to-contents{display:none}article{break-inside:auto}h2,h3,h4{break-after:avoid}details{display:block}details>summary{display:none}details::details-content{display:contents}header>.quick,.contents{background:white}}
"""
