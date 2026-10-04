from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels_app', '0005_channel_is_listed'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='ownership_verified',
            field=models.BooleanField(
                default=False,
                help_text='اگر True باشد پشتیبان مالک را تعیین کرده؛ چک بیو لازم نیست',
            ),
        ),
        migrations.AddField(
            model_name='channel',
            name='pending_manager_username',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='username بدون @؛ بعد از ورود کاربر به manager وصل می‌شود',
                max_length=255,
            ),
        ),
    ]
