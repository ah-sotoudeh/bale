from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('channels_app', '0008_channel_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='forbidden_topics',
            field=models.JSONField(blank=True, default=list, help_text='کدهای موضوع تبلیغ ممنوع (از AD_TOPICS)'),
        ),
        migrations.AddField(
            model_name='channel',
            name='auto_approve_banner',
            field=models.BooleanField(default=False, help_text='تأیید خودکار بنر — بدون بررسی دستی مدیر'),
        ),
        migrations.AddField(
            model_name='channel',
            name='auto_approve_time',
            field=models.BooleanField(default=False, help_text='تأیید خودکار زمان — بدون بررسی دستی تاریخ'),
        ),
        migrations.AddField(
            model_name='channelgroup',
            name='category',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='tariff',
            name='allowed_weekdays',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='channel',
            name='category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('economic', 'اقتصادی و مالی'),
                    ('education_art', 'آموزشی و هنری'),
                    ('news_politics', 'خبری و سیاسی'),
                    ('health', 'سلامت و پزشکی'),
                    ('lifestyle', 'سبک زندگی و خانواده'),
                    ('entertainment', 'سرگرمی و طنز'),
                    ('science_tech', 'علمی و فناوری'),
                    ('shop', 'فروشگاهی'),
                    ('religious', 'مذهبی و فرهنگی'),
                    ('sports', 'ورزشی'),
                    ('services', 'کاربردی و خدماتی'),
                    ('travel', 'گردشگری و طبیعت'),
                    ('other', 'سایر'),
                    ('news', 'خبری'),
                    ('women', 'بانوان'),
                    ('education', 'آموزشی'),
                    ('business', 'کسب‌وکار'),
                    ('tech', 'تکنولوژی'),
                    ('kids', 'کودک'),
                ],
                db_index=True,
                default='',
                help_text='دسته‌بندی موضوعی کانال',
                max_length=32,
            ),
        ),
    ]
