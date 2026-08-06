"""Minimal S3 presigned-URL generator (SigV4), stdlib only.

Why not boto3: it is ~100MB on disk and ~30-40MB RSS for the one operation we
need, on a 916MB box that has already thrashed itself dark once. The `explorer`
package is stdlib-only for the same reason. This module is ~100 lines and was
verified against the real bucket (PUT 200, GET 200, bytes match) before being
committed.

Credentials come from the EC2 instance role via IMDSv2, cached until shortly
before expiry. Falls back to AWS_* environment variables when present, so local
development and tests work without an instance profile.

Scope note: presigned URLs inherit the signer's permissions, so the EC2 role is
deliberately scoped to s3:PutObject/GetObject on `clips/*` of one bucket. The GPU
worker never receives AWS credentials — only a short-lived URL.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import threading
import urllib.parse
import urllib.request

_ALGORITHM = "AWS4-HMAC-SHA256"
_IMDS_ROOT = "http://169.254.169.254"
# Refresh this long before the credentials actually expire, so a request never
# races the rotation.
_REFRESH_MARGIN_S = 300


class _Credentials:
    def __init__(self, access_key: str, secret_key: str, token: str | None,
                 expires: _dt.datetime | None) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.token = token
        self.expires = expires

    def stale(self, now: _dt.datetime) -> bool:
        if self.expires is None:
            return False  # static env credentials never expire
        return now >= self.expires - _dt.timedelta(seconds=_REFRESH_MARGIN_S)


_cache: _Credentials | None = None
_lock = threading.Lock()


def _http(url: str, *, method: str = "GET", headers: dict | None = None,
          timeout: float = 2.0) -> bytes:
    req = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _imds_credentials() -> _Credentials:
    """Fetch instance-role credentials via IMDSv2 (token-required)."""
    token = _http(f"{_IMDS_ROOT}/latest/api/token", method="PUT",
                  headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"}).decode()
    h = {"X-aws-ec2-metadata-token": token}
    base = f"{_IMDS_ROOT}/latest/meta-data/iam/security-credentials/"
    role = _http(base, headers=h).decode().strip()
    doc = json.loads(_http(base + role, headers=h))
    expires = None
    if doc.get("Expiration"):
        expires = _dt.datetime.fromisoformat(doc["Expiration"].replace("Z", "+00:00"))
    return _Credentials(doc["AccessKeyId"], doc["SecretAccessKey"],
                        doc.get("Token"), expires)


def _env_credentials() -> _Credentials | None:
    ak = os.environ.get("AWS_ACCESS_KEY_ID")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if ak and sk:
        return _Credentials(ak, sk, os.environ.get("AWS_SESSION_TOKEN"), None)
    return None


def _credentials(now: _dt.datetime) -> _Credentials:
    global _cache
    with _lock:
        if _cache is None or _cache.stale(now):
            _cache = _env_credentials() or _imds_credentials()
        return _cache


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def presign(
    method: str,
    bucket: str,
    key: str,
    region: str,
    expires_in: int = 900,
    *,
    now: _dt.datetime | None = None,
) -> str:
    """Return a presigned S3 URL for ``method`` on ``bucket/key``.

    ``UNSIGNED-PAYLOAD`` is used so the caller may upload any body — the URL is
    already scoped to one bucket, one key, one method and a short TTL.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    creds = _credentials(now)
    host = f"{bucket}.s3.{region}.amazonaws.com"
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/s3/aws4_request"

    canonical_uri = "/" + urllib.parse.quote(key, safe="/~")
    query = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{creds.access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_in),
        "X-Amz-SignedHeaders": "host",
    }
    if creds.token:
        query["X-Amz-Security-Token"] = creds.token
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted(query.items())
    )

    canonical_request = "\n".join(
        [method, canonical_uri, canonical_qs, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    string_to_sign = "\n".join(
        [_ALGORITHM, amz_date, scope,
         hashlib.sha256(canonical_request.encode()).hexdigest()]
    )

    k_date = _sign(f"AWS4{creds.secret_key}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, "s3")
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return f"https://{host}{canonical_uri}?{canonical_qs}&X-Amz-Signature={signature}"


def reset_credential_cache() -> None:
    """Drop cached credentials (tests, and after an IMDS failure)."""
    global _cache
    with _lock:
        _cache = None
