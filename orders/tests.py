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
        self.assertIn('بازوی لینک‌بان', joined)
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
        self.assertIn('کانال‌دار', body['message'])
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

    def test_refresh_stores_views_and_linkyar_admin(self):
        from integrations.channel_stats import refresh_channel

        now = int(timezone.now().timestamp() * 1000)
        day = 86_400_000
        reading = {
            'ok': True,
            'peer_id': 1497133952,
            'title': 'تست بنر',
            'about': 'همراه @link_yar',
            'members': 8,
            'posts': [
                {'message_id': 1, 'date': now - 3 * day, 'views': 4, 'forwards': 0},
                {'message_id': 2, 'date': now - 2 * day, 'views': 6, 'forwards': 1},
            ],
            'linkyar_is_admin': True,
        }
        with patch('integrations.linkyar_client.collect_channel_stats', return_value=reading):
            result = refresh_channel(self.channel)
        self.assertTrue(result['ok'], result)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.members_count, 8)
        self.assertEqual(self.channel.avg_views, 5)
        self.assertTrue(self.channel.linkyar_is_admin)
        self.assertIsNotNone(self.channel.linkyar_checked_at)
        self.assertIsNone(self.channel.bot_checked_at)

    def test_refresh_asks_linkyar_only_for_due_tariff_channels(self):
        import json
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        Channel.objects.create(
            name='plain',
            link='@plain',
            manager=self.manager,
            avg_views=20,
            stats_updated_at=timezone.now(),
        )
        self.channel.avg_views = 0
        self.channel.stats_updated_at = timezone.now() - timedelta(minutes=10)
        self.channel.save(update_fields=['avg_views', 'stats_updated_at'])
        with patch('integrations.channel_stats.refresh_channel', return_value={'ok': True}) as refresh:
            owner = self.client.post(
                '/miniapp/api/channels/refresh',
                data=json.dumps({'debug_bale_id': 'm9'}),
                content_type='application/json',
            )
        self.assertEqual(owner.status_code, 200, owner.content)
        self.assertEqual(refresh.call_count, 1)
        self.assertEqual(refresh.call_args.args[0].link, self.channel.link)

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
        self.assertIn('حساب دستیار', body['message'])
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
            self.assertEqual(denied.json()['code'], 'owner_username')
            self.assertIn('@link_yar', error)
            self.assertIn('درباره', error)
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

    def test_debug_manager_still_needs_username_in_about(self):
        import json
        import os

        User.objects.create_user(
            username='linkyar-debug',
            password='pass',
            bale_user_id='1164810718',
            bale_username='link_yar',
        )
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        os.environ['DEBUG_BALE_ID'] = '1164810718'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        self.addCleanup(lambda: os.environ.pop('DEBUG_BALE_ID', None))
        info = {'title': 'تست بنر', 'id': 7}
        with patch('integrations.channel_stats.refresh_channel', return_value={'ok': False}):
            with patch('integrations.bale_client.get_channel_info', return_value={**info, 'bio': 'تبلیغات'}):
                denied = self.client.post(
                    '/miniapp/api/channels/add',
                    data=json.dumps({'link': '@debugproof', 'debug_bale_id': '1164810718'}),
                    content_type='application/json',
                )
            self.assertEqual(denied.status_code, 400, denied.content)
            body = denied.json()
            self.assertEqual(body['code'], 'owner_username')
            self.assertIn('@link_yar', body['message'])
            self.assertIn('درباره', body['message'])
            with patch('integrations.bale_client.get_channel_info', return_value={'error': 'not_found'}):
                missed = self.client.post(
                    '/miniapp/api/channels/add',
                    data=json.dumps({'link': '@debugproof', 'debug_bale_id': '1164810718'}),
                    content_type='application/json',
                )
        self.assertEqual(missed.status_code, 400, missed.content)
        self.assertEqual(missed.json()['code'], 'lookup_failed')
        self.assertIn('پیوند', missed.json()['message'])


