"""
ASGI config for config project.

Routes HTTP requests to Django as normal, and WebSocket connections
(ws://.../ws/...) through Channels to our consumers, with JWT auth
applied in the middleware stack below.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# get_asgi_application() must run before importing anything that touches
# models (routing -> consumers -> models), or Django raises
# AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from chat.jwt_auth_middleware import JWTAuthMiddlewareStack  # noqa: E402
from chat.routing import websocket_urlpatterns  # noqa: E402
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        JWTAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
