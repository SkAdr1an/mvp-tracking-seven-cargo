from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import Permission, Principal, hash_password, require_permission, verify_password
from app.storage.users import UserIdentity, UserRepository
from app.services.audit import AuditAction, AuditService


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

class PermanentDeleteRequest(BaseModel):
    creator_password: str = Field(min_length=1, max_length=500)


def _repository() -> UserRepository:
    return UserRepository(get_settings().operations_database_path)


def _audit(principal: Principal, action: AuditAction, user_id: str, *, before=None, after=None,
           connection=None) -> None:
    AuditService(get_settings().operations_database_path).record(
        principal, action, "user", resource_id=user_id, before=before, after=after,
        connection=connection,
    )


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
        return HTTPException(status_code=404, detail="Usuário não encontrado")
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
        user = _repository().create(
            username=payload.username, display_name=payload.display_name,
            password_hash=hash_password(payload.password), role_code=payload.role,
            created_by_user_id=actor,
            audit=lambda connection, created: _audit(
                principal, AuditAction.USER_CREATED, created.id,
                after={"username": created.username, "display_name": created.display_name,
                       "role": created.role_code, "status": created.status}, connection=connection),
        )
        result = _response(user)
        return result
    except ValueError as exc:
        raise _translate(exc) from exc


@router.patch("/{user_id}")
async def update_user(
    user_id: str, payload: UserUpdateRequest,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    actor, repository = _actor(principal), _repository()
    try:
        original = repository.by_id(user_id)
        if original is None:
            raise KeyError(user_id)
        if payload.role is not None:
            repository.change_role(user_id, payload.role, actor, audit=lambda connection, changed: _audit(
                principal, AuditAction.USER_ROLE_CHANGED, user_id,
                before={"role": original.role_code}, after={"role": changed.role_code},
                connection=connection))
        if payload.display_name is not None:
            repository.update_display_name(user_id, payload.display_name, actor,
                audit=lambda connection, changed: _audit(
                    principal, AuditAction.USER_UPDATED, user_id,
                    before={"display_name": original.display_name},
                    after={"display_name": changed.display_name}, connection=connection))
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
        user = _repository().change_password(
            user_id, hash_password(payload.password), _actor(principal),
            audit=lambda connection, changed: _audit(
                principal, AuditAction.USER_PASSWORD_RESET, user_id,
                after={"password_changed": True}, connection=connection),
        )
        return _response(user)
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    try:
        user = _repository().inactivate(user_id, _actor(principal),
            audit=lambda connection, changed: _audit(
                principal, AuditAction.USER_DEACTIVATED, user_id,
                before={"status": "ACTIVE"}, after={"status": changed.status},
                connection=connection))
        return _response(user)
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, object]:
    try:
        user = _repository().activate(user_id, _actor(principal),
            audit=lambda connection, changed: _audit(
                principal, AuditAction.USER_ACTIVATED, user_id,
                before={"status": "INACTIVE"}, after={"status": changed.status},
                connection=connection))
        return _response(user)
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc

@router.post("/{user_id}/permanent-delete")
async def permanently_delete_user(
    user_id: str, payload: PermanentDeleteRequest,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict[str, bool]:
    actor = _actor(principal)
    if actor == user_id:
        raise HTTPException(status_code=409, detail="Você não pode excluir permanentemente sua própria conta")
    configured_hash = get_settings().creator_delete_password_hash
    if not configured_hash or not verify_password(payload.creator_password, configured_hash):
        raise HTTPException(status_code=403, detail="Senha exclusiva de exclusão incorreta")
    repository = _repository()
    original = repository.by_id(user_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    try:
        repository.purge_permanently(
            user_id, audit=lambda connection: _audit(
                principal, AuditAction.USER_DELETED, user_id,
                before={"username": original.username, "display_name": original.display_name,
                        "role": original.role_code, "status": original.status},
                after={"permanently_deleted": True}, connection=connection),
        )
        return {"deleted": True}
    except (KeyError, ValueError) as exc:
        raise _translate(exc) from exc
