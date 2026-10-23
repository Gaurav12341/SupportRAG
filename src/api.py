"""The HTTP API: login with a password, then ask questions with the token.

    uvicorn src.api:app            (or `python -m src.ui`, which serves this API and the Gradio page together)

POST /login   form fields username, password  ->  {"access_token", "token_type", "role", "licenses"}
GET  /me      who the token belongs to
POST /ask     {"question", "history": [{"q", "a"}], "product"}  ->  see src.pipeline.to_dict. The token is optional: no token = the
              public role; a bad or expired token = 401 (never silently downgraded). Blocked questions return 200 with status "blocked".
GET  /health  is the server up
Access levels and licenses are SIMULATED (docs are public); the checks are real.
"""
import logging
from typing import Literal

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src import auth
from src.access import AccessStore, Principal
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


def store():
    s = AccessStore(cfg=CFG)  # one connection per request: SQLite connections cannot cross threads
    try:
        yield s
    finally:
        s.db.close()


def principal_of(creds: HTTPAuthorizationCredentials | None = Depends(bearer), s: AccessStore = Depends(store)):
    if creds is None:
        return Principal.public(), None
    try:
        user = auth.read_token(creds.credentials, s)
    except auth.AuthError as e:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"}) from None
    return s.principal(user), user


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), s: AccessStore = Depends(store)):
    try:
        token = auth.login(s, username, password, CFG)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from None
    who = s.principal(username)
    return {"access_token": token, "token_type": "bearer", "role": who.role, "licenses": sorted(who.licenses)}


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


@app.get("/health")
def health():
    return {"ok": True}
