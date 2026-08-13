from django.urls import re_path

from chat.consumers import ChatConsumer, NotificationConsumer

websocket_urlpatterns = [
    # room_name allows word characters and hyphens — plain rooms use names
    # like "Public", DM rooms use generated names like "dm-1-2".
    re_path(r"ws/chat/(?P<room_name>[\w-]+)/$", ChatConsumer.as_asgi()),
    # Always-on per-user channel for cross-conversation live updates.
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
]
