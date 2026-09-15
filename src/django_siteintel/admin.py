# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django import forms
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


class ExternalApiKeyForm(forms.ModelForm):
    """`key` is never a form field (it would come back pre-filled): `new_key` is write-only, blank keeps it on edit."""

    new_key = forms.CharField(
        required=False, label="Key", widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the stored key.",
    )  # fmt: skip

    class Meta:
        model = ExternalApiKey
        fields = ("source", "is_active")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance._state.adding:  # a new key has nothing to keep (item 6)
            self.fields["new_key"].required = True
            self.fields["new_key"].help_text = ""

    def save(self, commit: bool = True) -> ExternalApiKey:
        new_key = self.cleaned_data.get("new_key", "").strip()
        if new_key:
            self.instance.key = new_key
        return super().save(commit=commit)


@admin.register(ExternalApiKey)
class ExternalApiKeyAdmin(admin.ModelAdmin):
    form = ExternalApiKeyForm
    list_display = ("source", "masked_key", "is_active", "modified_at")
    list_filter = ("is_active",)
    fields = ("source", "is_active", "new_key")

    @admin.display(description="key")
    def masked_key(self, obj: ExternalApiKey) -> str:
        return "set" if obj.key else "empty"
