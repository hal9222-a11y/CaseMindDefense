import tempfile
from pathlib import Path

from app.services.evidence_service import SUPPORTED_EXTENSIONS
from app.services.text_service import extract_text
from app.services.transcription_service import MEDIA_EXTENSIONS, VIDEO_EXTENSIONS

# a real forensic interception manifest keeps its data in attributes
WIRETAP_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Product Switch_start_time="13-07-2021 23:08:39" Target="2021-342020" '
    'Product_type="Voice" Comment="שיחה רלוונטית" Identified_party="גבר-אישה 2" />'
)


def test_forensic_xml_attributes_are_extracted():
    p = Path(tempfile.mktemp(suffix=".xml"))
    p.write_text(WIRETAP_XML, encoding="utf-8")
    text, method = extract_text(p)
    assert method == "text"
    # the evidence lives in attributes, which a plain itertext() would miss
    assert "2021-342020" in text          # Target
    assert "שיחה רלוונטית" in text          # Hebrew comment
    assert "13-07-2021" in text            # timestamp


def test_malformed_xml_falls_back_to_stripped_text():
    p = Path(tempfile.mktemp(suffix=".xml"))
    p.write_text("<broken><unclosed Target='X999'>call log text", encoding="utf-8")
    text, _ = extract_text(p)
    assert "call log text" in text
    assert "<" not in text  # tags stripped


def test_xml_and_dvd_video_are_supported():
    assert ".xml" in SUPPORTED_EXTENSIONS
    assert ".vob" in VIDEO_EXTENSIONS and ".vob" in MEDIA_EXTENSIONS
    assert ".vob" in SUPPORTED_EXTENSIONS


def test_disc_structure_and_config_are_still_skipped():
    # not evidence content — importing them would only add noise (and the folder
    # import already reports them as skipped)
    for ext in (".ifo", ".bup", ".end", ".ini"):
        assert ext not in SUPPORTED_EXTENSIONS
