from django.urls import path

from .views import RoomListView, RoomMessageListView, UserListView, DMListView, StartDMView

urlpatterns = [
    path("rooms/", RoomListView.as_view(), name="room-list"),
    path("rooms/<int:room_id>/messages/", RoomMessageListView.as_view(), name="room-messages"),
    path("users/", UserListView.as_view(), name="user-list"),
    path("dms/", DMListView.as_view(), name="dm-list"),          # GET
    path("dms/start/", StartDMView.as_view(), name="dm-start"),  # POST
]
