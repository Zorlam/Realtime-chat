from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        # set_password hashes it — never store raw passwords
        user = User(username=validated_data["username"])
        user.set_password(validated_data["password"])
        user.save()
        return user


class ProfileSerializer(serializers.ModelSerializer):
    """Fuller user representation for profile pages — includes date_joined,
    which the chat app's compact UserSerializer omits since it's not
    needed in lists/pickers."""

    class Meta:
        model = User
        fields = ["id", "username", "is_online", "date_joined"]
