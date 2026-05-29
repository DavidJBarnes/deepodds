from pydantic import BaseModel


class KalshiKeysUpdate(BaseModel):
    api_key_id: str
    private_key_pem: str


class KalshiKeysStatus(BaseModel):
    has_keys: bool
    key_preview: str | None = None
    valid: bool = False
