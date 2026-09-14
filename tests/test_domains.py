# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pytest

from django_siteintel.utils.domains import normalise_domain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("shop.pl", ("shop.pl", "https://shop.pl")),
        ("www.shop.pl/pl", ("shop.pl", "https://www.shop.pl/pl")),
        ("https://sklep.shop.pl/x?y", ("shop.pl", "https://sklep.shop.pl/x?y")),
        ("HTTP://WWW.Shop.com.pl", ("shop.com.pl", "HTTP://WWW.Shop.com.pl")),
        (
            "http://fixtures:8000/fixtures/siteintel/sites/good/index.html",
            ("fixtures", "http://fixtures:8000/fixtures/siteintel/sites/good/index.html"),
        ),
        ("example-shop-1.test", ("example-shop-1.test", "https://example-shop-1.test")),
    ],
)
def test_normalise_domain(raw, expected):
    assert normalise_domain(raw) == expected


def test_myshop_is_not_shop():
    assert normalise_domain("myshop.pl")[0] != normalise_domain("shop.pl")[0]


@pytest.mark.parametrize("raw", ["", "   ", "ftp://shop.pl", "https://"])
def test_invalid_input_raises(raw):
    with pytest.raises(ValueError):
        normalise_domain(raw)
