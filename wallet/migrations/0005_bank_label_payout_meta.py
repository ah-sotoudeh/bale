from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0004_alter_walletledger_entry_type'),  # may need adjust
    ]

    operations = [
        migrations.AddField(
            model_name='bankaccount',
            name='label',
            field=models.CharField(blank=True, default='', help_text='نام کوتاه حساب مثلاً شخصی', max_length=64),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='bank_label',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='bank_tx_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='bank_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payouts', to='wallet.bankaccount'),
        ),
    ]
