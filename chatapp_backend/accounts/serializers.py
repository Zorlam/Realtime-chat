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
