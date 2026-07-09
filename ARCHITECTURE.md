\# CaseMind Defense Architecture



\## 1. Overview



CaseMind Defense is a local-first Evidence Management and Investigation Intelligence platform.



The system is designed around three independent layers:



```mermaid

flowchart TD

&#x20;   Desktop\[PySide6 Desktop Client]

&#x20;   Backend\[FastAPI Backend]

&#x20;   Agents\[Future AI Agent Layer]

&#x20;   DB\[(SQLite Database)]

&#x20;   Store\[(Evidence Store)]



&#x20;   Desktop --> Backend

&#x20;   Agents --> Backend

&#x20;   Backend --> DB

&#x20;   Backend --> Store

