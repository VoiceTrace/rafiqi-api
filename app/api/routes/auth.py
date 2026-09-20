from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse
from app.services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login",
    responses={
        200: {"description": "Successful login — returns a signed access token and a refresh token."},
        401: {
            "description": "Invalid credentials.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": {
                                "code": "unauthorized",
                                "message": "Invalid credentials",
                            }
                        }
                    }
                }
            },
        },
    },
)
async def login_route(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """
    Authenticate with email and password. Returns a signed access token plus a
    refresh token.

    The access token payload contains:
    - **sub** — user ID
    - **school_id** — the user's school (all data is scoped to this)
    - **role** — `teacher` or `student`
    - **exp** — expiry (`ACCESS_TOKEN_EXPIRE_MINUTES` from issue)

    Pass the access token in every subsequent request:
    ```
    Authorization: Bearer <access_token>
    ```

    When it expires, use `POST /auth/refresh` with the `refresh_token` to get a
    new pair without asking the user to log in again.
    """
    access_token, refresh_token = await auth_svc.login(body.email, body.password, db)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    responses={
        401: {"description": "Refresh token is invalid, expired, already used, or the account is inactive."},
    },
)
async def refresh_route(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """
    Exchange a refresh token for a new access/refresh token pair.

    Refresh tokens rotate on every use: the one you send is revoked and a new
    one is returned in its place. Reusing an already-exchanged (or logged-out)
    refresh token fails with 401.
    """
    access_token, refresh_token = await auth_svc.refresh_access_token(body.refresh_token, db)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/logout",
    status_code=204,
    summary="Logout",
    responses={204: {"description": "Refresh token revoked. Same response whether or not it was found."}},
)
async def logout_route(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """
    Revoke a refresh token so it can no longer be exchanged for a new access token.

    This does not invalidate an already-issued access token — it stays valid
    until it naturally expires (up to `ACCESS_TOKEN_EXPIRE_MINUTES`), which is
    why access tokens are kept short-lived. Always returns 204, whether or not
    the token was found, so the response never reveals whether it existed.
    """
    await auth_svc.logout(body.refresh_token, db)
