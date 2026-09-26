from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from users.models import User
from channels_app.models import Channel, Tariff
from orders.availability import has_slot_conflict
from orders.cart import add_to_cart, get_or_create_draft
from orders.models import Order, OrderItem
from orders.slots import SlotConflict
from wallet.services import credit_manager_for_execution
from django.utils import timezone

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
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=self.tariff.duration_hours)
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
    def test_payment_webhook_marks_paid(self, mock_send_message, mock_bot_admin, mock_schedule):
        self.order.status = 'waiting_payment'
        self.order.save()
        self.item.manager_status = 'approved'
        self.item.save()
        mock_bot_admin.return_value = False
        url = reverse('webhook-payment')
        payload = {'order_id': self.order.id, 'status': 'paid'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(self.item.execution_status, 'paid')
        mock_send_message.assert_called()
        mock_schedule.assert_not_called()


class SlotAndLedgerTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='buyer', password='pass', bale_user_id='b1')
        self.manager = User.objects.create_user(username='owner', password='pass', bale_user_id='m1')
        self.channel = Channel.objects.create(name='ch', link='@ch', manager=self.manager)
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='noon', duration_hours=24, price=5000, start_hour=12
        )

    def test_second_booking_same_day_conflicts(self):
        day = timezone.localdate() + timedelta(days=3)
        first = add_to_cart(self.customer, self.tariff, day)
        self.assertTrue(first['ok'], first)
        other = User.objects.create_user(username='buyer2', password='pass', bale_user_id='b2')
        second = add_to_cart(other, self.tariff, day)
        self.assertFalse(second['ok'])
        self.assertEqual(second['error'], 'slot_conflict')

    def test_one_draft_per_customer(self):
        a = get_or_create_draft(self.customer)
        b = get_or_create_draft(self.customer)
        self.assertEqual(a.id, b.id)

    def test_paid_order_blocks_the_day(self):
        start = timezone.now() + timedelta(days=4)
        end = start + timedelta(hours=24)
        order = Order.objects.create(customer=self.customer, status='paid')
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=end,
            price=5000,
            manager=self.manager,
            manager_status='approved',
            duration_hours=24,
        )
        self.assertTrue(has_slot_conflict(self.tariff, start, end, channel=self.channel))

    def test_direct_overlap_raises(self):
        start = timezone.now() + timedelta(days=5)
        end = start + timedelta(hours=24)
        order = Order.objects.create(customer=self.customer, status='waiting_payment')
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=end,
            manager=self.manager,
            manager_status='approved',
            duration_hours=24,
        )
        with self.assertRaises(SlotConflict):
            OrderItem.objects.create(
                order=order,
                channel=self.channel,
                tariff=self.tariff,
                requested_start=start,
                requested_end=end,
                manager=self.manager,
                manager_status='pending',
                duration_hours=24,
            )

    def test_earn_is_idempotent(self):
        a = credit_manager_for_execution(self.manager, 10000, 77)
        b = credit_manager_for_execution(self.manager, 10000, 77)
        self.assertEqual(a.id, b.id)
        self.assertEqual(self.manager.ledger.count(), 1)


class BaleInvoiceTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='pay', password='pass', bale_user_id='p1')
        self.order = Order.objects.create(customer=self.customer, status='waiting_payment', total_amount=150_000)

    @patch('orders.bale_pay.bc.answer_pre_checkout_query')
    def test_precheckout_rejects_wrong_rial(self, mock_answer):
        from orders.bale_pay import handle_pre_checkout

        handle_pre_checkout({
            'id': 'q1',
            'invoice_payload': f'order-{self.order.id}',
            'total_amount': 150_000,
            'currency': 'IRR',
        })
        mock_answer.assert_called_once()
        self.assertFalse(mock_answer.call_args.args[1])

    @patch('orders.bale_pay.bc.answer_pre_checkout_query')
    def test_precheckout_accepts_rial(self, mock_answer):
        from orders.bale_pay import handle_pre_checkout

        handle_pre_checkout({
            'id': 'q2',
            'invoice_payload': f'order-{self.order.id}',
            'total_amount': 1_500_000,
            'currency': 'IRR',
        })
        mock_answer.assert_called_with('q2', True)
