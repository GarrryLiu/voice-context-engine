import json
from .engine import Engine

engine = Engine()
engine.fork("main")
engine.ingest("e1", "main", "session-1", key="database", value="Use PostgreSQL for durable memory")
engine.drain()
engine.fork("alternative", "main")
engine.ingest("e2", "alternative", "session-2", key="database", value="Evaluate SQLite for local development")
engine.drain()
print(json.dumps({"main": engine.recall("main"), "alternative": engine.recall("alternative")}, indent=2))
engine.close()
