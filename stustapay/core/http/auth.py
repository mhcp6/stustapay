"""
asdf
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from abrechnung.application.users import UserService
from abrechnung.domain.users import User
from abrechnung.http.dependencies import get_user_service

logger = logging.getLogger(__name__)

REQUEST_AUTH_KEY = "user"
REQUEST_SESSION_KEY = "session_id"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")


# request handler dependencies

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
) -> User:
    try:
        return await user_service.get_user_from_token(token=token)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_session_id(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
) -> int:
    token_metadata = user_service.decode_jwt_payload(token)
    return token_metadata.session_id
"""
