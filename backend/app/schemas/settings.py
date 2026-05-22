from pydantic import BaseModel


class KalshiKeysUpdate(BaseModel):
    api_key_id: str
    api_private_key: str


class KalshiKeysStatus(BaseModel):
    has_keys: bool
    key_id_preview: str | None = None
    valid: bool = False
