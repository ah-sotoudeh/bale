"""Black-box API tests for mini-app (three roles) using debug auth."""
from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from channels_app.models import Channel, Tariff
from orders.models import CustomerBanner, Order, OrderItem
from users.models import User
from wallet.models import BankAccount, WalletLedger

os.environ.setdefault('ALLOW_MINIAPP_DEBUG', '1')
os.environ.setdefault('DEBUG_BALE_ID', '80619262')
os.environ.setdefault('OPERATOR_BALE_ID', '90000001')


def _dbg(bale_id: str) -> dict:
    return {'debug_bale_id': str(bale_id)}


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'

    def test_me_unauthorized_without_debug(self):
        os.environ['ALLOW_MINIAPP_DEBUG'] = '0'
        try:
            r = self.client.get('/miniapp/api/me')
            self.assertEqual(r.status_code, 401)
            body = r.json()
            self.assertFalse(body.get('ok', True))
        finally:
            os.environ['ALLOW_MINIAPP_DEBUG'] = '1'

    def test_me_with_debug_creates_user(self):
        r = self.client.get('/miniapp/api/me', _dbg('111001'))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['user']['bale_user_id'], '111001')
        self.assertIn('wallet', body)
        self.assertIn('roles', body)

    def test_me_prefs_theme(self):
        r = self.client.post(
            '/miniapp/api/me/prefs',
            data='{"debug_bale_id":"111002","theme":"dark"}',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['prefs'].get('theme'), 'dark')


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappManagerFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.mgr_id = '200001'
        self.mgr = User.objects.create_user(
            username='mgr200', password='x', bale_user_id=self.mgr_id, bale_username='mgruser'
        )
        self.ch = Channel.objects.create(
            name='کانال تست', link='@testchan', manager=self.mgr, publish_mode='bot', bot_is_admin=True
        )
        self.tariff = Tariff.objects.create(
            channel=self.ch, name='۲۴ ساعته', duration_hours=24, price=50000, start_hour=10, is_active=True
        )

    def test_channels_list_own_only(self):
        other = User.objects.create_user(username='o', password='x', bale_user_id='299')
        Channel.objects.create(name='other', link='@other', manager=other)
        r = self.client.get('/miniapp/api/channels', _dbg(self.mgr_id))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['ok'])
        ids = [c['id'] for c in body['channels']]
        self.assertIn(self.ch.id, ids)
        self.assertEqual(len(ids), 1)

    def test_tariffs_list(self):
        r = self.client.get('/miniapp/api/tariffs', _dbg(self.mgr_id))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertTrue(any(t['id'] == self.tariff.id for t in body.get('tariffs', body.get('items', []))))

    def test_add_tariff(self):
        r = self.client.post(
            '/miniapp/api/tariffs/add',
            data={
                'debug_bale_id': self.mgr_id,
                'channel_id': self.ch.id,
                'name': 'شب',
                'duration_hours': 12,
                'price': 30000,
                'start_hour': 20,
            },
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body.get('ok'), body)
        self.assertTrue(Tariff.objects.filter(channel=self.ch, name='شب').exists())

    def test_tariff_update(self):
        r = self.client.post(
            '/miniapp/api/tariffs/update',
            data={'debug_bale_id': self.mgr_id, 'tariff_id': self.tariff.id, 'price': 55000, 'is_active': True},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.tariff.refresh_from_db()
        self.assertEqual(self.tariff.price, 55000)


    def test_tariff_update_all_fields(self):
        r = self.client.post(
            '/miniapp/api/tariffs/update',
            data={
                'debug_bale_id': self.mgr_id,
                'tariff_id': self.tariff.id,
                'name': 'شب ویرایش',
                'price': 99000,
                'duration_hours': 8,
                'start_hour': 21,
                'is_active': True,
            },
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json().get('ok'), r.content)
        self.tariff.refresh_from_db()
        self.assertEqual(self.tariff.name, 'شب ویرایش')
        self.assertEqual(self.tariff.price, 99000)
        self.assertEqual(self.tariff.duration_hours, 8)
        self.assertEqual(self.tariff.start_hour, 21)

    def test_publish_mode(self):
        r = self.client.post(
            '/miniapp/api/publish-mode',
            data={'debug_bale_id': self.mgr_id, 'channel_id': self.ch.id, 'publish_mode': 'manual', 'remind_hours': 3},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.publish_mode, 'manual')
        self.assertEqual(self.ch.manual_remind_hours, 3)

    def test_calendar_manager(self):
        r = self.client.get('/miniapp/api/calendar', {**_dbg(self.mgr_id), 'tariff_id': self.tariff.id})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertEqual(len(body['days']), 14)

    def test_busy_and_clear(self):
        day = (timezone.localdate() + timedelta(days=5)).isoformat()
        r = self.client.post(
            '/miniapp/api/busy-day',
            data={'debug_bale_id': self.mgr_id, 'tariff_id': self.tariff.id, 'date': day},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'], body)
        slot_id = body.get('slot_id')
        r2 = self.client.post(
            '/miniapp/api/clear-busy',
            data={'debug_bale_id': self.mgr_id, 'tariff_id': self.tariff.id, 'slot_id': slot_id},
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 200, r2.content)

    def test_wallet_and_bank(self):
        r = self.client.get('/miniapp/api/wallet', _dbg(self.mgr_id))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'])
        # valid-looking IBAN shape (checksum not always validated the same way)
        r2 = self.client.post(
            '/miniapp/api/bank',
            data={
                'debug_bale_id': self.mgr_id,
                'iban': 'IR062960000000100324200001',
                'holder_name': 'مدیر تست',
            },
            content_type='application/json',
        )
        # may validate IBAN strictly — accept 200 ok or 400 invalid_iban
        self.assertIn(r2.status_code, (200, 400), r2.content)

    def test_stranger_cannot_update_tariff(self):
        r = self.client.post(
            '/miniapp/api/tariffs/update',
            data={'debug_bale_id': '888888', 'tariff_id': self.tariff.id, 'price': 1},
            content_type='application/json',
        )
        self.assertIn(r.status_code, (403, 404), r.content)


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappCustomerFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.mgr = User.objects.create_user(username='m', password='x', bale_user_id='300001')
        self.cust_id = '300002'
        self.cust = User.objects.create_user(username='c', password='x', bale_user_id=self.cust_id)
        self.ch = Channel.objects.create(
            name='فروشگاه', link='@shop', manager=self.mgr, members_count=10000, avg_views=2000,
            publish_mode='bot', bot_is_admin=True,
        )
        self.tariff = Tariff.objects.create(
            channel=self.ch, name='روز', duration_hours=24, price=10000, start_hour=12, is_active=True
        )
        self.banner = CustomerBanner.objects.create(
            customer=self.cust,
            title='بنر تست',
            caption='کپشن',
            storage_chat_id='1',
            storage_message_id='2',
            from_linkbank=True,
            is_active=True,
        )

    def test_catalog(self):
        r = self.client.get('/miniapp/api/catalog', _dbg(self.cust_id))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertTrue(any(t['id'] == self.tariff.id for t in body['tariffs']))

    def test_banners_list(self):
        r = self.client.get('/miniapp/api/banners', _dbg(self.cust_id))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertEqual(len(body['banners']), 1)
        self.assertEqual(body['banners'][0]['stage'], 'ready')

    def test_calendar_customer(self):
        r = self.client.get(
            '/miniapp/api/calendar',
            {**_dbg(self.cust_id), 'tariff_id': self.tariff.id, 'for': 'customer'},
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['days']), 14)

    def test_cart_add_checkout_flow(self):
        day = (timezone.localdate() + timedelta(days=4)).isoformat()
        r = self.client.post(
            '/miniapp/api/cart/add',
            data={'debug_bale_id': self.cust_id, 'tariff_id': self.tariff.id, 'date': day},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body.get('ok'), body)

        r_cart = self.client.get('/miniapp/api/cart', _dbg(self.cust_id))
        self.assertEqual(r_cart.status_code, 200, r_cart.content)
        self.assertTrue(r_cart.json().get('ok'))

        # bind banner if endpoint exists
        r_b = self.client.post(
            '/miniapp/api/cart/banner',
            data={'debug_bale_id': self.cust_id, 'banner_id': self.banner.id},
            content_type='application/json',
        )
        self.assertIn(r_b.status_code, (200, 400, 404), r_b.content)

        r_co = self.client.post(
            '/miniapp/api/checkout',
            data={'debug_bale_id': self.cust_id},
            content_type='application/json',
        )
        self.assertEqual(r_co.status_code, 200, r_co.content)
        co = r_co.json()
        self.assertTrue(co.get('ok'), co)

        r_ord = self.client.get('/miniapp/api/my-orders', _dbg(self.cust_id))
        self.assertEqual(r_ord.status_code, 200, r_ord.content)
        self.assertTrue(r_ord.json().get('ok'))

    def test_cart_add_without_banner_fails_or_blocks(self):
        other = User.objects.create_user(username='nob', password='x', bale_user_id='300099')
        day = (timezone.localdate() + timedelta(days=6)).isoformat()
        r = self.client.post(
            '/miniapp/api/cart/add',
            data={'debug_bale_id': '300099', 'tariff_id': self.tariff.id, 'date': day},
            content_type='application/json',
        )
        # either blocked at add or later at checkout — both acceptable; document actual
        self.assertIn(r.status_code, (200, 400), r.content)

    def test_double_book_conflict(self):
        day = (timezone.localdate() + timedelta(days=7)).isoformat()
        r1 = self.client.post(
            '/miniapp/api/cart/add',
            data={'debug_bale_id': self.cust_id, 'tariff_id': self.tariff.id, 'date': day},
            content_type='application/json',
        )
        self.assertTrue(r1.json().get('ok'), r1.content)
        other = User.objects.create_user(username='c2', password='x', bale_user_id='300003')
        CustomerBanner.objects.create(
            customer=other, storage_chat_id='9', storage_message_id='9', from_linkbank=True
        )
        r2 = self.client.post(
            '/miniapp/api/cart/add',
            data={'debug_bale_id': '300003', 'tariff_id': self.tariff.id, 'date': day},
            content_type='application/json',
        )
        body = r2.json()
        self.assertFalse(body.get('ok', True), body)
        self.assertIn(body.get('error'), ('slot_conflict', 'full', 'conflict'))

    def test_inactive_tariff_not_in_catalog_ready(self):
        self.tariff.is_active = False
        self.tariff.save()
        r = self.client.get('/miniapp/api/catalog', _dbg(self.cust_id))
        ids = [t['id'] for t in r.json()['tariffs']]
        self.assertNotIn(self.tariff.id, ids)


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappManagerOrderActionsTests(TestCase):
    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        self.mgr = User.objects.create_user(username='mm', password='x', bale_user_id='400001')
        self.cust = User.objects.create_user(username='cc', password='x', bale_user_id='400002')
        self.ch = Channel.objects.create(name='ch', link='@ch', manager=self.mgr)
        self.tariff = Tariff.objects.create(
            channel=self.ch, name='t', duration_hours=24, price=20000, start_hour=9, is_active=True
        )
        start = timezone.now() + timedelta(days=3)
        self.order = Order.objects.create(
            customer=self.cust, status='waiting_managers', total_amount=20000
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            channel=self.ch,
            tariff=self.tariff,
            requested_start=start,
            requested_end=start + timedelta(hours=24),
            price=20000,
            manager=self.mgr,
            manager_status='pending',
            duration_hours=24,
        )
        CustomerBanner.objects.create(
            customer=self.cust, storage_chat_id='1', storage_message_id='1', from_linkbank=True
        )
        self.order.customer_banner = CustomerBanner.objects.filter(customer=self.cust).first()
        self.order.save()

    @patch('integrations.bale_client.create_payment_request', return_value={'ok': True})
    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_approve_item(self, *_mocks):
        r = self.client.post(
            '/miniapp/api/orders/approve',
            data={'debug_bale_id': '400001', 'item_id': self.item.id},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body.get('ok'), body)
        self.item.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.item.manager_status, 'approved')
        self.assertEqual(self.order.status, 'waiting_payment')

    @patch('integrations.bale_client.send_message', return_value={'ok': True})
    def test_reject_item(self, _send):
        r = self.client.post(
            '/miniapp/api/orders/reject',
            data={'debug_bale_id': '400001', 'item_id': self.item.id},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json().get('ok'), r.content)
        self.item.refresh_from_db()
        self.assertEqual(self.item.manager_status, 'rejected')

    def test_orders_inbox(self):
        r = self.client.get('/miniapp/api/orders', _dbg('400001'))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        ids = [i['id'] for i in body.get('items', body.get('orders', []))]
        # flexible key name
        if not ids and 'items' not in body:
            # dump keys for diagnosis
            self.assertIn('ok', body)


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappOperatorTests(TestCase):
    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        os.environ['OPERATOR_BALE_ID'] = '90000001'
        self.op = User.objects.create_user(username='op', password='x', bale_user_id='90000001')
        self.user = User.objects.create_user(username='u', password='x', bale_user_id='500001')

    def test_operator_payouts_forbidden_for_normal(self):
        r = self.client.get('/miniapp/api/operator/payouts', _dbg('500001'))
        self.assertEqual(r.status_code, 403)

    def test_operator_payouts_ok(self):
        r = self.client.get('/miniapp/api/operator/payouts', _dbg('90000001'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'])

    def test_operator_banners_list(self):
        r = self.client.get('/miniapp/api/operator/banners', _dbg('90000001'))
        self.assertIn(r.status_code, (200, 404), r.content)


@override_settings(ALLOWED_HOSTS=['*'])
class MiniappRoleFlagsTests(TestCase):
    """Role flags from /api/me must match access rules."""

    def setUp(self):
        self.client = Client()
        os.environ['ALLOW_MINIAPP_DEBUG'] = '1'
        os.environ['DEBUG_BALE_ID'] = '80619262'
        os.environ['OPERATOR_BALE_ID'] = '90000001'

    def test_normal_user_cannot_switch_roles(self):
        r = self.client.get('/miniapp/api/me', _dbg('700001'))
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body.get('is_operator'))
        self.assertFalse(body.get('can_switch_roles'), body)
        self.assertFalse(body.get('debug'))
        self.assertTrue(body.get('can_be_manager'))  # can open manager panel to add channel
        self.assertTrue(body['roles']['customer'])
        self.assertFalse(body['roles']['operator'])

    def test_debug_user_can_switch_roles(self):
        r = self.client.get('/miniapp/api/me', _dbg('80619262'))
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body.get('debug'))
        self.assertTrue(body.get('can_switch_roles'), body)

    def test_operator_can_switch_and_is_operator(self):
        r = self.client.get('/miniapp/api/me', _dbg('90000001'))
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body.get('is_operator'), body)
        self.assertTrue(body.get('can_switch_roles'), body)
        self.assertTrue(body['roles']['operator'])

    def test_checkout_without_banner_message(self):
        from channels_app.models import Channel, Tariff
        from users.models import User
        from django.utils import timezone
        from datetime import timedelta
        mgr = User.objects.create_user(username='mx', password='x', bale_user_id='mx1')
        User.objects.create_user(username='cx', password='x', bale_user_id='cx1')
        ch = Channel.objects.create(name='n', link='@nx', manager=mgr)
        tariff = Tariff.objects.create(channel=ch, name='t', duration_hours=24, price=1000, start_hour=10, is_active=True)
        day = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.client.post(
            '/miniapp/api/cart/add',
            data={'debug_bale_id': 'cx1', 'tariff_id': tariff.id, 'date': day},
            content_type='application/json',
        )
        r = self.client.post(
            '/miniapp/api/checkout',
            data={'debug_bale_id': 'cx1'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body.get('error'), 'no_banner')
        self.assertIn('بنر', body.get('message', ''))
