"""Web chat UI: the report plus a chat box that asks the agent, in one page.

Run:  uv run mcca-web        # serves http://127.0.0.1:8000

GET /   -> the HTML report with a chat panel injected.
POST /ask {question} -> runs the LangGraph agent and returns its answer.

The agent answers only via validated query tools, so figures are never invented; the
web layer just relays them. Tracing (Langfuse) is applied if enabled.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from mcca.agent.graph import build_agent_graph
from mcca.agent.model import build_model
from mcca.config import get_settings
from mcca.logging import configure_logging
from mcca.surface.report import (
    _first_of_month,
    _minus_months,
    build_report_data,
    render_html,
)
from mcca.tracing import flush_tracing, tracing_config
from mcca.warehouse.postgres import PostgresRepository

_CHAT_HTML = """
<div class='panel'>
  <h2>Ask the agent</h2>
  <div id='chat'></div>
  <form id='askform'>
    <input id='q' autocomplete='off'
      placeholder='e.g. Top 3 services and month-over-month trend for 2026-01-01 to 2026-07-01'>
    <button type='submit'>Ask</button>
  </form>
  <div class='foot'>Answers come only from validated queries &amp; calculations —
  numbers are never invented by the model.</div>
</div>
<style>
#chat{max-height:340px;overflow-y:auto;margin-bottom:12px}
#chat .msg{padding:9px 12px;border-radius:10px;margin:6px 0;font-size:13px;white-space:pre-wrap;
  line-height:1.45}
#chat .you{background:#eef2ff;color:#1f2328;margin-left:60px}
#chat .agent{background:#f6f8fa;border:1px solid #eaeef2;margin-right:60px}
#chat .pending{color:#8b949e;font-style:italic}
#askform{display:flex;gap:8px}
#q{flex:1;padding:10px 12px;border:1px solid #d0d7de;border-radius:8px;font-size:13px}
#askform button{padding:10px 18px;border:0;border-radius:8px;background:#2563eb;color:#fff;
  font-weight:600;cursor:pointer}
#askform button:disabled{opacity:.5;cursor:default}
</style>
<script>
(function(){
  const form=document.getElementById('askform'), q=document.getElementById('q'),
        chat=document.getElementById('chat'), btn=form.querySelector('button');
  function add(who,text){const d=document.createElement('div');d.className='msg '+who;
    d.textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const question=q.value.trim(); if(!question) return;
    add('you',question); q.value=''; btn.disabled=true;
    const pending=add('agent','thinking…'); pending.classList.add('pending');
    try{
      const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({question})});
      const j=await r.json();
      pending.textContent=j.answer||j.error||'(no answer)';
    }catch(err){ pending.textContent='Error: '+err; }
    pending.classList.remove('pending'); btn.disabled=false; q.focus();
  });
})();
</script>
"""

_FALLBACK = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Cloud Cost Agent</title><style>body{font-family:-apple-system,Segoe UI,Roboto,"
    "Arial,sans-serif;background:#f6f8fa;color:#1f2328;margin:0}.wrap{max-width:900px;"
    "margin:0 auto;padding:32px}.panel{background:#fff;border:1px solid #d0d7de;"
    "border-radius:10px;padding:20px;margin-bottom:24px}.panel h2{font-size:15px;margin:0 0 14px}"
    ".foot{color:#8b949e;font-size:11px;margin-top:8px}</style></head><body><div class='wrap'>"
    "<h1>Multi-Cloud Cost Agent</h1>"
    "<div class='panel'>No cost data yet — run <code>uv run mcca-seed</code> "
    "(with Postgres up) to load the demo warehouse, then refresh.</div>"
    "</div></body></html>"
)


def _with_chat(html: str) -> str:
    """Inject the chat panel right after the page title."""
    for title in ("<h1>Multi-Cloud Cost Report</h1>", "<h1>Multi-Cloud Cost Agent</h1>"):
        if title in html:
            return html.replace(title, title + _CHAT_HTML, 1)
    return html + _CHAT_HTML


class AskRequest(BaseModel):
    question: str


def _message_text(content: Any) -> str:
    """Flatten a chat message's content (str or list-of-parts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
        return "".join(p for p in parts if p)
    return str(content)


def create_app(repo: Any | None = None, model: Any | None = None, months: int = 9) -> Any:
    """Build the FastAPI app. Agent graph is built lazily on first question."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    settings = get_settings()
    repo = repo or PostgresRepository()
    app = FastAPI(title="Multi-Cloud Cost Agent")
    state: dict[str, Any] = {"graph": None}

    def graph() -> Any:
        if state["graph"] is None:
            state["graph"] = build_agent_graph(repo, model or build_model(settings))
        return state["graph"]

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        end = _first_of_month(date.today())
        start = _minus_months(end, months)
        try:
            html = render_html(build_report_data(repo, start, end))
        except Exception:  # noqa: BLE001 - empty/unreachable warehouse -> chat-only page
            html = _FALLBACK
        return _with_chat(html)

    @app.post("/ask")
    def ask(body: AskRequest) -> dict[str, str]:
        try:
            result = graph().invoke(
                {"messages": [{"role": "user", "content": body.question}]},
                config=tracing_config(settings),
            )
            flush_tracing(settings)
            return {"answer": _message_text(result["messages"][-1].content)}
        except Exception as exc:  # noqa: BLE001 - relay the error to the UI
            flush_tracing(settings)
            return {"error": f"{type(exc).__name__}: {exc}"}

    return app


def main() -> None:
    import uvicorn

    configure_logging()
    print("Serving the cost agent at http://127.0.0.1:8000  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
