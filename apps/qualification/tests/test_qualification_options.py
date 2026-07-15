"""Unit tests for deterministic qualification option normalization."""

from __future__ import annotations

import pytest

from apps.qualification.domain.qualification_options import (
    normalize_customer_type,
    normalize_project_type,
    normalize_referral_source,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("new", "new_customer"),
        ("New customer", "new_customer"),
        ("first time", "new_customer"),
        ("1", "new_customer"),
        ("I'm a new customer", "new_customer"),
        ("existing", "existing_customer"),
        ("Existing customer", "existing_customer"),
        ("already a customer", "existing_customer"),
        ("returning", "existing_customer"),
        ("2", "existing_customer"),
        # Project descriptions must not be read as a customer type.
        ("I need a new website", None),
        ("upgrade my website", None),
        ("", None),
        ("maybe", None),
    ],
)
def test_normalize_customer_type(message, expected):
    assert normalize_customer_type(message) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("عميل جديد", "new_customer"),
        ("جديد", "new_customer"),
        ("عميل حالي", "existing_customer"),
        ("حالي", "existing_customer"),
        ("عميل موجود", "existing_customer"),
        # Arabic project description at the customer-type step is not a customer type.
        ("موقع جديد", None),
    ],
)
def test_normalize_customer_type_accepts_arabic_labels(message, expected):
    assert normalize_customer_type(message) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("google", "google"),
        ("Google search", "google"),
        ("1", "google"),
        ("instagram", "instagram"),
        ("insta", "instagram"),
        ("2", "instagram"),
        ("facebook", "facebook"),
        ("fb", "facebook"),
        ("3", "facebook"),
        ("friend", "friend_referral"),
        ("a friend referred me", "friend_referral"),
        ("referral", "friend_referral"),
        ("4", "friend_referral"),
        ("other", "other"),
        ("5", "other"),
        ("", None),
    ],
)
def test_normalize_referral_source(message, expected):
    assert normalize_referral_source(message) == expected


@pytest.mark.parametrize(
    ("button_payload", "expected"),
    [
        ("google", "google"),
        ("instagram", "instagram"),
        ("facebook", "facebook"),
        ("friend_referral", "friend_referral"),
        ("other", "other"),
    ],
)
def test_normalize_referral_source_accepts_twilio_button_ids(button_payload, expected):
    assert (
        normalize_referral_source("ignored label", button_payload=button_payload)
        == expected
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("جوجل", "google"),
        ("قوقل", "google"),
        ("إنستغرام", "instagram"),
        ("انستغرام", "instagram"),
        ("فيسبوك", "facebook"),
        ("صديق", "friend_referral"),
        ("إحالة", "friend_referral"),
        ("ترشيح", "friend_referral"),
        ("أخرى", "other"),
        ("غير ذلك", "other"),
    ],
)
def test_normalize_referral_source_accepts_arabic_labels(message, expected):
    assert normalize_referral_source(message) == expected


@pytest.mark.parametrize(
    ("message", "button_payload", "expected"),
    [
        (None, "new_website", "new_website"),
        (None, "website_upgrade", "website_upgrade"),
        (None, "both", "new_and_upgrade"),
        ("New website", "new_website", "new_website"),
        ("Upgrade existing website", "website_upgrade", "website_upgrade"),
        ("Both", "both", "new_and_upgrade"),
    ],
)
def test_normalize_project_type_accepts_twilio_button_ids(
    message, button_payload, expected
):
    assert (
        normalize_project_type(message, button_payload=button_payload) == expected
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("موقع جديد", "new_website"),
        ("تحديث موقع موجود", "website_upgrade"),
        ("ترقية موقع حالي", "website_upgrade"),
        ("كلاهما", "new_and_upgrade"),
        ("كليهما", "new_and_upgrade"),
    ],
)
def test_normalize_project_type_accepts_arabic_labels(message, expected):
    assert normalize_project_type(message) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("new website", "new_website"),
        ("new", "new_website"),
        ("build website", "new_website"),
        ("1", "new_website"),
        ("upgrade", "website_upgrade"),
        ("existing website", "website_upgrade"),
        ("redesign", "website_upgrade"),
        ("improve website", "website_upgrade"),
        ("2", "website_upgrade"),
        ("both", "new_and_upgrade"),
        ("3", "new_and_upgrade"),
        ("", None),
        ("hello there", None),
    ],
)
def test_normalize_project_type(message, expected):
    assert normalize_project_type(message) == expected
