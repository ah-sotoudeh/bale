from rest_framework import generics
from .models import Channel, AvailabilitySlot
from .serializers import ChannelSerializer, AvailabilitySlotSerializer
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

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
