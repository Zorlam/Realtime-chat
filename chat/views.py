from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Room, Message, ReadState
from .serializers import RoomSerializer, MessageSerializer, UserSerializer, ProfileSerializer

User = get_user_model()


def notify_user(user_id):
    """Pings a user's always-on notification socket (see
    NotificationConsumer) so their sidebar refetches — used for anything
    that happens outside their own WebSocket action, e.g. someone else
    starting a DM with them, or a request being accepted/declined."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(f"notify_user_{user_id}", {"type": "conversation_update"})


class RoomListView(generics.ListAPIView):
    """Public/group rooms only — DMs are surfaced separately via /api/dms/."""
    queryset = Room.objects.filter(is_private=False)
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]


class UserListView(generics.ListAPIView):
    """GET /api/users/ — other users you can start a DM with.
    Supports ?search=<query> — an exact (case-insensitive) username match,
    optionally prefixed with "@" (stripped before matching)."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = User.objects.exclude(id=self.request.user.id)
        search = self.request.query_params.get("search")
        if search:
            search = search.lstrip("@").strip()
            qs = qs.filter(username__iexact=search) if search else qs.none()
        return qs.order_by("username")


class UserProfileView(generics.RetrieveAPIView):
    """GET /api/users/<id>/profile/ — another user's public profile."""
    queryset = User.objects.all()
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "user_id"


class DMListView(generics.ListAPIView):
    """GET /api/dms/ — your normal conversations: accepted DMs, plus any
    pending request YOU sent (you see your own outgoing request normally;
    it's the recipient who sees it separately as a request to respond to
    — see DMRequestListView)."""
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Room.objects.filter(is_private=True, participants=self.request.user).filter(
            Q(accepted=True) | Q(initiated_by=self.request.user)
        )


class DMRequestListView(generics.ListAPIView):
    """GET /api/dms/requests/ — pending DMs someone else started with you,
    that you haven't accepted yet."""
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Room.objects.filter(
            is_private=True, accepted=False, participants=self.request.user
        ).exclude(initiated_by=self.request.user)


class StartDMView(APIView):
    """
    POST /api/dms/start/ {"username": "bob"} — finds the existing DM room
    between the current user and the named user, or creates one. A new DM
    starts as a pending request (accepted=False) from the recipient's
    side; the initiator can use it normally right away.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        username = request.data.get("username")
        if not username:
            return Response({"detail": "username is required"}, status=status.HTTP_400_BAD_REQUEST)

        other_user = get_object_or_404(User, username=username)
        if other_user.id == request.user.id:
            return Response({"detail": "Can't start a DM with yourself"}, status=status.HTTP_400_BAD_REQUEST)

        ids = sorted([request.user.id, other_user.id])
        room_name = f"dm-{ids[0]}-{ids[1]}"

        room, created = Room.objects.get_or_create(
            name=room_name,
            defaults={"is_private": True, "initiated_by": request.user, "accepted": False},
        )
        if created:
            room.participants.set([request.user, other_user])
            notify_user(other_user.id)  # so it shows up in their requests without a refresh

        return Response(
            RoomSerializer(room, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AcceptDMRequestView(APIView):
    """POST /api/dms/<room_id>/accept/ — accepts a pending message request."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id, is_private=True)
        if not room.participants.filter(id=request.user.id).exists():
            return Response({"detail": "Not a participant"}, status=status.HTTP_403_FORBIDDEN)
        if room.initiated_by_id == request.user.id:
            return Response({"detail": "Can't accept your own request"}, status=status.HTTP_400_BAD_REQUEST)

        room.accepted = True
        room.save(update_fields=["accepted"])
        if room.initiated_by_id:
            notify_user(room.initiated_by_id)

        return Response(RoomSerializer(room, context={"request": request}).data)


class DeclineDMRequestView(APIView):
    """POST /api/dms/<room_id>/decline/ — declines and deletes a pending
    message request (and its messages, via cascade)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id, is_private=True)
        if not room.participants.filter(id=request.user.id).exists():
            return Response({"detail": "Not a participant"}, status=status.HTTP_403_FORBIDDEN)
        if room.initiated_by_id == request.user.id:
            return Response({"detail": "Can't decline your own request"}, status=status.HTTP_400_BAD_REQUEST)

        initiator_id = room.initiated_by_id
        room.delete()
        if initiator_id:
            notify_user(initiator_id)

        return Response(status=status.HTTP_204_NO_CONTENT)


class MessagePagination(CursorPagination):
    page_size = 30
    ordering = "-created_at"


class RoomMessageListView(generics.ListAPIView):
    """GET /api/rooms/<room_id>/messages/ — history to load when a user joins a room."""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MessagePagination

    def get_queryset(self):
        room_id = self.kwargs["room_id"]
        room = get_object_or_404(Room, id=room_id)

        if room.is_private and not room.participants.filter(id=self.request.user.id).exists():
            return Message.objects.none()

        return Message.objects.filter(room_id=room_id).order_by("-created_at")


class MarkRoomReadView(APIView):
    """POST /api/rooms/<room_id>/read/ — updates (or creates) the current
    user's read marker for this room to now, clearing its unread count."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        read_state, _ = ReadState.objects.get_or_create(user=request.user, room=room)
        read_state.save()
        return Response({"last_read_at": read_state.last_read_at})
