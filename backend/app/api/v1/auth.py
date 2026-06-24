from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


# Registration disabled — the app is single-tenant for now. Re-enable together with
# the Settings / per-user-keys / multi-tenant work.
# @router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
# async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(User).where(User.email == body.email))
#     if result.scalar_one_or_none():
#         raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
#     user = User(email=body.email, hashed_password=hash_password(body.password))
#     db.add(user)
#     await db.commit()
#     await db.refresh(user)
#     return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=user.id,
        email=user.email,
        has_kalshi_keys=user.kalshi_api_key_id is not None,
        created_at=user.created_at,
    )
