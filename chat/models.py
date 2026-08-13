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

    # --- message requests ---
    # A new DM starts as a "request" from the recipient's perspective: the
    # initiator can use it normally, but the recipient sees it separately
    # and must accept before it behaves like a normal conversation. Public
    # rooms are unaffected — accepted defaults True and initiated_by stays
    # unset for those.
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Who started this DM — only set for private rooms.",
    )
    accepted = models.BooleanField(
        default=True,
        help_text="False for a new DM until the recipient accepts (or replies).",
    )

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
    # Soft delete — keeps the row (and its place in the conversation) so a
    # "this message was deleted" placeholder can render, rather than
    # leaving a confusing gap or shifting other messages' grouping.
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["room", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user}: {self.content[:30]}"
