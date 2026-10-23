# Generated merge-compat: server graph expected this node name.
from django.db import migrations


class Migration(migrations.Migration):
    """
    Compatibility node for environments that recorded/created
    0011_banner_submission_draft. Real schema is in
    0011_customerbusiness_and_banner_draft — this file is a no-op leaf
    so a merge can unify the graph.
    """

    dependencies = [
        ('orders', '0010_banner_copy_meta'),
    ]

    operations = []
