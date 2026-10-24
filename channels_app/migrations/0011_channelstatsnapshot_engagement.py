from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('channels_app', '0010_alter_channel_publish_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='channelstatsnapshot',
            name='engagement',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
    ]
