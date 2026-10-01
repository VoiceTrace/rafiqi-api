# Booting a real stack for QA

Read before Phase 1. Every trap below has actually produced a wrong QA result in
this project. They are cheap to avoid and expensive to diagnose.

## Facts you will need, so you do not have to go looking

| Thing | Value |
|---|---|
| Python | `.venv/Scripts/python.exe` from `rafiqi-api/` — not bare `python` |
| Seeded teacher | `teacher@alnoor.edu.sa` / `teacher123` |
| Seeded students | `student@alnoor.edu.sa`, `student2@alnoor.edu.sa` / `student123` |
| Get a token | `POST /auth/login` `{"email": ..., "password": ...}` → `access_token` |
| Auth header | `Authorization: Bearer <access_token>` |
| Alembic reads | `DATABASE_URL_SYNC` (psycopg2 URL) |
| App and seed read | `DATABASE_URL` (asyncpg URL) |
| Frontend reads | `API_URL` (server) **and** `NEXT_PUBLIC_API_URL` (client) |
| Frontend port | `npm run dev` has no port flag — use `npx next dev -p <port>` |

Shell environment variables override `.env` and `.env.local`, which is what makes a
one-off QA stack possible. Worth knowing: `rafiki-frontend/.env.local` points at
`http://localhost:8000`, which is usually **not** the API you just started.

## Shell variables do not survive between commands

Each Bash tool call is a fresh shell, so `QA_PORT=5439` set in one call is gone in the
next. Write your choices to a file in the scratchpad once, then source it at the top
of every later command — otherwise you will drift onto a default port mid-pass and
attach to the wrong stack:

```bash
cat > "$SCRATCH/qa.env" <<'EOF'
QA_DB=rafiqi-qa-3f9c21
QA_PORT=5439
API_PORT=8021
FE_PORT=3141
EOF

# every later call starts with:
source "$SCRATCH/qa.env"
```

Store PIDs the same way (`$SCRATCH/api.pid`, `$SCRATCH/fe.pid`) so teardown can find
them after any number of intervening calls.

A token, in one line:

```bash
TOKEN=$(curl -s -X POST localhost:$API_PORT/auth/login -H "Content-Type: application/json" \
  -d '{"email":"student@alnoor.edu.sa","password":"student123"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

Commands here are written for the Bash tool. PowerShell is this machine's primary
shell — if you use it, `VAR=x cmd` becomes `$env:VAR="x"; cmd`, and `&&` is not
available. Write scratch files and logs to your **scratchpad directory**, not `/tmp`.

## The rule underneath all of this

**Never trust a process you did not start.** Something answering on the right port
is not evidence it is your database, your code, or even this project. Verify
identity at each step. The cost is seconds; the cost of skipping it is debugging
correct code.

## 1. Find out what is actually on the port

`localhost:5432` responding does not mean the project's database is answering. On
this machine, postgres instances have repeatedly competed for 5432 — a Docker
container and separate local installs, including one started by another coding
agent under `C:\Users\IT\Documents\Codex\...`.

The giveaway is misleading:

```
FATAL: password authentication failed for user "rafiqi"
```

This reads like a credentials problem. It usually means the credentials are correct
and you are talking to the **wrong postgres** — one that has never heard of that user.

Identify the owner before changing anything:

```bash
docker ps --format "{{.Names}}\t{{.Ports}}"

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5432 -State Listen |
  ForEach-Object { Get-Process -Id \$_.OwningProcess |
  Select-Object Id,ProcessName,StartTime,Path } | Format-List"
```

`Path` tells you whose it is. `StartTime` tells you whether it is stale.

Also note: `localhost` may resolve to IPv6 `::1` while a container binds IPv4
`0.0.0.0`. If one host form fails and the other works, that is what happened —
prefer `127.0.0.1` to force IPv4.

### When the port is taken by something that is not yours

Do not kill it. It may hold another agent's or a teammate's state, and killing it
is not reversible. Start your own instance on a free port instead.

**Choose a unique name and port — do not copy the ones below.** A previous QA pass
left a `rafiqi-qa-db` on 5433, so the obvious choice is often already taken. Pick
something session-specific and check it is free first:

```bash
QA_DB="rafiqi-qa-$(date +%H%M%S)"
QA_PORT=5434    # bump until free

# Confirm nothing holds it, and no container owns the name:
netstat -ano | grep ":$QA_PORT " || echo "port free"
docker ps -a --format "{{.Names}}" | grep -x "$QA_DB" && echo "NAME TAKEN — pick another"

docker run -d --name "$QA_DB" \
  -e POSTGRES_USER=rafiqi -e POSTGRES_PASSWORD=rafiqi -e POSTGRES_DB=rafiqi_test \
  -p $QA_PORT:5432 postgres:16-alpine
```

Additive, isolated, and removable with `docker rm -f "$QA_DB"` when you are done.
Carry `$QA_PORT` through every later command rather than hardcoding a number.

Apply the same reasoning to the API and frontend ports. `8000` and `3000` are
routinely occupied here; `8001`/`3100` are habits, not guarantees. Check, then choose.

Only stop a process when the user asks, or when you started it yourself this session.

## 2. Migrate a dedicated test database

Never point QA at a database holding real or dev data — the suite drops and recreates
tables. Use a database whose name ends in `_test`; the integration fixtures refuse
anything else, which is a guard worth keeping.

```bash
DATABASE_URL_SYNC="postgresql+psycopg2://rafiqi:rafiqi@127.0.0.1:$QA_PORT/rafiqi_test" \
  .venv/Scripts/python.exe -m alembic upgrade head
