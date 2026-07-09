import httpx

class CaseMindApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    def list_evidence(self) -> list[dict]:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{self.base_url}/evidence")
            r.raise_for_status()
            return r.json()

    def import_file(self, path: str) -> dict:
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{self.base_url}/evidence/import-file", json={"path": path})
            r.raise_for_status()
            return r.json()

    def semantic_search(self, query: str, limit: int = 10) -> list[dict]:
        with httpx.Client(timeout=30) as client:
            r = client.get(f"{self.base_url}/search/semantic", params={"q": query, "limit": limit})
            r.raise_for_status()
            return r.json()

    def ask_ai(self, question: str) -> dict:
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{self.base_url}/ai/ask", json={"question": question})
            r.raise_for_status()
            return r.json()
