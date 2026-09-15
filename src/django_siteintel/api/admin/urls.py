# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API URL routing — manual `path()` per Volkanos convention."""

from django.urls import path

from django_siteintel.api.admin.views.audit_views import AuditDetailView, AuditListView, AuditRerunView
from django_siteintel.api.admin.views.test_views import ExpireNowView, RunNowView, is_development

urlpatterns = [
    path("audits/", AuditListView.as_view(), name="admin-siteintel-audits"),
    path("audits/<uuid:audit_id>/", AuditDetailView.as_view(), name="admin-siteintel-audit-detail"),
    path("audits/<uuid:audit_id>/rerun/", AuditRerunView.as_view(), name="admin-siteintel-audit-rerun"),
]

if is_development():
    urlpatterns += [
        path("test/run-now/<uuid:audit_id>/", RunNowView.as_view(), name="admin-siteintel-test-run-now"),
        path("test/expire-now/", ExpireNowView.as_view(), name="admin-siteintel-test-expire-now"),
    ]
