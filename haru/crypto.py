"""맥↔폰 메시지 암호화 (AES-256-GCM). 중계 서버(ntfy)는 암호문만 본다.

봉투(bytes) = 0x01 | nonce(12) | 암호문+태그(16)   — AAD = 토픽 이름 (다른 토픽으로 옮겨 붙이기 방지)
글자 메시지는 'H1:' + base64url(봉투). 폰(Kotlin)도 똑같이 구현한다 (android/.../Envelope.kt).
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"
PREFIX = "H1:"


class CryptoError(ValueError):
    pass


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_key() -> str:
    return b64u(AESGCM.generate_key(bit_length=256))


def seal(key_b64: str, topic: str, plaintext: bytes) -> bytes:
    key = unb64u(key_b64)
    nonce = os.urandom(12)
    return VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, topic.encode())


def open_(key_b64: str, topic: str, envelope: bytes) -> bytes:
    if len(envelope) < 1 + 12 + 16 or envelope[:1] != VERSION:
        raise CryptoError("하루서랍 봉투가 아니에요")
    key = unb64u(key_b64)
    try:
        return AESGCM(key).decrypt(envelope[1:13], envelope[13:], topic.encode())
    except Exception as e:  # InvalidTag
        raise CryptoError("복호화 실패 (키가 다르거나 변조됨)") from e


def seal_text(key_b64: str, topic: str, obj: dict) -> str:
    return PREFIX + b64u(seal(key_b64, topic, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()))


def open_text(key_b64: str, topic: str, text: str) -> dict:
    if not text or not text.startswith(PREFIX):
        raise CryptoError("하루서랍 메시지가 아니에요")
    return json.loads(open_(key_b64, topic, unb64u(text[len(PREFIX):])).decode())
