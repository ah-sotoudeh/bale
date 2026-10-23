from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0015_review_manager_reply'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerbusiness',
            name='active_banner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='active_for_businesses', to='orders.customerbanner'),
        ),
    ]
