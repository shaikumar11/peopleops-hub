import os, sqlite3, time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

DB = os.environ.get("DB_PATH", "hub.db")
LEAVE_ALLOWANCE, LEAVE_AUTO_DAYS, EXPENSE_AUTO_LIMIT = 20, 2, 1000
app = FastAPI(title="PeopleOps Hub")
LATENCY: dict = {}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("create table if not exists requests(id integer primary key autoincrement,"
              " employee text, kind text, amount real, note text, status text, decided_by text)")
    return c


class NewRequest(BaseModel):
    employee: str = Field(min_length=1)
    kind: str = Field(pattern="^(leave|expense)$")
    amount: float = Field(gt=0)  # days for leave, rupees for expense
    note: str = ""


class Decision(BaseModel):
    approver: str = Field(min_length=1)
    action: str = Field(pattern="^(approve|reject)$")


@app.middleware("http")
async def telemetry(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", request.url.path)
    LATENCY.setdefault(route, []).append((time.perf_counter() - start) * 1000)
    return response


def balance(c, employee):
    used = c.execute("select coalesce(sum(amount),0) from requests where employee=? and kind='leave'"
                     " and status='approved'", (employee,)).fetchone()[0]
    return LEAVE_ALLOWANCE - used


def fetch(c, rid):
    row = c.execute("select * from requests where id=?", (rid,)).fetchone()
    if not row:
        raise HTTPException(404, "request not found")
    return dict(row)


@app.post("/requests", status_code=201)
def create(n: NewRequest):
    with db() as c:
        if n.kind == "leave" and n.amount > balance(c, n.employee):
            raise HTTPException(400, "insufficient leave balance")
        auto = (n.kind == "leave" and n.amount <= LEAVE_AUTO_DAYS) or \
               (n.kind == "expense" and n.amount <= EXPENSE_AUTO_LIMIT)
        cur = c.execute("insert into requests(employee,kind,amount,note,status,decided_by)"
                        " values(?,?,?,?,?,?)", (n.employee, n.kind, n.amount, n.note,
                        "approved" if auto else "pending", "auto" if auto else None))
        return fetch(c, cur.lastrowid)


@app.post("/requests/{rid}/decision")
def decide(rid: int, d: Decision):
    with db() as c:
        r = fetch(c, rid)
        if r["status"] != "pending":
            raise HTTPException(409, "already decided")
        if d.approver == r["employee"]:
            raise HTTPException(403, "self approval not allowed")
        if d.action == "approve" and r["kind"] == "leave" and r["amount"] > balance(c, r["employee"]):
            raise HTTPException(400, "insufficient leave balance")
        c.execute("update requests set status=?, decided_by=? where id=?",
                  ("approved" if d.action == "approve" else "rejected", d.approver, rid))
        return fetch(c, rid)


@app.get("/requests")
def listing(status: str | None = None):
    q = "select * from requests" + (" where status=?" if status else "") + " order by id desc"
    with db() as c:
        return [dict(r) for r in c.execute(q, (status,) if status else ())]


@app.get("/employees/{name}/leave-balance")
def leave_balance(name: str):
    with db() as c:
        return {"employee": name, "remaining_days": balance(c, name)}


@app.get("/summary")
def summary():
    with db() as c:
        rows = [dict(r) for r in c.execute("select kind,status,count(*) n,sum(amount) total"
                                           " from requests group by kind,status")]
        spend = c.execute("select coalesce(sum(amount),0) from requests"
                          " where kind='expense' and status='approved'").fetchone()[0]
    return {"by_kind_status": rows, "approved_expense_total": spend}


@app.get("/metrics")
def metrics():
    out = {}
    for route, v in LATENCY.items():
        s = sorted(v)
        out[route] = {"count": len(s), "avg_ms": round(sum(s) / len(s), 2),
                      "p95_ms": round(s[min(len(s) - 1, int(len(s) * 0.95))], 2)}
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))
