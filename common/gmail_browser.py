"""Save and re-open drafts using Morrow's already signed-in Google browser.

Only compose, upload, save/close and search are used. There is no send action.
Unknown account, ambiguous matches and interrupted writes fail closed.
"""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlsplit

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from . import connections


class DraftVerificationError(ValueError):
    pass


def available(settings, sender):
    if not connections.managed_profile(settings.browser_profile_dir):
        return False
    state = connections.read_metadata(Path(settings.browser_profile_dir)).get('google', {})
    return (state.get('state') == 'connected'
            and str(state.get('verified_account', '')).strip().lower() == sender.lower())


def draft_content(raw, sender, recipient):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if (parseaddr(str(msg['From']))[1].lower() != sender.lower()
            or [address.lower() for _, address in getaddresses(msg.get_all('To', []))] != [recipient.lower()]
            or msg.get('Cc') or msg.get('Bcc')):
        raise DraftVerificationError('Draft sender or recipient does not match the selected account.')
    part = msg.get_body(preferencelist=('plain',))
    attachments = list(msg.iter_attachments())
    if part is None or len(attachments) != 1:
        raise DraftVerificationError('A plain-text pitch and one PDF résumé are required.')
    attachment = attachments[0]
    filename = attachment.get_filename() or ''
    payload = attachment.get_payload(decode=True) or b''
    if Path(filename).name != filename or not filename.lower().endswith('.pdf') or not payload.startswith(b'%PDF-'):
        raise DraftVerificationError('The draft does not contain a valid PDF résumé.')
    subject, body = str(msg['Subject'] or '').strip(), part.get_content().strip()
    if not subject or not body or len(payload) > 20 * 1024 * 1024:
        raise DraftVerificationError('The pitch is empty or its résumé exceeds 20 MB.')
    return subject, body, filename, payload


def normalize(value):
    return ' '.join(str(value).split())


