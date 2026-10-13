"""Conditional lexical spans only. No SQL validity, entry or runtime acceptance."""
import codecs
from dataclasses import dataclass
import hashlib
import json
import math
import re
import struct
import time

PROFILE = 'UTF8-standard-strings-on-throughout'
RULE_VERSION = 'sql-lexical-scanner-v3'
MAX_INPUT = 128 * 1024**2
MAX_TOKEN = 1024**2
MAX_IDENTIFIER = 16 * 1024
MAX_TAG = 128
MAX_DEPTH = 128
MAX_STATEMENTS = 16384
MAX_RECORDS = 262144
MAX_META = 32
MAX_COPY = 8192
MAX_BINDINGS = 2 * 1024**2
MAX_INDEX = 8 * 1024**2
MAX_RECEIPT = 16 * 1024
CHUNK = 4096
RECORD = struct.Struct('<BII')
# Leaf and token kind namespaces are separate and fixed.
TRIVIA, SQL, META, COPY_DATA, COPY_END = range(1, 6)
SPACE, IDENT, NUMBER, STRING, ESCAPE, QUOTED_IDENT, DOLLAR, LINE_COMMENT, BLOCK_COMMENT, PUNCT = range(1, 11)
TRIVIA_TOKEN_KINDS = (SPACE, LINE_COMMENT, BLOCK_COMMENT)
RETAINED_TOKEN_KINDS = (IDENT, NUMBER, STRING, ESCAPE, QUOTED_IDENT, DOLLAR, PUNCT)
DIGITS = b'0123456789'
HEX = b'0123456789abcdefABCDEF'
ASCII_START = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'
ASCII_CONT = ASCII_START + DIGITS
REASONS = frozenset(('input', 'profile', 'deadline', 'encoding', 'limit', 'binding',
    'meta', 'copy', 'literal', 'token', 'begin', 'depth', 'unfinished', 'coverage'))


class Unavailable(ValueError):
    def __init__(self, reason, limit=None):
        self.reason = reason if reason in REASONS else 'input'
        if limit is not None:
            require(self.reason == 'limit', 'binding')
            validate_limit(limit)
        self.limit = limit
        super().__init__('sql_lexical_unavailable')


def require(test, reason):
    if not test:
        raise Unavailable(reason)


def limit_rules():
    """Closed guard expressions, not estimates of unscanned object sizes."""
    return {
        'binding_bytes': (MAX_BINDINGS, MAX_BINDINGS + MAX_TOKEN, 'bytes', 'none', None),
        'token_records': (MAX_RECORDS, MAX_RECORDS + 1, 'records', 'required', None),
        'leaf_records': (MAX_RECORDS, MAX_RECORDS + 1, 'records', 'required', None),
        'index_bytes': (MAX_INDEX, MAX_INDEX + RECORD.size, 'bytes', 'required', None),
        # An escape advances at most10bytes; a final E-string span adds at most2.
        'token_bytes': (MAX_TOKEN, min(MAX_INPUT, MAX_TOKEN + 10), 'bytes', 'required', None),
        # Quoted script identifiers first use the generic token progress guard.
        # Binding identifiers use the tighter guard throughout; a doubled quote
        # can overshoot that guard by2. The fifth field bounds null offsets.
        'identifier_bytes': (MAX_IDENTIFIER, min(MAX_INPUT, max(MAX_TOKEN + 1, MAX_IDENTIFIER + 2)),
                             'bytes', 'optional', min(MAX_TOKEN, MAX_IDENTIFIER + 2)),
        'dollar_tag_prefix_bytes': (MAX_TAG + 1, MAX_TAG + 2, 'bytes', 'required', None),
        'dollar_body_bytes': (MAX_TOKEN, min(MAX_INPUT, MAX_TOKEN + max(MAX_TAG + 2, min(CHUNK, 4096))),
                              'bytes', 'required', None),
        'copy_groups': (MAX_COPY, MAX_COPY + 1, 'groups', 'required', None),
        'statements': (MAX_STATEMENTS, MAX_STATEMENTS + 1, 'statements', 'required', None),
        # Receipt chunks contain fixed keys, bounded integers and64-byte hashes.
        'receipt_bytes': (MAX_RECEIPT, MAX_RECEIPT + 1024, 'bytes', 'none', None),
    }


