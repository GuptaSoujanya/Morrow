import logging
from datetime import datetime

import pytest

from common import run
from common.models import Settings


@pytest.mark.parametrize(
    "name, label",
    [
        ("ranking", "ranking"),
        ("naukri_bot.cli", "naukri"),
        ("naukri_bot.sources", "naukri search"),
        ("naukri_bot.apply", "naukri apply"),
        ("naukri_bot.auth", "naukri sign-in"),
        ("startup_bot.cli", "startups"),
        ("sites_bot.startup_jobs", "startup jobs"),
        ("sites_bot.browser_agent", "browser agent"),
        ("sites_bot.cold_email", "cold email"),
        ("sites_bot.external", "company site"),
        ("sites_bot.platforms", "boards"),
        ("sites_bot.profile_agent", "profile agent"),
        ("common.company_outreach", "company emails"),
        ("common.llm", "llm"),
        ("common.run", "run"),
        ("pipeline.run", "run"),
        ("urllib3.connectionpool", "http"),
        ("selenium.webdriver.remote", "selenium"),
    ],
)
def test_logger_names_become_plain_words(name, label):
    assert run.log_label(name) == label


def test_the_kept_log_names_the_part_at_work_not_the_module(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    settings = Settings(email="e", password="p", report_dir=str(tmp_path))
    path = run.keep_log(settings, "startups", now=datetime(2026, 11, 3, 19, 18, 50))
    try:
        logging.getLogger("sites_bot.startup_jobs").info("YC startup jobs: 31")
        logging.getLogger("ranking").info("Startup jobs: 2 go to the LLM")
        logging.getLogger("__main__").info("done")
    finally:
        for handler in list(logging.getLogger().handlers):
            if isinstance(handler, run._KeptLog):
                logging.getLogger().removeHandler(handler)
                handler.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert path.name == "startups-191850.log"
    assert "INFO    run            This run's log:" in lines[0]
    assert "INFO    startup jobs   YC startup jobs: 31" in lines[1]
    assert "INFO    ranking        Startup jobs: 2 go to the LLM" in lines[2]
    assert "INFO    startups       done" in lines[3]
    assert not any("_bot." in line for line in lines)
