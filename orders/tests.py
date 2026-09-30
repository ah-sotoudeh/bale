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
        from orders.cart import process_manager_item

        self.item.manager_status = 'pending'
        self.item.save()
        mock_create_payment.return_value = {'ok': True}
        result = process_manager_item(self.item.id, self.manager.bale_user_id, 'approve')
        self.assertTrue(result.get('ok'), result)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'waiting_payment')
        mock_send_message.assert_called()
        mock_create_payment.assert_called()
        closed = self.client.post(reverse('webhook-manager-response'), {'order_item_id': self.item.id}, format='json')
        self.assertEqual(closed.status_code, 410)

    @patch('integrations.bale_client.forward_message')
    @patch('integrations.bale_client.send_message')
    def test_payment_records_only_from_waiting_payment(self, mock_send_message, mock_forward):
        from orders.services import process_payment_paid

        mock_forward.return_value = {'ok': False}
        self.order.status = 'waiting_managers'
        self.order.save()
        denied = process_payment_paid(self.order.id)
        self.assertFalse(denied.get('ok'))
        self.order.status = 'waiting_payment'
        self.order.save()
        self.item.manager_status = 'approved'
        self.item.save()
        result = process_payment_paid(self.order.id)
        self.assertTrue(result.get('ok'), result)
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(self.item.execution_status, 'paid')
        mock_send_message.assert_called()
        closed = self.client.post(reverse('webhook-payment'), {'order_id': self.order.id, 'status': 'paid'}, format='json')
        self.assertEqual(closed.status_code, 410)


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

    def test_jalali_roundtrip_for_manager_dates(self):
        from datetime import date

        from bot_flow.jalali import gregorian_to_jalali, parse_jalali_date

        self.assertEqual(gregorian_to_jalali(2024, 3, 12), (1402, 12, 22))
        self.assertEqual(parse_jalali_date(1405, 5, 20), date(2026, 8, 11))

    def test_stranger_cannot_mark_paid_from_chat(self):
        from bot_flow.access import is_debug_user

        os_environ = __import__('os').environ
        os_environ['DEBUG_BALE_ID'] = '80619262'
        self.assertTrue(is_debug_user('80619262'))
        self.assertFalse(is_debug_user(self.customer.bale_user_id))

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


class MarketplaceRulesTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='shopper', password='pass', bale_user_id='c9')
        self.manager = User.objects.create_user(username='pub', password='pass', bale_user_id='m9')
        self.channel = Channel.objects.create(
            name='shop', link='@shop', manager=self.manager, members_count=10000, avg_views=2500
        )
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='noon', duration_hours=24, price=20000, start_hour=10
        )

    def _pending_order(self):
        start = timezone.now() + timedelta(days=6)
        end = start + timedelta(hours=24)
        order = Order.objects.create(
            customer=self.customer,
            status='waiting_managers',
            managers_deadline=timezone.now() + timedelta(hours=12),
        )
        item = OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=end,
            price=20000,
            manager=self.manager,
            manager_status='pending',
            duration_hours=24,
        )
        return order, item

    @patch('integrations.bale_client.create_payment_request', return_value={'ok': True})
    @patch('integrations.bale_client.send_message')
    def test_one_rejection_keeps_the_other_item(self, _send, _pay):
        from orders.services import process_manager_response

        order, first = self._pending_order()
        start = timezone.now() + timedelta(days=7)
        second = OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=20000,
            manager=self.manager,
            manager_status='pending',
            duration_hours=24,
        )
        rejected = process_manager_response(first.id, self.manager.bale_user_id, 'reject')
        self.assertTrue(rejected.get('ok'), rejected)
        order.refresh_from_db()
        self.assertEqual(order.status, 'waiting_managers')
        approved = process_manager_response(second.id, self.manager.bale_user_id, 'approve')
        self.assertTrue(approved.get('ok'), approved)
        order.refresh_from_db()
        self.assertEqual(order.status, 'waiting_payment')
        self.assertEqual(order.total_amount, 20000)

    @patch('integrations.bale_client.send_message')
    def test_cancel_unpaid_frees_the_day(self, _send):
        from orders.cart import add_to_cart, cancel_customer_order

        day = timezone.localdate() + timedelta(days=8)
        order = Order.objects.create(customer=self.customer, status='waiting_payment', total_amount=20000)
        start = timezone.now() + timedelta(days=8)
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=20000,
            manager=self.manager,
            manager_status='approved',
            duration_hours=24,
        )
        blocked = add_to_cart(self.customer, self.tariff, day)
        self.assertFalse(blocked['ok'])
        result = cancel_customer_order(order)
        self.assertTrue(result['ok'], result)
        other = User.objects.create_user(username='next', password='pass', bale_user_id='c10')
        opened = add_to_cart(other, self.tariff, day)
        self.assertTrue(opened['ok'], opened)

    @patch('integrations.bale_client.send_message')
    def test_payment_deadline_frees_the_day(self, _send):
        from orders.cart import add_to_cart, cancel_unpaid_orders

        day = timezone.localdate() + timedelta(days=9)
        start = timezone.now() + timedelta(days=9)
        order = Order.objects.create(
            customer=self.customer,
            status='waiting_payment',
            total_amount=20000,
            managers_deadline=timezone.now() - timedelta(minutes=5),
        )
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=20000,
            manager=self.manager,
            manager_status='approved',
            duration_hours=24,
        )
        self.assertEqual(cancel_unpaid_orders(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        other = User.objects.create_user(username='later', password='pass', bale_user_id='c11')
        opened = add_to_cart(other, self.tariff, day)
        self.assertTrue(opened['ok'], opened)