class GmailDrafts:
    def __init__(self, settings, sender, driver_factory=connections.create_driver):
        self.settings, self.sender, self.factory = settings, sender, driver_factory
        self.driver = None
        self.mutated = False
        self.account_url = ''

    def __enter__(self):
        try:
            self.driver = self.factory(self.settings)
            self.driver.get(self.url('#drafts'))
            self.wait(lambda d: d.find_elements(By.CSS_SELECTOR, '[role=main]'))
            self.check_account()
            self.account_url = self.driver.current_url.split('#', 1)[0].split('?', 1)[0]
            if self.visible('input[name=subjectbox]'):
                raise DraftVerificationError('Close the open Gmail compose window before starting this run.')
            return self
        except (TimeoutException, WebDriverException) as exc:
            self.__exit__(None, None, None)
            raise DraftVerificationError('Could not open Gmail in the saved Google session. Check Google / Gmail in Connections and retry.') from exc
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None

    def wait(self, condition, seconds=30):
        return WebDriverWait(self.driver, seconds, poll_frequency=.3).until(condition)

    def url(self, fragment):
        if self.account_url:
            return self.account_url + fragment
        return 'https://mail.google.com/mail/u/?authuser=' + quote(self.sender) + fragment

    def visible(self, css):
        return [e for e in self.driver.find_elements(By.CSS_SELECTOR, css) if e.is_displayed()]

    def check_account(self):
        if urlsplit(self.driver.current_url).hostname != 'mail.google.com':
            raise DraftVerificationError('Sign in to Gmail in Connections before preparing drafts.')
        labels = [e.get_attribute('aria-label') or '' for e in self.visible('[aria-label^="Google Account:"]')]
        emails = {email.lower() for label in labels for email in re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', label)}
        if emails != {self.sender.lower()}:
            raise DraftVerificationError('Gmail is open under a different or unverified account. Check Connections.')

    def compose(self):
        self.wait(lambda d: d.find_element(By.XPATH, "//*[@role='button' and normalize-space(.)='Compose']")).click()
        self.wait(lambda _: self.visible('input[name=subjectbox]'))

    def close_compose(self):
        buttons = self.visible('[aria-label="Save & close"]')
        if len(buttons) != 1:
            raise DraftVerificationError('Gmail’s save control could not be identified safely.')
        buttons[0].click()
        self.wait(lambda _: not self.visible('input[name=subjectbox]'))

    def search(self, subject, recipient):
        safe_subject = subject.replace('"', ' ').replace('\\', ' ')
        query = f'in:anywhere to:({recipient}) subject:"{safe_subject}"'
        self.driver.get(self.url('#search/' + quote(query, safe='')))
        self.wait(lambda d: d.find_elements(By.CSS_SELECTOR, '[role=main]'))
        self.check_account()
        def results(_):
            searches = self.visible('input[aria-label="Search mail"]')
            if not searches or searches[0].get_attribute('value').strip() != query:
                return False
            mains = self.visible('[role=main]')
            if not mains:
                return False
            rows = [e for e in mains[0].find_elements(By.CSS_SELECTOR, 'tr[role=row]') if e.is_displayed()]
            if rows and all(normalize(subject) in normalize(row.text) for row in rows):
                return ('rows', rows)
            if any(text in mains[0].text for text in ('No conversations found', 'No results found', 'No messages matched your search')):
                return ('empty', [])
            return False
        return self.wait(results)[1]

    def verify_open(self, subject, body, filename, recipient):
        subjects = self.visible('input[name=subjectbox]')
        if len(subjects) != 1 or subjects[0].get_attribute('value') != subject:
            return False
        region = subjects[0].find_element(By.XPATH, 'ancestor::*[@role="region" and @data-compose-id][1]')
        bodies = region.find_elements(By.CSS_SELECTOR, '[contenteditable=true][role=textbox]')
        recipients = {e.get_attribute('email').lower() for e in region.find_elements(By.CSS_SELECTOR, '[email]') if e.get_attribute('email')}
        # Gmail's current recipient chips use data-hovercard-id on the visible address.
        recipients.update(e.get_attribute('data-hovercard-id').lower() for e in region.find_elements(By.CSS_SELECTOR, '[data-hovercard-id]') if '@' in (e.get_attribute('data-hovercard-id') or ''))
        return (recipients == {recipient.lower()} and len(bodies) == 1
                and normalize(bodies[0].get_attribute('innerText')) == normalize(body)
                and filename in region.text
                and not region.find_elements(By.CSS_SELECTOR, '[role=progressbar]'))

    def wait_verified(self, subject, body, filename, recipient):
        try:
            self.wait(lambda _: self.verify_open(subject, body, filename, recipient))
        except TimeoutException as exc:
            raise DraftVerificationError('The saved draft or résumé did not pass verification. Review Gmail Drafts.') from exc

    def save(self, row, uncertain=False):
        self.mutated = False
        subject, body, filename, payload = draft_content(Path(row['data']['eml']).read_bytes(), self.sender, row['recipient'])
        matches = self.search(subject, row['recipient'])
        if len(matches) > 1:
            raise DraftVerificationError('Multiple matching messages need review in Gmail; no extra draft was created.')
        if matches:
            if not re.search(r'\bDraft\b', matches[0].text):
                raise DraftVerificationError('A matching message already exists outside Drafts; review it before retrying.')
            matches[0].click()
            self.wait(lambda _: self.visible('input[name=subjectbox]'))
            self.wait_verified(subject, body, filename, row['recipient'])
            self.close_compose()
            return self.driver.current_url
        if uncertain:
            raise DraftVerificationError('The earlier save could not be located. Review Gmail Drafts before retrying manually.')
        self.check_account()
        if self.visible('input[name=subjectbox]'):
            raise DraftVerificationError('An existing Gmail compose window needs attention.')
        self.compose()
        # Mark uncertainty before the first field is changed: Gmail autosaves.
        self.mutated = True
        recipient = self.wait(lambda _: self.visible('input[aria-label="To recipients"]'))[0]
        recipient.send_keys(row['recipient'], Keys.TAB)
        self.visible('input[name=subjectbox]')[0].send_keys(subject)
        message = self.visible('[contenteditable=true][aria-label="Message Body"]')[0]
        message.click()
        # Replace any Gmail signature with the exact already-signed local pitch.
        import sys
        message.send_keys(Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL, 'a', Keys.NULL)
        message.send_keys(Keys.BACKSPACE)
        message.send_keys(body)
        with tempfile.TemporaryDirectory(prefix='morrow-resume-') as folder:
            attachment = Path(folder) / filename
            attachment.write_bytes(payload)
            attachment.chmod(0o600)
            self.driver.find_element(By.CSS_SELECTOR, 'input[type=file][name=Filedata]').send_keys(str(attachment))
            self.wait(lambda _: self.verify_open(subject, body, filename, row['recipient']), seconds=90)
            self.close_compose()
        matches = self.search(subject, row['recipient'])
        if len(matches) != 1 or not re.search(r'\bDraft\b', matches[0].text):
            raise DraftVerificationError('Gmail has not confirmed one saved draft. Review it before retrying.')
        matches[0].click()
        self.wait(lambda _: self.visible('input[name=subjectbox]'))
        self.wait_verified(subject, body, filename, row['recipient'])
        self.close_compose()
        return self.driver.current_url
