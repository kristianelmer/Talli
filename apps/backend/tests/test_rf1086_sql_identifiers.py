import collections
import hashlib
import importlib.util
from pathlib import Path
import re
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('identifier_renderer', BASE/'scripts/rf1086_sql_identifiers.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RendererTests(unittest.TestCase):
    def render(self, name):
        return module.identifier(name, deadline=time.monotonic()+4)

    def reject(self, method, *args, **kw):
        with self.assertRaises(module.Unavailable) as caught:
            method(*args, deadline=kw['deadline'] if 'deadline' in kw else time.monotonic()+4)
        self.assertEqual(str(caught.exception), 'identifier_rendering_unavailable')

    def test_independent_examples(self):
        examples = {
            b'graphql':b'graphql', b'graphql_public':b'graphql_public', b'pg_net':b'pg_net',
            b'postgres':b'postgres', b'begin':b'begin', b'copy':b'copy', b'value':b'value',
            b'between':b'"between"', b'values':b'"values"', b'authorization':b'"authorization"',
            b'current_schema':b'"current_schema"', b'select':b'"select"', b'user':b'"user"',
            b'Foo':b'"Foo"', b'a$b':b'"a$b"', b'a.b':b'"a.b"',
            'blå'.encode():'"blå"'.encode(), b'a"b':b'"a""b"', b'1db':b'"1db"',
            b'a\\b':b'"a\\b"', b"a'b":b'"a\'b"', b'_a09':b'_a09', b' SELECT ':b'" SELECT "',
            b'':None,
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                if expected is None:self.reject(module.identifier,raw)
                else:self.assertEqual(self.render(raw),expected)

    def test_complete_pinned_source_classification(self):
        # Independent PG17.6 source fixture; provenance is beside the fixture.
        source=(Path(__file__).parent/'fixtures/pg176_kwlist.h').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),module.SOURCE_KEYWORDS_SHA256)
        rows=[]
        for line in source.splitlines():
            if not line.startswith(b'PG_KEYWORD'):continue
            match=re.fullmatch(rb'PG_KEYWORD\("([a-z_]+)", [A-Z_]+, ([A-Z_]+), [A-Z_]+\)(?:\s*/\*[^\n]*\*/)?',line)
            self.assertIsNotNone(match)
            rows.append(match.groups())
        names=[name for name,_ in rows]
        self.assertEqual(len(rows),491)
        self.assertEqual(names,sorted(set(names)))
        self.assertEqual(max(map(len,names)),17)
        categories=collections.Counter(kind for _,kind in rows)
        self.assertEqual(categories,{b'UNRESERVED_KEYWORD':327,b'COL_NAME_KEYWORD':63,b'TYPE_FUNC_NAME_KEYWORD':23,b'RESERVED_KEYWORD':78})
        force={name for name,kind in rows if kind!=b'UNRESERVED_KEYWORD'}
        self.assertEqual(len(force),164)
        self.assertEqual(module.FORCE_QUOTE,force)
        for name,kind in rows:
            expected=name if kind==b'UNRESERVED_KEYWORD' else b'"'+name+b'"'
            self.assertEqual(self.render(name),expected)

    def test_qualification_component_identity(self):
        for schema,name,expected in [(None,b'a.b',b'"a.b"'),(b'a',b'b',b'a.b'),(b'a.b',b'c',b'"a.b".c'),(b'select',b'Foo',b'"select"."Foo"')]:
            self.assertEqual(module.qualified(schema,name,deadline=time.monotonic()+4),expected)
        self.reject(module.qualified,b'',b'a')
        self.reject(module.qualified,b'a',None)
        self.reject(module.qualified,'a',b'b')

    def test_simple_connect_exact(self):
        for raw,expected in [(b'postgres',b'\\connect postgres\n'),(b'select',b'\\connect "select"\n'),(b'Foo',b'\\connect "Foo"\n'),(b'1db',b'\\connect "1db"\n'),(b'a.b',b'\\connect "a.b"\n'),(b'_',b'\\connect _\n')]:
            self.assertEqual(module.simple_connect(raw,deadline=time.monotonic()+4),expected)
        for raw in (b'',b'a-b',b'a b',b'a$b',b'a"b',b'a\\b',b"a'b",'blå'.encode(),b'a\rb',b'a\nb'):
            self.reject(module.simple_connect,raw)

    def test_input_type_and_encoding_rejection(self):
        class BytesSubclass(bytes):pass
        for raw in (None,True,12,'a',bytearray(b'a'),memoryview(b'a'),BytesSubclass(b'a'),b'a\0b',b'a\rb',b'a\nb',b'\xff',b'\xc0\xaf',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\xe2\x82',b'\x80'):
            self.reject(module.identifier,raw)
        for ch in ('å','☃','😀'):
            raw=ch.encode()
            for cut in range(1,len(raw)):
                self.reject(module.identifier,b'a'*4095+raw[:cut])

    def test_multibyte_crosses_chunks(self):
        for ch in ('å','☃','😀'):
            raw=ch.encode()
            for split in range(1,len(raw)):
                name=b'a'*(4096-split)+raw+b'xyz'
                self.assertEqual(self.render(name),b'"'+name+b'"')

    def test_exact_limits_and_no_truncation(self):
        raw=b'a'*16384
        self.assertEqual(self.render(raw),raw)
        self.assertEqual(self.render(b'"'*16384),b'"'+b'"'*32768+b'"')
        self.assertEqual(len(module.qualified(b'"'*16384,b'"'*16384,deadline=time.monotonic()+4)),65541)
        self.assertEqual(module.simple_connect(b'A'*16384,deadline=time.monotonic()+4),b'\\connect "'+b'A'*16384+b'"\n')
        for fn in (module.identifier,module.simple_connect):self.reject(fn,b'a'*16385)
        self.reject(module.qualified,b'a'*16385,b'a')
        self.reject(module.qualified,b'a',b'a'*16385)
        self.assertEqual(self.render(b'selectx'*20),b'selectx'*20)

    def test_deadline_contract(self):
        for deadline in (None,True,'1',float('nan'),float('inf'),-float('inf'),-1,0,10**1000,time.monotonic()+6):
            self.reject(module.identifier,b'a',deadline=deadline)
        with patch.object(module.time,'monotonic',return_value=0):
            self.assertEqual(module.identifier(b'a',deadline=5),b'a')
            self.reject(module.identifier,b'a',deadline=5.00001)

    def test_expiry_and_cancellation_at_every_checkpoint(self):
        class Cancel(BaseException):pass
        operations=[(module.identifier,(b'a',)),(module.identifier,(b'"'*16384,)),
                    (module.qualified,(b'"'*16384,b'"'*16384)),
                    (module.simple_connect,(b'A'*16384,))]
        for method,args in operations:
            with patch.object(module.time,'monotonic',return_value=0) as clock:
                method(*args,deadline=1)
                count=clock.call_count
            self.assertGreaterEqual(count,5)
            for position in range(count):
                with patch.object(module.time,'monotonic',side_effect=[0]*position+[2]):
                    self.reject(method,*args,deadline=1)
                marker=Cancel()
                with patch.object(module.time,'monotonic',side_effect=[0]*position+[marker]):
                    with self.assertRaises(Cancel) as caught:method(*args,deadline=1)
                    self.assertIs(caught.exception,marker)


if __name__=='__main__': unittest.main(verbosity=2)
