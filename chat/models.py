from django.conf import settings
from django.db import models


class Room(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_private = models.BooleanField(default=False)  # True for 1:1 DMs
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="dm_rooms",
        blank=True,
        help_text="Only used for private (DM) rooms — restricts who can join.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ReadState(models.Model):
    """Tracks the last time a user read a given room — used to compute
    unread message counts (messages in the room newer than last_read_at,
    excluding the user's own)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    last_read_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "room")


class Message(models.Model):
    room = models.ForeignKey(Room, related_name="messages", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["room", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user}: {self.content[:30]}"