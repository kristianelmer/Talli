"""Fixed ES256 negative fixture for the captured, owned local Auth identity.

Synthetic signature checks here establish key correspondence, not GoTrue session
acceptance. The owning restore rehearsal must still prove the stateless denial.
"""
import base64
import json
import math
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils


def _decode(value):
    if type(value) is not str or not value or re.fullmatch(r'[A-Za-z0-9_-]+', value) is None:
        raise ValueError('Invalid encoded value')
    raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if _encode(raw) != value:
        raise ValueError('Noncanonical encoded value')
    return raw


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _object(value):
    def unique(pairs):
        fields = {}
        for key, item in pairs:
            if key in fields:
                raise ValueError('Duplicate field')
            fields[key] = item
        return fields
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Nonfinite number')
        return number
    def invalid(value):
        raise ValueError('Nonfinite constant')
    text = value.decode('utf-8') if type(value) is bytes else value
    return json.loads(text, object_pairs_hook=unique, parse_float=finite, parse_constant=invalid)


def _private_key(header, keyset):
    keys = _object(keyset)
    if type(keys) is not list or not 1 <= len(keys) <= 32 or any(type(key) is not dict for key in keys):
        raise ValueError('Invalid captured keyset')
    matching = [key for key in keys if key.get('kid') == header['kid']]
    if len(matching) != 1:
        raise ValueError('Ambiguous captured key')
    key = matching[0]
    if key.get('kty') != 'EC' or key.get('crv') != 'P-256':
        raise ValueError('Unsupported captured key')
    if ('alg' in key and key['alg'] != 'ES256') or ('use' in key and key['use'] != 'sig'):
        raise ValueError('Unsupported captured key metadata')
    if 'key_ops' in key:
        operations = key['key_ops']
        if (type(operations) is not list or any(type(item) is not str for item in operations)
                or len(operations) != len(set(operations)) or 'sign' not in operations
                or not set(operations) <= {'sign', 'verify'}):
            raise ValueError('Unsupported captured key operations')
    coordinates = [_decode(key.get(name)) for name in ('x', 'y', 'd')]
    if any(len(value) != 32 for value in coordinates):
        raise ValueError('Invalid captured key coordinates')
    x, y, scalar = [int.from_bytes(value, 'big') for value in coordinates]
    return ec.EllipticCurvePrivateNumbers(scalar,
        ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1())).private_key()


def stateless_es256_owner_token(token, source_auth_environment):
    """Verify the original under its unique captured key; remove only its SID.

    No alternate key, refreshed session, external authority or privileged claim
    is available. All refusal text is fixed and contains no captured values.
    """
    if type(source_auth_environment) is not dict:
        raise ValueError('Owned ES256 stateless fixture verification failed')
    keyset = source_auth_environment.get('GOTRUE_JWT_KEYS')
    if type(keyset) is not str or not keyset:
        raise ValueError('Owned stateless fixture requires captured ES256 signing configuration')
    try:
        if type(token) is not str or len(token) > 128 * 1024 or len(keyset) > 256 * 1024:
            raise ValueError('Invalid captured input size')
        if len(keyset.encode('utf-8')) > 256 * 1024:
            raise ValueError('Invalid captured keyset byte size')
        parts = token.split('.')
        if len(parts) != 3 or len(parts[0]) > 4096:
            raise ValueError('Invalid original token')
        encoded_header, payload, signature = parts
        header = _object(_decode(encoded_header))
        if (type(header) is not dict or header.get('alg') != 'ES256'
                or type(header.get('kid')) is not str or not 1 <= len(header['kid']) <= 512
                or any(name in header for name in ('jwk', 'jku', 'x5u', 'x5c', 'crit', 'b64'))):
            raise ValueError('Unsupported original header')
        private = _private_key(header, keyset)
        raw_signature = _decode(signature)
        if len(raw_signature) != 64:
            raise ValueError('Invalid original signature size')
        original_body = (encoded_header + '.' + payload).encode('ascii')
        der = utils.encode_dss_signature(int.from_bytes(raw_signature[:32], 'big'),
            int.from_bytes(raw_signature[32:], 'big'))
        public = private.public_key()
        public.verify(der, original_body, ec.ECDSA(hashes.SHA256()))
        claims = _object(_decode(payload))
        if (type(claims) is not dict or type(claims.get('session_id')) is not str
                or not claims['session_id']):
            raise ValueError('Original token lacks live session')
        del claims['session_id']
        body = encoded_header + '.' + _encode(json.dumps(claims, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode())
        der = private.sign(body.encode('ascii'), ec.ECDSA(hashes.SHA256()))
        public.verify(der, body.encode('ascii'), ec.ECDSA(hashes.SHA256()))
        first, second = utils.decode_dss_signature(der)
        return body + '.' + _encode(first.to_bytes(32, 'big') + second.to_bytes(32, 'big'))
    except (InvalidSignature, ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('Owned ES256 stateless fixture verification failed') from None
