from django.urls import path
from . import views

urlpatterns = [
    path('channels/', views.ChannelListView.as_view(), name='channels-list'),
    path('channels/<int:pk>/availability/', views.ChannelAvailabilityView.as_view(), name='channel-availability'),
]
