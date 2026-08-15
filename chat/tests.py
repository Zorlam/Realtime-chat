import asyncio
from unittest.mock import AsyncMock, patch

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from config.asgi import application
from .models import Room, Message, ReadState

User = get_user_model()


# ---------------------------------------------------------------------------
# REST API tests
# ---------------------------------------------------------------------------
# CHANNEL_LAYERS is overridden to the in-memory backend for all REST tests
# because a few views (StartDMView, Accept/DeclineDMRequestView) push a
# live notification through the channel layer as a side effect — using
# the in-memory layer here means these tests don't need a real Redis
# instance running, same as they wouldn't in CI.

@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class RoomListViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")
        self.client.force_authenticate(user=self.user)

    def test_lists_only_public_rooms(self):
        Room.objects.create(name="Public", is_private=False)
        Room.objects.create(name="dm-1-2", is_private=True)

        response = self.client.get("/api/rooms/")
        names = [r["name"] for r in response.data]
        self.assertIn("Public", names)
        self.assertNotIn("dm-1-2", names)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class UserSearchTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")
        User.objects.create_user(username="lazzar", password="testpass123")
        self.client.force_authenticate(user=self.user)

    def test_partial_query_returns_nothing(self):
        response = self.client.get("/api/users/?search=l")
        self.assertEqual(len(response.data), 0)

    def test_exact_username_matches(self):
        response = self.client.get("/api/users/?search=lazzar")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["username"], "lazzar")

    def test_at_prefix_is_stripped(self):
        response = self.client.get("/api/users/?search=@lazzar")
        self.assertEqual(len(response.data), 1)

    def test_search_is_case_insensitive(self):
        response = self.client.get("/api/users/?search=LAZZAR")
        self.assertEqual(len(response.data), 1)

    def test_excludes_self(self):
        response = self.client.get("/api/users/?search=alice")
        self.assertEqual(len(response.data), 0)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class UserProfileViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")
        self.other = User.objects.create_user(username="bob", password="testpass123")
        self.client.force_authenticate(user=self.user)

    def test_returns_profile_with_join_date(self):
        response = self.client.get(f"/api/users/{self.other.id}/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "bob")
        self.assertIn("date_joined", response.data)

    def test_404_for_nonexistent_user(self):
        response = self.client.get("/api/users/99999/profile/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class StartDMViewTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="testpass123")
        self.bob = User.objects.create_user(username="bob", password="testpass123")
        self.client.force_authenticate(user=self.alice)

    def test_creates_pending_room(self):
        response = self.client.post("/api/dms/start/", {"username": "bob"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        room = Room.objects.get(id=response.data["id"])
        self.assertTrue(room.is_private)
        self.assertFalse(room.accepted)
        self.assertEqual(room.initiated_by, self.alice)
        self.assertCountEqual(room.participants.all(), [self.alice, self.bob])

    def test_calling_again_returns_existing_room(self):
        first = self.client.post("/api/dms/start/", {"username": "bob"})
        second = self.client.post("/api/dms/start/", {"username": "bob"})
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])

    def test_cannot_dm_self(self):
        response = self.client.post("/api/dms/start/", {"username": "alice"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class DMRequestLifecycleTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="testpass123")
        self.bob = User.objects.create_user(username="bob", password="testpass123")
        self.room = Room.objects.create(
            name="dm-1-2", is_private=True, initiated_by=self.alice, accepted=False
        )
        self.room.participants.set([self.alice, self.bob])

    def test_recipient_sees_it_as_a_request_not_a_normal_dm(self):
        self.client.force_authenticate(user=self.bob)
        self.assertEqual(len(self.client.get("/api/dms/").data), 0)

        requests = self.client.get("/api/dms/requests/").data
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0]["is_pending_request"])

    def test_initiator_sees_it_normally_not_as_a_request(self):
        self.client.force_authenticate(user=self.alice)
        dms = self.client.get("/api/dms/").data
        self.assertEqual(len(dms), 1)
        self.assertFalse(dms[0]["is_pending_request"])

    def test_initiator_cannot_accept_own_request(self):
        self.client.force_authenticate(user=self.alice)
        response = self.client.post(f"/api/dms/{self.room.id}/accept/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_recipient_can_accept(self):
        self.client.force_authenticate(user=self.bob)
        response = self.client.post(f"/api/dms/{self.room.id}/accept/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.room.refresh_from_db()
        self.assertTrue(self.room.accepted)

    def test_recipient_can_decline_and_room_is_deleted(self):
        self.client.force_authenticate(user=self.bob)
        response = self.client.post(f"/api/dms/{self.room.id}/decline/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Room.objects.filter(id=self.room.id).exists())

    def test_non_participant_cannot_accept_or_decline(self):
        outsider = User.objects.create_user(username="charlie", password="testpass123")
        self.client.force_authenticate(user=outsider)
        response = self.client.post(f"/api/dms/{self.room.id}/accept/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class RoomMessagePrivacyTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="testpass123")
        self.bob = User.objects.create_user(username="bob", password="testpass123")
        self.outsider = User.objects.create_user(username="charlie", password="testpass123")
        self.room = Room.objects.create(name="dm-1-2", is_private=True)
        self.room.participants.set([self.alice, self.bob])
        Message.objects.create(room=self.room, user=self.alice, content="hello")

    def test_participant_can_read_history(self):
        self.client.force_authenticate(user=self.bob)
        response = self.client.get(f"/api/rooms/{self.room.id}/messages/")
        self.assertEqual(len(response.data["results"]), 1)

    def test_non_participant_cannot_read_history(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/api/rooms/{self.room.id}/messages/")
        self.assertEqual(len(response.data["results"]), 0)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class UnreadCountTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="testpass123")
        self.bob = User.objects.create_user(username="bob", password="testpass123")
        self.room = Room.objects.create(name="dm-1-2", is_private=True, accepted=True)
        self.room.participants.set([self.alice, self.bob])
        Message.objects.create(room=self.room, user=self.bob, content="hi alice")
        self.client.force_authenticate(user=self.alice)

    def test_unread_count_before_and_after_marking_read(self):
        dms = self.client.get("/api/dms/").data
        self.assertEqual(dms[0]["unread_count"], 1)

        self.client.post(f"/api/rooms/{self.room.id}/read/")

        dms = self.client.get("/api/dms/").data
        self.assertEqual(dms[0]["unread_count"], 0)

    def test_own_messages_never_count_as_unread(self):
        Message.objects.create(room=self.room, user=self.alice, content="my own message")
        dms = self.client.get("/api/dms/").data
        # Still 1 — the one from bob, not the one alice just sent herself.
        self.assertEqual(dms[0]["unread_count"], 1)


# ---------------------------------------------------------------------------
# WebSocket consumer tests
# ---------------------------------------------------------------------------
# presence.mark_connected/mark_disconnected are patched out with AsyncMock
# rather than hitting real Redis — these tests should be able to run
# anywhere (including CI) without a Redis instance available, same
# reasoning as the CHANNEL_LAYERS override above.

def make_token(user):
    return str(AccessToken.for_user(user))


def ws_communicator(path):
    """WebsocketCommunicator doesn't send an Origin header by default, and
    AllowedHostsOriginValidator (in config/asgi.py) rejects connections
    that lack one — same thing we hit with manual test scripts earlier in
    the project. Every communicator that's expected to actually connect
    needs this."""
    return WebsocketCommunicator(application, path, headers=[(b"origin", b"http://localhost:3000")])


async def drain(communicator, timeout=0.2):
    """Receives and discards whatever's currently queued. NOTE: only safe
    to use on a communicator you're done with (e.g. right before
    disconnecting it) — timing out here tears down the consumer's
    underlying task in this library version, so a communicator you still
    need to send/receive on afterward should use an exact receive count
    instead (see test_sender_can_delete_own_message_others_cannot)."""
    drained = []
    while True:
        try:
            drained.append(await communicator.receive_json_from(timeout=timeout))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break
    return drained


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class ChatConsumerTests(TransactionTestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="testpass123")
        self.bob = User.objects.create_user(username="bob", password="testpass123")
        self.room = Room.objects.create(name="Public", is_private=False)

    @patch("chat.presence.mark_connected", new_callable=AsyncMock, return_value=True)
    @patch("chat.presence.mark_disconnected", new_callable=AsyncMock, return_value=True)
    async def test_unauthenticated_connection_is_rejected(self, mock_disc, mock_conn):
        communicator = WebsocketCommunicator(application, "/ws/chat/Public/")
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    @patch("chat.presence.mark_connected", new_callable=AsyncMock, return_value=True)
    @patch("chat.presence.mark_disconnected", new_callable=AsyncMock, return_value=True)
    async def test_authenticated_user_can_connect_and_send_message(self, mock_disc, mock_conn):
        token = make_token(self.alice)
        communicator = ws_communicator(f"/ws/chat/Public/?token={token}")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # own user_joined event
        await communicator.receive_json_from()  # own presence (online) event

        await communicator.send_json_to({"content": "hello everyone"})
        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "message")
        self.assertEqual(response["content"], "hello everyone")
        self.assertEqual(response["username"], "alice")

        await communicator.disconnect()

    @patch("chat.presence.mark_connected", new_callable=AsyncMock, return_value=True)
    @patch("chat.presence.mark_disconnected", new_callable=AsyncMock, return_value=True)
    async def test_non_participant_rejected_from_private_room(self, mock_disc, mock_conn):
        private_room = await self._create_private_room_for_alice_only()
        token = make_token(self.bob)  # bob is NOT a participant
        communicator = ws_communicator(f"/ws/chat/{private_room.name}/?token={token}")
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    @patch("chat.presence.mark_connected", new_callable=AsyncMock, return_value=True)
    @patch("chat.presence.mark_disconnected", new_callable=AsyncMock, return_value=True)
    async def test_sender_can_delete_own_message_others_cannot(self, mock_disc, mock_conn):
        # Receiving with a timeout (as drain() does) turns out to tear
        # down the underlying consumer task in this library version, so
        # for a communicator that's still going to be used afterward, we
        # receive an exact known count instead of timeout-draining.
        token_alice = make_token(self.alice)
        token_bob = make_token(self.bob)

        alice_ws = ws_communicator(f"/ws/chat/Public/?token={token_alice}")
        await alice_ws.connect()
        await alice_ws.receive_json_from()  # alice's own user_joined
        await alice_ws.receive_json_from()  # alice's own presence (online)

        bob_ws = ws_communicator(f"/ws/chat/Public/?token={token_bob}")
        await bob_ws.connect()
        await bob_ws.receive_json_from()   # bob's own user_joined
        await bob_ws.receive_json_from()   # bob's own presence (online)
        await alice_ws.receive_json_from()  # alice sees bob join
        await alice_ws.receive_json_from()  # alice sees bob come online

        await alice_ws.send_json_to({"content": "delete me"})
        alice_msg = await alice_ws.receive_json_from()
        await bob_ws.receive_json_from()  # bob sees the message too
        message_id = alice_msg["id"]

        # bob (not the sender) tries to delete it — should have no effect,
        # and no event is broadcast for a failed delete at all.
        await bob_ws.send_json_to({"type": "delete_message", "message_id": message_id})

        # alice (the actual sender) deletes it
        await alice_ws.send_json_to({"type": "delete_message", "message_id": message_id})
        deleted_event = await alice_ws.receive_json_from()
        self.assertEqual(deleted_event["event"], "message_deleted")
        self.assertEqual(deleted_event["id"], message_id)

        bob_deleted_event = await bob_ws.receive_json_from()
        self.assertEqual(bob_deleted_event["event"], "message_deleted")

        await alice_ws.disconnect()
        await bob_ws.disconnect()

        message = await Message.objects.aget(id=message_id)
        self.assertTrue(message.is_deleted)
        self.assertEqual(message.content, "")

    async def _create_private_room_for_alice_only(self):
        room = await Room.objects.acreate(name="dm-1-3", is_private=True)
        await room.participants.aadd(self.alice)
        return room
