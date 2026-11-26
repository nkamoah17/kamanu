"""Ed25519 (RFC 8032, section 5.1) in the standard library alone: what a hallmark is signed and checked with.

    public_key(seed) -> bytes            the 32-byte public key of a 32-byte private seed
    sign(seed, message) -> bytes         the 64-byte signature R || S
    verify(public, message, signature) -> bool

Pure Python on integers: hashlib's SHA-512 and nothing else. It is not constant time; it signs a record on the
issuer's own machine and checks public records, where timing tells nothing secret to anyone. Importing it loads
no module outside the standard library (kamanu.assay's __init__ imports nothing either).
"""
from __future__ import annotations

import hashlib

P = 2 ** 255 - 19                                            # the field
L = 2 ** 252 + 27742317777372353535851937790883648493       # the order of the base point
D = (-121665 * pow(121666, P - 2, P)) % P                    # the curve's d
SQRT_M1 = pow(2, (P - 1) // 4, P)                            # a square root of -1


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_mod_l(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little") % L


# Points in extended homogeneous coordinates (X, Y, Z, T) with x = X/Z, y = Y/Z, x*y = T/Z.
def _point_add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % P
    b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P
    d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _scalar_mult(k: int, p):
    acc = (0, 1, 1, 0)                                       # the neutral element
    while k:
        if k & 1:
            acc = _point_add(acc, p)
        p = _point_add(p, p)
        k >>= 1
    return acc


def _same(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % P == 0 and (p[1] * q[2] - q[1] * p[2]) % P == 0


def _x_of(y: int, sign: int):
    """The x with the given low bit on the curve at y, or None."""
    if y >= P:
        return None
    u = (y * y - 1) % P
    v = (D * y * y + 1) % P
    x2 = u * pow(v, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_BY = 4 * pow(5, P - 2, P) % P
_BX = _x_of(_BY, 0)
BASE = (_BX, _BY, 1, _BX * _BY % P)


def _encode(p) -> bytes:
    zinv = pow(p[2], P - 2, P)
    x, y = p[0] * zinv % P, p[1] * zinv % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(b: bytes):
    if len(b) != 32:
        return None
    n = int.from_bytes(b, "little")
    sign, y = n >> 255, n & ((1 << 255) - 1)
    x = _x_of(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _secret(seed: bytes) -> tuple[int, bytes]:
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError("an Ed25519 private seed is 32 bytes")
    h = _sha512(bytes(seed))
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    a, _ = _secret(seed)
    return _encode(_scalar_mult(a, BASE))


def sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _secret(seed)
    pub = _encode(_scalar_mult(a, BASE))
    r = _sha512_mod_l(prefix + bytes(message))
    big_r = _encode(_scalar_mult(r, BASE))
    s = (r + _sha512_mod_l(big_r + pub + bytes(message)) * a) % L
    return big_r + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    try:
        public, message, signature = bytes(public), bytes(message), bytes(signature)
    except TypeError:
        return False
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _decode(public), _decode(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    k = _sha512_mod_l(signature[:32] + public + message)
    return _same(_scalar_mult(s, BASE), _point_add(r, _scalar_mult(k, a)))
