from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Channel
from .serializers import ChannelSerializer, AvailabilitySlotSerializer
from integrations import bale_client
from django.shortcuts import get_object_or_404
import logging

logger = logging.getLogger(__name__)


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
    """ثبت کانال برای کاربر جاری.

    نام کاربری بله (مثل @link_yar) باید در توضیحات کانال باشد.
    """

    def post(self, request):
        user = request.user
        channel_link = request.data.get('channel_link')
        if not channel_link:
            return Response({'detail': 'channel_link required'}, status=status.HTTP_400_BAD_REQUEST)
        from bot_flow.handlers import bio_matches_owner, ownership_prompt

        if not getattr(user, 'bale_username', None):
            return Response({'ok': False, 'detail': ownership_prompt(user)}, status=status.HTTP_400_BAD_REQUEST)

        info = bale_client.get_channel_info(channel_link)
        if info.get('error'):
            return Response(
                {'ok': False, 'detail': 'نتوانستیم اطلاعات کانال را از بله بگیریم', 'error': info.get('error')},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        bio = info.get('bio') or info.get('description') or ''

        if not bio_matches_owner(str(bio), user):
            return Response(
                {'ok': False, 'detail': ownership_prompt(user)},
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
        try:
            from integrations.channel_stats import refresh_channel

            refresh_channel(ch)
        except Exception:
            logger.exception('stats after register failed')
        return Response({'ok': True, 'channel_id': ch.id, 'created': created})


class ChannelStatsView(APIView):
    """تاریخچهٔ برداشت لینک‌یار برای نمودار روند کانال."""

    def get(self, request, pk):
        channel = get_object_or_404(Channel, pk=pk)
        snaps = list(channel.stat_snapshots.order_by('-taken_at')[:90])
        snaps.reverse()
        return Response(
            {
                'channel_id': channel.id,
                'members': channel.members_count,
                'avg_views': channel.avg_views,
                'daily_reach': channel.daily_reach,
                'posts_per_day': channel.posts_per_day,
                'citation_index': channel.citation_index,
                'err_percent': channel.err_percent,
                'language': channel.language,
                'about': channel.about,
                'updated_at': channel.stats_updated_at,
                'history': [
                    {
                        'at': snap.taken_at,
                        'members': snap.members,
                        'views': snap.avg_views,
                        'daily_reach': snap.daily_reach,
                        'posts': snap.posts,
                        'forwards': snap.forwards,
                    }
                    for snap in snaps
                ],
            }
        )
