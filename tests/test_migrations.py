# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import importlib
from datetime import timedelta

from django.apps import apps
from django.db import connection
from django.utils import timezone

from django_siteintel.enums import AuditStatus, ReportStatus
from django_siteintel.models import Audit, Report
from tests.conftest import CHANNEL_IDX, DOMAIN

migration_0003 = importlib.import_module("django_siteintel.migrations.0003_audit_one_in_flight_per_domain_channel")


def _audit(age_minutes: int, status: str = AuditStatus.PENDING, domain: str = DOMAIN) -> Audit:
    audit = Audit.objects.create(
        domain=domain, url=f"https://{domain}/", channel_idx=CHANNEL_IDX, status=status, requested_by="t",
        expires_at=timezone.now() + timedelta(days=1),
    )  # fmt: skip
    Audit.objects.filter(pk=audit.pk).update(created_at=timezone.now() - timedelta(minutes=age_minutes))
    Report.objects.create(audit=audit, source="heuristic")
    return audit


def test_item5_migration_fails_all_but_newest_duplicate_in_flight_audit(db):
    """Postgres DDL is transactional: the constraint dropped here comes back with the test's rollback."""
    constraint = Audit._meta.constraints[0]
    with connection.schema_editor() as editor:
        editor.remove_constraint(Audit, constraint)
    oldest, older, newest = _audit(30), _audit(20, AuditStatus.RUNNING), _audit(10)
    other = _audit(40, domain="other-shop.test")

    with connection.schema_editor() as editor:
        migration_0003.fail_duplicate_in_flight_audits(apps, editor)
        editor.add_constraint(Audit, constraint)

    statuses = dict(Audit.objects.values_list("pk", "status"))
    assert [statuses[a.pk] for a in (oldest, older, newest, other)] == ["failed", "failed", "pending", "pending"]
    assert set(Report.objects.filter(audit__in=[oldest, older]).values_list("status", "error_detail")) == {
        (ReportStatus.FAILED, migration_0003.DUPLICATE_DETAIL)
    }
