from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    # شناسه عددی کاربر در بله
    bale_user_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    # آیدی عمومی بدون @ مثلا linkpakhsh
    bale_username = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    def __str__(self):
        if self.bale_username:
            return f'@{self.bale_username}'
        return self.username if self.username else (self.bale_user_id or 'user')

    @property
    def bale_handle(self) -> str:
        if self.bale_username:
            return f'@{str(self.bale_username).lstrip("@")}'
        return str(self.bale_user_id or '')


class BotSession(models.Model):
    """وضعیت گفتگوی چندمرحله‌ای کاربر با ربات"""

    bale_user_id = models.CharField(max_length=64, unique=True, db_index=True)
    state = models.CharField(max_length=64, default='idle')
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.bale_user_id}:{self.state}'
