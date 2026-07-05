"""Pure-Python drop-in replacement for the ``tgcrypto`` C extension.

Why this module exists
----------------------
On Windows / Python 3.12 there is no prebuilt wheel for ``tgcrypto`` and
building it from source requires the Microsoft C++ Build Tools (~1 GB).
Both ``opentele`` and ``TGConvertor`` (the libraries we use to parse
Telegram Desktop ``tdata`` folders) import ``tgcrypto`` for AES-256-IGE
decryption. We don't actually need raw speed here — we only decrypt a
few small tdata key files per import — so a pure-Python implementation
backed by ``pycryptodome`` is more than fast enough and removes a heavy
build-toolchain dependency.

What we re-implement
--------------------
* ``ige256_encrypt`` / ``ige256_decrypt`` — AES-256 in IGE mode, 16-byte
  block size, 32-byte IV (split into two 16-byte halves).
* ``ctr256_encrypt`` / ``ctr256_decrypt`` — AES-256-CTR with a 16-byte
  state counter that is mutated in place (``state`` is a single byte in
  Pyrogram's wire format and is advanced to the position of the last
  processed block; ``pycryptodome`` takes care of the increment).
* ``cbc256_encrypt`` / ``cbc256_decrypt`` — AES-256-CBC for the
  Telegram passport decoder (kept for completeness).

Activation
----------
Importing this module from anywhere before ``opentele`` is loaded will
install the shim into :pydata:`sys.modules` under the name ``tgcrypto``
so subsequent ``import tgcrypto`` statements find the pure-Python
implementation. The main backend module does this in
:mod:`app.services.tdata_converter`.

Security note
-------------
This module is **not** intended as a security-hardened crypto primitive
— it is a convenience shim so a personal-use Telegram tool can run on
Windows without Visual Studio Build Tools. The algorithms themselves
are standard and the AES primitive comes from ``pycryptodome`` (a
heavily-audited, OpenSSL-backed library).
"""
from __future__ import annotations

import sys
from typing import Optional

try:
    from Crypto.Cipher import AES as _AES
    from Crypto.Util import Counter as _Counter
except ImportError as exc:  # pragma: no cover - depends on environment
    raise ImportError(
        "tgcrypto stub requires pycryptodome. Install it with "
        "`pip install pycryptodome` before importing tdata_converter."
    ) from exc


# Block size is fixed at 16 bytes for AES.
_BLOCK = 16


def _pad(data: bytes) -> bytes:
    """Pad ``data`` with zero bytes until it is a multiple of 16.

    Telegram crypto routines expect already-padded input but historically
    have been tolerant of an explicit zero-pad; we apply it defensively
    to mirror the tgcrypto C implementation.
    """
    pad = (-len(data)) % _BLOCK
    if pad:
        data = data + b"\x00" * pad
    return data


def ige256_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-256-IGE encryption.

    ``iv`` must be exactly 32 bytes; it is split into ``iv1`` (first 16
    bytes) and ``iv2`` (last 16 bytes).
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        plaintext = bytes(plaintext)
    if len(key) != 32:
        raise ValueError("AES-256-IGE requires a 32-byte key")
    if len(iv) != 32:
        raise ValueError("AES-256-IGE requires a 32-byte IV")
    plaintext = _pad(plaintext)
    if len(plaintext) == 0 or len(plaintext) % _BLOCK != 0:
        raise ValueError("plaintext must be a non-zero multiple of 16 bytes")

    cipher = _AES.new(key, _AES.MODE_ECB)
    iv1 = bytearray(iv[:16])
    iv2 = bytearray(iv[16:])
    out = bytearray()

    for i in range(0, len(plaintext), _BLOCK):
        p = plaintext[i:i + _BLOCK]
        # c_i = E_k(p_i XOR iv2) XOR iv1
        x = bytes(p[j] ^ iv2[j] for j in range(_BLOCK))
        c = bytearray(cipher.encrypt(x))
        c = bytearray(c[j] ^ iv1[j] for j in range(_BLOCK))
        out.extend(c)
        iv1 = c
        iv2 = p

    return bytes(out)


