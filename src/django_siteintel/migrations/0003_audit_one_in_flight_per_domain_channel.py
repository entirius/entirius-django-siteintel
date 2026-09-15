# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("django_siteintel", "0002_audit_run_id_internal_error"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="audit",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("pending", "running"))),
                fields=("domain", "channel_idx"),
                name="siteintel_audit_one_in_flight_per_domain_channel",
            ),
        ),
    ]
