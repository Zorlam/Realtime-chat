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
    other_participant = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_last_read = serializers.SerializerMethodField()
    # Whether the requesting user still needs to accept this DM as a
    # message request — always False for public rooms, and False for the
    # person who started the DM (they don't "request" their own message).
    is_pending_request = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = [
            "id", "name", "is_private", "created_at",
            "other_participant", "unread_count", "other_last_read",
            "is_pending_request",
        ]

    def get_other_participant(self, room):
        if not room.is_private:
            return None
        request = self.context.get("request")
        if not request:
            return None
        other = room.participants.exclude(id=request.user.id).first()
        return UserSerializer(other).data if other else None

    def get_other_last_read(self, room):
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

    def get_is_pending_request(self, room):
        if not room.is_private or room.accepted:
            return False
        request = self.context.get("request")
        if not request:
            return False
        return room.initiated_by_id != request.user.id


class MessageSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    deleted = serializers.BooleanField(source="is_deleted", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "room", "user", "username", "content", "created_at", "deleted"]
        read_only_fields = ["user"]
