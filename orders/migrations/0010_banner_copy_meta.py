from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0009_customerbanner_linkyar_forward_ids'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerbanner',
            name='bot_file_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='ly_file_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='ly_file_access_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='ly_file_size',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='ly_file_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='ly_mime_type',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
    ]
