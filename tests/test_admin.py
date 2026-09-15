# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pytest

from django_siteintel.models import ExternalApiKey

STORED_KEY = "TEST-stored-secret"
NEW_KEY = "TEST-new-secret"


@pytest.fixture
def api_key(db) -> ExternalApiKey:
    return ExternalApiKey.objects.create(source="lighthouse", key=STORED_KEY)


@pytest.fixture
def change_url(api_key) -> str:
    return f"/admin/django_siteintel/externalapikey/{api_key.pk}/change/"


def _post(admin_client, change_url, new_key: str):
    data = {"source": "lighthouse", "is_active": "on", "new_key": new_key}
    assert admin_client.post(change_url, data).status_code == 302


def test_item6_admin_change_form_hides_stored_key(admin_client, change_url):
    body = admin_client.get(change_url).content.decode()
    assert STORED_KEY not in body


def test_item6_admin_blank_key_keeps_stored_one(admin_client, change_url, api_key):
    _post(admin_client, change_url, "")
    api_key.refresh_from_db()
    assert api_key.key == STORED_KEY


def test_item6_admin_new_key_replaces_stored_one(admin_client, change_url, api_key):
    _post(admin_client, change_url, NEW_KEY)
    api_key.refresh_from_db()
    assert api_key.key == NEW_KEY
