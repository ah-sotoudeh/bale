from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_sync_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerbanner',
            name='linkyar_rid',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='linkyar_date',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='linkyar_seq',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
