from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0014_policy_blocks_discounts_reviews'),
    ]

    operations = [
        migrations.AddField(
            model_name='channelreview',
            name='manager_reply',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='channelreview',
            name='manager_replied_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
