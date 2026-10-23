"""The HTTP API: login with a password, then ask questions, browse the documents and (admins) manage users and licenses.

    uvicorn src.api:app --port 8000        the web app in web/ (Next.js) talks to this; it never exposes it to the browser directly

POST /login            form fields username, password  ->  {"access_token", "token_type", "expires_in", "user", "role", "licenses"}
GET  /me               who the token belongs to
POST /ask              {"question", "history": [{"q", "a"}], "product"}  ->  see src.pipeline.to_dict. The token is optional: no token = the
                       public role; a bad or expired token = 401 (never silently downgraded). Blocked questions return 200 with status "blocked".
GET  /documents        the pages this caller may read, plus how many are locked for them per product
GET  /metrics          the evaluation numbers, read from eval/results/*.json
GET  /admin/users                              (admin) users, roles, licenses
POST /admin/users                              (admin) {"user", "password", "role"}: create a user; the password is hashed here, never stored as sent
PUT|DELETE /admin/users/{user}/licenses/{product}   (admin) grant / revoke
GET  /admin/audit                              (admin) the latest changes
GET  /health           is the server up
Access levels and licenses are SIMULATED (docs are public); the checks are real.
"""
import logging
from typing import Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from src import auth, catalog, metrics
from src.access import PRODUCTS, AccessStore, Principal, open_store
from src.llm import QuotaExhausted, load_config
from src.pipeline import ask, to_dict

log = logging.getLogger("supportrag.llm")
app = FastAPI(title="SupportRAG", description="Support and troubleshooting answers that cite the docs, or say they do not know.")
bearer = HTTPBearer(auto_error=False)
CFG = load_config()


class Turn(BaseModel):
    q: str = Field(max_length=4000)
    a: str = Field("", max_length=4000)


class AskIn(BaseModel):
    question: str = Field(max_length=20000)  # the real limit (input.max_chars) is applied by the guard, which explains itself
    history: list[Turn] = Field(default_factory=list, max_length=20)
    product: Literal["kubernetes", "postgres", "kafka", "github"] | None = None


class NewUser(BaseModel):
    user: str = Field(max_length=32)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["member", "admin"] = "member"


@app.exception_handler(PyMongoError)
async def user_database_down(_: Request, e: PyMongoError):
    log.error("USER DATABASE failed: %s: %s", type(e).__name__, e)
    return JSONResponse({"detail": "The user database is not available right now."}, status_code=503)


def store():
    return open_store(CFG)  # lazy: nothing connects until a request actually reads a user (public questions never do)


def principal_of(creds: HTTPAuthorizationCredentials | None = Depends(bearer), s: AccessStore = Depends(store)):
    if creds is None:
        return Principal.public(), None
    try:
        user = auth.read_token(creds.credentials, s)
    except auth.AuthError as e:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"}) from None
    return s.principal(user), user


def admin_of(who=Depends(principal_of)):
    principal, user = who
    if principal.role != "admin":
        raise HTTPException(403, "Admins only.")
    return user


def describe(s, user):
    who = s.principal(user)
    return {"user": user, "role": who.role, "licenses": sorted(who.licenses)}


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), s: AccessStore = Depends(store)):
    username = username.strip().lower()
    try:
        token = auth.login(s, username, password, CFG)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from None
    return {"access_token": token, "token_type": "bearer", "expires_in": 60 * CFG["auth"]["token_minutes"], **describe(s, username)}


@app.get("/me")
def me(who=Depends(principal_of)):
    principal, user = who
    return {"user": user, "role": principal.role, "licenses": sorted(principal.licenses)}


@app.post("/ask")
def ask_endpoint(body: AskIn, who=Depends(principal_of)):
    principal, user = who
    try:
        res = ask(body.question, principal, [t.model_dump() for t in body.history], body.product, CFG)
    except QuotaExhausted:
        raise HTTPException(503, "The answer service has used up its free quota for today. Try again later.") from None
    except Exception as e:  # LLMs down, search down
        log.error("ASK failed for %s: %s: %s", user or "public", type(e).__name__, e)
        raise HTTPException(503, "The answer service is not available right now.") from None
    return to_dict(res)


@app.get("/documents")
def documents(who=Depends(principal_of)):
    return catalog.library(who[0], CFG)


@app.get("/metrics")
def evaluation():
    return metrics.evaluation(CFG)


# ----- admin -----

@app.get("/admin/users")
def admin_users(_: str = Depends(admin_of), s: AccessStore = Depends(store)):
    return {"users": s.list_users(), "products": list(PRODUCTS)}


@app.post("/admin/users", status_code=201)
def admin_add_user(body: NewUser, admin: str = Depends(admin_of), s: AccessStore = Depends(store)):
    user = body.user.strip().lower()
    if s.role_of(user) is not None:
        raise HTTPException(409, "That user name is taken.")
    try:
        s.add_user(admin, user, body.role, password_hash=auth.hash_password(body.password))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return describe(s, user)


def change_license(action, user, product, admin, s):
    try:
        getattr(s, action)(admin, user, product)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return describe(s, user)


@app.put("/admin/users/{user}/licenses/{product}")
def admin_grant(user: str, product: str, admin: str = Depends(admin_of), s: AccessStore = Depends(store)):
    return change_license("grant", user, product, admin, s)


@app.delete("/admin/users/{user}/licenses/{product}")
def admin_revoke(user: str, product: str, admin: str = Depends(admin_of), s: AccessStore = Depends(store)):
    if product not in PRODUCTS:
        raise HTTPException(422, f"unknown product {product!r}")
    return change_license("revoke", user, product, admin, s)


@app.get("/admin/audit")
def admin_audit(_: str = Depends(admin_of), s: AccessStore = Depends(store)):
    return {"entries": s.recent_audit(30)}


@app.get("/health")
def health():
    return {"ok": True}
