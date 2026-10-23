from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0005_bank_label_payout_meta'),
    ]

    operations = [
        migrations.AddField(model_name='payoutbatch', name='file_hash', field=models.CharField(blank=True, db_index=True, default='', max_length=64)),
        migrations.AddField(model_name='payoutbatch', name='status', field=models.CharField(choices=[('open', 'open'), ('processed', 'processed')], default='open', max_length=16)),
        migrations.AddField(model_name='payoutbatch', name='operator_message_id', field=models.CharField(blank=True, default='', max_length=64)),
        migrations.AddField(model_name='payoutbatch', name='result_summary', field=models.CharField(blank=True, default='', max_length=255)),
    ]
