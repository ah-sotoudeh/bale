from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from users.models import User
from channels_app.models import Channel, Tariff
from orders.models import Order, OrderItem
from unittest.mock import patch
from django.utils import timezone
import datetime

class OrdersWebhookFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # create customer and manager users
        self.customer = User.objects.create_user(username='cust', password='pass')
        self.customer.bale_user_id = 'cust-bale-1'
        self.customer.save()
        self.manager = User.objects.create_user(username='mgr', password='pass')
        self.manager.bale_user_id = '897950525'
        self.manager.save()
        # create channel and tariff
        self.channel = Channel.objects.create(name='testchan', link='@testchan', manager=self.manager)
        self.tariff = Tariff.objects.create(channel=self.channel, name='12h', duration_hours=12, price=1000)
        # create an order with one item
        order = Order.objects.create(customer=self.customer, status='waiting_managers')
        start = timezone.now() + datetime.timedelta(days=1)
        end = start + datetime.timedelta(hours=self.tariff.duration_hours)
        self.item = OrderItem.objects.create(order=order, channel=self.channel, tariff=self.tariff,
                                             requested_start=start, requested_end=end,
                                             price=self.tariff.price, manager=self.manager,
                                             banner_message_id='msg-123')
        order.total_amount = self.tariff.price
        order.save()
        self.order = order

    @patch('integrations.bale_client.create_payment_request')
    @patch('integrations.bale_client.send_message')
    def test_manager_approve_creates_payment_request(self, mock_send_message, mock_create_payment):
        # manager approves
        url = reverse('webhook-manager-response')
        payload = {'order_item_id': self.item.id, 'manager_bale_id': self.manager.bale_user_id, 'action': 'approve'}
        mock_create_payment.return_value = {'payment_url': 'https://pay.example/123'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        # reload order
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'waiting_payment')
        # customer should receive payment link via send_message
        mock_send_message.assert_called()
        mock_create_payment.assert_called()

    @patch('integrations.bale_client.schedule_message')
    @patch('integrations.bale_client.bot_is_channel_admin')
    @patch('integrations.bale_client.send_message')
    def test_payment_webhook_schedules_forward(self, mock_send_message, mock_bot_admin, mock_schedule):
        # simulate that manager already approved and order is waiting_payment
        self.order.status = 'waiting_payment'
        self.order.save()
        # assume bot is not channel admin -> schedule to manager
        mock_bot_admin.return_value = False
        url = reverse('webhook-payment')
        payload = {'order_id': self.order.id, 'status': 'paid'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        # order should be completed
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'completed')
        # schedule_message should have been called for the manager
        mock_schedule.assert_called()
        # confirmation message sent to customer
        mock_send_message.assert_called_with(self.customer.bale_user_id, f"سفارش شما #{self.order.id} با موفقیت ثبت و پرداخت شد. تبلیغات در زمان‌های مشخص منتشر خواهد شد.")