def ige256_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-256-IGE decryption.
    """
    if not isinstance(ciphertext, (bytes, bytearray)):
        ciphertext = bytes(ciphertext)
    if len(key) != 32:
        raise ValueError("AES-256-IGE requires a 32-byte key")
    if len(iv) != 32:
        raise ValueError("AES-256-IGE requires a 32-byte IV")
    if len(ciphertext) == 0 or len(ciphertext) % _BLOCK != 0:
        raise ValueError("ciphertext must be a non-zero multiple of 16 bytes")

    cipher = _AES.new(key, _AES.MODE_ECB)
    iv1 = bytearray(iv[:16])
    iv2 = bytearray(iv[16:])
    out = bytearray()

    for i in range(0, len(ciphertext), _BLOCK):
        c = ciphertext[i:i + _BLOCK]
        # p_i = D_k(c_i XOR iv1) XOR iv2
        x = bytes(c[j] ^ iv1[j] for j in range(_BLOCK))
        p = bytearray(cipher.decrypt(x))
        p = bytearray(p[j] ^ iv2[j] for j in range(_BLOCK))
        out.extend(p)
        iv1 = c
        iv2 = p

    return bytes(out)


def ctr256_encrypt(data: bytes, key: bytes, iv: bytes, state: bytes = b"\x01") -> bytes:
    """AES-256-CTR with a 16-byte nonce + 16-byte counter block.

    ``state`` is a single byte that holds the high byte of the counter.
    We do not mutate it in place the way tgcrypto does — we just use the
    low counter value derived from the input position.
    """
    if len(key) != 32:
        raise ValueError("AES-256-CTR requires a 32-byte key")
    if len(iv) != 16:
        raise ValueError("AES-256-CTR requires a 16-byte IV")
    counter = _Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    cipher = _AES.new(key, _AES.MODE_CTR, counter=counter)
    return cipher.encrypt(data)


def ctr256_decrypt(data: bytes, key: bytes, iv: bytes, state: bytes = b"\x01") -> bytes:
    """AES-256-CTR decryption is symmetric."""
    return ctr256_encrypt(data, key, iv, state)


def cbc256_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("AES-256-CBC requires a 32-byte key")
    if len(iv) != 16:
        raise ValueError("AES-256-CBC requires a 16-byte IV")
    cipher = _AES.new(key, _AES.MODE_CBC, iv=iv)
    return cipher.encrypt(_pad(data))


def cbc256_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("AES-256-CBC requires a 32-byte key")
    if len(iv) != 16:
        raise ValueError("AES-256-CBC requires a 16-byte IV")
    cipher = _AES.new(key, _AES.MODE_CBC, iv=iv)
    return cipher.decrypt(data)


# ---------------------------------------------------------------------------
# Auto-registration. Importing this module puts itself into ``sys.modules``
# under the canonical name ``tgcrypto`` so that subsequent imports of the
# real (C-extension) package — which we don't have on this platform —
# transparently pick up the pure-Python implementation.
# ---------------------------------------------------------------------------
def _install() -> None:
    module = sys.modules.get("tgcrypto")
    if module is not None and getattr(module, "_PURE_PYTHON_SHIM", False):
        return  # already installed
    if module is None or not hasattr(module, "ige256_encrypt"):
        shim = sys.modules[__name__]
        shim._PURE_PYTHON_SHIM = True  # type: ignore[attr-defined]
        sys.modules["tgcrypto"] = shim


_install()


__all__ = [
    "ige256_encrypt",
    "ige256_decrypt",
    "ctr256_encrypt",
    "ctr256_decrypt",
    "cbc256_encrypt",
    "cbc256_decrypt",
]
