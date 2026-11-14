import json, os
URL = os.environ.get("DATABASE_URL", "")

def enabled():
    return bool(URL)

def _c():
    import psycopg
    return psycopg.connect(URL, connect_timeout=15, autocommit=True)

def q(sql, args=(), one=False, many=False):
    with _c() as c:
        cur = c.execute(sql, args)
        if one:
            return cur.fetchone()
        if many:
            return cur.fetchall()

def init():
    q("CREATE TABLE IF NOT EXISTS lessons (id BIGSERIAL PRIMARY KEY, task TEXT NOT NULL, tools TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    q("ALTER TABLE lessons ADD COLUMN IF NOT EXISTS user_id BIGINT")
    q("CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, verified BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    q("CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL, expires TIMESTAMPTZ NOT NULL)")

def add(task, tools, uid=None):
    if not URL:
        return False
    q("INSERT INTO lessons (task, tools, user_id) VALUES (%s, %s, %s)", (task, json.dumps(tools), uid))
    return True

def count(uid):
    return q("SELECT count(*) FROM lessons WHERE user_id=%s", (uid,), one=True)[0]

def all_lessons():
    if not URL:
        return []
    rows = q("SELECT user_id, task, tools FROM lessons ORDER BY id", many=True)
    return [(r[0], r[1], json.loads(r[2])) for r in rows]
