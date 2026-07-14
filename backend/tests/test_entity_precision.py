from app.services.entity_service import looks_like_a_date, valid_israeli_id
from app.services.ner_service import extract_entities

# Everything here was found in the real 113-file case, reported to the user as
# a finding. All of it was false.
SAMPLE = (
    "IMG-20210705-WA0001.jpg הגיע. רכב 12-345-67 ורכב 123-45-678. "
    "ת.ז 317960771, ות.ז 900000000. טלפון 054-991-2233."
)


def test_a_date_in_a_filename_is_not_a_vehicle_plate():
    # all 232 "vehicle plates" in the real case were dates out of WhatsApp
    # filenames — there was not one real plate among them
    assert looks_like_a_date("20210705")
    plates = [e["text"] for e in extract_entities(SAMPLE) if e["label"] == "vehicle_plate"]
    assert not any("20210705" in p for p in plates)


def test_an_id_number_is_not_also_a_vehicle_plate():
    # the plate pattern was \d{2,3}-\d{2,3}-\d{2,3}, so every 9-digit ID matched
    plates = [e["text"] for e in extract_entities(SAMPLE) if e["label"] == "vehicle_plate"]
    assert not any(len(p.replace("-", "").replace(" ", "")) == 9 for p in plates)
    assert "12-345-67" in plates      # a real 7-digit plate survives
    assert "123-45-678" in plates     # and a real 8-digit one


def test_an_israeli_id_must_pass_its_check_digit():
    # half the "IDs" found in the real case were junk (900000000, 800708974...)
    assert valid_israeli_id("317960771")
    assert not valid_israeli_id("900000000")
    ids = [e["text"] for e in extract_entities(SAMPLE) if e["label"] == "israeli_id"]
    assert ids == ["317960771"]


def test_the_model_cannot_leak_its_internal_tags_as_entity_types():
    # raw NER codes were reaching the user as entity types — "duc", "ang",
    # "misc" — carrying values like "ip", "mn" and ". 2"
    allowed = {
        "person", "organization", "location", "time", "title",
        "phone", "israeli_id", "vehicle_plate", "name", "hebrew_term",
    }
    labels = {e["label"] for e in extract_entities(SAMPLE)}
    assert labels <= allowed, f"unexpected entity types leaked: {labels - allowed}"
