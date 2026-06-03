"""Crypto XGBoost model management for the scanner process."""

import logging
import os
import time

logger = logging.getLogger("scanner.models.crypto")

_MODEL_PATH: str | None = None
_loaded_mtime: float = 0.0


def check_and_reload(session=None) -> bool:
    """Check if the crypto model file has changed and reload if needed.

    The *session* parameter is accepted for API compatibility with the
    scanner loop but is not used (file-based check).
    """
    global _loaded_mtime
    from app.services.probability_model import MODEL_FILE, reload_booster

    try:
        cur_mtime = os.path.getmtime(MODEL_FILE)
    except OSError:
        return False

    if cur_mtime <= _loaded_mtime:
        return False

    reload_booster()
    _loaded_mtime = cur_mtime
    logger.info("Crypto model reloaded (mtime=%.0f)", cur_mtime)
    return True
