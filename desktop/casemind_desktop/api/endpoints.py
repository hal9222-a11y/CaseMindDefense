HEALTH = "/health"

EVIDENCE = "/evidence"
EVIDENCE_IMPORT_FILE = "/evidence/import-file"
EVIDENCE_IMPORT_FOLDER = "/evidence/import-folder"

SEARCH = "/search"
SEMANTIC_SEARCH = "/search/semantic"
AI_ASK = "/ai/ask"

TIMELINE = "/timeline"
ENTITIES = "/entities"
ENTITY_GRAPH = "/entities/graph"
CASES = "/cases"
CONTRADICTIONS = "/contradictions"
AUDIT = "/audit"


def evidence_content(evidence_id: int) -> str:
    return f"/evidence/{evidence_id}/content"