class MiniappLiveActionTests(TestCase):
    def setUp(self):
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        self.customer = User.objects.create_user(username='live-c', password='pass', bale_user_id='c-live')
        self.manager = User.objects.create_user(username='live-m', password='pass', bale_user_id='m-live')
        self.channel = Channel.objects.create(name='live', link='@live', manager=self.manager)
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='day', duration_hours=24, price=1000, start_hour=11
        )

    def _item(self, execution):
        start = timezone.now() + timedelta(days=2)
        order = Order.objects.create(customer=self.customer, status='paid', total_amount=1000)
        return OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=1000,
            manager=self.manager,
            manager_status='approved',
            execution_status=execution,
            duration_hours=24,
        )

    def _post(self, path, payload):
        import json

        return self.client.post(path, data=json.dumps(payload), content_type='application/json')

    def test_catalog_points_at_a_channel_avatar(self):
        from unittest.mock import patch

        listed = self.client.get('/miniapp/api/catalog', {'debug_bale_id': 'c-live'})
        self.assertEqual(listed.status_code, 200, listed.content)
        row = listed.json()['channels'][0]
        self.assertEqual(row['avatar_url'], f'/miniapp/api/channels/{self.channel.id}/avatar')
        from pathlib import Path

        root = Path('/tmp/lb-avatars')
        (root / f'{self.channel.id}.img').unlink(missing_ok=True)
        (root / f'{self.channel.id}.none').unlink(missing_ok=True)
        with patch('integrations.bale_client.get_channel_info', return_value={'raw': {}}):
            missing = self.client.get(row['avatar_url'])
        self.assertEqual(missing.status_code, 404)
        self.assertTrue((root / f'{self.channel.id}.none').is_file())
        with patch(
            'integrations.bale_client.get_channel_info',
            side_effect=AssertionError('cached miss should not call Bale'),
        ):
            again = self.client.get(row['avatar_url'])
        self.assertEqual(again.status_code, 404)

    def test_confirm_rejects_the_wrong_stage_in_persian(self):
        item = self._item('paid')
        response = self._post(
            '/miniapp/api/orders/confirm',
            {'item_id': item.id, 'accept': True, 'debug_bale_id': 'c-live'},
        )
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body['error'], 'bad_status')
        self.assertIn('ممکن', body['message'])
        item.refresh_from_db()
        self.assertEqual(item.execution_status, 'paid')

    @patch('integrations.bale_client.send_message')
    @patch('orders.execution.credit_manager_for_execution')
    def test_customer_confirm_writes_the_order(self, _credit, _send):
        item = self._item('awaiting_customer_confirm')
        response = self._post(
            '/miniapp/api/orders/confirm',
            {'item_id': item.id, 'accept': True, 'debug_bale_id': 'c-live'},
        )
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.execution_status, 'executed')
        stranger = self._post(
            '/miniapp/api/orders/confirm',
            {'item_id': item.id, 'accept': False, 'debug_bale_id': 'm-live'},
        )
        self.assertEqual(stranger.status_code, 400)
        self.assertEqual(stranger.json()['error'], 'not_customer')

    def test_published_button_uses_channel_history(self):
        item = self._item('paid')
        with patch(
            'orders.publish.verify_manager_published',
            return_value={'ok': False, 'error': 'not_found_in_history'},
        ):
            missing = self._post(
                '/miniapp/api/orders/published',
                {'item_id': item.id, 'debug_bale_id': 'm-live'},
            )
        self.assertEqual(missing.status_code, 400, missing.content)
        self.assertIn('تاریخچه', missing.json()['message'])
        with patch(
            'orders.publish.verify_manager_published',
            return_value={'ok': True, 'permalinks': ['https://ble.ir/live/1']},
        ) as verify:
            found = self._post(
                '/miniapp/api/orders/published',
                {'item_id': item.id, 'debug_bale_id': 'm-live'},
            )
        self.assertEqual(found.status_code, 200, found.content)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[0], item.id)

    @patch('wallet.services.OPERATOR_BALE_ID', 'm-live')
    def test_operator_home_loads_the_banner_queue(self):
        from orders.models import BannerPublishRequest

        BannerPublishRequest.objects.create(
            customer=self.customer,
            storage_chat_id='1',
            storage_message_id='2',
            caption='بنر آزمایشی برای صف پشتیبانی',
            media_kind='photo',
            fee_toman=0,
            status='pending',
        )
        home = self.client.get('/miniapp/api/me', {'debug_bale_id': 'm-live'})
        self.assertEqual(home.status_code, 200, home.content)
        banners = home.json()['operator_banners']
        self.assertEqual(len(banners), 1)
        self.assertIn('آزمایشی', banners[0]['caption'])
        customer = self.client.get('/miniapp/api/me', {'debug_bale_id': 'c-live'})
        self.assertEqual(customer.json()['operator_banners'], [])
        self.assertEqual(customer.json()['operator_payouts'], [])

    @patch('orders.publish.ly.delete_message', return_value={'ok': True})
    @patch('orders.publish.bc.delete_message', return_value={'ok': True})
    def test_expired_ad_is_removed_by_both_accounts(self, bot_del, ly_del):
        import json

        item = self._item('executed')
        item.requested_end = timezone.now() - timedelta(hours=1)
        item.published_at = timezone.now() - timedelta(hours=2)
        item.channel_message_id = json.dumps(
            [{
                'message_id': 55,
                'date': 1700000000000,
                'ref': '@linktest',
                'bot_message_id': 9,
            }],
            ensure_ascii=False,
        )
        item.save(update_fields=['requested_end', 'published_at', 'channel_message_id'])
        from orders.publish import delete_expired_posts

        self.assertEqual(delete_expired_posts(), 1)
        bot_del.assert_called_once_with('@linktest', 9)
        ly_del.assert_called_once_with('@linktest', 55, message_date=1700000000000)
        item.refresh_from_db()
        self.assertEqual(item.channel_message_id, '')

    def test_live_bundle_calls_the_order_endpoints(self):
        bundle = self.client.get('/miniapp/assets/index-Ce1t18yS.js')
        self.assertEqual(bundle.status_code, 200)
        script = b''.join(bundle.streaming_content).decode('utf-8')
        self.assertIn('/orders/published', script)
        self.assertIn('/orders/confirm', script)
        self.assertIn('operator_banners', script)
        self.assertIn("owner:`customer`", script)
        self.assertIn('debug_bale_id', script)
        self.assertIn('کانالتان را اضافه کنید', script)
        self.assertIn('تعرفه را مشخص کنید', script)
        self.assertIn('درخواست‌ها را جواب دهید', script)
        self.assertIn('C().manager.requestGuideTitle', script)
        self.assertIn('C().manager.tariffGuideTitle', script)
        self.assertIn('برآورد تعامل', script)
        self.assertIn('تعامل ثبت نشده', script)
        self.assertIn('unknown:`نامشخص`', script)
        self.assertIn('n.growth!=null', script)
        self.assertIn('errPack.known', script)
        self.assertIn('lb-pill', script)
        self.assertIn('{id:`customer`,label:C().role.customer},{id:`manager`,label:C().role.managerShort}', script)
        self.assertIn('الان چیزی برای واریز پایا نیست.', script)
        self.assertIn('function lyHome(', script)
        self.assertIn('C().operator.linkyarPending', script)
        self.assertIn('حساب دستیار هنوز بررسی نشده', script)
        self.assertNotIn('n.linkyar.connected?C().operator.linkyarOn', script)
        self.assertIn('برداشتن این روز', script)
        self.assertIn('روزی انتخاب نشده', script)
        self.assertIn('وضعیت انتشار: {status}', script)
        self.assertIn('این روز را قبلاً انتخاب کرده‌اید', script)
        self.assertNotIn('حذف از سبد', script)
        self.assertNotIn('افزودن به سبد بسته است', script)
        self.assertNotIn('به سبد اضافه شد', script)
        from bot_flow.messages import user_error

        self.assertNotIn('سبد', user_error('empty_cart'))
        self.assertIn('هنوز روزی انتخاب نکرده‌اید', user_error('empty_cart'))
        self.assertIn('نمی‌توانید روزی را انتخاب کنید', user_error('no_banner'))
        self.assertIn('Z(e=>e.channels).filter(c=>!live||c.owned)', script)
        self.assertNotIn('Z(e=>e.channels.filter', script)
        self.assertIn('e.length?(0,Q.jsx)(`p`,{className:`mb-2 px-1 text-xs leading-relaxed text-muted`,children:w(C().tpl.dueLine', script)
        self.assertIn('چطور کار می‌کند', script)
        self.assertIn('نام کاربری خودتان را در «درباره» کانال بنویسید', script)
        self.assertIn('steps:C().manager.emptyChannelSteps', script)
        self.assertIn('queueMicrotask(()=>t().refreshChannelStats())', script)
        self.assertIn('هنوز بررسی نشده', script)
        self.assertIn('iA(`/channels/refresh`,n?{force:!0}:{})', script)
        self.assertIn('شرایط و قوانین', script)
        self.assertIn('isOperator:op', script)
        self.assertIn('پیوند کانال را بنویسید', script)
        self.assertIn('lb-ava', script)
        self.assertIn('نشان‌شده‌ها', script)
        self.assertIn('toggleFavorite(cid,t.id)', script)
        self.assertIn('setLbTar', script)
        self.assertIn('lb-tar', script)
        days_at = script.find('days:WA(),model:')
        self.assertGreater(days_at, 0)
        days_model = script[days_at:days_at + 1600]
        self.assertIn('removeCart', days_model)
        self.assertIn('C().toast.removedCart', days_model)
        self.assertIn('C().toast.addedCart', days_model)
        self.assertIn('`past`', days_model)
        self.assertIn('`banner`', days_model)
        self.assertIn('C().day.past', script)
        self.assertIn('function lbHoldText(', script)
        self.assertIn('مهلت تمام', script)
        self.assertIn('holdUntil:String(l.hold_until', script)
        self.assertIn('o.canDispute', script)
        self.assertNotIn('n.go({name:`cart`})', script)
        self.assertIn('title:C().screen.orders,hint:C().customer.mineHint,onClick:()=>n.go({name:`mine`})', script)
        self.assertIn('روزهای انتخاب‌شده', script)
        self.assertIn('n.checkout()', script)
        self.assertIn('C().catalog.needBanner', script[script.find('روزهای انتخاب‌شده'):])
        self.assertNotIn('درباره کانال: ', script)
        rules = self.client.get('/miniapp/rules/')
        self.assertEqual(rules.status_code, 200)
        self.assertIn('قمار', rules.content.decode('utf-8'))
        shell = self.client.get('/miniapp/assets/shell.js')
        self.assertEqual(shell.status_code, 200)
        self.assertIn('شرایط و قوانین', b''.join(shell.streaming_content).decode('utf-8'))
        shop = self.client.get('/miniapp/assets/shop.css')
        self.assertIn('button.lb-pill', b''.join(shop.streaming_content).decode('utf-8'))


class CustomerBannerFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer', password='pass', bale_user_id='cust-1')
        self.manager = User.objects.create_user(username='owner', password='pass', bale_user_id='mgr-1')
        self.channel = Channel.objects.create(name='shop', link='@shop', manager=self.manager)
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='noon', duration_hours=24, price=1000, start_hour=11
        )

    def _sent_text(self, mock_send):
        parts = []
        for call in mock_send.call_args_list:
            if call.args:
                parts.append(str(call.args[1] if len(call.args) > 1 else call.args[0]))
        return '\n'.join(parts)

    @patch('integrations.bale_client.forward_message', return_value={'ok': True})
    @patch('integrations.bale_client.answer_callback_query', return_value={'ok': True})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_photo_banner_is_saved_and_confirmed(self, send, _answer, _forward):
        from bot_flow.customer import handle_customer_callback
        from bot_flow.dispatch import handle_update
        from orders.models import CustomerBanner

        handle_customer_callback('900', 'cust-1', 'cu:new', cq_id='c1')
        handle_update({
            'update_id': 1,
            'message': {
                'message_id': 50,
                'chat': {'id': 900},
                'from': {'id': 'cust-1'},
                'photo': [{'file_id': 'ph'}],
                'caption': 'خرید دمپایی تابستانی از این فروشگاه',
            },
        })
        banner = CustomerBanner.objects.get(customer=self.user)
        self.assertEqual(banner.media_kind, 'photo')
        self.assertIn('دمپایی', banner.caption)
        draft = Order.objects.get(customer=self.user, status='draft')
        self.assertEqual(draft.banner_message_id, '50')
        text = self._sent_text(send)
        self.assertIn('بنر رسید', text)
        self.assertIn('کانال و روز را انتخاب کنید', text)
        markup = ''
        for call in send.call_args_list:
            raw = call.kwargs.get('reply_markup')
            if raw:
                markup += str(raw)
        self.assertIn('cu:catalog', markup)
        self.assertIn('ویرایش', markup)

    @patch('integrations.bale_client.answer_callback_query', return_value={'ok': True})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_short_text_explains_the_banner_rule(self, send, _answer):
        from bot_flow.customer import handle_customer_callback
        from bot_flow.dispatch import handle_update
        from orders.models import CustomerBanner

        handle_customer_callback('900', 'cust-1', 'cu:new', cq_id='c1')
        send.reset_mock()
        handle_update({
            'update_id': 2,
            'message': {
                'message_id': 51,
                'chat': {'id': 900},
                'from': {'id': 'cust-1'},
                'text': 'سلام',
            },
        })
        self.assertEqual(CustomerBanner.objects.count(), 0)
        self.assertIn('عکس', self._sent_text(send))

    @patch('integrations.bale_client.forward_message', return_value={'ok': True})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_a_sentence_can_be_a_text_banner(self, send, _forward):
        from bot_flow.dispatch import handle_update
        from users.models import BotSession

        BotSession.objects.create(bale_user_id='cust-1', state='cust_await_banner', data={})
        handle_update({
            'update_id': 3,
            'message': {
                'message_id': 52,
                'chat': {'id': 900},
                'from': {'id': 'cust-1'},
                'text': 'تبلیغ فروشگاه کفش، ارسال رایگان تا آخر هفته',
            },
        })
        draft = Order.objects.get(customer=self.user, status='draft')
        self.assertEqual(draft.banner_message_id, '52')
        self.assertIn('بنر رسید', self._sent_text(send))

    @patch('integrations.bale_client.answer_callback_query', return_value={'ok': True})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_a_second_tap_does_not_send_the_same_panel_again(self, send, _answer):
        from bot_flow.dispatch import handle_callback_query

        payload = {
            'id': 'cq-1',
            'data': 'cu:new',
            'from': {'id': 'cust-1'},
            'message': {'message_id': 7, 'chat': {'id': 900}},
        }
        handle_callback_query(payload)
        first = send.call_count
        handle_callback_query({**payload, 'id': 'cq-2'})
        self.assertEqual(send.call_count, first)
        self.assertGreater(first, 0)

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_help_and_menu_are_known_commands(self, send):
        from bot_flow.dispatch import handle_update

        handle_update({
            'update_id': 4,
            'message': {'message_id': 1, 'chat': {'id': 900}, 'from': {'id': 'cust-1'}, 'text': '/help'},
        })
        self.assertIn('راهنما', self._sent_text(send))
        send.reset_mock()
        handle_update({
            'update_id': 5,
            'message': {'message_id': 2, 'chat': {'id': 900}, 'from': {'id': 'cust-1'}, 'text': '/menu'},
        })
        self.assertIn('لینک‌بان', self._sent_text(send))

    def test_every_user_can_switch_customer_and_manager(self):
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        me = self.client.get('/miniapp/api/me', {'debug_bale_id': 'cust-1'})
        self.assertEqual(me.status_code, 200, me.content)
        self.assertTrue(me.json()['can_switch_roles'])
        self.assertFalse(me.json()['is_operator'])

    def test_marking_someone_elses_day_is_a_persian_error(self):
        import json
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        denied = self.client.post(
            '/miniapp/api/busy-day',
            data=json.dumps({'tariff_id': self.tariff.id, 'date': '2026-10-08', 'debug_bale_id': 'cust-1'}),
            content_type='application/json',
        )
        self.assertEqual(denied.status_code, 403)
        self.assertIn('کانال شما', denied.json()['message'])


class CriticalMoneyTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='qa', password='pass', bale_user_id='qa-1')
        self.manager = User.objects.create_user(username='qa-mgr', password='pass', bale_user_id='qa-m')
        self.channel = Channel.objects.create(name='تست', link='@linktest', manager=self.manager)
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='تست QA', duration_hours=24, price=1000, start_hour=11
        )

    def _paid_item(self, hours_ahead):
        start = timezone.now() + timedelta(hours=hours_ahead)
        order = Order.objects.create(
            customer=self.customer, status='paid', total_amount=1000, banner_message_id='1'
        )
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=1000,
            manager=self.manager,
            manager_status='approved',
            execution_status='paid',
            duration_hours=24,
        )
        return order

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_pending_banner_is_listed_and_checkout_waits(self, send):
        from orders.banner_publish import banner_stage
        from orders.cart import checkout
        from orders.models import CustomerBanner

        banner = CustomerBanner.objects.create(
            customer=self.customer,
            title='تست QA',
            caption='تست QA - لطفا نادیده بگیرید',
            storage_chat_id='1',
            storage_message_id='9',
            from_linkbank=False,
            media_kind='photo',
        )
        self.assertEqual(banner_stage(banner), 'pending')
        order = Order.objects.create(
            customer=self.customer,
            status='draft',
            banner_message_id='9',
            banner_from_chat_id='1',
            customer_banner=banner,
        )
        start = timezone.now() + timedelta(days=4)
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=1000,
            manager=self.manager,
            manager_status='cart',
            duration_hours=24,
        )
        result = checkout(order)
        self.assertTrue(result.get('ok'), result)
        self.assertTrue(result.get('held_for_banner'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'waiting_banner')
        sent = '\n'.join(str(c.args[1]) for c in send.call_args_list if len(c.args) > 1)
        self.assertNotIn('درخواست تبلیغ تازه', sent)

    @patch('wallet.services.is_operator', return_value=True)
    @patch('integrations.bale_client.forward_message', return_value={'ok': True, 'result': {'message_id': 77}})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_approval_updates_the_same_banner(self, send, _fwd, _op):
        from orders.banner_publish import create_publish_request, operator_decide
        from orders.models import CustomerBanner

        banner = CustomerBanner.objects.create(
            customer=self.customer,
            caption='تست QA - لطفا نادیده بگیرید',
            storage_chat_id='1',
            storage_message_id='15',
            from_linkbank=False,
            media_kind='photo',
        )
        req = create_publish_request(
            self.customer,
            storage_chat_id='1',
            storage_message_id='15',
            caption=banner.caption,
            media_kind='photo',
            banner=banner,
        )['request']
        decided = operator_decide(req.id, 'op', True)
        self.assertTrue(decided.get('ok'), decided)
        banner.refresh_from_db()
        self.assertTrue(banner.from_linkbank)
        self.assertEqual(CustomerBanner.objects.filter(customer=self.customer).count(), 1)
        sent = '\n'.join(str(c.args[1]) for c in send.call_args_list if len(c.args) > 1)
        self.assertIn('تأیید شد و آماده است', sent)

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_customer_can_refund_a_paid_order_into_credit(self, _send):
        from orders.cart import add_to_cart, cancel_customer_order
        from wallet.services import balance_breakdown

        order = self._paid_item(48)
        result = cancel_customer_order(order)
        self.assertTrue(result.get('ok'), result)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(balance_breakdown(self.customer)['credit'], 1000)
        other = User.objects.create_user(username='nextqa', password='pass', bale_user_id='qa-2')
        day = timezone.localtime(order.items.first().requested_start).date()
        opened = add_to_cart(other, self.tariff, day)
        self.assertTrue(opened['ok'], opened)

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_refund_closes_inside_two_hours(self, _send):
        from orders.cart import cancel_customer_order

        order = self._paid_item(1)
        result = cancel_customer_order(order)
        self.assertFalse(result.get('ok'))
        self.assertEqual(result.get('error'), 'too_late')
        self.assertIn('۲ ساعت', result.get('message') or '')
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_a_second_payment_returns_to_credit(self, _send):
        from orders.bale_pay import handle_successful_payment
        from wallet.services import balance_breakdown

        order = Order.objects.create(customer=self.customer, status='waiting_payment', total_amount=1000)
        payload = f'order-{order.id}'

        def pay(charge):
            handle_successful_payment({
                'chat': {'id': 'qa-1'},
                'successful_payment': {
                    'invoice_payload': payload,
                    'total_amount': 10_000,
                    'telegram_payment_charge_id': charge,
                },
            })

        pay('charge-a')
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertEqual(balance_breakdown(self.customer)['credit'], 0)
        pay('charge-a')
        self.assertEqual(balance_breakdown(self.customer)['credit'], 0)
        pay('charge-b')
        self.assertEqual(balance_breakdown(self.customer)['credit'], 1000)

    @patch('orders.bale_pay.bc.create_payment_request', return_value={'ok': True})
    def test_the_same_invoice_is_not_sent_twice_in_a_row(self, create):
        from orders.bale_pay import send_order_invoices

        order = Order.objects.create(customer=self.customer, status='waiting_payment', total_amount=1000)
        first = send_order_invoices(order, 'qa-1')
        second = send_order_invoices(order, 'qa-1')
        self.assertEqual(first['sent'], 1)
        self.assertEqual(second['sent'], 0)
        self.assertEqual(create.call_count, 1)


class MiniappPrefsTests(TestCase):
    def test_theme_and_onboarding_round_trip(self):
        import json
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        saved = self.client.patch(
            '/miniapp/api/me/prefs',
            data=json.dumps({
                'debug_bale_id': 'prefs-1',
                'theme': 'dark',
                'onboarded': {'customer': True},
            }),
            content_type='application/json',
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()['prefs']['theme'], 'dark')
        self.assertTrue(saved.json()['prefs']['onboarded']['customer'])
        again = self.client.get('/miniapp/api/me/prefs', {'debug_bale_id': 'prefs-1'})
        self.assertEqual(again.json()['prefs']['theme'], 'dark')
        me = self.client.get('/miniapp/api/me', {'debug_bale_id': 'prefs-1'})
        self.assertEqual(me.json()['prefs']['theme'], 'dark')
        cleared = self.client.patch(
            '/miniapp/api/me/prefs',
            data=json.dumps({'debug_bale_id': 'prefs-1', 'theme': ''}),
            content_type='application/json',
        )
        self.assertIsNone(cleared.json()['prefs']['theme'])
        self.assertTrue(cleared.json()['prefs']['onboarded']['customer'])


class CalendarHoldTests(TestCase):
    def setUp(self):
        import os

        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.addCleanup(lambda: os.environ.pop('ALLOW_MINIAPP_DEBUG', None))
        self.customer = User.objects.create_user(username='hold-c', password='pass', bale_user_id='hold-c')
        self.other = User.objects.create_user(username='hold-o', password='pass', bale_user_id='hold-o')
        self.manager = User.objects.create_user(username='hold-m', password='pass', bale_user_id='hold-m')
        self.channel = Channel.objects.create(name='hold', link='@hold', manager=self.manager)
        self.day = timezone.localdate() + timedelta(days=5)
        self.tariff = Tariff.objects.create(
            channel=self.channel, name='۲۴ ساعته', duration_hours=24, price=1000, start_hour=11
        )
        self.night = Tariff.objects.create(
            channel=self.channel, name='شبانه', duration_hours=10, price=800, start_hour=22
        )

    def test_waiting_banner_day_is_full(self):
        from orders.availability import classify_day

        start, end = __import__('orders.cart', fromlist=['slot_for_day']).slot_for_day(self.tariff, self.day)
        order = Order.objects.create(customer=self.customer, status='waiting_banner')
        OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=end,
            price=1000,
            manager=self.manager,
            manager_status='pending',
            duration_hours=24,
        )
        self.assertEqual(classify_day(self.tariff, self.day), 'full')
        listed = self.client.get('/miniapp/api/catalog', {'debug_bale_id': 'hold-o'})
        self.assertEqual(listed.status_code, 200, listed.content)
        dates = [row['date'] for row in listed.json()['busy'] if row['tariff_id'] == self.tariff.id]
        self.assertIn(self.day.isoformat(), dates)
        calendar = self.client.get(
            '/miniapp/api/calendar',
            {'tariff_id': self.tariff.id, 'for': 'customer', 'debug_bale_id': 'hold-o'},
        )
        self.assertEqual(calendar.status_code, 200, calendar.content)
        row = next(d for d in calendar.json()['days'] if d['date'] == self.day.isoformat())
        self.assertEqual(row['status'], 'full')
        self.assertFalse(row['free'])
        blocked = add_to_cart(self.other, self.tariff, self.day)
        self.assertEqual(blocked.get('error'), 'slot_conflict')

    def test_overlapping_tariffs_lock_the_channel(self):
        early = Tariff.objects.create(
            channel=self.channel, name='صبح', duration_hours=2, price=400, start_hour=8
        )
        later_day = self.day + timedelta(days=2)
        morning = Tariff.objects.create(
            channel=self.channel, name='پیش از ظهر', duration_hours=4, price=400, start_hour=8
        )
        evening = Tariff.objects.create(
            channel=self.channel, name='عصر', duration_hours=4, price=400, start_hour=18
        )
        first = add_to_cart(self.customer, self.tariff, self.day)
        self.assertTrue(first['ok'], first)
        overlap = add_to_cart(self.other, self.night, self.day)
        self.assertFalse(overlap['ok'])
        self.assertEqual(overlap['error'], 'slot_conflict')
        before = add_to_cart(self.other, early, self.day)
        self.assertTrue(before['ok'], before)
        opened = add_to_cart(self.other, morning, later_day)
        self.assertTrue(opened['ok'], opened)
        beside = add_to_cart(self.customer, evening, later_day)
        self.assertTrue(beside['ok'], beside)

    def test_abandoned_cart_releases_after_the_hold(self):
        from orders.cart import CART_HOLD_MINUTES, release_abandoned_carts

        added = add_to_cart(self.customer, self.tariff, self.day)
        self.assertTrue(added['ok'], added)
        order = added['order']
        order.refresh_from_db()
        self.assertIsNotNone(order.managers_deadline)
        self.assertGreater(
            order.managers_deadline,
            timezone.now() + timedelta(minutes=CART_HOLD_MINUTES - 5),
        )
        listed = self.client.get('/miniapp/api/cart', {'debug_bale_id': 'hold-c'})
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertTrue(listed.json()['hold_until'])
        order.managers_deadline = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['managers_deadline'])
        self.assertEqual(release_abandoned_carts(), 1)
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        again = add_to_cart(self.other, self.tariff, self.day)
        self.assertTrue(again['ok'], again)

    def test_a_passed_start_hour_is_past(self):
        from orders.availability import classify_day

        today = timezone.localdate()
        early = Tariff.objects.create(
            channel=self.channel, name='نیمه‌شب', duration_hours=2, price=100, start_hour=0
        )
        self.assertEqual(classify_day(early, today), 'past')
        blocked = add_to_cart(self.customer, early, today)
        self.assertEqual(blocked.get('error'), 'past')
        calendar = self.client.get(
            '/miniapp/api/calendar',
            {'tariff_id': early.id, 'for': 'customer', 'debug_bale_id': 'hold-c'},
        )
        row = next(d for d in calendar.json()['days'] if d['date'] == today.isoformat())
        self.assertEqual(row['status'], 'past')
        self.assertIn(row['status'], ('free', 'full', 'past'))

    def test_paid_order_closes_when_every_slot_finishes(self):
        from orders.execution import settle_paid_order
        from orders.models import SlotReservation

        start = timezone.now() + timedelta(days=6)
        order = Order.objects.create(customer=self.customer, status='paid', total_amount=1000)
        item = OrderItem.objects.create(
            order=order,
            channel=self.channel,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=1000,
            manager=self.manager,
            manager_status='approved',
            execution_status='executed',
            duration_hours=24,
        )
        self.assertEqual(settle_paid_order(order.id), 'completed')
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        item.execution_status = 'failed_publish'
        item.save(update_fields=['execution_status'])
        order.status = 'paid'
        order.save(update_fields=['status'])
        self.assertTrue(SlotReservation.objects.filter(order_item=item).exists())
        self.assertEqual(settle_paid_order(order.id), 'cancelled')
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertFalse(SlotReservation.objects.filter(order_item=item).exists())

    def test_cancel_phrase_stays_inside_the_window(self):
        from bot_flow.messages import user_error

        self.assertNotIn('لغو نمی‌شود', user_error('not_cancellable'))
        self.assertIn('لغو نمی‌شود', user_error('too_late'))
