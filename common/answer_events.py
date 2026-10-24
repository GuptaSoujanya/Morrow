"""Private, structured answer-sheet updates carried by the existing run stream."""
import json
import os
from uuid import uuid4


PREFIX = "MORROW_ANSWER_EVENT "


def answer_saved(question: str, answer: str, source: str) -> None:
    token = os.environ.get("MORROW_ANSWER_EVENT_TOKEN")
    if not token:
        return
    event = dict(version=1, id=uuid4().hex, kind="answer_saved",
                 question=" ".join(question.split())[:2000],
                 answer=" ".join(answer.split())[:8000], source=source[:200], token=token)
    try:
        # UTF-8 keeps even 8,000 emoji below the runner's 64 KiB record limit.
        print(PREFIX + json.dumps(event, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        # Saving succeeded even if the dashboard has disconnected from stdout.
        pass
