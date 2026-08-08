"""
Authenticates WebSocket connections using the same JWTs issued by the
REST login endpoint.

Flask-SocketIO handles auth via a handshake payload; Channels has no
built-in equivalent, so we read the token from the connection URL's
query string (e.g. ws://.../ws/chat/general/?token=<jwt>) and validate
it ourselves before the connection is accepted.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        access_token = AccessToken(token)
        user_id = access_token["user_id"]
        return User.objects.get(id=user_id)
    except (TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope["query_string"].decode())
        token = query_string.get("token", [None])[0]

        scope["user"] = (
            await get_user_from_token(token) if token else AnonymousUser()
        )
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
