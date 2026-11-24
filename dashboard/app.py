"""python -m dashboard.app --port 8080. Local single-process sandbox, no paid APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from examples.workflow import CASES, FAULTS, Workflow, fixture
from recovery.intent_box import IntentBox


def create_app(data_dir=None):
    directory = Path(data_dir or Path.cwd() / "demo_state")
    directory.mkdir(parents=True, exist_ok=True)
    box = IntentBox(directory / "shared-intent-box.sqlite")
    token = secrets.token_urlsafe(24)
    runs = {}
    tasks = set()
    gate = asyncio.Lock()  # keep the local demo within its one active context

    @asynccontextmanager
    async def lifespan(app):
        yield
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        box.close()

    async def index(request):
        html = (Path(__file__).parent / "index.html").read_text().replace("__TOKEN__", token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    async def config(request):
        return JSONResponse(
            {"cases": {name: fixture(name) for name in CASES}, "faults": list(FAULTS)}
        )

    async def worker(workflow):
        rid = workflow.run_id
        try:
            async with gate:
                result = await workflow.run()
                runs[rid]["result"] = result
                (directory / rid / "result.json").write_text(json.dumps(result, indent=2))
        except Exception as exc:  # noqa: BLE001 - surface background job errors in the UI
            box.set_state(rid, "failed")
            runs[rid]["error"] = str(exc)
        finally:
            # Stopping local uvicorn threads must not block the dashboard event loop.
            await asyncio.to_thread(workflow.close)
            runs[rid]["finished"] = True

    async def start(request):
        if request.headers.get("X-Ledgerless-Token") != token:
            return JSONResponse({"error": "invalid local dashboard token"}, status_code=403)
        if any(not run["finished"] for run in runs.values()):
            return JSONResponse(
                {"error": "a workflow is already active in this context"}, status_code=409
            )
        raw = await request.body()
        if len(raw) > 65536:
            return JSONResponse({"error": "specification is too large"}, status_code=413)
        try:
            data = json.loads(raw)
            rid = uuid.uuid4().hex
            workflow = Workflow(
                data.get("case", "commerce"),
                data.get("fault", "clean"),
                box=box,
                run_id=rid,
                workdir=directory / rid,
                guidelines=data.get("guidelines"),
                specification=data.get("specification"),
            )
        except (ValueError, TypeError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        runs[rid] = {"run_id": rid, "finished": False, "result": None, "error": None}
        task = asyncio.create_task(worker(workflow))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return JSONResponse({"run_id": rid}, status_code=202)

    async def status(request):
        rid = request.path_params["run_id"]
        if rid not in runs:
            return JSONResponse({"error": "unknown run"}, status_code=404)
        return JSONResponse({**runs[rid], "context": box.snapshot(rid)})

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/config", config),
            Route("/api/runs", start, methods=["POST"]),
            Route("/api/runs/{run_id}", status),
        ],
        lifespan=lifespan,
    )
    app.state.box = box
    app.state.tasks = tasks
    app.state.directory = directory
    return app


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--data-dir", type=Path, default=Path("demo_state"))
    args = p.parse_args()
    print(f"Open http://127.0.0.1:{args.port} for the shared intent-box dashboard.")
    uvicorn.run(
        create_app(args.data_dir), host="127.0.0.1", port=args.port, workers=1, log_level="warning"
    )


if __name__ == "__main__":
    main()
