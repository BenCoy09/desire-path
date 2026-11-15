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
    q("ALTER TABLE lessons ADD COLUMN IF NOT EXISTS before_ids TEXT")
    q("ALTER TABLE lessons ADD COLUMN IF NOT EXISTS after_ids TEXT")
    q("CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, verified BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    q("CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL, expires TIMESTAMPTZ NOT NULL)")

def add(task, tools, uid=None, before=None, after=None):
    if not URL:
        return False
    q("INSERT INTO lessons (task, tools, user_id, before_ids, after_ids) VALUES (%s, %s, %s, %s, %s)",
      (task, json.dumps(tools), uid, json.dumps(before) if before is not None else None, json.dumps(after) if after is not None else None))
    return True

def count(uid):
    return q("SELECT count(*) FROM lessons WHERE user_id=%s", (uid,), one=True)[0]

def all_lessons():
    if not URL:
        return []
    rows = q("SELECT user_id, task, tools FROM lessons ORDER BY id", many=True)
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


def history(limit=50):
    if not URL:
        return []
    rows = q("SELECT task, tools, before_ids, after_ids, created_at::text FROM lessons WHERE user_id IS NULL ORDER BY id DESC LIMIT %s", (limit,), many=True)
    return [{"task": r[0], "tools": json.loads(r[1]), "before": json.loads(r[2]) if r[2] else None,
             "after": json.loads(r[3]) if r[3] else None, "at": r[4][:19]} for r in rows]
