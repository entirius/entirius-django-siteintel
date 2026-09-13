# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import re
from io import StringIO
from pathlib import Path

from django.core.management import call_command

SRC = Path(__file__).resolve().parent.parent / "src" / "django_siteintel"


def test_no_sleep_in_package():
    offenders = [str(path) for path in SRC.rglob("*.py") if re.search(r"\bsleep\s*\(", path.read_text())]
    assert offenders == []


def test_openapi_schema_validates(tmp_path):
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "schema.yaml"))


def test_migrations_are_complete(db):
    call_command("makemigrations", "django_siteintel", "--check", "--dry-run", stdout=StringIO())
