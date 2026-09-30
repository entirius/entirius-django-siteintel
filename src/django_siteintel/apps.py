# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from django.apps import AppConfig


class DjangoSiteintelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_siteintel"
    label = "django_siteintel"
    is_volkanos = True

    def ready(self) -> None:
        from django_siteintel import checks  # noqa: F401 — registers the configuration health checks