def validate_limit(value, *, input_bytes=None):
    require(type(value) is dict and set(value) == {'site', 'ceiling', 'observed', 'unit', 'offset'}, 'binding')
    rules = limit_rules()
    require(type(value['site']) is str and value['site'] in rules, 'binding')
    ceiling, maximum, unit, position, binding_maximum = rules[value['site']]
    require(type(value['ceiling']) is int and value['ceiling'] == ceiling
            and type(value['observed']) is int and ceiling < value['observed'] <= maximum
            and type(value['unit']) is str and value['unit'] == unit, 'binding')
    offset = value['offset']
    require(position != 'required' or offset is not None, 'binding')
    require(position != 'none' or offset is None, 'binding')
    if offset is None and binding_maximum is not None:
        require(value['observed'] <= binding_maximum, 'binding')
    if offset is not None:
        bound = MAX_INPUT if input_bytes is None else input_bytes
        require(type(bound) is int and 0 <= bound <= MAX_INPUT
                and type(offset) is int and 0 <= offset <= bound, 'binding')
        if value['site'] in ('token_bytes', 'identifier_bytes', 'dollar_tag_prefix_bytes',
                              'dollar_body_bytes'):
            require(value['observed'] <= offset, 'binding')
    return value


def limit_guard(observed, ceiling, site, offset=None):
    if observed > ceiling:
        unit = limit_rules()[site][2]
        raise Unavailable('limit', {'site': site, 'ceiling': ceiling,
                                   'observed': observed, 'unit': unit, 'offset': offset})


def ident_start(c):
    return c in ASCII_START or c >= 128


def ident_cont(c):
    return ident_start(c) or c in DIGITS or c == 36


@dataclass(frozen=True)
class Scan:
    leaves: bytes
    tokens: bytes
    receipt: bytes


