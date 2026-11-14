"""Sign up, email verification, login, and the private workspace API."""
import hashlib, hmac, json, os, re, secrets, time, urllib.request
import journal, learn

PUBLIC = os.environ.get("PUBLIC_URL", "").rstrip("/")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HITS = {}


def _hash(pw):
    s = secrets.token_bytes(16)
    return s.hex() + ":" + hashlib.scrypt(pw.encode(), salt=s, n=2**14, r=8, p=1).hex()


def _check(pw, stored):
    s, h = stored.split(":")
    return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(s), n=2**14, r=8, p=1).hex(), h)


def _tok(uid, kind, hours):
    t = secrets.token_urlsafe(32)
    journal.q("INSERT INTO tokens (hash, user_id, kind, expires) VALUES (%s, %s, %s, now() + (%s || ' hours')::interval)",
              (hashlib.sha256(t.encode()).hexdigest(), uid, kind, str(hours)))
    return t


def _use(t, kind, consume):
    h = hashlib.sha256(str(t).encode()).hexdigest()
    row = journal.q("SELECT user_id FROM tokens WHERE hash=%s AND kind=%s AND expires > now()", (h, kind), one=True)
    if row and consume:
        journal.q("DELETE FROM tokens WHERE hash=%s", (h,))
    return row[0] if row else None


def _cookie(t, age=2592000):
    return f"dp_session={t}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={age}"


def _sess(h):
    m = re.search(r"dp_session=([\w\-]+)", h.headers.get("Cookie", ""))
    return m.group(1) if m else ""


def _me(h):
    uid = _use(_sess(h), "session", False)
    row = journal.q("SELECT id, email FROM users WHERE id=%s AND verified", (uid,), one=True) if uid else None
    if not row:
        raise PermissionError("please log in")
    return row


def _ip(h):
    return h.headers.get("X-Forwarded-For", "").split(",")[0].strip() or h.client_address[0]


def _limit(ip):
    now = time.time()
    hits = [t for t in HITS.get(ip, []) if now - t < 600]
    if len(hits) >= 10:
        raise RuntimeError("too many attempts, wait a few minutes")
    HITS[ip] = hits + [now]


def _mail(to, link):
    key, sender = os.environ.get("BREVO_API_KEY"), os.environ.get("MAIL_FROM")
    if not key or not sender:
        return False
    body = json.dumps({"sender": {"email": sender, "name": "Desire Path"}, "to": [{"email": to}],
                       "subject": "Verify your Desire Path account",
                       "htmlContent": f'<p>Welcome to Desire Path.</p><p><a href="{link}">Verify your email</a> (valid 24 hours).</p>'}).encode()
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", body,
                                 {"api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


def _send(h, code, obj=None, cookie=None, loc=None):
    b = json.dumps(obj or {}).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    if loc:
        h.send_header("Location", loc)
    if cookie:
        h.send_header("Set-Cookie", cookie)
    h.send_header("Content-Length", str(len(b)))
    h.end_headers()
    h.wfile.write(b)


def _route(h, m, p, q, b):
    if not journal.enabled():
        raise RuntimeError("accounts need the database (DATABASE_URL)")
    if m == "POST" and p in ("/auth/signup", "/auth/login"):
        _limit(_ip(h))
        email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
        if p == "/auth/signup":
            if not EMAIL.match(email) or len(email) > 200:
                raise ValueError("enter a valid email")
            if len(pw) < 8:
                raise ValueError("password must be at least 8 characters")
            row = journal.q("SELECT id, verified FROM users WHERE email=%s", (email,), one=True)
            if row and row[1]:
                raise ValueError("this email is already registered, log in instead")
            if row:
                uid = row[0]
                journal.q("UPDATE users SET pw=%s WHERE id=%s", (_hash(pw), uid))
            else:
                uid = journal.q("INSERT INTO users (email, pw) VALUES (%s, %s) RETURNING id", (email, _hash(pw)), one=True)[0]
            link = f"{PUBLIC or 'https://' + h.headers.get('Host', '')}/auth/verify?token={_tok(uid, 'verify', 24)}"
            sent = _mail(email, link)
            out = {"ok": True, "emailed": sent}
            if not os.environ.get("BREVO_API_KEY"):
                out["demo_link"] = link
            return _send(h, 200, out)
        row = journal.q("SELECT id, pw, verified FROM users WHERE email=%s", (email,), one=True)
        if not row or not _check(pw, row[1]):
            raise PermissionError("wrong email or password")
        if not row[2]:
            raise PermissionError("verify your email first (check your inbox and spam)")
        return _send(h, 200, {"ok": True}, cookie=_cookie(_tok(row[0], "session", 720)))
    if m == "GET" and p == "/auth/verify":
        uid = _use(q.get("token", [""])[0], "verify", True)
        if not uid:
            return _send(h, 400, {"error": "link expired or already used"})
        journal.q("UPDATE users SET verified=true WHERE id=%s", (uid,))
        return _send(h, 302, {}, cookie=_cookie(_tok(uid, "session", 720)), loc="/dashboard.html")
    if m == "POST" and p == "/auth/logout":
        _use(_sess(h), "session", True)
        return _send(h, 200, {"ok": True}, cookie=_cookie("", 0))
    u = _me(h)
    if p == "/me":
        return _send(h, 200, {"email": u[1], "lessons": journal.count(u[0])})
    if p == "/my/select":
        task = q.get("task", [""])[0].strip()
        if not task:
            raise ValueError("task is required")
        tools, info, ms = learn.user_select(u[0], task, max(1, min(int(q.get("k", ["5"])[0]), 20)))
        if info.get("fallback"):
            return _send(h, 200, {"tools": [], "no_confident_match": True, "traversal_ms": ms})
        return _send(h, 200, {"tools": [{"name": t["name"], "server": t.get("server")} for t in tools], "traversal_ms": ms})
    if p == "/my/lessons":
        rows = journal.q("SELECT task, tools, created_at::text FROM lessons WHERE user_id=%s ORDER BY id DESC LIMIT 50", (u[0],), many=True)
        return _send(h, 200, {"lessons": [{"task": r[0], "tools": json.loads(r[1]), "at": r[2][:16]} for r in rows]})
    if m == "POST" and p == "/my/learn":
        return _send(h, 200, learn.teach_user(u[0], b.get("task", ""), b.get("tools") or []))
    _send(h, 404, {"error": "not found"})


def handle(h, method, path, q, body):
    if not (path.startswith("/auth/") or path.startswith("/my/") or path == "/me"):
        return False
    try:
        _route(h, method, path, q, body or {})
    except ValueError as e:
        _send(h, 400, {"error": str(e)})
    except PermissionError as e:
        _send(h, 401, {"error": str(e)})
    except RuntimeError as e:
        _send(h, 429, {"error": str(e)})
    except Exception as e:
        _send(h, 503, {"error": "server error: " + type(e).__name__})
    return True
