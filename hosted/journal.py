import json, os
URL = os.environ.get("DATABASE_URL", "")

def enabled():
    return bool(URL)

def _c():
    import psycopg
    return psycopg.connect(URL, connect_timeout=15, autocommit=True)

def init():
    with _c() as c:
        c.execute("CREATE TABLE IF NOT EXISTS lessons (id BIGSERIAL PRIMARY KEY, task TEXT NOT NULL, tools TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")

def add(task, tools):
    if not URL:
        return False
    with _c() as c:
        c.execute("INSERT INTO lessons (task, tools) VALUES (%s, %s)", (task, json.dumps(tools)))
    return True

def all_lessons():
    if not URL:
        return []
    with _c() as c:
        rows = c.execute("SELECT task, tools FROM lessons ORDER BY id").fetchall()
    return [(r[0], json.loads(r[1])) for r in rows]
