"""The UFED Reader Report.xml parser turns the folder-extraction format (flat
<contacts>/<sms_message> sections, no chats) into SMS conversations + a phone
book, grouped by counterparty and attributed to name+phone."""
from pathlib import Path

from app.services.ufed_reader_service import extract_ufed_reader, is_ufed_reader_report

SAMPLE = """<?xml version='1.0' encoding='utf-8'?>
<reports><report>
  <contacts>
    <contact><id>1</id><name>Dima</name>
      <phone_number><designation>Mobile</designation><value>+972528772478</value></phone_number>
    </contact>
  </contacts>
  <sms_message><id>1</id><number>+972528772478</number><name>Dima</name>
    <timestamp>2021-06-13T20:53:08+03:00</timestamp><type>Incoming</type>
    <text>are you coming tonight</text></sms_message>
  <sms_message><id>2</id><number>+972528772478</number><name>Dima</name>
    <timestamp>2021-06-13T20:55:00+03:00</timestamp><type>Outgoing</type>
    <text>yes in ten minutes</text></sms_message>
  <sms_message><id>3</id><number>999</number><name>N/A</name>
    <timestamp>2016-01-29T11:49:35+02:00</timestamp><type>Incoming</type>
    <text>your verification code is 2961</text></sms_message>
</report></reports>
"""


def test_detects_and_parses_sms_and_contacts(tmp_path):
    f = tmp_path / "Report.xml"
    f.write_text(SAMPLE, encoding="utf-8")
    assert is_ufed_reader_report(f) is True

    data = extract_ufed_reader(f)
    # phone book
    assert data["contacts"]["972528772478"] == "Dima"
    # two counterparties -> two SMS threads (Dima + the 999 shortcode)
    labels = {c["name"] for c in data["chats"]}
    assert "SMS_Dima" in labels

    dima = next(c for c in data["chats"] if c["name"] == "SMS_Dima")
    text = "\n".join(ch["text"] for ch in dima["chunks"])
    assert "are you coming tonight" in text and "yes in ten minutes" in text
    # the counterparty rides along as a speaker (name + phone) for graph linking
    speakers = {s for ch in dima["chunks"] for s in ch["speakers"]}
    assert "Dima" in speakers and "+972528772478" in speakers


def test_not_a_reader_report(tmp_path):
    f = tmp_path / "other.xml"
    f.write_text("<project><model type='Chat'/></project>", encoding="utf-8")
    assert is_ufed_reader_report(f) is False
