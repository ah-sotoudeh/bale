from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('orders', '0010_banner_copy_meta'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerBusiness',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('bale', 'کانال بله'), ('external', 'کسب‌وکار خارج از بله')], db_index=True, default='bale', max_length=16)),
                ('source_ref', models.CharField(blank=True, default='', max_length=255)),
                ('name', models.CharField(max_length=160)),
                ('avatar_url', models.URLField(blank=True, default='', max_length=1000)),
                ('categories', models.JSONField(blank=True, default=dict)),
                ('info_source', models.CharField(choices=[('auto', 'خودکار'), ('manual', 'دستی')], default='manual', max_length=16)),
                ('info_checked_at', models.DateTimeField(blank=True, null=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_businesses', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
        migrations.AddIndex(
            model_name='customerbusiness',
            index=models.Index(fields=['customer', 'is_deleted'], name='business_owner_deleted_idx'),
        ),
        migrations.AddField(
            model_name='customerbanner',
            name='business',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='banners', to='orders.customerbusiness'),
        ),
        migrations.CreateModel(
            name='BannerSubmissionDraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, default='', max_length=120)),
                ('caption', models.TextField(blank=True, default='')),
                ('media_kind', models.CharField(blank=True, default='', max_length=20)),
                ('media_path', models.CharField(blank=True, default='', max_length=500)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='banner_drafts', to='orders.customerbusiness')),
                ('customer', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='banner_submission_draft', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
