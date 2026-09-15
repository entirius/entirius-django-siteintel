# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import migrations, models
from django.utils import timezone

IN_FLIGHT = ("pending", "running")
DUPLICATE_DETAIL = "duplicate in-flight audit failed by migration 0003"


def fail_duplicate_in_flight_audits(apps, schema_editor) -> None:
    """Keep the newest pending/running audit per (domain, channel); fail the older ones and their open reports."""
    Audit = apps.get_model("django_siteintel", "Audit")
    Report = apps.get_model("django_siteintel", "Report")
    seen, duplicates = set(), []
    for audit in Audit.objects.filter(status__in=IN_FLIGHT).order_by("-created_at").only("domain", "channel_idx"):
        key = (audit.domain, audit.channel_idx)
        if key in seen:
            duplicates.append(audit.pk)
        seen.add(key)
    now = timezone.now()
    Report.objects.filter(audit_id__in=duplicates, status__in=IN_FLIGHT).update(
        status="failed", error_code="internal", error_detail=DUPLICATE_DETAIL, modified_at=now
    )
    Audit.objects.filter(pk__in=duplicates).update(status="failed", modified_at=now)


class Migration(migrations.Migration):
    dependencies = [
        ("django_siteintel", "0002_audit_run_id_internal_error"),
    ]

    operations = [
        migrations.RunPython(fail_duplicate_in_flight_audits, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="audit",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("pending", "running"))),
                fields=("domain", "channel_idx"),
                name="siteintel_audit_one_in_flight_per_domain_channel",
            ),
        ),
    ]
