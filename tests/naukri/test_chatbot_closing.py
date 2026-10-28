"""Naukri's chatbot ends with a sign-off, not a question. Treating "Thank you for your
responses." as an unanswerable question marked finished applications as abstained."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import chatbot


@pytest.mark.parametrize("message", [
    "Thank you for your responses.",
    "Thanks for your time!",
    "Thank you for applying. We will get back to you shortly.",
    "Your application has been submitted successfully.",
    "All the best for the next steps.",
])
def test_a_sign_off_is_recognised(message):
    assert chatbot.closing_message(message)


@pytest.mark.parametrize("message", [
    "",
    "Thank you. Are you open to relocating to Pune?",
    "How many years of experience do you have in Python?",
    "Please share your current CTC.",
    "What is your notice period?",
])
def test_anything_still_asking_is_not_a_sign_off(message):
    assert not chatbot.closing_message(message)
