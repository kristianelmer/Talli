"""Pure synthetic bytes. No repository/CI/key/archive/database inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[3] / 'scripts' / 'rf1086_sql_lexical.py'
spec = importlib.util.spec_from_file_location('lexical', PATH)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
META = (b'\\restrict abc123\n', b'\\unrestrict abc123\n', b'\\connect postgres\n', b'\\restrict abc123\n', b'\\unrestrict abc123\n')
COPY = b'COPY public.fixture (id, "strange""column") FROM stdin;\n'


class Tests(unittest.TestCase):
    def scan(self, raw, **kw):
        return m.scan(raw, deadline=time.monotonic()+5, profile=m.PROFILE, **kw)

    def reject(self, raw, **kw):
        with self.assertRaises(m.Unavailable) as caught: self.scan(raw, **kw)
        self.assertIn(caught.exception.reason, m.REASONS)
        self.assertEqual(str(caught.exception), 'sql_lexical_unavailable')

    def verify(self, raw, result):
        receipt = json.loads(result.receipt)
        self.assertEqual(receipt['input'], {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()})
        self.assertFalse(receipt['sqlGrammarAccepted'])
        self.assertFalse(receipt['entryIdentityAccepted'])
        self.assertFalse(receipt['completeLedgerAccepted'])
        self.assertFalse(receipt['runtimeAccepted'])
        self.assertEqual(receipt['profileCondition'], m.PROFILE)
        end = 0; reconstructed = bytearray()
        for kind, start, stop in m.RECORD.iter_unpack(result.leaves):
            self.assertEqual(start, end); self.assertLessEqual(start, stop)
            reconstructed.extend(raw[start:stop]); end = stop
        self.assertEqual(end, len(raw)); self.assertEqual(bytes(reconstructed), raw)
        for name in ('leaves', 'tokens'):
            value = getattr(result, name)
            self.assertEqual(receipt[name]['bytes'], len(value))
            self.assertEqual(receipt[name]['sha256'], hashlib.sha256(value).hexdigest())
        return receipt

    def test_quotes_comments_numeric_and_utf8_offsets(self):
        values = [b"SELECT 'semi; -- TOC entry 9\nBEGIN';\n", b'SELECT "semi;""BEGIN", 1.2e-3, .5, 3.;\n',
            b"SELECT E'quote\\\' semi;\\n';\n", b"SELECT $$;\\connect bad\nBEGIN$$;\n",
            b"SELECT $body$-- TOC entry 7\n$other$; BEGIN$body$;\n", b'SELECT name$tag$, 1::int;\n',
            b'/* outer /* inner */ ; */ SELECT 1; -- trailing\n', b'SELECT 1+/*comment*/2--comment\n;\n',
            'SELECT "blå;", \'北欧;\';\n'.encode(), b"SELECT someE'plain\\';\n"]
        for raw in values:
            with self.subTest(raw=raw): self.assertEqual(self.verify(raw, self.scan(raw))['statements'], 1)

    def test_meta_sequence_and_sql_between_groups(self):
        raw = b'-- prefix\n'+META[0]+b'SELECT 1;\n'+b''.join(META[1:4])+b'SELECT 2;\n'+META[-1]+b'-- end\n'
        result = self.scan(raw, expected_meta=META)
        self.assertEqual(self.verify(raw, result)['metaLines'], 5)

    def test_retained_tokens_preserve_original_byte_offsets_and_all_seven_kinds(self):
        parts = [(None, b' \t-- prefix\n'), (None, b'/* outer /* inner */ */ '),
            (m.IDENT, b'SELECT'), (None, b'\t'), (m.QUOTED_IDENT, '"blå"'.encode()),
            (m.PUNCT, b','), (None, b' /* interior */ '), (m.NUMBER, b'1.2e-3'),
            (m.PUNCT, b','), (None, b' '), (m.STRING, "'北欧; -- TOC entry'".encode()),
            (m.PUNCT, b','), (None, b'-- between\n'), (m.ESCAPE, b"E'x\\n'"),
            (m.PUNCT, b','), (None, b' '), (m.DOLLAR, b'$q$;\\connect hidden\n$q$'),
            (m.PUNCT, b';'), (None, b' -- suffix\n')]
        expected = []; offset = 0
        for kind, value in parts:
            if kind is not None: expected.append((kind, offset, offset+len(value)))
            offset += len(value)
        raw = b''.join(value for _, value in parts)
        result = self.scan(raw)
        self.assertEqual(self.verify(raw, result)['statements'], 1)
        self.assertEqual(list(m.RECORD.iter_unpack(result.tokens)), expected)
        self.assertEqual({kind for kind, _, _ in expected}, set(m.RETAINED_TOKEN_KINDS))

    def test_omitted_trivia_still_obeys_deadline_and_cancellation(self):
        for raw in (b' '*10000+b'SELECT 1;\n', b'--'+b'x'*10000+b'\nSELECT 1;\n',
                    b'/*'+b'x'*10000+b'*/ SELECT 1;\n'):
            for cancellation in (False, True):
                with self.subTest(raw=raw[:2], cancellation=cancellation):
                    active = [False]; ticks = [0]; interrupt = KeyboardInterrupt()
                    original = m.Scanner.progress
                    def progress(instance, *args, **kw):
                        active[0] = True
                        return original(instance, *args, **kw)
                    def clock():
                        if active[0]:
                            ticks[0] += 1
                            if cancellation and ticks[0] == 2: raise interrupt
                        return ticks[0]*0.6
                    with patch.object(m.Scanner, 'progress', progress), patch.object(m.time, 'monotonic', clock):
                        with self.assertRaises(KeyboardInterrupt if cancellation else m.Unavailable) as caught:
                            m.scan(raw, profile=m.PROFILE, deadline=5)
                    self.assertTrue(active[0])
                    if cancellation: self.assertIs(caught.exception, interrupt)
                    else: self.assertEqual(caught.exception.reason, 'deadline')

    def test_copy_payload_remains_opaque_and_empty_payload_is_valid(self):
        for data in (b'', b'\n', b'-- TOC entry 123\nBEGIN; $q$ \\connect bad\n\\\\.\n \\.\n\\.extra\n'):
            raw = COPY+data+b'\\.\n\n\nSELECT 1;\n'
            result = self.scan(raw, copy_commands=(COPY,))
            receipt = self.verify(raw, result)
            self.assertEqual(receipt['statements'], 2); self.assertEqual(receipt['copyGroups'], 1)
            payload = [(a,b) for k,a,b in m.RECORD.iter_unpack(result.leaves) if k == m.COPY_DATA]
            self.assertEqual([raw[a:b] for a,b in payload], [data])

    def test_all_byte_truncations_do_not_hide_unfinished_copy_or_meta(self):
        raw = META[0]+COPY+b'1\tvalue\n\\.\n'+META[-1]
        expected = (META[0], META[-1])
        for end in range(len(raw)):
            with self.subTest(end=end): self.reject(raw[:end], expected_meta=expected, copy_commands=(COPY,))
        self.verify(raw, self.scan(raw, expected_meta=expected, copy_commands=(COPY,)))

    def test_chunk_splits_utf8_dollar_and_copy_terminator(self):
        for size in range(1, 24):
            with patch.object(m, 'CHUNK', size):
                raw = 'SELECT $abc$北欧; $x$ $ab$abc$;\n'.encode()
                self.verify(raw, self.scan(raw))
                raw = COPY+b'123\ttext\n\\.\n'
                self.verify(raw, self.scan(raw, copy_commands=(COPY,)))

    def test_unsupported_literals_and_numeric_prefixes(self):
        values = [b"SELECT E'line\nline';\n", b"SELECT E'x\\\n';\n", b"SELECT E'\\q';\n",
            b"SELECT E'\\x';\n", b"SELECT E'\\u123';\n", b"SELECT E'a'\n'b';\n",
            b"SELECT 'a' -- comment\n'b';\n", b"SELECT 'a' /*comment*/ 'b';\n",
            b"SELECT U&'x';\n", b'SELECT U&"x";\n', b"SELECT B'0';\n", b"SELECT X'aa';\n", b"SELECT N'x';\n",
            b"SELECT 1e'x';\n", b'SELECT 1e+;\n', b'SELECT 1abc;\n', b'SELECT 1_000;\n',
            b'SELECT 0xff;\n', b'SELECT 1..10;\n', b'SELECT $1;\n', b'SELECT $bad;\n',
            'SELECT $å$x$å$;\n'.encode()]
        for raw in values:
            with self.subTest(raw=raw): self.reject(raw)

    def test_closed_escape_forms(self):
        for escaped in (b'\\\\', b"\\'", b'\\"', b'\\b', b'\\f', b'\\n', b'\\r', b'\\t', b'\\1', b'\\123', b'\\xA', b'\\xAF', b'\\u0041', b'\\U00000041'):
            raw = b"SELECT E'"+escaped+b"';\n"
            self.verify(raw, self.scan(raw))

    def test_begin_and_depth_and_incomplete_sql_reject(self):
        for raw in (b'BEGIN;\n', b'CREATE FUNCTION f() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT CASE WHEN true THEN 1 END; END;\n',
            b'SELECT (BEGIN);\n', b'SELECT );\n', b'SELECT (1;\n', b'SELECT 1\n', b'SELECT \'x;\n',
            b'SELECT $$x;\n', b'/* unfinished\n', b'/* closed but buffered */\n', b'SELECT 1;', b'-- no LF'):
            with self.subTest(raw=raw): self.reject(raw)

    def test_meta_and_copy_grammar_cannot_be_bypassed_by_bindings(self):
        invalid = [b'\\restrict a;\n', b'\\restrict a \\echo x\n', b'\\connect -reuse-previous=on postgres\n',
            b'\\connect postgres other\n', b'\\connect "a:b"\n', b'\\encoding UTF8\n', b'\\! evil\n']
        for line in invalid:
            with self.subTest(line=line): self.reject(line, expected_meta=(line,))
        for commands in ((META[-1],), (META[0], META[0], META[-1]), (META[0], b'\\unrestrict wrong\n'),
            (META[0], META[2], META[-1]), (META[0], META[1], META[2], META[-1])):
            self.reject(b''.join(commands), expected_meta=commands)
        for raw in (b' /* closed */\n'+META[0]+META[-1], META[0]+META[1]+b'SELECT 1;\n'+META[2]+META[3]+META[4],
            META[0]+META[-1]+b'SELECT 1;\n', b' '+META[0]+META[-1]):
            self.reject(raw, expected_meta=META if META[2] in raw else (META[0], META[-1]))
        for cmd in (b'COPY fixture (id) FROM stdin;\n', b'COPY public.t  FROM stdin;\n', b'COPY public.t () FROM stdin;\n',
            b'COPY public.t (id) FROM stdin WITH CSV;\n', b'COPY public.t (id) TO stdout;\n', b'COPY public.t (id) FROM PROGRAM \'x\';\n',
            b'COPY public.t (id/*comment*/) FROM stdin;\n', b'COPY public.t (id) FROM stdin; SELECT 1;\n'):
            self.reject(cmd+b'\\.\n', copy_commands=(cmd,))
        self.reject(COPY+b'\\.\n')
        self.reject(COPY+b'\\.\n', copy_commands=(COPY,COPY))
        self.reject(COPY+b'\\.\n', copy_commands=(COPY.replace(b'fixture',b'other'),))

    def test_colons_backslash_and_encoding_are_closed(self):
        for raw in (b'SELECT :value;\n', b'SELECT :\'value\';\n', b'SELECT \\;;\n', b'SELECT \\:\n',
            b'SELECT \v1;\n', b'SELECT \f1;\n', b'SELECT 1;\r\n', b'SELECT \x00;\n', b'SELECT \xff;\n',
            b'\xef\xbb\xbfSELECT 1;\n'):
            self.reject(raw)
        self.verify(b'SELECT 1::int, x:=1;\n', self.scan(b'SELECT 1::int, x:=1;\n'))

    def test_caps_fail_before_partial_result(self):
        cases = [('MAX_INPUT', 5, b'SELECT 1;\n', {}), ('MAX_TOKEN', 8, b"SELECT '0123456789';\n", {}),
            ('MAX_IDENTIFIER', 3, b'SELECT longname;\n', {}), ('MAX_TAG', 2, b'SELECT $long$x$long$;\n', {}),
            ('MAX_DEPTH', 2, b'SELECT (((1)));\n', {}), ('MAX_DEPTH', 2, b'/* /* /* x */ */ */ SELECT 1;\n', {}),
            ('MAX_STATEMENTS', 1, b'SELECT 1;SELECT 2;\n', {}), ('MAX_RECORDS', 2, b'SELECT 1;\n', {}),
            ('MAX_INDEX', 8, b'SELECT 1;\n', {}), ('MAX_RECEIPT', 8, b'SELECT 1;\n', {}),
            ('MAX_META', 1, META[0]+META[-1], {'expected_meta':(META[0],META[-1])}),
            ('MAX_COPY', 0, COPY+b'\\.\n', {'copy_commands':(COPY,)}),
            ('MAX_BINDINGS', 5, COPY+b'\\.\n', {'copy_commands':(COPY,)})]
        for attr, limit, raw, args in cases:
            with self.subTest(attr=attr), patch.object(m, attr, limit): self.reject(raw, **args)
        with patch.object(m, 'MAX_TOKEN', 100):
            raw = COPY+b'x'*101+b'\n\\.\n'
            self.verify(raw, self.scan(raw, copy_commands=(COPY,)))

    def test_quote_comment_truncations_require_the_full_bound_script(self):
        fragments = [b"SELECT 'semi;''quote';\n", b"SELECT E'escaped\\\'quote;';\n",
            b'SELECT "quoted""name;";\n', b'SELECT $tag$;-- fake\n$tag$;\n',
            b'/* outer /* nested */ */ SELECT 1;\n']
        for fragment in fragments:
            raw = META[0]+fragment+META[-1]
            args = {'expected_meta':(META[0],META[-1])}
            self.verify(raw, self.scan(raw, **args))
            for end in range(len(raw)):
                with self.subTest(fragment=fragment, end=end): self.reject(raw[:end], **args)

    def test_exact_token_bound_and_large_copy_payload(self):
        raw = b"SELECT '"+b'x'*(m.MAX_TOKEN-2)+b"';\n"
        self.verify(raw, self.scan(raw))
        self.reject(b"SELECT '"+b'x'*(m.MAX_TOKEN-1)+b"';\n")
        raw = COPY+(b'x'*4095+b'\n')*768+b'\\.\n'
        result = self.scan(raw, copy_commands=(COPY,))
        self.assertEqual(self.verify(raw, result)['copyGroups'], 1)

    def test_shared_deadline_and_cancellation(self):
        clock = [0.0]
        def tick(): clock[0] += 0.01; return clock[0]
        with patch.object(m.time, 'monotonic', tick):
            with self.assertRaises(m.Unavailable) as caught:
                m.scan(b"SELECT '"+b'x'*10000+b"';\n", deadline=0.2, profile=m.PROFILE)
            self.assertEqual(caught.exception.reason, 'deadline')
        cancellation = KeyboardInterrupt()
        with patch.object(m.Scanner, 'check', side_effect=cancellation):
            with self.assertRaises(KeyboardInterrupt) as caught: self.scan(b'SELECT 1;\n')
            self.assertIs(caught.exception, cancellation)

    def test_matching_and_dollar_checks_run_after_validation(self):
        long_copy = b'COPY public.fixture ('+b', '.join(b'column'+str(i).encode() for i in range(6000))+b') FROM stdin;\n'
        scenarios = [('matches', long_copy+b'\\.\n', {'copy_commands':(long_copy,)}),
            ('dollar', b'SELECT $abc$'+b'x'*60000+b'$abc$;\n', {}),
            ('copy_payload', COPY+b'x'*(2*1024**2)+b'\n\\.\n', {'copy_commands': (COPY,)})]
        for method, raw, kw in scenarios:
            for cancellation in (False, True):
                with self.subTest(method=method, cancellation=cancellation):
                    active = [False]; ticks = [0]; interrupt = KeyboardInterrupt()
                    original = getattr(m.Scanner, method)
                    def wrapped(instance, *args):
                        active[0] = True
                        return original(instance, *args)
                    def clock():
                        if active[0]:
                            ticks[0] += 1
                            if cancellation and ticks[0] == 2: raise interrupt
                        return ticks[0]*0.6
                    with patch.object(m.Scanner, method, wrapped), patch.object(m.time, 'monotonic', clock):
                        with self.assertRaises(KeyboardInterrupt if cancellation else m.Unavailable) as caught:
                            m.scan(raw, profile=m.PROFILE, deadline=5, **kw)
                    self.assertTrue(active[0]); self.assertGreaterEqual(ticks[0], 2)
                    if cancellation: self.assertIs(caught.exception, interrupt)
                    else: self.assertEqual(caught.exception.reason, 'deadline')

    def test_long_identifiers_and_dollar_overlap(self):
        raw = b'SELECT '+b'BEGIN'+b'x'*(m.MAX_IDENTIFIER-5)+b';\n'
        self.verify(raw, self.scan(raw))
        for offset in range(-8, 9):
            raw = b'SELECT $abc$'+b'x'*(4096+offset)+b'$a$abc$;\n'
            self.verify(raw, self.scan(raw))

    def test_metadata_types_and_external_profile_not_inferred(self):
        for kw in ({'expected_meta':[]}, {'copy_commands':[]}, {'database':b''}, {'database':b'evil;'}, {'expected_meta':('text',)}):
            self.reject(b'SELECT 1;\n', **kw)
        for profile in (None, True, 'UTF8'):
            with self.assertRaises(m.Unavailable): m.scan(b'SELECT 1;\n', profile=profile, deadline=time.monotonic()+5)
        # Lexical success deliberately does not claim that these settings remain on.
        raw = b'SET standard_conforming_strings = off;\n'
        self.assertFalse(self.verify(raw, self.scan(raw))['runtimeAccepted'])


if __name__ == '__main__': unittest.main()
