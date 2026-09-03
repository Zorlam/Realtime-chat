import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from chat import presence


class ChatConsumer(AsyncWebsocketConsumer):
    """
    One consumer instance per connected client. `room_group_name` maps to
    a Channels "group" — Channels' equivalent of a Socket.IO room — which
    is how we broadcast a message from one client to everyone else in the
    same room (and, in Phase 5, across server processes via the Redis
    channel layer).

    This consumer only reaches clients who currently have this specific
    room open. See NotificationConsumer below for the separate, always-on
    per-user channel that lets a person's sidebar/unread badges update
    even for conversations they don't have open right now.
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

        just_came_online = await presence.mark_connected(self.user.id)
        if just_came_online:
            await self.set_online_state(self.user, True)
            await self.channel_layer.group_send(
                self.room_group_name,
                {"type": "presence_update", "username": self.user.username, "is_online": True},
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

                just_went_offline = await presence.mark_disconnected(self.user.id)
                if just_went_offline:
                    await self.set_online_state(self.user, False)
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {"type": "presence_update", "username": self.user.username, "is_online": False},
                    )

    async def receive(self, text_data):
        data = json.loads(text_data)
        print("WEBSOCKET RECEIVED:", data, flush=True)
        
        if data.get("type") == "ping":
            # Heartbeat — answered directly, not broadcast to the room.
            # Lets the client detect a "zombie" connection (socket still
            # reports OPEN, but nothing's actually getting through — can
            # happen behind certain proxies/NAT timeouts) faster than
            # waiting on a TCP-level timeout.
            await self.send(text_data=json.dumps({"event": "pong"}))
            return

        if data.get("type") == "typing":
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing_update",
                    "username": self.user.username,
                    "is_typing": bool(data.get("is_typing")),
                    "sender_channel": self.channel_name,
                },
            )
            return

        if data.get("type") == "read":
            last_read_at = await self.mark_read(self.room_name, self.user)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "read_update",
                    "username": self.user.username,
                    "last_read_at": last_read_at.isoformat(),
                    "sender_channel": self.channel_name,
                },
            )
            return

        if data.get("type") == "delete_message":
            message_id = data.get("message_id")
            deleted = await self.delete_message(message_id, self.user)
            if deleted:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {"type": "message_deleted_update", "id": message_id},
                )
            return

        content = data.get("content", "").strip()
        if not content:
            return

        message, other_participant_ids = await self.save_message(self.room_name, self.user, content)

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

        # Notify the other participant(s) even if they don't have this
        # room open right now — this is what makes a brand-new DM (or any
        # message in a conversation you haven't opened) actually show up
        # without needing a page refresh.
        for user_id in other_participant_ids:
            await self.channel_layer.group_send(
                f"notify_user_{user_id}",
                {"type": "conversation_update"},
            )

    # --- group event handlers ---

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "event": "message",
            "id": event["id"],
            "username": event["username"],
            "content": event["content"],
            "created_at": event["created_at"],
            "deleted": False,
        }))

    async def message_deleted_update(self, event):
        await self.send(text_data=json.dumps({
            "event": "message_deleted",
            "id": event["id"],
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

    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            "event": "presence",
            "username": event["username"],
            "is_online": event["is_online"],
        }))

    async def typing_update(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send(text_data=json.dumps({
            "event": "typing",
            "username": event["username"],
            "is_typing": event["is_typing"],
        }))

    async def read_update(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send(text_data=json.dumps({
            "event": "read",
            "username": event["username"],
            "last_read_at": event["last_read_at"],
        }))

    # --- DB helpers ---

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
        message = Message.objects.create(room=room, user=user, content=content)

        # A reply from the recipient of a pending message request counts
        # as accepting it — no separate "accept" click needed once they've
        # engaged with the conversation.
        if room.is_private and not room.accepted and room.initiated_by_id != user.id:
            room.accepted = True
            room.save(update_fields=["accepted"])

        other_ids = []
        if room.is_private:
            other_ids = list(room.participants.exclude(id=user.id).values_list("id", flat=True))

        return message, other_ids

    @database_sync_to_async
    def delete_message(self, message_id, user):
        from chat.models import Message
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return False
        if message.user_id != user.id:
            return False  # only the sender can delete their own message
        message.is_deleted = True
        message.content = ""
        message.save(update_fields=["is_deleted", "content"])
        return True

    @database_sync_to_async
    def set_online_state(self, user, is_online):
        user.is_online = is_online
        user.save(update_fields=["is_online"])

    @database_sync_to_async
    def mark_read(self, room_name, user):
        from chat.models import Room, ReadState
        room = Room.objects.get(name=room_name)
        read_state, _ = ReadState.objects.get_or_create(user=user, room=room)
        read_state.save()
        return read_state.last_read_at


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    A separate, always-on connection per logged-in user (not per-room).
    Unlike ChatConsumer, which a client only connects to for whichever
    room is currently open, this one stays connected for as long as the
    app is open, so the sidebar (unread badges, new DMs, message requests)
    can update live regardless of what's currently on screen.
    """

    async def connect(self):
        self.user = self.scope["user"]
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.group_name = f"notify_user_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if data.get("type") == "ping":
            await self.send(text_data=json.dumps({"event": "pong"}))

    async def conversation_update(self, event):
        # Deliberately minimal payload — the frontend just re-fetches its
        # room/DM lists on receiving this, rather than duplicating
        # serialization logic here.
        await self.send(text_data=json.dumps({"event": "update"}))
