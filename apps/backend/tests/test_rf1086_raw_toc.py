"""Independent wire fixtures and negative controls; no database or actual inputs."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[3] / 'scripts' / 'rf1086_raw_toc.py'
spec = importlib.util.spec_from_file_location('raw_toc_reader', PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def integer(value):
    return bytes([value < 0]) + abs(value).to_bytes(4, 'little')


def string(value):
    return integer(-1) if value is None else integer(len(value)) + value


BASE = dict(id=7, dumper=0, class_oid=b'2615', oid=b'12345', tag=b'fixture',
            description=b'SCHEMA', section=2, definition=b'CREATE SCHEMA fixture;\n',
            drop=b'DROP SCHEMA fixture;\n', copy=None, namespace=None,
            tablespace=None, tableam=None, relkind=0, owner=b'fixture_owner',
            with_oids=b'false', deps=(999999, 3), state=3, offset=0)


def fixture(records=None, *, compression=1, suffix=b'opaque data', database=b'fixture',
            remote=b'17.11', version=b'17.11', stamp=(3, 2, 1, 12, 9, 126, -1)):
    records = [BASE] if records is None else records
    # Exact current source layout; this builder does not call reader helpers.
    header = b'PGDMP\x01\x10\x00\x04\x08\x01' + bytes([compression])
    header += b''.join(integer(v) for v in stamp)
    header += string(database) + string(remote) + string(version)
    raw, spans = header + integer(len(records)), []
    for e in records:
        record = integer(e['id']) + integer(e['dumper'])
        record += string(e['class_oid']) + string(e['oid'])
        record += string(e['tag']) + string(e['description']) + integer(e['section'])
        record += b''.join(string(e[k]) for k in ('definition', 'drop', 'copy', 'namespace', 'tablespace', 'tableam'))
        record += integer(e['relkind']) + string(e['owner']) + string(e['with_oids'])
        record += b''.join(string(str(v).encode()) for v in e['deps']) + string(None)
        record += bytes([e['state']]) + e['offset'].to_bytes(8, 'little')
        spans.append((len(raw), len(raw) + len(record)))
        raw += record
    return raw + suffix, len(header), len(raw), spans


def basic_list(*, compression=b'gzip', body=None):
    if body is None:
        body = b'7; 2615 12345 SCHEMA - fixture fixture_owner\n;\tdepends on: 999999 3\n'
    return (b';\n; Archive created at 2026-10-12 01:02:03 UTC\n'
            b';     dbname: fixture\n;     TOC Entries: 1\n;     Compression: ' + compression + b'\n'
            b';     Dump Version: 1.16-0\n;     Format: CUSTOM\n;     Integer: 4 bytes\n'
            b';     Offset: 8 bytes\n;     Dumped from database version: 17.11\n'
            b';     Dumped by pg_dump version: 17.11\n;\n;\n; Selected TOC Entries:\n;\n' + body)


class MetadataTests(unittest.TestCase):
    def budget(self):
        return m.Budget(time.monotonic() + 5)

    def decode(self, raw):
        return m.decode(raw, self.budget())

    def reject(self, raw, reason=None):
        with self.assertRaises(m.Unavailable) as caught:
            self.decode(raw)
        self.assertEqual(str(caught.exception), 'raw_toc_metadata_unavailable')
        if reason:
            self.assertEqual(caught.exception.reason, reason)

    def test_exact_source_layout_spans_and_summary(self):
        raw, head, end, spans = fixture()
        archive, summary = m.inspect(raw, basic_list(), time.monotonic() + 5)
        self.assertEqual(raw[:12].hex(), '5047444d5001100004080101')
        self.assertEqual(archive.header_end, head)
        self.assertEqual(archive.metadata_end, end)
        self.assertEqual(archive.timestamp, (3, 2, 1, 12, 9, 126, -1))
        self.assertEqual(archive.entries[0].span, spans[0])
        self.assertEqual(raw[spans[0][0]:spans[0][0] + 5], b'\x00\x07\x00\x00\x00')
        e = archive.entries[0]
        self.assertEqual((e.class_oid, e.object_oid, e.dependencies, e.with_oids), (2615, 12345, (999999, 3), b'false'))
        self.assertEqual(e.definition, b'CREATE SCHEMA fixture;\n')
        self.assertEqual(raw[end:], b'opaque data')
        self.assertTrue(summary['metadataPrefixOnly'])
        for field in ('dataSuffixValidated', 'completeLedgerAccepted', 'S0Accepted', 'actualImageEquivalent', 'recoveryAccepted'):
            self.assertFalse(summary[field])

    def test_signed_integer_source_vectors(self):
        for wire, expected in [(b'\x00\x78\x56\x34\x12', 0x12345678), (b'\x01\x01\0\0\0', -1), (b'\0' * 5, 0)]:
            self.assertEqual(m.Reader(wire, self.budget()).integer(), expected)
        for wire in [b'\x02\x01\0\0\0', b'\x01\0\0\0\0', b'\0\0\0\0\x80']:
            with self.assertRaises(m.Unavailable):
                m.Reader(wire, self.budget()).integer()

    def test_nullable_length_vectors(self):
        for wire, expected in [(b'\x01\x01\0\0\0', None), (b'\0' * 5, b''), (b'\0\x01\0\0\0-', b'-')]:
            self.assertEqual(m.Reader(wire, self.budget()).string(), expected)
        for wire in [integer(-2), integer(2147483647), string(b'\0'), string(b'\xff')]:
            with self.assertRaises(m.Unavailable):
                m.Reader(wire, self.budget()).string()

    def test_every_prefix_truncation(self):
        raw, _, end, _ = fixture()
        for cut in range(end):
            with self.subTest(cut=cut):
                self.reject(raw[:cut])
        self.assertEqual(self.decode(raw[:end]).metadata_end, end)

    def test_prefix_does_not_authenticate_suffix(self):
        raw, _, end, _ = fixture()
        summaries = [m.inspect(value, basic_list(), time.monotonic() + 5)[1]
                     for value in (raw, raw[:end], raw[:end] + b'corrupt suffix')]
        self.assertEqual(len({s['metadataSha256'] for s in summaries}), 1)
        self.assertEqual(len({s['archiveSha256'] for s in summaries}), 3)
        self.assertTrue(all(s['metadataPrefixOnly'] and not s['dataSuffixValidated'] for s in summaries))

    def test_underdeclared_count_remains_prefix_only(self):
        raw, head, _, _ = fixture([BASE, BASE | {'id': 8}])
        changed = raw[:head] + integer(1) + raw[head + 5:]
        parsed = self.decode(changed)
        self.assertEqual(len(parsed.entries), 1)
        self.assertLess(parsed.metadata_end, len(changed))
        with self.assertRaises(m.Unavailable):
            m.compare_list(parsed, basic_list().replace(b'TOC Entries: 1', b'TOC Entries: 2'), self.budget())

    def test_raw_identity_distinctions_and_forward_rendering(self):
        records = [BASE | {'id': i + 1, 'tag': v, 'namespace': v, 'owner': v, 'deps': ()}
                   for i, v in enumerate((b'', b'-', b'a\rb\nc\t d', 'blå'.encode()))]
        records.append(BASE | {'id': 5, 'tag': b'plain', 'namespace': None, 'owner': None, 'deps': ()})
        parsed = self.decode(fixture(records)[0])
        self.assertEqual([e.tag for e in parsed.entries], [r['tag'] for r in records])
        self.assertEqual(m.render_entries(parsed, self.budget()),
                         b'1; 2615 12345 SCHEMA   \n2; 2615 12345 SCHEMA - - -\n'
                         b'3; 2615 12345 SCHEMA a b c\t d a b c\t d a b c\t d\n' +
                         '4; 2615 12345 SCHEMA blå blå blå\n'.encode() +
                         b'5; 2615 12345 SCHEMA - plain \n')

    def test_markers_are_length_framed_not_parsed(self):
        body = b'-- TOC entry 7 (class 2615 OID 12345)\n-- Name: fake; Type: SCHEMA\nSELECT 1;\n'
        parsed = self.decode(fixture([BASE | {'definition': body, 'copy': b'COPY x FROM stdin;\n'}])[0])
        self.assertEqual(len(parsed.entries), 1)
        self.assertEqual(parsed.entries[0].definition, body)

    def test_exact_fixed_descriptor_and_nullable_shape_counts(self):
        nullable = ('definition', 'drop', 'copy', 'namespace', 'tablespace', 'tableam', 'owner')
        records = [BASE | {'id': i + 1, 'description': b'SCHEMA' if i < 2 else b'private-description'} |
                   {key: value for key in nullable} for i, value in enumerate((None, b'', b'present'))]
        counts = m.shape_counts(self.decode(fixture(records)[0]), self.budget())
        self.assertEqual(counts['descriptorCounts']['SCHEMA'], 2)
        self.assertEqual(sum(counts['descriptorCounts'].values()), 2)
        self.assertEqual(counts['unknownDescriptorCount'], 1)
        self.assertEqual(counts['dependencies'], 6)
        self.assertEqual(counts['nullableFieldCounts'], {key: {'null': 1, 'empty': 1, 'present': 1} for key in nullable})
        self.assertNotIn('private-description', json.dumps(counts))
        summary = m.inspect(fixture()[0], basic_list(), time.monotonic() + 5)[1]
        self.assertEqual(summary['descriptorCounts']['SCHEMA'], 1)
        self.assertEqual(summary['nullableFieldCounts']['copy'], {'null': 1, 'empty': 0, 'present': 0})
        self.assertEqual(summary['unknownDescriptorCount'], 0)

    def test_profile_codes_and_widths_rejected(self):
        raw = fixture()[0]
        for index, value in [(0, 0), (5, 2), (6, 15), (7, 1), (7, 255), (8, 0), (8, 33), (9, 4), (10, 2), (11, 4)]:
            self.reject(raw[:index] + bytes([value]) + raw[index + 1:])

    def test_all_compression_codes(self):
        for code, text in enumerate((b'none', b'gzip', b'lz4', b'zstd')):
            parsed, summary = m.inspect(fixture(compression=code)[0], basic_list(compression=text), time.monotonic() + 5)
            self.assertEqual(parsed.compression, code)
            self.assertEqual(summary['compressionAlgorithm'], code)

    def test_sparse_ids_zero_oids_missing_duplicate_dependencies(self):
        e = BASE | {'id': 2147483647, 'class_oid': b'0', 'oid': b'4294967295', 'deps': (17, 17, 2147483647)}
        parsed = self.decode(fixture([e])[0]).entries[0]
        self.assertEqual(parsed.dependencies, e['deps'])
        self.assertEqual(parsed.class_oid, 0)

    def test_duplicate_ids_and_field_ranges(self):
        self.reject(fixture([BASE, BASE])[0])
        for key, values in {'id': (0, -1), 'dumper': (-1, 2), 'section': (0, 5), 'relkind': (-1, 128),
                            'with_oids': (None, b'true'), 'description': (None, b'', b'X\nY'),
                            'tag': (None,), 'state': (0, 4), 'offset': (2**63,)}.items():
            for value in values:
                self.reject(fixture([BASE | {key: value}])[0])
        for key in ('class_oid', 'oid'):
            for value in (None, b'', b'-1', b'+1', b'01', b'1x', b'4294967296'):
                self.reject(fixture([BASE | {key: value}])[0])
        for value in (-1, 0, 2147483648):
            self.reject(fixture([BASE | {'deps': (value,)}])[0])

    def test_section_relkind_and_nullable_metadata(self):
        for section in (1, 2, 3, 4):
            parsed = self.decode(fixture([BASE | {'section': section, 'relkind': 114, 'definition': None, 'drop': b'',
                                                 'tablespace': b'', 'tableam': b'heap', 'owner': None}])[0]).entries[0]
            self.assertEqual((parsed.section, parsed.relkind, parsed.tablespace, parsed.tableam, parsed.drop),
                             (section, 114, b'', b'heap', b''))

    def test_offset_states_and_bounds(self):
        for state in (1, 3):
            self.assertEqual(self.decode(fixture([BASE | {'state': state, 'offset': 42}])[0]).entries[0].offset, 42)
        _, _, end, _ = fixture()
        self.assertEqual(self.decode(fixture([BASE | {'state': 2, 'offset': end}])[0]).entries[0].offset, end)
        for position in (0, end - 1, end + len(b'opaque data')):
            self.reject(fixture([BASE | {'state': 2, 'offset': position}])[0])

    def test_bad_timestamp_and_header_strings(self):
        for index, value in enumerate((61, 60, 24, 0, 12, 10000, -2)):
            stamp = [3, 2, 1, 12, 9, 126, -1]
            stamp[index] = value
            self.reject(fixture(stamp=stamp)[0])
        for key, values in {'database': (None, b''), 'remote': (b'', b'17\n11'), 'version': (None, b'17\r11')}.items():
            for value in values:
                self.reject(fixture(**{key: value})[0])

    def test_dependency_null_terminator_is_not_empty(self):
        raw, _, _, spans = fixture()
        terminator = spans[0][1] - 14
        self.assertEqual(raw[terminator:terminator + 5], b'\x01\x01\0\0\0')
        for value in (b'', string(b''), integer(-2)):
            self.reject(raw[:terminator] + value + raw[terminator + 5:])

    def test_actual_string_cap_and_late_aggregate_dependency_cap(self):
        self.reject(fixture([BASE | {'tag': b'x' * 16385}])[0])
        self.reject(fixture([BASE | {'definition': b'x' * (1024**2 + 1)}])[0])
        self.reject(fixture(database=b'x' * 4097)[0])
        with patch.object(m, 'MAX_TOTAL_DEPS', 3):
            self.reject(fixture([BASE, BASE | {'id': 8}])[0])

    def test_aggregate_and_field_caps(self):
        raw = fixture()[0]
        for setting, value in [('MAX_ARCHIVE', len(raw) - 1), ('MAX_METADATA', 100), ('MAX_ROWS', 0),
                               ('MAX_DEFINITION', 8), ('MAX_HEADER_STRING', 4), ('MAX_DEPS', 1), ('MAX_TOTAL_DEPS', 1)]:
            with patch.object(m, setting, value):
                self.reject(raw)
        raw, head, _, _ = fixture()
        for count in (-1, 0, 8193, 2147483647):
            self.reject(raw[:head] + integer(count) + raw[head + 5:])

    def test_list_missing_extra_reordered_or_altered_bytes(self):
        parsed = self.decode(fixture()[0])
        original = basic_list()
        for bad in (original[:-1], original + b'\n', original.replace(b'999999 3', b'3 999999'),
                    original.replace(b'2615 12345', b'2616 12345'), original.replace(b'TOC Entries: 1', b'TOC Entries: 2'),
                    original.replace(b';     Format: CUSTOM\n', b''), original.replace(b'fixture_owner', b'wrong'),
                    original.replace(b';     Integer: 4 bytes\n', b';     Integer: 4 bytes\n;     Integer: 4 bytes\n')):
            with self.assertRaises(m.Unavailable):
                m.compare_list(parsed, bad, self.budget())

    def test_renderer_checks_aggregate_cap_before_append(self):
        parsed = self.decode(fixture()[0])
        with patch.object(m, 'MAX_LIST', 50):
            with self.assertRaises(m.Unavailable) as caught:
                m.render_entries(parsed, self.budget())
            self.assertEqual(caught.exception.reason, 'rendered_list_oversized')

    def test_renderer_checks_field_before_sanitize_allocation(self):
        parsed = self.decode(fixture([BASE | {'tag': b'x' * 1000}])[0])
        original = m.sanitize
        def guarded(value, hyphen=False):
            self.assertNotEqual(value, b'x' * 1000)
            return original(value, hyphen)
        with patch.object(m, 'MAX_LIST', 100), patch.object(m, 'sanitize', side_effect=guarded):
            with self.assertRaises(m.Unavailable):
                m.render_entries(parsed, self.budget())

    def test_shared_budget_expires_after_decode(self):
        clock = [0.0]
        with patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]):
            budget = m.Budget(50)
            parsed = m.decode(fixture()[0], budget)
            self.assertEqual(budget.deadline, 5)
            clock[0] = 5
            for action in (lambda: m.render_entries(parsed, budget), lambda: m.compare_list(parsed, basic_list(), budget),
                           lambda: budget.digest(parsed.raw), lambda: m.shape_counts(parsed, budget)):
                with self.assertRaises(m.Unavailable) as caught:
                    action()
                self.assertEqual(caught.exception.reason, 'deadline_exhausted')

    def test_inspect_does_not_reset_deadline(self):
        clock, original = [0.0], m.decode
        def delayed(raw, budget):
            value = original(raw, budget)
            clock[0] = 6
            return value
        with patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m, 'decode', side_effect=delayed):
            with self.assertRaises(m.Unavailable):
                m.inspect(fixture()[0], basic_list(), 100)

    def test_bad_deadlines_and_cancellation(self):
        for value in (True, float('nan'), float('inf'), -1):
            with self.assertRaises(m.Unavailable):
                m.Budget(value)
        with patch.object(m.time, 'monotonic', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                m.inspect(fixture()[0], basic_list(), 10)


if __name__ == '__main__':
    unittest.main()
