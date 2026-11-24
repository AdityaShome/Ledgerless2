# One window and one shared intent box

Start `python -m dashboard.app`, then open http://127.0.0.1:8080.
The page contains the editable initial guidelines, the common JSON specification,
agent cards, the changing intent box, recovery evidence, and run metrics. All five
use cases run from that page. One foreground workflow executes at a time.

Every agent reads the same guidelines/specification hash before acting, checks its
own action against that specification, and posts its own signed contribution.
Updates carry author, observed version, new version, specification hash, and an
idempotency event key. Version comparison rejects stale writes; retries of the
same contribution do not duplicate it. Initial guidelines cannot be overwritten
by an agent. Editing them starts a new run; a run's common specification freezes
when execution starts. The box evolves through agent contributions, not destructive
replacement of another agent's output.

This is one UI context and public coordination board, not one shared LLM token
window. The supplied agents perform deterministic synthetic domain actions. No
LLM account or API key is required. A real LLM executor can consume the shared
snapshot, but its tool calls must pass the same evidence and action checks.

The shared box is deliberately not a task-execution log or recovery oracle.
Three organizations maintain separate databases and private signing keys. Each
has two replica-local recovery stores and one simulated external tool provider.
A provider is shared by replicas of that organization only: it supplies durable
idempotency and outcome lookup, like a payment processor accepting idempotency
keys. No tool database is shared across organizations. The public coordinator
is a convenience and availability dependency for the demo, not a claim that the
cross-org protocol requires every private log to be centrally readable.

The UI shows only opaque references and public status updates. It stores no real
clinical, payment, travel, or vendor data. Demo state is written under
`demo_state/` and is excluded from the distributed source archive. The local web
server binds loopback and uses a per-session mutation token. This is not a
production authentication, access-control, or multi-tenant deployment.
