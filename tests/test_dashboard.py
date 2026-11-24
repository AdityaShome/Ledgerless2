import asyncio
import re

import httpx

from dashboard.app import create_app


async def test_one_window_dashboard_runs_and_publishes_agent_updates(tmp_path):
    app = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as http:
        page = await http.get("/")
        assert "Shared intent box" in page.text
        token = re.search("const token='([^']+)'", page.text).group(1)
        config = (await http.get("/api/config")).json()
        assert len(config["cases"]) == 5
        assert (await http.post("/api/runs", json={})).status_code == 403
        response = await http.post(
            "/api/runs",
            headers={"X-Ledgerless-Token": token},
            json={
                "case": "travel",
                "guidelines": "Use only synthetic bookings. Respect the common spec.",
            },
        )
        assert response.status_code == 202
        rid = response.json()["run_id"]
        for _ in range(200):
            state = (await http.get("/api/runs/" + rid)).json()
            if state["finished"]:
                break
            await asyncio.sleep(0.05)
        assert state["finished"] and state["result"]["status"] == "completed"
        assert state["context"]["initial_guidelines"].startswith("Use only synthetic")
        assert len({u["org"] for u in state["context"]["updates"]}) == 3
        assert (tmp_path / rid / "result.json").exists()
    app.state.box.close()
