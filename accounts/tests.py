from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class RegisterViewTests(APITestCase):
    def test_register_creates_user_with_hashed_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "alice", "password": "testpass123"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(username="alice")
        # The raw password should never be stored as-is.
        self.assertNotEqual(user.password, "testpass123")
        self.assertTrue(user.check_password("testpass123"))

    def test_register_rejects_short_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "alice", "password": "short"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_duplicate_username(self):
        User.objects.create_user(username="alice", password="testpass123")
        response = self.client.post(
            "/api/auth/register/",
            {"username": "alice", "password": "testpass123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")

    def test_login_returns_access_and_refresh_tokens(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "alice", "password": "testpass123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "alice", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MeViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")

    def test_me_requires_authentication(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_own_profile(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "alice")
        self.assertIn("date_joined", response.data)


class ThrottlingTests(APITestCase):
    """DRF throttle state lives in the cache, which persists across tests
    within the same run — clearing it before/after each test keeps these
    isolated from each other and from unrelated tests hitting the same
    endpoints."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_login_is_throttled_after_repeated_attempts(self):
        User.objects.create_user(username="alice", password="testpass123")

        # 'login' scope is set to 5/min in settings — the first 5 should
        # go through (regardless of whether the credentials are right),
        # the 6th should be blocked by the throttle itself.
        for _ in range(5):
            response = self.client.post(
                "/api/auth/login/", {"username": "alice", "password": "wrongpassword"}
            )
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        response = self.client.post(
            "/api/auth/login/", {"username": "alice", "password": "wrongpassword"}
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_register_is_throttled_after_repeated_attempts(self):
        # 'register' scope is 3/min.
        for i in range(3):
            response = self.client.post(
                "/api/auth/register/", {"username": f"user{i}", "password": "testpass123"}
            )
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        response = self.client.post(
            "/api/auth/register/", {"username": "user_over_limit", "password": "testpass123"}
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
