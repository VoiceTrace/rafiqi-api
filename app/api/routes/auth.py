from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login",
    responses={
        200: {"description": "Successful login — returns a signed JWT valid for 6 hours."},
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
    Authenticate with email and password. Returns a signed JWT.

    The token payload contains:
    - **sub** — user ID
    - **school_id** — the user's school (all data is scoped to this)
    - **role** — `teacher` or `student`
    - **exp** — expiry (6 hours from issue)

    Pass the token in every subsequent request:
    ```
    Authorization: Bearer <access_token>
    ```
    """
    token = await login(body.email, body.password, db)
    return TokenResponse(access_token=token)
