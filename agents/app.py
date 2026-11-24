"""Assemble and serve one A2A agent with the recovery wrapper (local HTTP)."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette

from agents.chain_agent import ChainAgentExecutor
from recovery.a2a_middleware import RecoveryASGI, recovery_extension
from recovery.crypto import public_key_hex
from recovery.service import RecoveryService


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_card(name: str, url: str, service: RecoveryService | None, extension: bool) -> AgentCard:
    caps = AgentCapabilities(streaming=False)
    if extension and service is not None:
        caps.extensions.append(
            recovery_extension(
                service.org,
                public_key_hex(service.priv.public_key()),
                service.store.checkpoint_epoch,
            )
        )
    return AgentCard(
        name=name,
        description=f"{name} chain hop",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=caps,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[AgentSkill(id="work", name="work", description="does one effect", tags=["demo"])],
    )


def build_app(
    executor: ChainAgentExecutor, card: AgentCard, service: RecoveryService, extension: bool = True
):
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")
    app = Starlette(routes=routes)
    return RecoveryASGI(app, service) if extension else app


@dataclass
class RunningAgent:
    url: str
    server: uvicorn.Server
    thread: threading.Thread
    sock: socket.socket | None = None

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.sock is not None:
            self.sock.close()


def serve(app, port: int, sock: socket.socket | None = None) -> RunningAgent:
    # Reserve the socket before starting a thread; do not race bind in uvicorn startup.
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    port = sock.getsockname()[1]
    sock.setblocking(False)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        sock.close()
        raise RuntimeError("server did not start")
    return RunningAgent(f"http://127.0.0.1:{port}", server, thread, sock)
