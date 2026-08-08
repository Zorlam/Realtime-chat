import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class ChatConsumer(AsyncWebsocketConsumer):
    """
    One consumer instance per connected client. `room_group_name` maps to
    a Channels "group" — Channels' equivalent of a Socket.IO room — which
    is how we broadcast a message from one client to everyone else in the
    same room (and, in Phase 5, across server processes via the Redis
    channel layer).
    """

    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"
        self.user = self.scope["user"]

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)  # unauthorized
            return

        room_exists = await self.room_exists(self.room_name)
        if not room_exists:
            await self.close(code=4004)  # room not found
            return

        is_authorized = await self.user_can_access_room(self.room_name, self.user)
        if not is_authorized:
            await self.close(code=4003)  # forbidden — not a participant in this private room
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_joined",
                "username": self.user.username,
            },
        )

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            if self.user and self.user.is_authenticated:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "user_left",
                        "username": self.user.username,
                    },
                )

    async def receive(self, text_data):
        data = json.loads(text_data)
        content = data.get("content", "").strip()
        if not content:
            return

        message = await self.save_message(self.room_name, self.user, content)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "id": message.id,
                "username": self.user.username,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            },
        )

    # --- group event handlers ---
    # Each of these corresponds to a "type" sent via group_send above,
    # and pushes that event down to this consumer's own client socket.

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "event": "message",
            "id": event["id"],
            "username": event["username"],
            "content": event["content"],
            "created_at": event["created_at"],
        }))

    async def user_joined(self, event):
        await self.send(text_data=json.dumps({
            "event": "user_joined",
            "username": event["username"],
        }))

    async def user_left(self, event):
        await self.send(text_data=json.dumps({
            "event": "user_left",
            "username": event["username"],
        }))

    # --- DB helpers ---
    # Consumer methods are async, but the ORM isn't, so DB calls are
    # wrapped with database_sync_to_async.

    @database_sync_to_async
    def room_exists(self, room_name):
        from chat.models import Room
        return Room.objects.filter(name=room_name).exists()

    @database_sync_to_async
    def user_can_access_room(self, room_name, user):
        from chat.models import Room
        room = Room.objects.get(name=room_name)
        if not room.is_private:
            return True
        return room.participants.filter(id=user.id).exists()

    @database_sync_to_async
    def save_message(self, room_name, user, content):
        from chat.models import Room, Message
        room = Room.objects.get(name=room_name)
        return Message.objects.create(room=room, user=user, content=content)
