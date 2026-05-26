"""Regression tests for KalshiClient request signing.

The Kalshi v2 API requires the signed message to include the FULL URL path
(`/trade-api/v2/...`), not just the endpoint suffix. Signing only the suffix
returns 401 Unauthorized.
"""

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services.kalshi_client import URL_PATH_PREFIX, KalshiClient


def _make_test_client():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return KalshiClient("test-api-key", pem), private_key


def _verify(public_key, message: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(
            base64.b64decode(signature_b64),
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


class TestSignedPathIncludesPrefix:
    def test_path_prefix_is_v2(self):
        assert URL_PATH_PREFIX == "/trade-api/v2"

    def test_signed_message_has_v2_prefix(self):
        client, priv = _make_test_client()
        ts = "1700000000000"

        sig = client._sign(ts, "GET", "/portfolio/balance")

        # The signature should verify against the FULL path message
        correct_message = f"{ts}GET/trade-api/v2/portfolio/balance".encode()
        assert _verify(priv.public_key(), correct_message, sig), \
            "signature should verify against the full URL path message"

        # And should NOT verify against the suffix-only message (the old bug)
        old_buggy_message = f"{ts}GET/portfolio/balance".encode()
        assert not _verify(priv.public_key(), old_buggy_message, sig), \
            "signature must not verify against the suffix-only message"

    def test_signing_idempotent_when_prefix_already_present(self):
        # If the caller passes a path that already includes the prefix, we
        # should not double-prefix it.
        client, priv = _make_test_client()
        ts = "1700000000000"

        sig = client._sign(ts, "POST", "/trade-api/v2/portfolio/orders")
        expected = f"{ts}POST/trade-api/v2/portfolio/orders".encode()
        assert _verify(priv.public_key(), expected, sig)

    def test_method_included_in_signature(self):
        client, priv = _make_test_client()
        ts = "1700000000000"

        sig_get = client._sign(ts, "GET", "/portfolio/balance")
        sig_post = client._sign(ts, "POST", "/portfolio/balance")

        # Signatures are PSS so they're randomized, but each should verify
        # only against its own method's message.
        get_msg = f"{ts}GET/trade-api/v2/portfolio/balance".encode()
        post_msg = f"{ts}POST/trade-api/v2/portfolio/balance".encode()

        assert _verify(priv.public_key(), get_msg, sig_get)
        assert not _verify(priv.public_key(), post_msg, sig_get)
        assert _verify(priv.public_key(), post_msg, sig_post)

    def test_timestamp_included_in_signature(self):
        client, priv = _make_test_client()

        sig = client._sign("1700000000000", "GET", "/portfolio/balance")

        same_ts_msg = f"1700000000000GET/trade-api/v2/portfolio/balance".encode()
        wrong_ts_msg = f"1800000000000GET/trade-api/v2/portfolio/balance".encode()
        assert _verify(priv.public_key(), same_ts_msg, sig)
        assert not _verify(priv.public_key(), wrong_ts_msg, sig)


class TestHeadersStructure:
    def test_required_headers_present(self):
        client, _ = _make_test_client()
        headers = client._headers("GET", "/portfolio/balance")
        assert headers["KALSHI-ACCESS-KEY"] == "test-api-key"
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    def test_timestamp_is_milliseconds(self):
        client, _ = _make_test_client()
        headers = client._headers("GET", "/portfolio/balance")
        ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
        # Milliseconds since epoch — should be a 13-digit number for any
        # time in 2001–2286.
        assert 1_000_000_000_000 < ts < 10_000_000_000_000
