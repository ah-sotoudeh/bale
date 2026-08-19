from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('orders', '0005_customer_banner'),
    ]

    operations = [
        migrations.CreateModel(
            name='BannerPublishRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('storage_chat_id', models.CharField(max_length=64)),
                ('storage_message_id', models.CharField(max_length=64)),
                ('caption', models.TextField(blank=True, default='')),
                ('media_kind', models.CharField(blank=True, default='', max_length=20)),
                ('fee_toman', models.IntegerField(default=0)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('approved', 'approved'), ('rejected', 'rejected')], default='pending', max_length=20)),
                ('linkbank_message_id', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='banner_requests', to=settings.AUTH_USER_MODEL)),
                ('customer_banner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='publish_requests', to='orders.customerbanner')),
            ],
        ),
    ]
