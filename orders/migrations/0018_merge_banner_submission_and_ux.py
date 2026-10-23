# Merge parallel orders leaves
from django.db import migrations


class Migration(migrations.Migration):
    """
    Unify:
      - 0011_banner_submission_draft (compat / alternate branch)
      - 0017_business_ux_fields (main chain via customerbusiness)
    """

    dependencies = [
        ('orders', '0011_banner_submission_draft'),
        ('orders', '0017_business_ux_fields'),
    ]

    operations = []
