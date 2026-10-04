"""초안 재사용·공개 입력 경계·실패 재개·이미지 작업 연결·파일 경계를 검증한다."""
import json
from pathlib import Path

import pytest
from PIL import Image

from haru import archive, config, content, store
from haru.llm import LLMError
from haru.server import app

DAY = '2026-10-03'


def seed():
    config.update_settings({'content': {'enabled': True}})
    public = {'id': 'public', 'source': 'youtube', 'status': 'new', 'kind': 'link',
              'day': DAY, 'ts': DAY+'T22:00:00+09:00', 'url': 'https://www.youtube.com/watch?v=abcdefghijk',
              'text': 'PRIVATE_RAW_TEXT', 'meta': {'account': 'PRIVATE_ACCOUNT', 'transcription_pending': False}}
    store.upsert_item(public)
    store.update_item('public', status='analyzed')
    share = dict(public, id='private', source='share')
    store.upsert_item(share)
    store.update_item('private', status='analyzed')
    data = {'day': DAY, 'llm': {'backend': 'codex'}, 'headline': 'PRIVATE_HEADLINE', 'items': []}
    for ident in ['public', 'private']:
        data['items'].append({'id': ident, 'title': '공개 영상' if ident == 'public' else 'PRIVATE_TITLE',
                             'url': public['url'], 'briefing': [{'heading': 'PRIVATE_INTENT', 'body': 'PRIVATE_NOTES'}],
                             'transcript_sections': [{'sections': [{'heading': '공개 발언', 'time': '00:01:00',
                                  'body': '제작자는 실행 주기와 비용을 함께 살펴보라고 설명한다.'}], 'uncertain': ['정확한 서비스명 확인 필요']}]})
    store.save_digest(DAY, data, 'original')
    return data


def draft(*args, **kwargs):
    body = '작업의 목적과 확인 주기를 함께 정하고 결과를 검토한다. ' * 16
    return {'title': '자동화의 실행 주기', 'intro': '먼저 일을 나누어 생각한다.',
            'sections': [{'heading': f'관점 {n}', 'body': body} for n in range(4)],
            'conclusion': '작게 시작해 결과를 확인한다.', 'source_ids': ['public'],
            'image_prompt': 'Editorial illustration of a notebook and a clock, no text.',
            'image_alt': '노트와 시계가 함께 놓인 모습', 'review_notes': ['발언의 조건과 실제 서비스명 확인']}


def cover(tmp_path):
    image = tmp_path / 'generated.png'
    Image.new('RGB', (640, 640), '#faf9f6').save(image)
    return image


def test_public_inputs_do_not_include_private_notes_and_drafts_wait_for_images(home):
    seed()
    calls = []
    def writer(prompt, *args, **kwargs):
        calls.append(prompt)
        assert 'PRIVATE_' not in prompt
        assert '공개 발언' in prompt and '정확한 서비스명 확인 필요' in prompt
        return draft()
    built = content.build(DAY, writer=writer)
    assert len(calls) == 1 and built['status'] == 'image_pending' and not built['ready']
    assert content.pending() == [DAY]
    assert Path(built['path']).is_file()
    assert store.get_digest(DAY)['version'] == 1


def test_completed_content_is_reused_and_archive_export_does_not_remove_it(home, tmp_path):
    seed()
    before = content.build(DAY, writer=draft)
    ready = content.attach_image(DAY, before['signature'], cover(tmp_path))
    assert ready['ready'] and content.pending() == []
    def fail(*args, **kwargs):
        pytest.fail('완성한 초안은 다시 AI로 작성하지 않는다')
    cached = content.build(DAY, writer=fail)
    assert cached['ready'] and cached['signature'] == before['signature']
    Path(cached['path']).write_text('사용자가 검토하고 고친 글', encoding='utf-8')
    assert content.build(DAY, writer=fail)['ready']
    original = Path(cached['path']).read_bytes()
    archive.export_day(DAY)
    assert Path(cached['path']).read_bytes() == original
    client = app.test_client()
    assert client.get(cached['url']).status_code == 200
    assert client.get(cached['url'].replace('blog.html', ready['image'])).status_code == 200
    assert client.get(cached['url'].replace('blog.html', 'draft.json')).status_code == 404
    assert client.get(cached['url'].replace('blog.html', 'image-prompt.txt')).status_code == 404
    assert client.get(f'/reports/{DAY}/콘텐츠/{content.INDEX}').status_code == 404
    assert client.get(f'/api/day/{DAY}').json['content']['ready']


