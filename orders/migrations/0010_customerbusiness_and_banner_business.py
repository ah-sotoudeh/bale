# Compatibility node for environments that recorded this migration name.
from django.db import migrations


class Migration(migrations.Migration):
    """
    Some deploys reported leaf:
      0010_customerbusiness_and_banner_business
    alongside the main chain that ends at 0018_merge_...

    Real CustomerBusiness / BannerSubmissionDraft schema lives in
    0011_customerbusiness_and_banner_draft. This file is a no-op so the
    graph can load and be merged without CreateModel conflicts.
    """

    dependencies = [
        ('orders', '0009_customerbanner_linkyar_forward_ids'),
    ]

    operations = []
