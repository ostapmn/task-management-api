from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.user import Token, UserCreate, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, session: SessionDep) -> User:
    email = data.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, full_name=data.full_name, hashed_password=await hash_password(data.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return user


@router.post("/auth/login", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep) -> Token:
    user = await session.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not await verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/users/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(_: CurrentUser, session: SessionDep) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.id))).all())
