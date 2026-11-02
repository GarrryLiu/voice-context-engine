"""Revision-keyed, disposable Redis context cache; PostgreSQL remains authoritative."""
from contextlib import nullcontext
import hashlib
import json
import uuid
from .storage import Postgres


def install_revision(db):
    if not isinstance(db, Postgres):raise ValueError('revision cache requires PostgreSQL')
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_revision (singleton INTEGER PRIMARY KEY, namespace TEXT NOT NULL, revision BIGINT NOT NULL)')
        db.execute('INSERT INTO workspace_revision VALUES (1,?,0) ON CONFLICT DO NOTHING', (uuid.uuid4().hex,))
        db.raw.execute('''CREATE OR REPLACE FUNCTION bump_workspace_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE workspace_revision SET revision=revision+1 WHERE singleton=1; RETURN NULL; END $$''')
        for table in ('branches','events','fork_bases','memory','transcripts','transcript_visibility',
                      'interaction_sessions','replies','response_segments','output_chunks','stage_calls'):
            db.raw.execute(f'DROP TRIGGER IF EXISTS context_revision ON {table}')
            db.raw.execute(f'CREATE TRIGGER context_revision AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION bump_workspace_revision()')


class ContextCache:
    def __init__(self, url, ttl=60):
        import redis
        if not isinstance(ttl, int) or ttl <= 0:raise ValueError('positive TTL required')
        self.redis = redis.Redis.from_url(url, socket_connect_timeout=.05, socket_timeout=.05)
        self.ttl = ttl
        self.hits = self.misses = self.failures = 0

    def context(self, transcripts, branch, query='', budget=4096, count=None):
        db = transcripts.db
        # Custom tokenizers have no stable identity; never share their cache entries.
        if count is not None:return transcripts.context(branch, query, budget, count)
        with (nullcontext() if db.transaction is not None else db):
            row = db.execute('SELECT namespace,revision FROM workspace_revision WHERE singleton=1').fetchone()
            digest = hashlib.sha256(json.dumps([branch, query, budget], ensure_ascii=False).encode()).hexdigest()
            key = f"voice:context:{row['namespace']}:{row['revision']}:{digest}"
            import redis
            try:
                encoded = self.redis.get(key)
                if encoded is not None:
                    result = json.loads(encoded)
                    if isinstance(result, dict) and 'revision' in result and 'text' in result:
                        self.hits += 1
                        return result
            except (redis.RedisError, ValueError, TypeError):self.failures += 1
            self.misses += 1
            result = transcripts.context(branch, query, budget)
            try:self.redis.set(key, json.dumps(result), ex=self.ttl)
            except redis.RedisError:self.failures += 1
            return result

    def close(self):self.redis.close()
