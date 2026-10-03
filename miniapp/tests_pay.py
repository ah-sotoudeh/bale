"""پرداخت از اعتبار و مسیر فاکتور بازو — black-box."""
from django.test import Client, TestCase, override_settings

from channels_app.models import Channel, Tariff
from orders.models import Order, OrderItem
from users.models import User
from wallet.models import WalletLedger
from wallet.services import credit as wallet_credit


@override_settings(ALLOW_MINIAPP_DEBUG=True)
class PayFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.cust = User.objects.create_user(username='payc', password='x', bale_user_id='900100')
        self.mgr = User.objects.create_user(username='paym', password='x', bale_user_id='900200')
        self.ch = Channel.objects.create(name='کانال پرداخت', manager=self.mgr, link='https://ble.ir/c')
        self.tariff = Tariff.objects.create(
            channel=self.ch, name='روزانه', price=50_000, duration_hours=24, start_hour=12, is_active=True,
        )

    def _order_waiting(self, total=50_000):
        from django.utils import timezone
        from datetime import timedelta
        o = Order.objects.create(customer=self.cust, status='waiting_payment', total_amount=total)
        start = timezone.now() + timedelta(days=3)
        OrderItem.objects.create(
            order=o, channel=self.ch, tariff=self.tariff, manager=self.mgr,
            requested_start=start, requested_end=start + timedelta(hours=24),
            price=total, manager_status='approved', execution_status='none',
        )
        return o

    def test_pay_from_credit(self):
        wallet_credit(self.cust, 100_000, 'refund', ref='topup', note='test', idempotency_key='topup:900100')
        o = self._order_waiting()
        r = self.client.post(
            '/miniapp/api/pay/invoice',
            data={'debug_bale_id': '900100', 'order_id': o.id, 'via': 'wallet'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body.get('ok'))
        self.assertEqual(body.get('via'), 'wallet')
        o.refresh_from_db()
        self.assertEqual(o.status, 'paid')

    def test_pay_wallet_low_balance(self):
        o = self._order_waiting(total=80_000)
        r = self.client.post(
            '/miniapp/api/pay/invoice',
            data={'debug_bale_id': '900100', 'order_id': o.id, 'via': 'wallet'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json().get('error'), 'low_balance')

    def test_my_orders_includes_items(self):
        o = self._order_waiting()
        r = self.client.get('/miniapp/api/my-orders', {'debug_bale_id': '900100'})
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json().get('orders') or []
        match = next((x for x in rows if x['id'] == o.id), None)
        self.assertIsNotNone(match)
        self.assertTrue(match.get('items'))
        self.assertEqual(match['items'][0]['price'], 50_000)

    def test_wallet_report_month_earn(self):
        from wallet.services import credit as wallet_credit
        wallet_credit(self.mgr, 120_000, 'earn', ref='item:1', note='test earn', idempotency_key='earn:test:1')
        r = self.client.get('/miniapp/api/wallet', {'debug_bale_id': '900200'})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body.get('ok'))
        report = body.get('report') or {}
        self.assertGreaterEqual(int(report.get('month_earn') or 0), 120_000)

    def test_publish_due_flag_for_manual(self):
        from django.utils import timezone
        from datetime import timedelta
        self.ch.publish_mode = 'manual'
        self.ch.manual_remind_hours = 48
        self.ch.save(update_fields=['publish_mode', 'manual_remind_hours'])
        o = Order.objects.create(customer=self.cust, status='paid', total_amount=50_000)
        start = timezone.now() + timedelta(hours=12)
        it = OrderItem.objects.create(
            order=o, channel=self.ch, tariff=self.tariff, manager=self.mgr,
            requested_start=start, requested_end=start + timedelta(hours=24),
            price=50_000, manager_status='approved', execution_status='paid',
        )
        r = self.client.get('/miniapp/api/orders', {'debug_bale_id': '900200'})
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json().get('orders') or []
        match = next((x for x in rows if x['id'] == it.id), None)
        self.assertIsNotNone(match)
        self.assertTrue(match.get('publish_due'))
