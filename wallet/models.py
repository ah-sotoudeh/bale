"""Wallet, bank accounts, and payout requests for managers and customers."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class BankAccount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_accounts'
    )
    iban = models.CharField(max_length=34)  # IR + 24 digits
    holder_name = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'iban')]

    def __str__(self):
        return f'{self.holder_name} {self.iban[-4:]}'


class WalletLedger(models.Model):
    """Append-only ledger. Amounts in Toman (positive credit, negative debit)."""

    TYPE_CHOICES = [
        ('earn', 'Earn'),  # manager after executed ad
        ('refund', 'Refund'),  # customer credit on cancel / failed publish
        ('penalty', 'Penalty'),  # manager 14% fine
        ('payout_lock', 'PayoutLock'),
        ('payout_paid', 'PayoutPaid'),
        ('payout_unlock', 'PayoutUnlock'),  # if request cancelled
        ('spend', 'Spend'),  # use wallet balance on new order (future)
        ('adjust', 'Adjust'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ledger'
    )
    amount = models.IntegerField(help_text='تومان؛ مثبت = افزایش موجودی')
    entry_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    ref = models.CharField(max_length=64, blank=True, default='')
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'{self.user_id} {self.entry_type} {self.amount}'


class PayoutRequest(models.Model):
    STATUS = [
        ('pending', 'pending'),
        ('paid', 'paid'),
        ('rejected', 'rejected'),
        ('cancelled', 'cancelled'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payouts'
    )
    amount_toman = models.PositiveIntegerField()
    amount_rial = models.PositiveIntegerField()
    iban = models.CharField(max_length=34)
    holder_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    batch = models.ForeignKey(
        'PayoutBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requests',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Payout #{self.id} {self.amount_toman}t {self.status}'


class PayoutBatch(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payout_batches',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    file_text = models.TextField(blank=True, default='')
    note = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return f'Batch #{self.id}'
