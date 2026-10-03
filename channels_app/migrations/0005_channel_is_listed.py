from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels_app', '0004_channel_stats'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='is_listed',
            field=models.BooleanField(
                default=True,
                help_text='اگر False باشد از کاتالوگ مشتری مخفی است؛ سفارش‌ها می‌مانند',
            ),
        ),
    ]
