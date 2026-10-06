"""저장 문서의 테마 스크립트만 실행을 허용하고 자료의 코드는 차단한다."""
import base64
import hashlib
from html.parser import HTMLParser

import pytest

from haru import archive, briefing, config


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.scripts = []
        self.policy = ""
        self.in_script = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy":
            self.policy = attrs["content"]
        if tag == "script":
            assert not attrs.get("src")
            self.in_script = True
            self.scripts.append("")

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False


@pytest.mark.parametrize("kind", ["report", "source"])
def test_saved_document_allows_only_the_exact_theme_script(kind):
    attack = '</script><script>alert("private material")</script>'
    digest = {"day": "2026-10-03", "version": 5, "headline": attack, "summary": attack, "items": [
        {"id": "test", "title": attack, "summary": attack, "transcript_sections": [
            {"sections": [{"heading": attack, "body": attack, "time": "00:00:01"}]}]}]}
    if kind == "report":
        rendered = archive._report_html(digest, {})
    else:
        rendered = briefing.source_document(digest, {}, {"test": "source-test"}, set())
    doc = Document(rendered)
    script = (config.WEB_DIR / "js/theme.js").read_text(encoding="utf-8")
    assert doc.scripts == [script]
    digest = base64.b64encode(hashlib.sha256(doc.scripts[0].encode("utf-8")).digest()).decode("ascii")
    directives = dict(piece.strip().split(" ", 1) for piece in doc.policy.split(";") if piece.strip())
    assert directives["script-src"] == f"'sha256-{digest}'"
    assert directives["default-src"] == "'none'"
    assert directives["base-uri"] == directives["form-action"] == "'none'"
    assert attack not in rendered and "&lt;script&gt;" in rendered
    assert '<select data-theme-select aria-label="화면 테마">' in rendered