```

Alembic reads `DATABASE_URL_SYNC`; the app and `seed.py` read `DATABASE_URL`. Setting
only one is a common way to migrate one database and then run against another.

Watch the output for the final revision. If it says "Running upgrade" for revisions
you do not recognise from this branch, you are migrating the wrong database.

## 3. Seed, then check the seed satisfies the feature

`scripts/seed.py` creates a school, a teacher, and students. Running it is not enough —
**confirm the seeded data meets the feature's preconditions.**

Real example: homework is distributed to a whole grade, matching on
`User.grade_level`. The seed script did not set `grade_level`, so every seeded student
had `NULL`, distribution matched nobody, and the feature could not be demonstrated at
all in a fresh environment. Nothing errored. The list was simply empty.

Before trusting the environment, ask what the feature filters on and verify the
seeded rows satisfy it:

```bash
docker exec "$QA_DB" psql -U rafiqi -d rafiqi_test \
  -c "SELECT email, role, grade_level FROM users;"
```

If the seed cannot support the feature, fix the seed — that is a real defect, since
every developer hits it.

## 4. Start the API, then prove two things about it

```bash
DATABASE_URL="postgresql+asyncpg://rafiqi:rafiqi@127.0.0.1:$QA_PORT/rafiqi_test" \
  nohup .venv/Scripts/python.exe -m uvicorn app.main:app --port $API_PORT \
  > "$SCRATCH/qa-api.log" 2>&1 &
API_PID=$!
```

### 4a. Prove it bound

`nohup` hides bind failures, and uvicorn's log is actively misleading — it prints
`Application startup complete` **and then** the bind error:

```
INFO:     Application startup complete.
ERROR:    [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000):
          only one usage of each socket address ... is normally permitted
```

A health check still passes, because the **other** process answers. Always grep:

```bash
grep -iE "error|bind" "$SCRATCH/qa-api.log"
```

### 4b. Prove it is running your code

A stale server serving old code caused a browser check to fail against code that was
correct. The fix was already in the repo and the tests passed; only the running
process was old.

Request something that only exists in your build — a field you just added, a route
you just created. The cheapest probe needs no token at all, if the ticket added a
route: `/openapi.json` lists every path the running process knows about.

```bash
curl -s localhost:$API_PORT/openapi.json |
  python -c "import json,sys; print(sorted(json.load(sys.stdin)['paths']))" | tr ',' '\n' | grep <your-route>
```

For a new **field**, you need a real response. Get a token (see the table above), call
the route, and look for the field:

```bash
curl -s localhost:$API_PORT/homework/me/assignments -H "Authorization: Bearer $TOKEN"
```

An empty list means the seed does not satisfy the feature (step 3), not that the
field is missing — resolve that first, then re-probe a populated response.

A missing field means you are talking to a stale process. Fix that before
interpreting any other result.

## 5. Start the frontend pointed at that API

The frontend reads `API_URL` (server components, server actions) and
`NEXT_PUBLIC_API_URL` (client components). Both must point at the API you just
verified, or server-rendered pages and client fetches will disagree.

```bash
cd rafiki-frontend
API_URL="http://localhost:$API_PORT" NEXT_PUBLIC_API_URL="http://localhost:$API_PORT" \
  nohup npx next dev -p $FE_PORT > "$SCRATCH/qa-fe.log" 2>&1 &
FE_PID=$!
```

`npm run dev` accepts no port argument, so use `npx next dev -p <port>` when 3000 is
taken — which it often is.

`curl` returning **307** on the root URL is correct — it is the locale redirect to
`/en`, not an error.

Two auth notes that cost a session each:

- `AUTH_SECRET` must be set in `.env.local`. NextAuth v5 reads `AUTH_SECRET`, not
  `NEXTAUTH_SECRET`. Without it `getBackendAccessToken()` returns `null` silently and
  every server component renders empty — which looks exactly like a backend bug.
- If you restart the API on a new port, **restart the frontend too**.
  `NEXT_PUBLIC_*` is inlined at build time, so a running dev server keeps the old URL.

## 6. Teardown — stop only what you started

**Do not stop a process by port.** "Whatever is listening on 3000" is not the same as
"the server I started", and on this machine it frequently is not. Killing by port
would destroy a teammate's or another agent's work, irreversibly.

Record the PID when you start something, and stop that PID.

**`$!` does not give you the right PID here.** Under Git Bash on Windows it returns
the shell's job id, not the Windows process — one trial captured `1640` while uvicorn
was actually `12620`, so the teardown would have silently left the server running.
Resolve the real PID from the port once the server is up, then confirm it is yours
before recording it:

```bash
sleep 5   # let it bind
API_PID=$(powershell -NoProfile -Command \
  "(Get-NetTCPConnection -LocalPort $API_PORT -State Listen).OwningProcess" | tr -d '\r')

# Confirm it is your venv python before trusting it — if Path is not this project,
# you resolved someone else's process and must not record or kill it.
powershell -NoProfile -Command "Get-Process -Id $API_PID | Select-Object Id,Path"
echo "$API_PID" > "$SCRATCH/api.pid"
```

At teardown, re-verify identity and then stop it:

```bash
API_PID=$(cat "$SCRATCH/api.pid")
powershell -NoProfile -Command "Get-Process -Id $API_PID | Select-Object Path"  # still yours?
kill "$API_PID" 2>/dev/null
```

If you lost track of a PID, identify the process before stopping it and confirm the
`Path` and `StartTime` are yours:

```bash
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort $PORT -State Listen |
  ForEach-Object { Get-Process -Id \$_.OwningProcess |
  Select-Object Id,ProcessName,StartTime,Path } | Format-List"
```

Containers, by the unique name you chose:

```bash
docker rm -f "$QA_DB"   # only the one you created
```

Then report what you left running, and every foreign process you found and did not
touch — the user usually wants to know their machine has three postgres instances on it.
