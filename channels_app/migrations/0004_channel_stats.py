from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('channels_app', '0003_availabilityslot_slot_tariff_start_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='about',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='channel',
            name='avg_views',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='channel',
            name='bale_peer_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='channel',
            name='citation_index',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name='channel',
            name='daily_reach',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='channel',
            name='err_percent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name='channel',
            name='language',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='channel',
            name='members_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='channel',
            name='posts_per_day',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name='channel',
            name='stats_error',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='channel',
            name='stats_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='ChannelStatSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('taken_at', models.DateTimeField()),
                ('members', models.PositiveIntegerField(default=0)),
                ('avg_views', models.PositiveIntegerField(default=0)),
                ('daily_reach', models.PositiveIntegerField(default=0)),
                ('posts', models.PositiveSmallIntegerField(default=0)),
                ('forwards', models.PositiveIntegerField(default=0)),
                ('source', models.CharField(default='linkyar', max_length=16)),
                (
                    'channel',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='stat_snapshots',
                        to='channels_app.channel',
                    ),
                ),
            ],
            options={
                'ordering': ['taken_at'],
            },
        ),
        migrations.AddIndex(
            model_name='channelstatsnapshot',
            index=models.Index(fields=['channel', 'taken_at'], name='stat_channel_taken_idx'),
        ),
    ]
