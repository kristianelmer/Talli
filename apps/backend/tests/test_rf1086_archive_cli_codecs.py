"""The browser's offline CLI accepts both owned codecs, without transcoding bytes."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import runpy

import pytest

from talli_backend.application import shareholder_register_archive as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_stream_fixture import retained_stream_fixture
from test_rf1086_archive_stream import download as legacy_download
from test_rf1086_archive_originals import source_archive
from test_rf1086_retained_archive_stream import download, query
from test_rf1086_retained_archive_stream_adversarial import legacy_case


def cli(tmp_path, content, archive, *flags):
    path = tmp_path / 'browser-download'
    path.write_bytes(content)
    result = subprocess.run([sys.executable,
        str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'),
        str(path), '--company-id', str(archive.company_id),
        '--income-year', str(int(archive.income_year)), *flags], text=True, capture_output=True)
    assert result.stderr == ''
    assert path.read_bytes() == content
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize('retained', [False, True])
def test_browser_cli_accepts_exact_actual_producer_bytes(tmp_path, retained):
    if retained:
        archive, originals = retained_stream_fixture(status='accepted', bound_feedback=True)
        content, _ = download(archive, originals)
        flags = ('--require-source-history', '--require-override-history',
                 '--require-register-withdrawal-history', '--require-feedback-originals')
        expected = stream.verify_retained_archive_stream
    else:
        archive = source_archive()
        content = legacy_download(archive)
        flags = ('--require-source-originals',)
        expected = stream.verify_archive_stream
    _, sources, feedback = expected(BytesIO(content), query=query(archive))
    code, report = cli(tmp_path, content, archive, '--stream', *flags)
    assert code == 0, report
    assert report['status'] == 'verified_rf_canonical_record'
    assert report['sourceOriginalBytesVerified'] and report['sourceOriginals'] == sources
    assert report['feedbackOriginalBytesVerified'] and report['feedbackOriginals'] == feedback
    assert report['databaseRestorePerformed'] is False


@pytest.mark.parametrize('change', ['unknown-codec', 'cross-codec', 'duplicate-codec',
    'extra-header', 'missing-footer', 'truncated-footer', 'digest', 'trailing', 'original-bytes'])
@pytest.mark.parametrize('retained', [False, True])
def test_cli_dispatch_does_not_bless_corruption_or_wrong_codec(tmp_path, retained, change):
    if retained:
        archive, originals = retained_stream_fixture(status='accepted', bound_feedback=True)
        content, _ = download(archive, originals)
    else:
        archive = source_archive()
        content = legacy_download(archive)
    lines = content.splitlines(keepends=True)
    header = json.loads(lines[0])
    if change in ('unknown-codec', 'cross-codec', 'extra-header'):
        if change == 'unknown-codec': header['codec'] = 'rf1086-production-stream-v99'
        elif change == 'cross-codec':
            header['codec'] = stream.STREAM_CODEC if retained else stream.RETAINED_STREAM_CODEC
        else: header['extra'] = True
        lines[0] = (json.dumps(header) + '\n').encode()
        footer = json.loads(lines[-1])
        footer['sha256'] = sha256(b''.join(lines[:-1])).hexdigest()
        lines[-1] = (json.dumps(footer) + '\n').encode()
        content = b''.join(lines)
    elif change == 'duplicate-codec':
        content = content.replace(b'{"codec":', b'{"codec":"duplicate","codec":', 1)
    elif change == 'missing-footer': content = b''.join(lines[:-1])
    elif change == 'truncated-footer': content = content[:-1]
    elif change == 'trailing': content += b'\n'
    else:
        row = json.loads(lines[-1] if change == 'digest' else lines[1])
        if change == 'digest': row['sha256'] = '0' * 64
        else: row['original']['canonicalOriginal'] = '{}'
        lines[-1 if change == 'digest' else 1] = (json.dumps(row) + '\n').encode()
        if change == 'original-bytes':
            footer = json.loads(lines[-1])
            footer['sha256'] = sha256(b''.join(lines[:-1])).hexdigest()
            lines[-1] = (json.dumps(footer) + '\n').encode()
        content = b''.join(lines)
    code, report = cli(tmp_path, content, archive, '--stream')
    assert code == 1
    assert report == {'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}


@pytest.mark.parametrize('bound', [False, True])
def test_strict_feedback_flag_keeps_unknown_legacy_coverage_rejected(tmp_path, bound):
    archive, originals = retained_stream_fixture(status='accepted', bound_feedback=bound)
    content, _ = download(archive, originals)
    code, report = cli(tmp_path, content, archive, '--stream', '--require-feedback-originals')
    assert code == (0 if bound else 1)
    if bound: assert report['feedbackOriginalsComplete'] is True


@pytest.mark.parametrize('wrapper', [False, True])
def test_retained_canonical_record_uses_owned_v6_parser(tmp_path, wrapper):
    archive, _ = retained_stream_fixture(status='accepted')
    canonical = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    content = json.dumps({'rf1086Production': {'canonicalArchive': canonical}}).encode() if wrapper else canonical.encode()
    code, report = cli(tmp_path, content, archive, '--require-source-history',
        '--require-override-history', '--require-register-withdrawal-history')
    assert code == 0, report
    assert report['sourceOriginalBytesVerified'] is False
    assert report['feedbackOriginalBytesVerified'] is False
    assert report['databaseRestorePerformed'] is False
    assert cli(tmp_path, content, archive, '--require-source-originals')[0] == 1


@pytest.mark.parametrize('codec', [1, 2, 3, 4, 5])
@pytest.mark.parametrize('format', ['stream', 'canonical', 'wrapper'])
def test_all_legacy_inner_codecs_remain_readable(tmp_path, codec, format):
    archive, factory, actor = legacy_case(codec)
    content = legacy_download(archive, factory, actor)
    canonical = json.loads(content.splitlines()[0])['canonicalArchive']
    assert json.loads(canonical)['codec'] == f'rf1086-production-archive-v{codec}'
    if format == 'canonical': content = canonical.encode()
    if format == 'wrapper': content = json.dumps({'rf1086Production': {'canonicalArchive': canonical}}).encode()
    code, report = cli(tmp_path, content, archive, *('--stream',) if format == 'stream' else ())
    assert code == 0, report
    assert report['sourceHistoryIncluded'] is (codec >= 2)
    assert report['overrideHistoryIncluded'] is (codec >= 4)
    assert report['registerWithdrawalHistoryIncluded'] is (codec >= 5)
    if codec == 1: assert cli(tmp_path, content, archive, *('--stream',) if format == 'stream' else (), '--require-source-history')[0] == 1
    if codec < 4: assert cli(tmp_path, content, archive, *('--stream',) if format == 'stream' else (), '--require-override-history')[0] == 1
    if codec < 5: assert cli(tmp_path, content, archive, *('--stream',) if format == 'stream' else (), '--require-register-withdrawal-history')[0] == 1


@pytest.mark.parametrize('retained', [False, True])
def test_codec_probe_is_bounded_and_exact_header_limit_passes(monkeypatch, retained):
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'))
    verify = namespace['verify_download_stream']
    if retained:
        archive, originals = retained_stream_fixture()
        content, _ = download(archive, originals)
    else:
        archive = source_archive()
        content = legacy_download(archive)
    length = len(content.splitlines(keepends=True)[0])
    class Bounded(BytesIO):
        def readline(self, size=-1):
            assert 0 < size <= stream.MAX_STREAM_HEADER_BYTES + 1
            return super().readline(size)
        def read(self, size=-1):
            assert size == 1
            return super().read(size)
    monkeypatch.setitem(verify.__globals__, 'MAX_STREAM_HEADER_BYTES', length)
    assert verify(Bounded(content), query=query(archive), require_source_history=False,
                  require_feedback_originals=False)[0] == archive
    monkeypatch.setitem(verify.__globals__, 'MAX_STREAM_HEADER_BYTES', length - 1)
    with pytest.raises(ValueError):
        verify(Bounded(content), query=query(archive), require_source_history=False,
               require_feedback_originals=False)
