from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0012_publish_retry_and_tickets'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerbusiness',
            name='primary_topic',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='customerbusiness',
            name='secondary_topics',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
