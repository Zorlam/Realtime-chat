from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Room, Message
from .serializers import RoomSerializer, MessageSerializer, UserSerializer

User = get_user_model()


class RoomListView(generics.ListAPIView):
    """Public/group rooms only — DMs are surfaced separately via /api/dms/."""
    queryset = Room.objects.filter(is_private=False)
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]


class UserListView(generics.ListAPIView):
    """GET /api/users/ — other users you can start a DM with."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.exclude(id=self.request.user.id).order_by("username")


class DMListView(generics.ListAPIView):
    """GET /api/dms/ — your existing 1:1 conversations."""
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Room.objects.filter(is_private=True, participants=self.request.user)


class StartDMView(APIView):
    """
    POST /api/dms/ {"username": "bob"} — finds the existing DM room between
    the current user and the named user, or creates one. Room names for DMs
    are derived deterministically from both user IDs (sorted, so it's the
    same regardless of who starts the conversation) rather than exposed as
    something guessable from usernames alone.
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
            defaults={"is_private": True},
        )
        if created:
            room.participants.set([request.user, other_user])

        return Response(
            RoomSerializer(room, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MessagePagination(CursorPagination):
    # Cursor pagination (vs. offset/limit) so results stay stable even as
    # new messages are added while someone scrolls up through history —
    # doing this now avoids the Phase 4 rework flagged earlier.
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

        # Private rooms: only participants may read history. Public rooms:
        # anyone authenticated can (matches the open-room model from Phase 1).
        if room.is_private and not room.participants.filter(id=self.request.user.id).exists():
            return Message.objects.none()

        return Message.objects.filter(room_id=room_id).order_by("-created_at")
