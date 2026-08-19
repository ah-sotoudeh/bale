from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('orders', '0004_alter_orderitem_channel_message_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerBanner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, default='', max_length=120)),
                ('caption', models.TextField(blank=True, default='')),
                ('storage_chat_id', models.CharField(max_length=64)),
                ('storage_message_id', models.CharField(max_length=64)),
                ('from_linkbank', models.BooleanField(default=False)),
                ('linkbank_chat_id', models.CharField(blank=True, default='', max_length=64)),
                ('linkbank_message_id', models.CharField(blank=True, default='', max_length=64)),
                ('media_kind', models.CharField(blank=True, default='', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='banners', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-id']},
        ),
        migrations.AddField(
            model_name='order',
            name='customer_banner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='orders', to='orders.customerbanner'),
        ),
    ]
