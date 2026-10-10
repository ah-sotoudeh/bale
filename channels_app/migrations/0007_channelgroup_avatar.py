from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('channels_app', '0006_channel_ownership_assign'),
    ]
    operations = [
        migrations.AddField(
            model_name='channelgroup',
            name='avatar_channel_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
