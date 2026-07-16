"""Unit tests for post-booking link reply selection."""

from __future__ import annotations

from apps.qualification.domain.post_booking_link_response import build_post_booking_link_reply


def test_post_booking_wellbeing_reply():
    reply = build_post_booking_link_reply(message="How are you?", language="en")
    assert "doing well" in reply
    assert "booking link above" in reply


def test_post_booking_greeting_reply():
    reply = build_post_booking_link_reply(message="Hi bro", language="en")
    assert reply.startswith("Hi.")
    assert "booking link above" in reply


def test_post_booking_thanks_reply():
    reply = build_post_booking_link_reply(message="Thanks", language="en")
    assert "welcome" in reply.lower()
    assert "booking link above" in reply


def test_post_booking_exit_reply():
    reply = build_post_booking_link_reply(message="Exit chat", language="en")
    assert "message us again anytime" in reply


def test_post_booking_resend_request_reply():
    reply = build_post_booking_link_reply(message="Send link again", language="en")
    assert "already shared above" in reply


def test_post_booking_default_reply_matches_contract():
    reply = build_post_booking_link_reply(message="", language="en")
    assert reply == "Please use the booking link above whenever you're ready."


def test_post_booking_default_reply_arabic_matches_contract():
    reply = build_post_booking_link_reply(message="", language="ar")
    assert reply == "يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا."
