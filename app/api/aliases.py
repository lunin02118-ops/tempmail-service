from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import AppSettings
from app.repositories.aliases import AliasRepository
from app.schemas.alias import AliasCreateRequest, AliasResponse
from app.services.alias_service import generate_alias_local_part, normalize_alias_email

router = APIRouter()


def get_alias_repository(settings: AppSettings = Depends(AppSettings.from_env)) -> AliasRepository:
    return AliasRepository(settings)


def get_settings() -> AppSettings:
    return AppSettings.from_env()


def require_alias_api_token(
    settings: AppSettings = Depends(get_settings),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    expected_token = settings.alias_api_token
    if not expected_token:
        return

    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()

    provided_token = bearer_token or x_api_key
    if provided_token != expected_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid alias api token")


@router.post("/aliases", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
def create_alias(
    request: AliasCreateRequest,
    settings: AppSettings = Depends(get_settings),
    repo: AliasRepository = Depends(get_alias_repository),
    _: None = Depends(require_alias_api_token),
) -> AliasResponse:
    if not settings.default_from_alias_domain:
        raise HTTPException(status_code=500, detail="DEFAULT_FROM_ALIAS_DOMAIN is not configured")

    for _ in range(10):
        local_part = generate_alias_local_part(request.local_part_length)
        alias_email = normalize_alias_email(local_part, settings.default_from_alias_domain)
        if repo.get_by_alias_email(alias_email) is None:
            alias_id = repo.create_alias(
                alias_local_part=local_part,
                alias_email=alias_email,
                telegram_chat_id=request.telegram_chat_id,
                telegram_user_id=request.telegram_user_id,
                description=request.description,
            )
            return AliasResponse(
                id=alias_id,
                alias_local_part=local_part,
                alias_email=alias_email,
                telegram_chat_id=request.telegram_chat_id,
                telegram_user_id=request.telegram_user_id,
                description=request.description,
                is_active=True,
            )

    raise HTTPException(status_code=500, detail="failed to generate unique alias")


@router.get("/aliases", response_model=list[AliasResponse])
def list_aliases(
    repo: AliasRepository = Depends(get_alias_repository),
    _: None = Depends(require_alias_api_token),
) -> list[AliasResponse]:
    rows = repo.list_aliases()
    return [
        AliasResponse(
            id=int(row["id"]),
            alias_local_part=str(row["alias_local_part"]),
            alias_email=str(row["alias_email"]),
            telegram_chat_id=str(row["telegram_chat_id"]),
            telegram_user_id=str(row["telegram_user_id"]) if row["telegram_user_id"] is not None else None,
            description=str(row["description"]) if row["description"] is not None else None,
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]
