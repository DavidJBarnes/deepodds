from pydantic import BaseModel


class RobinhoodKeysUpdate(BaseModel):
    api_key: str
    private_key: str


class RobinhoodKeysStatus(BaseModel):
    has_keys: bool
    key_preview: str | None = None
    valid: bool = False
