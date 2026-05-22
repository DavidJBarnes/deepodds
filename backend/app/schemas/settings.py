from pydantic import BaseModel


class CoinbaseKeysUpdate(BaseModel):
    api_key: str
    private_key: str


class CoinbaseKeysStatus(BaseModel):
    has_keys: bool
    key_preview: str | None = None
    valid: bool = False
