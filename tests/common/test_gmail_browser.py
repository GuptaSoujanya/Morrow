"""A native Gmail signature is allowed; unexpected pitch/footer changes are not."""
from types import SimpleNamespace

import pytest

from common.gmail_browser import body_matches


class Body:
    def __init__(self, text, signatures=()):
        self.text, self.signatures = text, signatures

    def get_attribute(self, _):
        return self.text

    def find_elements(self, *_):
        return [SimpleNamespace(get_attribute=lambda _, text=text: text) for text in self.signatures]


@pytest.mark.parametrize('text,signatures,expected', [
    ('My résumé is attached.', (), True),
    ('My résumé is attached.\n\nJane Doe\nhttps://jane.dev', ('Jane Doe\nhttps://jane.dev',), True),
    ('My résumé is attached.\n\nJane Doe', (), False),
    ('My résumé is attached.\nBest regards,\nJane Doe', ('Jane Doe',), False),
    ('My résumé is attached.\nJane Doe\nUnexpected extra text', ('Jane Doe',), False),
    ('A changed pitch.\nJane Doe', ('Jane Doe',), False),
    ('Jane Doe', ('Jane Doe',), False),
    ('My résumé is attached.\nJane Doe\nJane Doe', ('Jane Doe',), False),
])
def test_reconcile_only_accepts_exact_pitch_and_native_signature(text, signatures, expected):
    assert body_matches(Body(text, signatures), 'My résumé is attached.') is expected


def test_existing_signed_drafts_still_reconcile_without_rewriting():
    body = 'My résumé is attached.\n\nJane Doe'
    assert body_matches(Body(body), body)


def test_missing_signature_fails_when_verifying_the_complete_new_draft():
    assert not body_matches(Body('My résumé is attached.'), 'My résumé is attached.\n\nJane Doe')
