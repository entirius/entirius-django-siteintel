# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_siteintel.models import Audit, ExternalApiKey, Report


class ReportInline(admin.TabularInline):
    model = Report
    extra = 0
    can_delete = False
    fields = ("source", "status", "retry_count", "duration_s", "error_code", "error_detail", "processed", "modified_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("domain", "status", "channel_idx", "requested_by", "expires_at", "created_at")
    list_filter = ("status", "channel_idx")
    search_fields = ("domain", "requested_by")
    readonly_fields = ("id", "domain", "url", "channel_idx", "status", "requested_by", "expires_at")
    inlines = [ReportInline]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(ExternalApiKey)
class ExternalApiKeyAdmin(admin.ModelAdmin):
    list_display = ("source", "masked_key", "is_active", "modified_at")
    list_filter = ("is_active",)

    @admin.display(description="key")
    def masked_key(self, obj: ExternalApiKey) -> str:
        return "set" if obj.key else "empty"
