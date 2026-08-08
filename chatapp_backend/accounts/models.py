from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. We extend AbstractUser instead of rolling our own
    so we get Django's battle-tested password hashing, permissions system,
    and admin integration for free. Even if we don't need extra fields yet,
    starting with a custom user model means we're never stuck if we do
    later (swapping AUTH_USER_MODEL after the first migration is painful).
    """
    is_online = models.BooleanField(default=False)

    def __str__(self):
        return self.username
