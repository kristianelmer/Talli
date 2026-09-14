"""Finite-date acceptance of the released Node 24.20.0 TT02 import boundary.

Adapted from V8 DateParser (Copyright 2011 the V8 project authors).
See V8-LICENSE and the pinned reference hashes in issue #153 evidence.
Only finite acceptance is used; this does not assign an authority timestamp.
"""
from __future__ import annotations

import calendar
import icu

from .numbers import SPACE

_WHITE = SPACE.replace('\n', '').replace('\r', '').replace('\u2028', '').replace('\u2029', '')
_MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
_ZONES = {'ut': 0, 'utc': 0, 'z': 0, 'gmt': 0, 'cdt': -5, 'cst': -6, 'edt': -4,
          'est': -5, 'mdt': -6, 'mst': -7, 'pdt': -7, 'pst': -8}
_END = ('end', None, 0)


def _tokens(value):
    value = value.split('\0', 1)[0]
    result = []
    index = 0
    while index < len(value):
        char, start = value[index], index
        if '0' <= char <= '9':
            while index < len(value) and '0' <= value[index] <= '9':
                index += 1
            digits = value[start:index]
            result.append(('number', int(digits.lstrip('0')[:9] or '0'), len(digits)))
        elif char in ':-+.)':
            result.append(('symbol', char, 1))
            index += 1
        elif ord(char) >= 65 and char not in _WHITE:
            while index < len(value) and ord(value[index]) >= 65 and value[index] not in _WHITE:
                index += 1
            word = ''.join(chr(ord(c) + 32) if 'A' <= c <= 'Z' else c for c in value[start:index])
            prefix = word[:3]
            kind, number = ('month', _MONTHS.index(prefix) + 1) if prefix in _MONTHS else (
                ('zone', _ZONES[word]) if word in _ZONES else ('ampm', 0 if word == 'am' else 12)
                if word in ('am', 'pm') else ('separator', 0) if word == 't' else ('word', 0))
            result.append((kind, number, len(word)))
        elif char in SPACE:
            result.append(('space', None, 1))
            index += 1
        elif char == '(':
            depth = 0
            while index < len(value):
                depth += (value[index] == '(') - (value[index] == ')')
                index += 1
                if depth == 0:
                    break
            result.append(('unknown', None, index - start))
        else:
            result.append(('unknown', None, 1))
            index += 1
    result.append(_END)
    return result


