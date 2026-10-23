from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('orders', '0016_business_active_banner')]
    operations = [
        migrations.AddField(model_name='customerbusiness', name='sort_order', field=models.PositiveIntegerField(db_index=True, default=0)),
        migrations.AddField(model_name='customerbusiness', name='last_opened_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='customerbusiness', name='display_name', field=models.CharField(blank=True, default='', max_length=160)),
        migrations.AddField(model_name='customerbusiness', name='channel_unreachable', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='customerbusiness', name='members_count', field=models.PositiveIntegerField(blank=True, null=True)),
    ]
