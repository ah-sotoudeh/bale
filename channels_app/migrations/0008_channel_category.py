from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels_app', '0007_channelgroup_avatar'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('news', 'خبری'),
                    ('women', 'بانوان'),
                    ('entertainment', 'سرگرمی'),
                    ('education', 'آموزشی'),
                    ('business', 'کسب‌وکار'),
                    ('tech', 'تکنولوژی'),
                    ('sports', 'ورزشی'),
                    ('lifestyle', 'سبک زندگی'),
                    ('kids', 'کودک'),
                    ('other', 'سایر'),
                ],
                db_index=True,
                default='',
                help_text='موضوع کانال برای فیلتر کاتالوگ',
                max_length=32,
            ),
        ),
    ]