def test_new_report_rejects_stale_image_and_keeps_previous_versions(home, tmp_path):
    data = seed()
    before = content.build(DAY, writer=draft)
    content.attach_image(DAY, before['signature'], cover(tmp_path))
    store.save_digest(DAY, data, 'updated')
    assert content.status(DAY)['outdated'] and content.pending() == [DAY]
    with pytest.raises(ValueError, match='현재 작업'):
        content.attach_image(DAY, before['signature'], cover(tmp_path))
    after = content.build(DAY, writer=draft)
    assert after['signature'] != before['signature'] and not after['ready']
    assert Path(before['path']).exists()
    archive.export_day(DAY)
    assert app.test_client().get(before['url']).status_code == 200


def test_missing_image_is_pending_and_missing_html_is_restored_without_ai(home, tmp_path):
    seed()
    before = content.build(DAY, writer=draft)
    ready = content.attach_image(DAY, before['signature'], cover(tmp_path))
    target = Path(ready['path']).parent
    (target/'blog.html').unlink()
    def fail(*args, **kwargs):
        pytest.fail('저장한 초안을 재사용한다')
    assert content.build(DAY, writer=fail)['ready']
    (target/ready['image']).unlink()
    assert not content.status(DAY)['ready']
    recovered = content.build(DAY, writer=fail)
    assert recovered['status'] == 'image_pending' and not recovered['ready']


@pytest.mark.parametrize('problem', ['body', 'source'])
def test_incomplete_or_invented_source_draft_is_not_success(home, problem):
    seed()
    result = draft()
    if problem == 'body':
        result['sections'] = []
    else:
        result['source_ids'] = ['invented']
    with pytest.raises(LLMError):
        content.build(DAY, writer=lambda *a, **kw: result)
    assert content.status(DAY) is None and content.pending() == [DAY]


def test_generated_html_escapes_source_text_and_does_not_publish(home):
    seed()
    result = draft()
    result['title'] = '<img src=x onerror=alert(1)>'
    result['sections'][0]['body'] += '<script>alert(1)</script>'
    built = content.build(DAY, writer=lambda *a, **kw: result)
    doc = Path(built['path']).read_text()
    assert '<script>alert(1)</script>' not in doc and '&lt;script&gt;' in doc
    assert '<img src=x' not in doc and '&lt;img' in doc
    assert store.get_digest(DAY).get('published_at') is None


def test_activation_date_skips_history_but_resumes_existing_jobs(home):
    seed()
    config.update_settings({'content': {'enabled': True, 'start_day': '2026-10-04'}})
    assert content.pending() == []
    content.build(DAY, writer=draft)
    assert content.pending() == [DAY]


def test_corrupt_registry_is_not_served_or_treated_as_completed(home):
    seed()
    built = content.build(DAY, writer=draft)
    path = content.folder(DAY) / content.INDEX
    index = json.loads(path.read_text())
    index['versions'][index['current']]['files'] = ['draft.json']
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        content.status(DAY)
    assert app.test_client().get(built['url']).status_code == 404


def test_source_urls_do_not_pass_private_playlist_or_tracking_parameters(home):
    data = seed()
    data['items'][0]['url'] += '&list=PRIVATE_LIST&tracking=PRIVATE_ID'
    store.save_digest(DAY, data, 'url')
    _, inputs = content.sources(DAY)
    assert inputs[0]['url'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert 'PRIVATE_' not in json.dumps(inputs)


def test_disabled_private_pending_and_path_escape_are_rejected(home):
    seed()
    store.update_item('public', status='hidden')
    assert content.pending() == []
    assert content.build(DAY, writer=lambda *a: pytest.fail('개인 자료로 글을 쓰지 않는다'))['status'] == 'no_public_material'
    with pytest.raises(ValueError):
        content.folder('../../outside')
    config.update_settings({'content': {'enabled': False}})
    assert content.pending() == []
