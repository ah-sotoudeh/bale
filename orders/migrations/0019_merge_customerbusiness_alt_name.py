# Merge alternate leaf name with unified graph
from django.db import migrations


class Migration(migrations.Migration):
    """
    Unify:
      - 0018_merge_banner_submission_and_ux (main graph)
      - 0010_customerbusiness_and_banner_business (compat / misnamed leaf)
    """

    dependencies = [
        ('orders', '0018_merge_banner_submission_and_ux'),
        ('orders', '0010_customerbusiness_and_banner_business'),
    ]

    operations = []
