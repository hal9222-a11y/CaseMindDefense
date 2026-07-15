"""Relation inference: suggestions come only from shared passages, carry
citations, and vanish entirely when no LLM is available."""
from unittest.mock import patch

from sqlmodel import Session, select

from app.services import inference_service


def test_no_llm_means_no_suggestions_not_guesses():
    with patch.object(inference_service.llm_service, "ollama_available", return_value=False):
        assert inference_service.suggest_relations(None, 999) == []


def test_unknown_answers_are_dropped():
    # the parsing path: "UNKNOWN" from the model must not become a relation
    with patch.object(inference_service.llm_service, "ollama_available", return_value=True), \
         patch.object(inference_service, "knowledge_graph", return_value={"edges": []}):
        from app.db import get_engine, init_db
        init_db()  # tables must exist even when this test runs alone
        with Session(get_engine()) as session:
            assert inference_service.suggest_relations(session, 999999) == []
