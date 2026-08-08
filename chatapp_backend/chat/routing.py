from django.urls import re_path

from chat.consumers import ChatConsumer

websocket_urlpatterns = [
    # room_name allows word characters and hyphens — plain rooms use names
    # like "Public", DM rooms use generated names like "dm-1-2".
    re_path(r"ws/chat/(?P<room_name>[\w-]+)/$", ChatConsumer.as_asgi()),
]
