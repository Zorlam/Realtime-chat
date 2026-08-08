from django.contrib.auth import get_user_model
from rest_framework import serializers

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

    class Meta:
        model = Room
        fields = ["id", "name", "is_private", "created_at", "other_participant", "unread_count"]

    def get_other_participant(self, room):
        if not room.is_private:
            return None
        request = self.context.get("request")
        if not request:
            return None
        other = room.participants.exclude(id=request.user.id).first()
        return UserSerializer(other).data if other else None

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
