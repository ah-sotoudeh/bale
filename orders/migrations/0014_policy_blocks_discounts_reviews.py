from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('channels_app', '0009_channel_settings_topics'),
        ('orders', '0013_business_topics'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='time_change_count',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='manager_reminded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='ManagerCustomerBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocked_by_managers', to=settings.AUTH_USER_MODEL)),
                ('manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocked_customers', to=settings.AUTH_USER_MODEL)),
            ],
            options={'unique_together': {('manager', 'customer')}},
        ),
        migrations.CreateModel(
            name='TariffDiscount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, default='', max_length=120)),
                ('percent', models.PositiveSmallIntegerField(default=0)),
                ('fixed_amount', models.PositiveIntegerField(default=0)),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tariff_discounts', to=settings.AUTH_USER_MODEL)),
                ('tariffs', models.ManyToManyField(blank=True, related_name='discounts', to='channels_app.tariff')),
            ],
        ),
        migrations.CreateModel(
            name='ChannelReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.PositiveSmallIntegerField()),
                ('body', models.TextField(blank=True, default='')),
                ('views_count', models.PositiveIntegerField(default=0)),
                ('reactions_count', models.PositiveIntegerField(default=0)),
                ('banner_link', models.CharField(blank=True, default='', max_length=500)),
                ('tariff_name', models.CharField(blank=True, default='', max_length=120)),
                ('executed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_hidden', models.BooleanField(default=False)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to='channels_app.channel')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='channel_reviews', to=settings.AUTH_USER_MODEL)),
                ('order_item', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='review', to='orders.orderitem')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
