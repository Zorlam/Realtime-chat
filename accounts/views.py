from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, ProfileSerializer
from .throttles import RegisterRateThrottle, LoginRateThrottle


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterRateThrottle]


class LoginView(TokenObtainPairView):
    """Same as simplejwt's TokenObtainPairView, just with a strict
    per-IP throttle — this is the main brute-force protection point."""
    throttle_classes = [LoginRateThrottle]


class MeView(APIView):
    """Returns the logged-in user's own profile."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(ProfileSerializer(request.user).data)