class _Parser:
    def __init__(self, value):
        self.tokens = _tokens(value)
        self.index = 0
        self.days = []
        self.hours = []
        self.named_month = None
        self.hour_offset = None
        self.zone_sign = self.zone_hour = self.zone_minute = None
        self.iso = False

    def peek(self):
        return self.tokens[min(self.index, len(self.tokens) - 1)]

    def next(self):
        result = self.peek()
        self.index += 1
        return result

    def skip(self, symbol):
        if self.peek()[:2] == ('symbol', symbol):
            self.next()
            return True
        return False

    def fixed(self, length, low=None, high=None):
        kind, value, size = self.peek()
        return kind == 'number' and size == length and (low is None or low <= value <= high)

    def zone(self, offset):
        self.zone_sign = -1 if offset < 0 else 1
        self.zone_hour, self.zone_minute = abs(offset), 0

    def hour_add(self, value, final=False):
        if len(self.hours) == 4:
            return False
        self.hours.append(value)
        if final:
            self.hours += [0] * (4 - len(self.hours))
        return True

    def expecting_time(self, value):
        return len(self.hours) in (1, 2) and 0 <= value <= 59 or len(self.hours) == 3 and 0 <= value <= 999

    @staticmethod
    def milliseconds(token):
        _, value, length = token
        return value * 10 ** (3 - length) if length < 3 else value // 10 ** (min(length, 9) - 3)

    def parse_iso(self):
        if self.peek()[:2] in (('symbol', '+'), ('symbol', '-')):
            sign = self.next()
            if not self.fixed(6):
                return sign
            year = self.next()[1]
            if sign[1] == '-' and year == 0:
                return sign
            self.days.append(-year if sign[1] == '-' else year)
        elif self.fixed(4):
            self.days.append(self.next()[1])
        else:
            return self.next()
        if self.skip('-'):
            if not self.fixed(2, 1, 12):
                return self.next()
            self.days.append(self.next()[1])
            if self.skip('-'):
                if not self.fixed(2, 1, 31):
                    return self.next()
                self.days.append(self.next()[1])
        if self.peek()[0] != 'separator':
            if self.peek()[0] != 'end':
                return self.next()
        else:
            self.next()
            if not self.fixed(2, 0, 24):
                return None
            midnight = self.peek()[1] == 24
            self.hour_add(self.next()[1])
            if not self.skip(':') or not self.fixed(2, 0, 0 if midnight else 59):
                return None
            self.hour_add(self.next()[1])
            if self.skip(':'):
                if not self.fixed(2, 0, 0 if midnight else 59):
                    return None
                self.hour_add(self.next()[1])
                if self.skip('.'):
                    if self.peek()[0] != 'number' or midnight and self.peek()[1] > 0:
                        return None
                    self.hour_add(self.milliseconds(self.next()))
            if self.peek() == ('zone', 0, 1):
                self.next()
                self.zone(0)
            elif self.peek()[:2] in (('symbol', '+'), ('symbol', '-')):
                self.zone_sign = 1 if self.next()[1] == '+' else -1
                if self.fixed(4):
                    value = self.next()[1]
                    self.zone_hour, self.zone_minute = divmod(value, 100)
                    if self.zone_hour > 23 or self.zone_minute > 59:
                        return None
                else:
                    if not self.fixed(2, 0, 23):
                        return None
                    self.zone_hour = self.next()[1]
                    if not self.skip(':') or not self.fixed(2, 0, 59):
                        return None
                    self.zone_minute = self.next()[1]
            if self.peek()[0] != 'end':
                return None
        if self.zone_hour is None and not self.hours:
            self.zone(0)
        self.iso = True
        return _END

    def parse(self):
        token = self.parse_iso()
        if token is None:
            return False
        read_number = bool(self.days)
        while token[0] != 'end':
            kind, value, length = token
            if kind == 'number':
                read_number = True
                if self.skip(':'):
                    if self.skip(':'):
                        if self.hours:
                            return False
                        self.hours.extend((value, 0))
                    else:
                        if not self.hour_add(value):
                            return False
                        self.skip('.')
                elif self.skip('.') and self.expecting_time(value):
                    self.hour_add(value)
                    if self.peek()[0] != 'number':
                        return False
                    self.hour_add(self.milliseconds(self.next()), final=True)
                elif self.zone_hour is not None and self.zone_minute is None and 0 <= value <= 59:
                    self.zone_minute = value
                elif self.expecting_time(value):
                    self.hour_add(value, final=True)
                    peek = self.peek()
                    if peek[0] not in ('end', 'space') and peek != ('zone', 0, 1) and peek[:2] not in (('symbol', '+'), ('symbol', '-')):
                        return False
                else:
                    if len(self.days) == 3:
                        return False
                    self.days.append(value)
                    self.skip('-')
            elif kind in ('month', 'zone', 'separator', 'ampm', 'word'):
                if kind == 'ampm' and self.hours:
                    self.hour_offset = value
                elif kind == 'month':
                    self.named_month = value
                    self.skip('-')
                elif kind == 'zone' and read_number:
                    self.zone(value)
                elif read_number or self.peek()[0] == 'number':
                    return False
            elif kind == 'symbol' and value in ('+', '-') and (self.zone_hour == 0 and self.zone_minute == 0 or self.hours):
                self.zone_sign = 1 if value == '+' else -1
                number, size = (0, 0)
                if self.peek()[0] == 'number':
                    _, number, size = self.next()
                read_number = True
                if self.peek()[:2] == ('symbol', ':'):
                    self.zone_hour, self.zone_minute = number, None
                elif size in (1, 2):
                    self.zone_hour, self.zone_minute = number, 0
                elif size in (3, 4):
                    self.zone_hour, self.zone_minute = divmod(number, 100)
                else:
                    return False
            elif kind == 'symbol' and value in ('+', '-', ')') and read_number:
                return False
            token = self.next()
        return self.finite()

    def finite(self):
        if not self.days:
            return False
        parts = self.days + [1] * (3 - len(self.days))
        if self.named_month is None:
            year, month, day = parts if self.iso or not 1 <= parts[0] <= 31 else (parts[2], parts[0], parts[1])
        else:
            month = self.named_month
            year, day = (parts[0], parts[1]) if not 1 <= parts[0] <= 31 else (parts[1], parts[0])
        if not self.iso:
            year += 2000 if 0 <= year <= 49 else 1900 if 50 <= year <= 99 else 0
        if not 1 <= month <= 12 or not 1 <= day <= 31 or abs(year) > 1000000:
            return False
        hour, minute, second, millisecond = self.hours + [0] * (4 - len(self.hours))
        if self.hour_offset is not None:
            if not 0 <= hour <= 12:
                return False
            hour = hour % 12 + self.hour_offset
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59 and 0 <= millisecond <= 999) and (hour, minute, second, millisecond) != (24, 0, 0, 0):
            return False
        prior = year - 1
        days = 365 * prior + prior // 4 - prior // 100 + prior // 400
        days += sum(calendar.monthrange(year, m)[1] for m in range(1, month)) + day - 1 - 719162
        instant = ((days * 24 + hour) * 3600 + minute * 60 + second) * 1000 + millisecond
        if self.zone_sign is None:
            # Every civil date more than a day inside TimeClip is finite in
            # every IANA timezone. At the endpoints use ICU, as pinned V8 does;
            # libc mktime cannot represent negative civil years on macOS.
            if abs(instant) < 8640000000000000 - 86400000:
                return True
            if abs(instant) > 8640000000000000 + 86400000:
                return False
            raw_offset, dst_offset = icu.TimeZone.createDefault().getOffset(instant / 1000, True)
            instant -= raw_offset + dst_offset
        else:
            offset = ((self.zone_hour or 0) * 3600 + (self.zone_minute or 0) * 60) % 2 ** 32
            if offset > 1073741823:
                return False
            instant -= self.zone_sign * offset * 1000
        return abs(instant) <= 8640000000000000


def finite_date_parse(value: str) -> bool:
    return _Parser(value).parse()
