"""Every agent answers in the employer's terms and in the candidate's favour, but never falsely.

The stance is one text (common.stance.EMPLOYER_STANCE) that reaches the Naukri chatbot and the
board forms through llm.resolve_answer, the judge, the browser agent's rules (and so the
questionnaire and lead prompts built on task_prompt) and the Gmail reply writer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import answers as answers_module, llm, stance
from common.models import JobPosting, Profile, Settings

POSTING = """About us
We build payments software for banks.

Requirements
- 2+ years of experience with Python and FastAPI
- Hands-on experience with PostgreSQL and Docker
- Strong knowledge of REST API design
- Must be willing to work from our Gurugram office (hybrid)
Benefits: free lunch and a great team.
We offer competitive pay.
"""


def test_requirements_keeps_the_asking_lines_and_drops_the_rest():
    text = stance.requirements(POSTING)
    assert "2+ years of experience with Python and FastAPI" in text
    assert "Must be willing to work from our Gurugram office (hybrid)" in text
    assert "payments software" not in text and "free lunch" not in text and "competitive pay" not in text
    assert stance.requirements("") == ""
    long = "\n".join("- Must know tool number %d very well indeed" % n for n in range(200))
    assert len(stance.requirements(long)) <= stance.MAX_REQUIREMENT_CHARS


class _Client:
    def __init__(self, response=None):
        self.response = response or {"can_answer": False, "answer": "", "grounded_in": "", "confidence": 0.0}
        self.prompts = []
        self.settings = Settings()

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return dict(self.response)


def test_resolve_answer_tells_the_model_the_stance_and_what_the_posting_asks():
    client = _Client()
    llm.resolve_answer(client, Profile(current_location="Gurugram"), "Relevant experience in backend?",
                       job_context={"title": "Backend Engineer", "requirements": "2+ years with FastAPI"})
    prompt = client.prompts[0]
    assert "How to answer, so it reads the way this employer hopes and stays true" in prompt
    assert "Never state what the facts do not make true" in prompt
    assert '"job_requirements": "2+ years with FastAPI"' in prompt
    assert "job_requirements, when present, lists what this posting asks for" in prompt


def test_the_engine_passes_the_postings_requirements_with_the_job(tmp_path):
    class _Ledger:
        def get_answer(self, *a):
            return None

        def save_answer(self, *a, **k):
            pass

        def purge_stale_answers(self, *a):
            return 0

    engine = answers_module.AnswerEngine(_Ledger(), _Client(), Profile(), Settings(data_dir=str(tmp_path)))
    engine.set_job_context(JobPosting(job_id="1", title="Backend Engineer", company="Acme", url="https://x",
                                      location="Gurugram", description=POSTING))
    assert engine.job_context["title"] == "Backend Engineer" and engine.job_context["location"] == "Gurugram"
    assert "Python and FastAPI" in engine.job_context["requirements"]
    engine.set_job_context(JobPosting(job_id="2", title="Other", company="B", url="https://y", description=""))
    assert "requirements" not in engine.job_context


def test_the_judge_and_the_browser_agent_carry_the_stance():
    from sites_bot import browser_agent, replies

    assert "prefer the one that fits THE JOB below" in llm._JUDGE_PROMPT
    assert "How to answer, so it reads the way this employer hopes" in browser_agent._RULES
    assert "Never state what the facts do not make true" in browser_agent._RULES
    assert browser_agent._RULES.index("3. Use only the facts below") < browser_agent._RULES.index("How to answer") < \
        browser_agent._RULES.index("4. Voluntary questions")
    prompt = browser_agent.task_prompt("Answer the questionnaire", "https://cutshort.io/x", "- name: A", "a@b.c",
                                       has_password=False)
    assert "How to answer, so it reads the way this employer hopes" in prompt
    assert "leading with the facts that match what this role asks for" in replies._DRAFT_PROMPT
