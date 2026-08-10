from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.serializers import ProfileSerializer  # re-exported for chat/views.py
from .models import Room, Message, ReadState

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "is_online"]


class RoomSerializer(serializers.ModelSerializer):
    # For private (DM) rooms, surface the *other* participant so the
    # frontend can show "Bob" instead of the internal room name like
    # "dm-1-2" — the room name stays an implementation detail.
    other_participant = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_last_read = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "name", "is_private", "created_at", "other_participant", "unread_count", "other_last_read"]

    def get_other_participant(self, room):
        if not room.is_private:
            return None
        request = self.context.get("request")
        if not request:
            return None
        other = room.participants.exclude(id=request.user.id).first()
        return UserSerializer(other).data if other else None

    def get_other_last_read(self, room):
        # When the other DM participant last read this room — lets the
        # frontend show "Seen" under the last message they've actually
        # read, iMessage-style, without waiting for a live event.
        if not room.is_private:
            return None
        request = self.context.get("request")
        if not request:
            return None
        other = room.participants.exclude(id=request.user.id).first()
        if not other:
            return None
        read_state = ReadState.objects.filter(user=other, room=room).first()
        return read_state.last_read_at if read_state else None

    def get_unread_count(self, room):
        request = self.context.get("request")
        if not request:
            return 0

        read_state = ReadState.objects.filter(user=request.user, room=room).first()
        qs = Message.objects.filter(room=room).exclude(user=request.user)
        if read_state:
            qs = qs.filter(created_at__gt=read_state.last_read_at)
        return qs.count()


class MessageSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "room", "user", "username", "content", "created_at"]
        read_only_fields = ["user"]
