from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Channel
from .serializers import ChannelSerializer
from integrations import bale_client
from django.shortcuts import get_object_or_404

class ChannelListView(generics.ListAPIView):
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer

class ChannelAvailabilityView(APIView):
    def get(self, request, pk):
        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')
        channel = get_object_or_404(Channel, pk=pk)
        slots = channel.availability.all()
        # Optional: filter by range
        serializer = AvailabilitySlotSerializer(slots, many=True)
        return Response(serializer.data)

class RegisterChannelView(APIView):
    """Allow a user to register a channel as theirs. The user must have bale_user_id set and it must appear in channel bio."""
    def post(self, request):
        # expected payload: {"channel_link": "..."}
        user = request.user
        channel_link = request.data.get('channel_link')
        if not user.bale_user_id:
            return Response({'detail':'user has no bale_user_id'}, status=status.HTTP_400_BAD_REQUEST)
        # fetch channel info from Bale
        info = bale_client.get_channel_info(channel_link)
        bio = info.get('bio','') if info else ''
        if user.bale_user_id in bio:
            # register channel locally
            ch, created = Channel.objects.get_or_create(link=channel_link, defaults={'name': info.get('title','(no title)')})
            ch.manager = user
            ch.save()
            return Response({'ok':True, 'channel_id': ch.id})
        else:
            return Response({'ok':False, 'detail':'لطفاً شناسه‌تان را در بیو کانال وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
