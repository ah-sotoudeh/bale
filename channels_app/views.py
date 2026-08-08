from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Channel
from .serializers import ChannelSerializer, AvailabilitySlotSerializer
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
        if from_date:
            slots = slots.filter(end__gte=from_date)
        if to_date:
            slots = slots.filter(start__lte=to_date)
        serializer = AvailabilitySlotSerializer(slots, many=True)
        return Response(serializer.data)


class RegisterChannelView(APIView):
    """Register a channel as belonging to the current user.

    User must have bale_user_id set; that id must appear in the channel bio/description.
    """

    def post(self, request):
        user = request.user
        channel_link = request.data.get('channel_link')
        if not channel_link:
            return Response({'detail': 'channel_link required'}, status=status.HTTP_400_BAD_REQUEST)
        if not getattr(user, 'bale_user_id', None):
            return Response({'detail': 'user has no bale_user_id'}, status=status.HTTP_400_BAD_REQUEST)

        info = bale_client.get_channel_info(channel_link)
        if info.get('error'):
            return Response(
                {'ok': False, 'detail': 'نتوانستیم اطلاعات کانال را از بله بگیریم', 'error': info.get('error')},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        bio = info.get('bio') or info.get('description') or ''
        if str(user.bale_user_id) not in str(bio):
            return Response(
                {'ok': False, 'detail': 'لطفاً شناسه‌تان را در بیو کانال وارد کنید'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ch, created = Channel.objects.get_or_create(
            link=channel_link,
            defaults={'name': info.get('title') or '(no title)'},
        )
        if not created and not ch.name:
            ch.name = info.get('title') or ch.name
        ch.manager = user
        ch.save()
        return Response({'ok': True, 'channel_id': ch.id, 'created': created})
