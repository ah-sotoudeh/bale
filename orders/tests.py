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
        texts = []
        for call in mock_send_message.call_args_list:
            if len(call.args) > 1:
                texts.append(str(call.args[1]))
            elif 'text' in call.kwargs:
                texts.append(str(call.kwargs['text']))
        joined = '\n'.join(texts)
        self.assertIn('ساعت', joined)
        self.assertNotIn('2026', joined)
        self.assertNotIn('+00', joined)
        self.assertIn('لینک‌ساز خودکار', joined)
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

    def test_slot_time_stays_jalali_in_rtl_chat(self):
        from datetime import datetime

        from bot_flow.jalali import format_slot

        text = format_slot(timezone.make_aware(datetime(2026, 10, 3, 12, 0)))
        self.assertNotIn('+', text)
        self.assertNotIn('2026', text)
        self.assertIn('ساعت', text)
        self.assertIn('۱۲:۰۰', text)

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

    def test_amounts_above_one_million_split_into_invoices(self):
        from orders.bale_pay import payment_parts, send_order_invoices

        self.assertEqual(payment_parts(1_000_000), [1_000_000])
        self.assertEqual(payment_parts(1_000_001), [1_000_000, 1])
        self.assertEqual(payment_parts(2_500_000), [1_000_000, 1_000_000, 500_000])
        self.order.total_amount = 2_500_000
        self.order.save(update_fields=['total_amount'])
        with patch('orders.bale_pay.bc.create_payment_request', return_value={'ok': True}) as create:
            result = send_order_invoices(self.order, 'p1')
        self.assertEqual(result['sent'], 3)
        self.assertEqual(result['failed'], 0)
        amounts = [call.kwargs['amount'] for call in create.call_args_list]
        payloads = [call.kwargs['payload'] for call in create.call_args_list]
        self.assertEqual(amounts, [1_000_000, 1_000_000, 500_000])
        self.assertTrue(all(amount <= 1_000_000 for amount in amounts))
        self.assertEqual(payloads[0], f'order-{self.order.id}-p1-1000000')
        self.assertEqual(payloads[2], f'order-{self.order.id}-p3-500000')

    @patch('orders.bale_pay.bc.create_invoice_link', return_value={'ok': True, 'invoice_params': 'inv', 'amount_rial': 10_000_000})
    def test_miniapp_opens_the_next_unpaid_slice(self, link):
        from orders.bale_pay import invoice_for_order

        self.order.total_amount = 1_500_000
        self.order.save(update_fields=['total_amount'])
        first = invoice_for_order(self.order)
        self.assertEqual(first['amount_toman'], 1_000_000)
        self.assertEqual(first['part'], 1)
        self.assertEqual(first['parts'], 2)
        self.assertIn('بخش', first['message'])
        self.assertLessEqual(link.call_args.kwargs['amount_toman'], 1_000_000)

    @patch('orders.bale_pay.bc.answer_pre_checkout_query')
    @patch('integrations.bale_client.send_message')
    def test_order_stays_open_until_every_wallet_part_is_paid(self, _send, mock_answer):
        from orders.bale_pay import handle_pre_checkout, handle_successful_payment
        from wallet.models import WalletLedger
        from wallet.services import available_balance, recent_ledger

        self.order.total_amount = 2_500_000
        self.order.save(update_fields=['total_amount'])
        oid = self.order.id
        handle_pre_checkout({
            'id': 'whole',
            'invoice_payload': f'order-{oid}',
            'total_amount': 25_000_000,
        })
        self.assertFalse(mock_answer.call_args.args[1])

        def pay(payload, rial):
            handle_successful_payment({
                'chat': {'id': 'p1'},
                'successful_payment': {'invoice_payload': payload, 'total_amount': rial},
            })

        pay(f'order-{oid}-p1-1000000', 10_000_000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'waiting_payment')
        self.assertEqual(WalletLedger.objects.filter(idempotency_key__startswith=f'inv:{oid}:').count(), 1)
        self.assertEqual(available_balance(self.customer), 0)
        self.assertEqual(recent_ledger(self.customer), [])
        pay(f'order-{oid}-p1-1000000', 10_000_000)
        self.assertEqual(WalletLedger.objects.filter(idempotency_key__startswith=f'inv:{oid}:').count(), 1)
        handle_pre_checkout({
            'id': 'again',
            'invoice_payload': f'order-{oid}-p1-1000000',
            'total_amount': 10_000_000,
        })
        self.assertFalse(mock_answer.call_args.args[1])
        pay(f'order-{oid}-p2-1000000', 10_000_000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'waiting_payment')
        pay(f'order-{oid}-p3-500000', 5_000_000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')


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

    @patch('integrations.bale_client.create_payment_request', return_value={'ok': True})
    @patch('integrations.bale_client.send_message')
    def test_stranger_cannot_answer_a_channel(self, _send, _pay):
        from orders.cart import process_manager_item

        _order, item = self._pending_order()
        stranger = User.objects.create_user(username='str', password='pass', bale_user_id='x9')
        denied = process_manager_item(item.id, stranger.bale_user_id, 'approve')
        self.assertEqual(denied.get('error'), 'not_item_manager')
        item.manager = None
        item.save(update_fields=['manager'])
        still = process_manager_item(item.id, stranger.bale_user_id, 'approve')
        self.assertEqual(still.get('error'), 'not_item_manager')
        owned = process_manager_item(item.id, self.manager.bale_user_id, 'approve')
        self.assertTrue(owned.get('ok'), owned)

    @patch('integrations.bale_client.send_message')
    def test_ignored_time_proposal_frees_the_day(self, _send):
        from orders.cart import add_to_cart, expire_timed_out_items

        order, item = self._pending_order()
        item.manager_status = 'edited'
        item.manager_edited_start = item.requested_start + timedelta(days=1)
        item.save()
        order.managers_deadline = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['managers_deadline'])
        proposed = timezone.localtime(item.manager_edited_start).date()
        other = User.objects.create_user(username='free', password='pass', bale_user_id='c12')
        blocked = add_to_cart(other, self.tariff, proposed)
        self.assertFalse(blocked['ok'])
        self.assertEqual(expire_timed_out_items(), 1)
        item.refresh_from_db()
        self.assertEqual(item.manager_status, 'expired')
        opened = add_to_cart(other, self.tariff, proposed)
        self.assertTrue(opened['ok'], opened)

    @patch('integrations.bale_client.send_message')
    def test_declining_one_time_returns_order_to_managers(self, _send):
        from orders.cart import customer_confirm_edit

        order, first = self._pending_order()
        first.manager_status = 'edited'
        first.manager_edited_start = first.requested_start
        first.save()
        order.status = 'waiting_customer_confirm'
        order.save(update_fields=['status'])
        start = timezone.now() + timedelta(days=11)
        OrderItem.objects.create(
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
        result = customer_confirm_edit(first.id, self.customer.bale_user_id, False)
        self.assertTrue(result.get('ok'), result)
        order.refresh_from_db()
        self.assertEqual(order.status, 'waiting_managers')

    def test_tariff_with_orders_is_switched_off_not_deleted(self):
        from orders.cart import retire_tariff

        _order, item = self._pending_order()
        self.assertTrue(retire_tariff(self.tariff))
        self.tariff.refresh_from_db()
        self.assertFalse(self.tariff.is_active)
        item.refresh_from_db()
        self.assertEqual(item.price, 20000)
        self.tariff.price = 90000
        self.tariff.save(update_fields=['price'])
        item.refresh_from_db()
        self.assertEqual(item.price, 20000)

    def test_tariff_price_keeps_full_toman_amount(self):
        from bot_flow.handlers import parse_tariff_lines

        rows = parse_tariff_lines('طرح عادی | ۱۰ | ۲۴ | ۲۰۰٬۰۰۰')
        self.assertEqual(rows, [('طرح عادی', 10, 24, 200000)])

    @patch('orders.publish.check_bot_admin', return_value='unknown')
    def test_failed_admin_check_does_not_hide_tariffs(self, _check):
        from orders.publish import daily_admin_audit

        self.channel.publish_mode = 'bot'
        self.channel.save(update_fields=['publish_mode'])
        result = daily_admin_audit()
        self.assertEqual(result['deactivated_tariffs'], 0)
        self.tariff.refresh_from_db()
        self.assertTrue(self.tariff.is_active)

    @patch('orders.publish.bc.send_message')
    @patch('orders.publish.bc.forward_message', return_value={'ok': True, 'result': {'message_id': 9}})
    @patch('orders.publish.bc.get_me', return_value={'ok': True, 'result': {'id': 355714786}})
    @patch('orders.publish.check_bot_admin', return_value='admin')
    @patch('orders.publish.recover_permalink', return_value={'permalink': 'https://ble.ir/linktest/1/2'})
    @patch('orders.publish.ly.get_me', side_effect=ModuleNotFoundError('aiobale'))
    def test_bot_publish_runs_when_linkyar_library_is_missing(self, *_mocks):
        from orders.publish import publish_due_items

        start = timezone.now() - timedelta(hours=2)
        order = Order.objects.create(
            customer=self.customer,
            status='paid',
            banner_from_chat_id='@linktest',
            banner_message_id='42',
        )
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=12),
            price=1000,
            manager=self.manager,
            manager_status='approved',
            execution_status='paid',
            duration_hours=12,
        )
        self.channel.publish_mode = 'bot'
        self.channel.save(update_fields=['publish_mode'])
        result = publish_due_items()
        self.assertEqual(result['published'], 1)
        self.assertEqual(result['failed_channels'], 0)

    def test_customer_sees_order_lines_outside_the_manager_inbox(self):
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        _order, item = self._pending_order()
        customer = self.client.get('/miniapp/api/orders', {'debug_bale_id': 'c9'})
        self.assertEqual(customer.status_code, 200, customer.content)
        rows = customer.json()['orders']
        self.assertEqual([row['id'] for row in rows], [item.id])
        self.assertFalse(rows[0]['inbox'])
        self.assertEqual(rows[0]['group_id'], None)
        manager = self.client.get('/miniapp/api/orders', {'debug_bale_id': 'm9'})
        self.assertTrue(manager.json()['orders'][0]['inbox'])
        stranger = self.client.get('/miniapp/api/orders', {'debug_bale_id': 'zz-new'})
        self.assertEqual(stranger.json()['orders'], [])

    def test_my_orders_show_the_open_deadline(self):
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        order, _item = self._pending_order()
        order.status = 'waiting_payment'
        order.managers_deadline = timezone.now() + timedelta(hours=5, minutes=10)
        order.save(update_fields=['status', 'managers_deadline'])
        response = self.client.get('/miniapp/api/my-orders', {'debug_bale_id': 'c9'})
        self.assertEqual(response.status_code, 200, response.content)
        hint = response.json()['orders'][0]['pay_hint']
        self.assertIn('پرداخت', hint)
        self.assertIn('۵', hint)
        order.status = 'waiting_managers'
        order.save(update_fields=['status'])
        again = self.client.get('/miniapp/api/my-orders', {'debug_bale_id': 'c9'})
        self.assertIn('پاسخ کانال', again.json()['orders'][0]['pay_hint'])

    def test_stranger_reject_is_persian_and_assets_refresh(self):
        import json
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        _order, item = self._pending_order()
        denied = self.client.post(
            '/miniapp/api/orders/reject',
            data=json.dumps({'item_id': item.id, 'debug_bale_id': 'zz-deny'}),
            content_type='application/json',
        )
        self.assertEqual(denied.status_code, 400)
        body = denied.json()
        self.assertEqual(body['error'], 'not_item_manager')
        self.assertIn('مدیر', body['message'])
        asset = self.client.get('/miniapp/assets/shop.css')
        self.assertEqual(asset.status_code, 200)
        self.assertIn('no-cache', asset['Cache-Control'])

    def test_channel_stats_ignore_a_brand_new_post_and_a_quiet_day(self):
        from integrations.channel_stats import summarize_reading

        now = int(timezone.now().timestamp() * 1000)
        day = 86_400_000
        summary = summarize_reading(
            10_000,
            [
                {'message_id': 1, 'views': 1000, 'date': now - 3 * day, 'forwards': 4},
                {'message_id': 2, 'views': 0, 'date': now - 60_000, 'forwards': 0},
            ],
        )
        self.assertEqual(summary['avg_views'], 1000)
        self.assertEqual(summary['err_percent'], 10.0)
        self.assertEqual(summary['daily_reach'], 0)
        quiet = summarize_reading(10_000, [{'message_id': 1, 'views': 500, 'date': now - 3 * day, 'forwards': 0}])
        self.assertEqual(quiet['daily_reach'], 0)
        self.assertEqual(quiet['avg_views'], 500)

    def test_stats_job_reads_one_channel_and_a_failure_moves_on(self):
        from integrations.channel_stats import refresh_channel, refresh_due_channels

        Channel.objects.create(name='second', link='@second', manager=self.manager)
        with patch('integrations.channel_stats.refresh_channel', return_value={'ok': True}) as refresh:
            result = refresh_due_channels(limit=1)
        self.assertEqual(result, {'done': 1, 'failed': 0})
        self.assertEqual(refresh.call_count, 1)
        self.channel.link = ''
        self.channel.save(update_fields=['link'])
        failed = refresh_channel(self.channel)
        self.assertFalse(failed['ok'])
        self.channel.refresh_from_db()
        self.assertIsNotNone(self.channel.stats_updated_at)

    def test_reread_button_calls_linkyar_for_the_owner_only(self):
        import json
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        with patch(
            'integrations.channel_stats.refresh_channel',
            return_value={'ok': False, 'error': 'BALE_TOKEN missing'},
        ) as refresh:
            owner = self.client.post(
                '/miniapp/api/channels/refresh',
                data=json.dumps({'debug_bale_id': 'm9'}),
                content_type='application/json',
            )
            stranger = self.client.post(
                '/miniapp/api/channels/refresh',
                data=json.dumps({'debug_bale_id': 'c9'}),
                content_type='application/json',
            )
        self.assertEqual(owner.status_code, 200, owner.content)
        body = owner.json()
        self.assertEqual(body['failed'], 1)
        self.assertIn('لینک‌یار', body['message'])
        self.assertEqual(stranger.json()['done'], 0)
        self.assertEqual(refresh.call_count, 1)

    def test_channel_proof_is_the_username(self):
        import json
        import os

        from bot_flow.handlers import bio_matches_owner, ownership_prompt

        owner = User.objects.create_user(
            username='linkyar',
            password='pass',
            bale_user_id='1164810718',
            bale_username='link_yar',
        )
        self.assertFalse(bio_matches_owner('تبلیغ 1164810718', owner))
        self.assertTrue(bio_matches_owner('همراه @link_yar و @linkpakhsh', owner))
        self.assertTrue(bio_matches_owner('LINK_YAR', owner))
        self.assertFalse(bio_matches_owner('@link_yar_shop', owner))
        bare = User.objects.create_user(username='noname', password='pass', bale_user_id='42')
        self.assertFalse(bio_matches_owner('42', bare))
        named = ownership_prompt(owner)
        self.assertIn('@link_yar', named)
        self.assertNotIn('1164810718', named)
        self.assertIn('نام کاربری', ownership_prompt(bare))

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        os.environ['DEBUG_BALE_ID'] = ''
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        self.addCleanup(lambda: os.environ.pop('DEBUG_BALE_ID', None))
        info = {'title': 'تست بنر', 'id': 7}
        with patch('integrations.channel_stats.refresh_channel', return_value={'ok': False}):
            with patch('integrations.bale_client.get_channel_info', return_value={**info, 'bio': '1164810718'}):
                denied = self.client.post(
                    '/miniapp/api/channels/add',
                    data=json.dumps({'link': '@ownedproof', 'debug_bale_id': '1164810718'}),
                    content_type='application/json',
                )
            self.assertEqual(denied.status_code, 400, denied.content)
            error = denied.json()['error']
            self.assertIn('@link_yar', error)
            self.assertNotIn('1164810718', error)
            self.assertNotIn('عددی', error)
            with patch(
                'integrations.bale_client.get_channel_info',
                return_value={**info, 'bio': 'لینک‌کالا\n@link_yar'},
            ):
                accepted = self.client.post(
                    '/miniapp/api/channels/add',
                    data=json.dumps({'link': '@ownedproof', 'debug_bale_id': '1164810718'}),
                    content_type='application/json',
                )
        self.assertEqual(accepted.status_code, 200, accepted.content)

        self.client.force_login(owner)
        with patch('integrations.bale_client.get_channel_info', return_value={**info, 'bio': '1164810718'}):
            api_denied = self.client.post(
                '/api/channels/register/',
                data=json.dumps({'channel_link': '@ownedproof'}),
                content_type='application/json',
            )
        self.assertEqual(api_denied.status_code, 400, api_denied.content)
        self.assertIn('@link_yar', api_denied.json()['detail'])
        self.assertNotIn('1164810718', api_denied.json()['detail'])