class Scanner:
    def __init__(self, raw, expected_meta, database, copy_commands, deadline, profile):
        require(type(deadline) in (int, float) and math.isfinite(deadline)
                and 0 < deadline-time.monotonic() <= 5, 'deadline')
        self.deadline = deadline
        self.work = 0
        require(type(raw) is bytes and len(raw) <= MAX_INPUT, 'input')
        require(type(profile) is str and profile == PROFILE, 'profile')
        self.raw = raw
        self.n = len(raw)
        self.leaves = bytearray()
        self.tokens = bytearray()
        self.counts = [0] * 6
        self.statements = self.copies = self.meta_at = self.copy_at = 0
        self.expected_meta = expected_meta
        self.copy_commands = copy_commands
        self.database = database
        self.check()
        self.input_hash = self.validate_bytes(raw)
        require(not raw.startswith(b'\xef\xbb\xbf') and (not raw or raw.endswith(b'\n')), 'encoding')
        require(type(expected_meta) is tuple and type(copy_commands) is tuple
                and len(expected_meta) <= MAX_META and len(copy_commands) <= MAX_COPY, 'binding')
        require(type(database) is bytes and 0 < len(database) <= 128
                and re.fullmatch(rb'[A-Za-z0-9_.]+', database), 'binding')
        total = 0
        for value in (*expected_meta, *copy_commands):
            self.check()
            require(type(value) is bytes and len(value) <= MAX_TOKEN, 'binding')
            total += len(value)
            limit_guard(total, MAX_BINDINGS, 'binding_bytes')
            self.validate_bytes(value)
        self.meta_modes = self.validate_meta()
        for value in copy_commands:
            self.validate_copy(value)
        self.sql_allowed = not expected_meta

    def check(self):
        if time.monotonic() >= self.deadline:
            raise Unavailable('deadline')

    def validate_bytes(self, raw):
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        hashed = hashlib.sha256()
        try:
            for start in range(0, len(raw), CHUNK):
                self.check()
                chunk = memoryview(raw)[start:start+CHUNK]
                require(raw.find(b'\0', start, start+CHUNK) < 0
                        and raw.find(b'\r', start, start+CHUNK) < 0, 'encoding')
                decoder.decode(chunk, final=False)
                hashed.update(chunk)
                self.check()
            decoder.decode(b'', final=True)
        except UnicodeDecodeError:
            raise Unavailable('encoding') from None
        self.check()
        return hashed.hexdigest()

    def hash_index(self, value):
        h = hashlib.sha256()
        for i in range(0, len(value), CHUNK):
            self.check(); h.update(memoryview(value)[i:i+CHUNK])
        self.check()
        return h.hexdigest()

    def add(self, target, kind, start, end):
        self.check()
        require(0 <= start <= end <= self.n and (start < end or kind == COPY_DATA and target is self.leaves), 'coverage')
        limit_guard(len(target)//RECORD.size + 1, MAX_RECORDS,
                    'leaf_records' if target is self.leaves else 'token_records', end)
        limit_guard(len(self.tokens)+len(self.leaves)+RECORD.size, MAX_INDEX, 'index_bytes', end)
        target.extend(RECORD.pack(kind, start, end))
        if target is self.leaves:
            self.counts[kind] += 1

    def token(self, kind, start, end, *, identifier=False):
        limit_guard(end-start, MAX_IDENTIFIER if identifier else MAX_TOKEN,
                    'identifier_bytes' if identifier else 'token_bytes', end)
        if kind in TRIVIA_TOKEN_KINDS:
            # Trivia still drives the scanner state and complete byte leaves.
            # Statement grammar skips it, so retain no redundant token record.
            self.check()
            require(0 <= start < end <= self.n, 'coverage')
            return
        self.add(self.tokens, kind, start, end)

    def progress(self, start, end, *, limit=MAX_TOKEN, site='token_bytes', script=True):
        limit_guard(end-start, limit, site, end if script else None)
        self.work += 1
        if self.work >= 256:  # Each loop advances at most an11-byte escape.
            self.work = 0
            self.check()

    def validate_meta(self):
        if not self.expected_meta:
            return ()
        modes = []
        state = 'initial'
        key = None
        for index, line in enumerate(self.expected_meta):
            self.check()
            require(len(line) <= 512, 'meta')
            match = re.fullmatch(rb'\\(restrict|unrestrict) ([A-Za-z0-9]{1,128})\n', line)
            if match:
                action, observed = match.groups()
                if key is None: key = observed
                require(observed == key, 'meta')
                if action == b'restrict':
                    require(state in ('initial', 'connect'), 'meta')
                    state = 'restricted'; modes.append(True)
                else:
                    require(state == 'restricted', 'meta')
                    state = 'closed' if index == len(self.expected_meta)-1 else 'unrestricted'
                    modes.append(False)
            else:
                match = re.fullmatch(rb'\\connect ([a-z_][a-z0-9_]*|"[A-Za-z0-9_.]+")\n', line)
                require(match is not None and state == 'unrestricted', 'meta')
                name = match[1]
                decoded = name[1:-1] if name.startswith(b'"') else name
                require(len(decoded) <= 128 and decoded == self.database, 'meta')
                state = 'connect'; modes.append(False)
        require(state == 'closed', 'meta')
        return tuple(modes)

    def copy_identifier(self, raw, at):
        start = at
        require(at < len(raw), 'copy')
        if raw[at] == 34:
            at += 1; content = at
            while at < len(raw):
                self.progress(start, at, limit=MAX_IDENTIFIER, site='identifier_bytes', script=False)
                require(raw[at] not in (0, 10, 13), 'copy')
                if raw[at] == 34:
                    if at+1 < len(raw) and raw[at+1] == 34: at += 2; continue
                    require(at > content, 'copy')
                    limit_guard(at+1-start, MAX_IDENTIFIER, 'identifier_bytes')
                    return at+1
                at += 1
            raise Unavailable('copy')
        require(ident_start(raw[at]), 'copy')
        at += 1
        while at < len(raw) and ident_cont(raw[at]):
            self.progress(start, at, limit=MAX_IDENTIFIER, site='identifier_bytes', script=False); at += 1
        limit_guard(at-start, MAX_IDENTIFIER, 'identifier_bytes')
        return at

    def validate_copy(self, raw):
        self.check()
        require(raw.startswith(b'COPY ') and raw.endswith(b' FROM stdin;\n'), 'copy')
        at = self.copy_identifier(raw, 5)
        require(raw[at:at+1] == b'.', 'copy')
        at = self.copy_identifier(raw, at+1)
        require(raw[at:at+2] == b' (', 'copy')
        at = self.copy_identifier(raw, at+2)
        while raw[at:at+2] == b', ':
            self.check(); at = self.copy_identifier(raw, at+2)
        require(len(raw)-at == len(b') FROM stdin;\n') and raw.startswith(b') FROM stdin;\n', at), 'copy')
        self.check()

    def quoted(self, at, quote, escape=False):
        start = at; at += 1
        while at < self.n:
            self.progress(start, at)
            c = self.raw[at]
            if escape and c == 10: raise Unavailable('literal')
            if c == quote:
                if at+1 < self.n and self.raw[at+1] == quote: at += 2; continue
                return at+1
            if escape and c == 92:
                at += 1
                require(at < self.n, 'literal')
                c = self.raw[at]
                if c in b'\\\'"bfnrt': at += 1; continue
                if c in b'01234567':
                    end = at+1
                    while end < min(at+3, self.n) and self.raw[end] in b'01234567': end += 1
                    at = end; continue
                if c in b'xuU':
                    count = {120:2, 117:4, 85:8}[c]; at += 1; end = at
                    while end < min(at+count, self.n) and self.raw[end] in HEX: end += 1
                    require(end-at >= 1 if c == 120 else end-at == count, 'literal')
                    at = end; continue
                raise Unavailable('literal')
            at += 1
        raise Unavailable('unfinished')

    def dollar(self, at):
        start = at; at += 1
        if at < self.n and self.raw[at] != 36:
            require(self.raw[at] in ASCII_START, 'literal')
            while at < self.n and self.raw[at] in ASCII_CONT:
                at += 1; limit_guard(at-start, MAX_TAG+1, 'dollar_tag_prefix_bytes', at)
        require(at < self.n and self.raw[at] == 36, 'literal')
        delimiter = self.raw[start:at+1]
        at += 1
        while at < self.n:
            self.check(); limit_guard(at-start, MAX_TOKEN, 'dollar_body_bytes', at)
            window = max(len(delimiter), min(CHUNK, 4096))
            end = min(self.n, at+window)
            found = self.raw.find(delimiter, at, end)
            self.check()
            if found >= 0:
                limit_guard(found+len(delimiter)-start, MAX_TOKEN, 'dollar_body_bytes', found+len(delimiter))
                return found+len(delimiter)
            if end == self.n: raise Unavailable('unfinished')
            at = end-len(delimiter)+1  # Retain overlap inside the next bounded window.
        raise Unavailable('unfinished')

    def number(self, at):
        start = at
        def digits(pos):
            while pos < self.n and self.raw[pos] in DIGITS:
                self.progress(start, pos); pos += 1
            return pos
        at = digits(at)
        if at < self.n and self.raw[at] == 46:
            require(self.raw[at:at+2] != b'..', 'token')
            at = digits(at+1)
        if at < self.n and self.raw[at] in b'eE':
            at += 1
            if at < self.n and self.raw[at] in b'+-': at += 1
            end = digits(at); require(end > at, 'token'); at = end
        require(at == self.n or not ident_cont(self.raw[at]), 'token')
        require(self.raw[at:at+1] != b'.', 'token')
        return at

    def matches(self, expected, at):
        for start in range(0, len(expected), CHUNK):
            self.check()
            part = expected[start:start+CHUNK]
            if not self.raw.startswith(part, at+start):
                return False
            self.check()
        return True

    def copy_payload(self, at):
        self.copies += 1; limit_guard(self.copies, MAX_COPY, 'copy_groups', at)
        start = at
        # COPY rows are opaque spans, bounded by MAX_INPUT rather than the SQL
        # token limit. Retain offsets only; never allocate a whole line buffer.
        while at < self.n:
            line = at
            while at < self.n:
                self.check()
                found = self.raw.find(b'\n', at, min(self.n, at+CHUNK))
                if found >= 0:
                    at = found+1; break
                at = min(self.n, at+CHUNK)
            require(at > line and self.raw[at-1:at] == b'\n', 'copy')
            if at-line == 3 and self.raw[line:at] == b'\\.\n':
                self.add(self.leaves, COPY_DATA, start, line)
                self.add(self.leaves, COPY_END, line, at)
                return at
        raise Unavailable('unfinished')

    def run(self):
        at = 0; leaf_start = 0; statement = None; first_token = True
        copy = False; pending_quote = False; depth = 0
        while at < self.n:
            self.check()
            start = at; c = self.raw[at]
            if c in b' \t\n':
                at += 1
                while at < self.n and self.raw[at] in b' \t\n':
                    self.progress(start, at); at += 1
                self.token(SPACE, start, at)
                continue
            if self.raw[at:at+2] == b'--':
                at += 2
                while at < self.n and self.raw[at] != 10:
                    self.progress(start, at); at += 1
                require(at < self.n, 'unfinished'); at += 1
                self.token(LINE_COMMENT, start, at); continue
            if c == 92:
                require(statement is None and not pending_quote and (at == 0 or self.raw[at-1] == 10), 'meta')
                require(self.meta_at < len(self.expected_meta), 'meta')
                line = self.expected_meta[self.meta_at]
                require(self.raw.startswith(line, at), 'meta')
                if leaf_start < at: self.add(self.leaves, TRIVIA, leaf_start, at)
                self.add(self.leaves, META, at, at+len(line))
                self.sql_allowed = self.meta_modes[self.meta_at]; self.meta_at += 1
                at += len(line); leaf_start = at; continue
            require(self.sql_allowed, 'meta')
            if statement is None:
                if leaf_start < at: self.add(self.leaves, TRIVIA, leaf_start, at)
                statement = at; leaf_start = at; first_token = True; copy = False
            if self.raw[at:at+2] == b'/*':
                nesting = 1; at += 2
                while at < self.n and nesting:
                    self.progress(start, at)
                    if self.raw[at:at+2] == b'/*': nesting += 1; require(nesting <= MAX_DEPTH, 'depth'); at += 2
                    elif self.raw[at:at+2] == b'*/': nesting -= 1; at += 2
                    else: at += 1
                require(nesting == 0, 'unfinished'); self.token(BLOCK_COMMENT, start, at); continue
            if c == 39:
                require(not pending_quote, 'literal')
                at = self.quoted(at, 39); self.token(STRING, start, at); pending_quote = True; first_token = False; continue
            pending_quote = False
            if c in b'\x0b\x0c': raise Unavailable('token')
            if c in b'uU' and self.raw[at+1:at+3] in (b"&'", b'&"'): raise Unavailable('literal')
            if c in b'bBxXnN' and self.raw[at+1:at+2] == b"'": raise Unavailable('literal')
            if c in b'eE' and self.raw[at+1:at+2] == b"'":
                at = self.quoted(at+1, 39, True); self.token(ESCAPE, start, at); pending_quote = True
            elif c == 34:
                at = self.quoted(at, 34); self.token(QUOTED_IDENT, start, at, identifier=True)
            elif c == 36:
                at = self.dollar(at); self.token(DOLLAR, start, at)
            elif ident_start(c):
                at += 1
                while at < self.n and ident_cont(self.raw[at]):
                    self.progress(start, at, limit=MAX_IDENTIFIER, site='identifier_bytes'); at += 1
                self.token(IDENT, start, at, identifier=True)
                word = self.raw[start:at].lower() if at-start in (4, 5) else None
                require(word != b'begin', 'begin')
                if word == b'copy': require(first_token, 'copy'); copy = True
            elif c in DIGITS or c == 46 and at+1 < self.n and self.raw[at+1] in DIGITS:
                at = self.number(at); self.token(NUMBER, start, at)
            elif c == 58:
                require(self.raw[at:at+2] in (b'::', b':='), 'token')
                at += 2; self.token(PUNCT, start, at)
            elif c == 40:
                depth += 1; require(depth <= MAX_DEPTH, 'depth'); at += 1; self.token(PUNCT, start, at)
            elif c == 41:
                require(depth > 0, 'depth'); depth -= 1; at += 1; self.token(PUNCT, start, at)
            elif c == 59:
                at += 1; self.token(PUNCT, start, at)
                if depth == 0:
                    self.statements += 1; limit_guard(self.statements, MAX_STATEMENTS, 'statements', at)
                    if copy:
                        require(self.copy_at < len(self.copy_commands) and self.raw[at:at+1] == b'\n', 'copy')
                        expected = self.copy_commands[self.copy_at]
                        require(at+1-statement == len(expected) and self.matches(expected, statement), 'copy')
                        self.copy_at += 1; at += 1
                    self.add(self.leaves, SQL, statement, at)
                    if copy: at = self.copy_payload(at)
                    statement = None; leaf_start = at; first_token = True
                    continue
            else:
                # Remaining punctuation has no quote, comment or depth effect.
                require(32 <= c < 127 and c != 92, 'token')
                at += 1; self.token(PUNCT, start, at)
            first_token = False
        require(statement is None and depth == 0 and not pending_quote, 'unfinished')
        require(self.meta_at == len(self.expected_meta) and self.copy_at == len(self.copy_commands), 'binding')
        if leaf_start < self.n: self.add(self.leaves, TRIVIA, leaf_start, self.n)
        self.check()
        end = 0
        for offset in range(0, len(self.leaves), RECORD.size):
            self.check(); _, start, stop = RECORD.unpack_from(self.leaves, offset)
            require(start == end and stop >= start, 'coverage'); end = stop
        require(end == self.n, 'coverage')
        receipt = {'schema': RULE_VERSION, 'ruleVersionSha256': hashlib.sha256(RULE_VERSION.encode('ascii')).hexdigest(), 'status': 'conditional_lexical_spans', 'profileCondition': PROFILE,
            'input': {'bytes': self.n, 'sha256': self.input_hash},
            'leaves': {'bytes': len(self.leaves), 'sha256': self.hash_index(self.leaves), 'counts': self.counts[1:]},
            'tokens': {'bytes': len(self.tokens), 'sha256': self.hash_index(self.tokens)},
            'statements': self.statements, 'copyGroups': self.copies, 'metaLines': self.meta_at,
            'sqlGrammarAccepted': False, 'entryIdentityAccepted': False, 'completeLedgerAccepted': False,
            'runtimeAccepted': False, 'cooperativeDeadline': True}
        output = bytearray()
        for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':')).iterencode(receipt):
            self.check(); encoded = chunk.encode('ascii')
            limit_guard(len(output)+len(encoded), MAX_RECEIPT, 'receipt_bytes'); output.extend(encoded)
        result = Scan(bytes(self.leaves), bytes(self.tokens), bytes(output)); self.check()
        return result


def scan(raw, *, expected_meta=(), database=b'postgres', copy_commands=(), deadline, profile):
    return Scanner(raw, expected_meta, database, copy_commands, deadline, profile).run()
