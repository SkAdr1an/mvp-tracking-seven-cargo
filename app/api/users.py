from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import Permission, Principal, hash_password, require_permission
from app.storage.users import UserIdentity, UserRepository


router = APIRouter(prefix="/api/users", tags=["users"])
OfficialRole = Literal["ADMIN", "GR", "MONITORING"]


class UserCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=3, max_length=100)
    role: OfficialRole
    password: str = Field(min_length=12, max_length=500)


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: OfficialRole | None = None


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12, max_length=500)


def _repository() -> UserRepository:
    return UserRepository(get_settings().operations_database_path)


def _actor(principal: Principal) -> str:
    if principal.user_id is None:
        raise HTTPException(status_code=409, detail="Persistent administrator identity required")
    return principal.user_id


def _response(user: UserIdentity) -> dict[str, object]:
    return {
        "id": user.id, "username": user.username, "display_name": user.display_name,
        "role": user.role_code, "status": user.status, "created_at": user.created_at,
        "updated_at": user.updated_at,
        "permissions": sorted(user.permissions), "last_login": None,
    }


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="User not found")
    return HTTPException(status_code=409, detail=str(exc))


@router.get("")
async def list_users(
    principal: Principal = Depends(require_permission(Permission.USERS_READ)),
) -> dict[str, object]:
    _actor(principal)
    return {"users": [_response(user) for user in _repository().list_all()]}


@router.post("", status_code=201)
async def create_user(
    payload: UserCreateRequest,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    actor = _actor(principal)
    try:
        return _response(_repository().create(
            username=payload.username, display_name=payload.display_name,
            password_hash=hash_password(payload.password), role_code=payload.role,
            created_by_user_id=actor,
        ))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.patch("/{user_id}")
async def update_user(
    user_id: str, payload: UserUpdateRequest,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    actor, repository = _actor(principal), _repository()
    try:
        if payload.role is not None:
            repository.change_role(user_id, payload.role, actor)
        if payload.display_name is not None:
            repository.update_display_name(user_id, payload.display_name, actor)
        user = repository.by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return _response(user)
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: str, payload: PasswordResetRequest,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    try:
        return _response(_repository().change_password(
            user_id, hash_password(payload.password), _actor(principal)
        ))
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    try:
        return _response(_repository().inactivate(user_id, _actor(principal)))
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    try:
        return _response(_repository().activate(user_id, _actor(principal)))
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc
