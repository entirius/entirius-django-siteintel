# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_utils.models.base_model import BaseModel


class ExternalApiKey(BaseModel):
    """API key of one source. Read at fetch time only — never logged, never returned by the API."""

    source = models.CharField(max_length=32, unique=True)
    key = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.source
