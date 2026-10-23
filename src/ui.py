"""The Gradio page: login, a question box, the answer with clickable citations, the retrieved passages, and a clear
"No documented fix found" state.

    python -m src.ui        ->  http://127.0.0.1:7860/ui   (the page)   and   http://127.0.0.1:7860/docs   (the API, src/api.py)

The page calls the same functions as the API (auth.login / auth.read_token / pipeline.ask), so a token expires and a license change
applies exactly as it does over HTTP. Access levels and users are SIMULATED. Text written by the model or taken from the docs is shown
as plain text or in code blocks: images and links inside it are removed, so a poisoned passage cannot make the page load a URL.
"""
import re
import sys

import gradio as gr

from src import auth
from src.access import PRODUCTS, AccessStore
from src.llm import QuotaExhausted, load_config
from src.pipeline import ask, to_dict

CFG = load_config()
REFUSE_BANNER = ("### No documented fix found\n"
                 "The documentation this account can read does not answer that, and I would rather say so than guess. "
                 "Try rewording it (include the exact error text or setting name), pick the product, or check the passages below, "
                 "which are the closest text I found.")
IMG, LINK = re.compile(r"!\[[^\]]*\]\([^)]*\)"), re.compile(r"\[([^\]]*)\]\([^)]*\)")


def clean_md(text):
    """Model-written text for the page: no images (they would be fetched), links reduced to their label, no raw HTML tags."""
    text = LINK.sub(r"\1", IMG.sub("", text or ""))
    return re.sub(r"<[^>]{1,200}>", "", text)


def code_block(text):
    return "```text\n" + text.replace("```", "'''") + "\n```"


def render_answer(res):
    """(banner/answer markdown, passages markdown, notes markdown) for a pipeline result dict (pipeline.to_dict)."""
    notes = []
    if res["rewritten"]:
        notes.append(f"Searched for: *{clean_md(res['question_used'])}*")
    if res["products"]:
        notes.append("Product detected: " + ", ".join(res["products"]) + (f" (search limited to {res['product_filter']})" if res["product_filter"] else ""))
    if res["dropped_chunks"]:
        notes.append(f"{len(res['dropped_chunks'])} retrieved passage(s) were left out because they looked like injected instructions.")
    if res["status"] == "blocked":
        return f"### Question not run\n{clean_md(res['message'])}", "", "  \n".join(notes)
    number = {s["chunk_id"]: i for i, s in enumerate(res["sources"], 1)}
    url = {s["chunk_id"]: s["url"] for s in res["sources"]}
    if res["status"] == "refused":
        head = REFUSE_BANNER
    else:
        head = [clean_md(res["summary"])] if res["summary"] else []
        head += [f"> {w}" for w in res["summary_warnings"]]
        if res["partial_note"]:
            head.append(f"*{clean_md(res['partial_note'])}*")
        for i, p in enumerate(res["points"], 1):
            cites = " ".join(f"[[{number[c]}]]({url[c]})" for c in p["cited"] if c in number)
            head.append(f"{i}. {clean_md(p['text'])} {cites}")
            head += [f"   > ⚠ {w}" for w in p["warnings"]]
        head.append("\n**Sources**")
        head += [f"{number[s['chunk_id']]}. [{clean_md(s['title'])}]({s['url']}) ({s['product']})" for s in res["sources"]]
        head = "\n".join(head)
        notes.append(f"Answer by {res['provider']}, checked by {res['verified_by'] or 'nothing'}; the writer says it covers the question: {res['coverage']}.")
    passages = "\n\n".join(f"**{p['label']}. [{clean_md(p['title'])}]({p['url']})** ({p['product']}, {p['access_level']})\n{code_block(p['text'])}"
                           for p in res.get("passages", []))
    return head, passages or "_Nothing readable was retrieved._", "  \n".join(notes)


def do_login(user, password, token):
    s = AccessStore(cfg=CFG)
    try:
        new = auth.login(s, (user or "").strip(), password or "", CFG)
        who = s.principal(user.strip())
        return new, f"Logged in as **{user.strip()}** ({who.role}" + (f"; licenses: {', '.join(sorted(who.licenses))}" if who.licenses else "") + ")."
    except auth.AuthError as e:
        return token, f"Not logged in. {e}"
    finally:
        s.db.close()


def do_logout():
    return "", "Not logged in: you see public documentation only."


def do_ask(question, product, token, turns):
    s = AccessStore(cfg=CFG)
    try:
        try:
            who = s.principal(auth.read_token(token, s)) if token else None
        except auth.AuthError as e:
            return f"### Please log in again\n{e}", "", "", turns, ""
        from src.access import Principal
        res = to_dict(ask(question, who or Principal.public(), turns, product or None, CFG))
    except QuotaExhausted:
        return "### Try again later\nThe free answer quota for today is used up.", "", "", turns, question
    except Exception as e:
        print(f"ask failed: {type(e).__name__}: {e}", file=sys.stderr)
        return "### Not available\nThe answer service is not available right now.", "", "", turns, question
    finally:
        s.db.close()
    answer_md, passages_md, notes_md = render_answer(res)
    if res["status"] == "answered":  # follow-ups see the question and a short form of the answer
        turns = (turns + [{"q": question, "a": res["summary"] or res["points"][0]["text"]}])[-CFG["input"]["max_history_turns"]:]
    return answer_md, passages_md, notes_md, turns, ""


def build():
    with gr.Blocks(title="SupportRAG") as demo:
        gr.Markdown("# SupportRAG\nAsk about an error or symptom in **Kubernetes, PostgreSQL, Kafka or GitHub Actions**. Answers cite the docs; "
                    "if the docs have no fix, it says so. *Users, roles and access levels are simulated on public docs.*")
        token, turns = gr.State(""), gr.State([])
        with gr.Sidebar(label="Login"):
            who = gr.Markdown("Not logged in: you see public documentation only.")
            user, password = gr.Textbox(label="User", placeholder="alice"), gr.Textbox(label="Password", type="password")
            with gr.Row():
                login_btn, logout_btn = gr.Button("Log in", variant="primary"), gr.Button("Log out")
        question = gr.Textbox(label="Your question", lines=3, max_lines=8, placeholder="psql says: FATAL: password authentication failed for user ...")
        with gr.Row():
            product = gr.Dropdown([""] + list(PRODUCTS), value="", label="Product (optional)")
            ask_btn, new_btn = gr.Button("Ask", variant="primary"), gr.Button("New conversation")
        answer_md = gr.Markdown(label="Answer")
        notes = gr.Markdown()
        with gr.Accordion("Retrieved passages (what the answer was written from)", open=False):
            passages = gr.Markdown()
        login_btn.click(do_login, [user, password, token], [token, who]).then(lambda: "", None, password)
        logout_btn.click(do_logout, None, [token, who])
        for trigger in (ask_btn.click, question.submit):
            trigger(do_ask, [question, product, token, turns], [answer_md, passages, notes, turns, question])
        new_btn.click(lambda: ([], "", "", "", ""), None, [turns, answer_md, passages, notes, question])
    return demo


def serve(port=7860):
    import uvicorn
    from src.api import app
    gr.mount_gradio_app(app, build(), path="/ui")
    print(f"Page: http://127.0.0.1:{port}/ui    API docs: http://127.0.0.1:{port}/docs")
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    serve()
