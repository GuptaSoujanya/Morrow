"""user/inputs/persona.yaml: who the writer, the card and the study plan speak as."""

from pathlib import Path

from common import persona


def test_a_missing_file_gives_a_neutral_persona(tmp_path):
    who = persona.load_persona(tmp_path / "nope.yaml")
    assert not who.is_set
    assert (who.they, who.them, who.their) == ("they", "them", "their")
    assert who.learner_line().startswith("a software engineer")
    block = who.voice_block()
    assert "claim nothing about the author" in block and "How they writes" in block


def test_a_persona_round_trips_and_knows_its_pronouns(tmp_path):
    path = tmp_path / "persona.yaml"
    who = persona.Persona(name="Asha Rao", pronouns="she/her", headline="data engineer at Acme",
                          experience_years=4, location="Pune", site="asha.example",
                          focus="streaming pipelines", facts=["Built the Kafka ingestion"],
                          voice="plain and short", voice_sample="I move data.", topics=["Kafka", "Spark"],
                          study_areas=[persona.StudyArea("kafka", "Kafka and streams")], goal="staff interviews")
    persona.save_persona(who, path)
    back = persona.load_persona(path)
    assert back.name == "Asha Rao" and back.path == path and back.is_set
    assert (back.they, back.them, back.their) == ("she", "her", "her")
    assert back.learner_line() == "a data engineer at Acme (about 4 years of experience, streaming pipelines)"
    assert back.topics == ["Kafka", "Spark"]
    assert back.study_areas == [persona.StudyArea("kafka", "Kafka and streams")]
    block = back.voice_block()
    assert "- Asha Rao, data engineer at Acme." in block and "- Built the Kafka ingestion." in block
    assert "- Site: asha.example" in block and "How she writes: plain and short" in block
    assert 'in her own words: "I move data."' in block


def test_unknown_pronouns_and_odd_values_do_not_break_it(tmp_path):
    who = persona.from_mapping({"name": 7, "pronouns": "xe/xem", "facts": "one fact", "topics": None,
                                "study_areas": ["Kafka and streams", {"title": "Spark"}, {"slug": "x"}],
                                "experience_years": "2.5"}, Path("p.yaml"))
    assert who.name == "7" and who.they == "they"          # unknown sets fall back to they/them
    assert who.facts == ["one fact"] and who.topics == []
    assert who.experience_years == 2.5
    assert [(a.slug, a.title) for a in who.study_areas] == [("kafka-and-streams", "Kafka and streams"), ("spark", "Spark")]
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    assert not persona.load_persona(bad).is_set


def test_slugify_makes_file_name_pieces():
    assert persona.slugify("LLM-as-judge & the council!") == "llm-as-judge-the-council"
    assert persona.slugify("  ") == "area"
