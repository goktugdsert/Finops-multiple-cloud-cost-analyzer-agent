"""Web chat UI: the report plus a chat box that asks the agent, in one page.

Run:  uv run mcca-web        # serves http://127.0.0.1:8000

GET /   -> the HTML report with a chat panel injected.
POST /ask {question} -> runs the LangGraph agent and returns its answer.

The agent answers only via validated query tools, so figures are never invented; the
web layer just relays them. Tracing (Langfuse) is applied if enabled.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from pydantic import BaseModel

from mcca.agent.graph import build_agent_graph
from mcca.agent.model import build_model
from mcca.config import get_settings
from mcca.eval.faithfulness import check_messages, warning_line
from mcca.logging import configure_logging
from mcca.surface.report import (
    _first_of_month,
    _minus_months,
    build_report_data,
    render_html,
)
from mcca.tracing import flush_tracing, tracing_config
from mcca.warehouse.postgres import PostgresRepository

logger = logging.getLogger(__name__)

_CHAT_HTML = """
<div class="mc-chat">
  <div class="mc-head">Ask the agent</div>
  <div id="chat" class="mc-log"></div>
  <form id="askform" class="mc-form">
    <input id="q" autocomplete="off"
      placeholder="e.g. Top 3 services by cost from 2026-01-01 to 2026-07-01">
    <button type="submit">Ask</button>
  </form>
  <div class="mc-foot">Answers come only from validated queries &amp; calculations —
  numbers are never invented by the model, and any untraceable figure is flagged.</div>
</div>
<style>
.mc-chat{background:var(--surface,#fcfcfb);border:1px solid var(--border,rgba(11,11,11,.1));
  border-radius:14px;padding:18px 20px;margin-bottom:18px;
  box-shadow:0 1px 2px rgba(11,11,11,.04),0 4px 18px rgba(11,11,11,.05)}
.mc-head{font-size:14px;font-weight:640;margin-bottom:12px;color:var(--ink,#0b0b0b)}
.mc-log{max-height:340px;overflow-y:auto;margin-bottom:12px;display:flex;flex-direction:column;gap:8px}
.mc-log:empty{display:none}
.mc-msg{padding:10px 13px;border-radius:12px;font-size:13px;white-space:pre-wrap;
  line-height:1.5;max-width:84%}
.mc-you{align-self:flex-end;background:#2a78d6;color:#fff}
.mc-agent{align-self:flex-start;background:var(--plane,#f1f1ee);color:var(--ink,#0b0b0b);
  border:1px solid var(--border,rgba(11,11,11,.1))}
.mc-pending{opacity:.6;font-style:italic}
.mc-form{display:flex;gap:8px}
#q{flex:1;padding:11px 13px;border:1px solid var(--border,rgba(11,11,11,.18));border-radius:9px;
  font-size:13px;background:var(--plane,#fff);color:var(--ink,#0b0b0b)}
#q:focus{outline:2px solid #2a78d6;outline-offset:-1px;border-color:#2a78d6}
.mc-form button{padding:11px 20px;border:0;border-radius:9px;background:#2a78d6;color:#fff;
  font-weight:600;font-size:13px;cursor:pointer}
.mc-form button:disabled{opacity:.5;cursor:default}
.mc-foot{color:var(--muted,#898781);font-size:11px;margin-top:9px}
@media (prefers-color-scheme:dark){
  .mc-chat{background:#1a1a19;border-color:rgba(255,255,255,.1)}
  .mc-agent{background:#0d0d0d;border-color:rgba(255,255,255,.1);color:#fff}
  #q{background:#0d0d0d;border-color:rgba(255,255,255,.18);color:#fff}
  .mc-head{color:#fff}
}
</style>
<script>
(function(){
  const form=document.getElementById('askform'), q=document.getElementById('q'),
        chat=document.getElementById('chat'), btn=form.querySelector('button');
  function add(who,text){const d=document.createElement('div');
    d.className='mc-msg '+(who==='you'?'mc-you':'mc-agent');
    d.textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const question=q.value.trim(); if(!question) return;
    add('you',question); q.value=''; btn.disabled=true;
    const pending=add('agent','thinking…'); pending.classList.add('mc-pending');
    try{
      const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({question})});
      const j=await r.json();
      pending.textContent=j.answer||j.error||'(no answer)';
    }catch(err){ pending.textContent='Error: '+err; }
    pending.classList.remove('mc-pending'); btn.disabled=false; q.focus();
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


def _with_refresh(html: str, seconds: int) -> str:
    """Inject a meta-refresh so the dashboard auto-reloads (for the live simulator)."""
    tag = f'<meta http-equiv="refresh" content="{seconds}">'
    return html.replace("<head>", "<head>" + tag, 1) if "<head>" in html else html


def _with_chat(html: str) -> str:
    """Inject the chat panel at the top of the dashboard (just below the header)."""
    if "</header>" in html:  # the dashboard report
        return html.replace("</header>", "</header>" + _CHAT_HTML, 1)
    for title in ("<h1>Multi-Cloud Cost Dashboard</h1>", "<h1>Multi-Cloud Cost Agent</h1>"):
        if title in html:  # the fallback page
            return html.replace(title, title + _CHAT_HTML, 1)
    return html + _CHAT_HTML


class AskRequest(BaseModel):
    question: str


class DecideRequest(BaseModel):
    key: str
    status: str  # APPROVED | DISMISSED | SNOOZED
    start: str
    end: str


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
    def index(refresh: int | None = None) -> str:
        end = _first_of_month(date.today())
        start = _minus_months(end, months)
        try:
            html = render_html(build_report_data(repo, start, end))
        except Exception:  # noqa: BLE001 - empty/unreachable warehouse -> chat-only page
            html = _FALLBACK
        page = _with_chat(html)
        # ?refresh=N auto-reloads the page every N seconds — pairs with `mcca-simulate`.
        if refresh and refresh > 0:
            page = _with_refresh(page, refresh)
        return page

    @app.post("/ask")
    def ask(body: AskRequest) -> dict[str, str]:
        try:
            result = graph().invoke(
                {"messages": [{"role": "user", "content": body.question}]},
                config=tracing_config(settings),
            )
            flush_tracing(settings)
            messages = result["messages"]
            answer = _message_text(messages[-1].content)
            # Runtime faithfulness guard: flag any stated figure not traceable to a tool.
            untraceable = check_messages(messages)
            if untraceable:
                warning = warning_line(untraceable)
                logger.warning("Faithfulness: untraceable figure(s) %s", untraceable)
                return {"answer": f"{answer}\n\n{warning}", "warning": warning}
            return {"answer": answer}
        except Exception as exc:  # noqa: BLE001 - relay the error to the UI
            flush_tracing(settings)
            return {"error": f"{type(exc).__name__}: {exc}"}

    @app.post("/decide")
    def decide_recommendation(body: DecideRequest) -> dict[str, str]:
        # Record a human decision on a recommendation. Intent only — nothing is executed.
        from datetime import date

        from mcca.optimization.service import decide

        try:
            rec = decide(
                repo,
                date.fromisoformat(body.start),
                date.fromisoformat(body.end),
                body.key,
                body.status,
                decided_by="web",
            )
            return {"key": rec.key, "status": rec.status}
        except Exception as exc:  # noqa: BLE001 - relay the error to the UI
            return {"error": f"{type(exc).__name__}: {exc}"}

    return app


def main() -> None:
    import uvicorn

    configure_logging()
    print("Serving the cost agent at http://127.0.0.1:8000  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
