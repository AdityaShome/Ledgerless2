# Related work

Status of each entry: **found** means the paper exists and the description below matches its
abstract or search summary; I have not read any paper in full, so check details against the paper
before publication. **unchecked** means not yet looked up.

- **Temporal and durable execution for LLM agents.** (unchecked, well-known) One control plane
  keeps a readable event history and replays workflow code from it, giving exactly-once-style
  behavior inside one organization. We assume no shared control plane or readable log across
  organizations, so we recover from minimal signed evidence at each hop. Our benchmark's Temporal
  system is an in-process stand-in and is labelled an upper bound.
- **LangGraph durable execution.** (unchecked) Checkpoints graph state so a run resumes after
  failure, inside one deployment. It does not address a remote organization whose effect may or
  may not have run. Verify against current docs.
- **SagaLLM** (Chang and Geng, arXiv 2503.11951, PVLDB 18, 2025). (found) Adds saga-style
  compensating transactions, context management and validation agents to multi-agent LLM planning
  inside one orchestrator. Our Saga baseline models the orchestrator-with-full-view idea and shows
  its limits: it duplicates when hops do not dedup, and it cannot undo an in-doubt effect it
  cannot see. We do not model SagaLLM's validation or context agents.
- **Microsoft AgentMesh.** (unchecked) Described in the guide as trust quarantine, not recovery.
  We use quarantine only as a safe outcome of `decide()`.
- **Beyond Single-Use Tokens: Durable Authorization State for Replay-Resistant LLM Agent
  Actions** (arXiv 2608.01710, Aug 2026). (abstract read) Defines "semantic replay": an agent that
  replans, retries, delegates or resumes after a crash can get one user authorization executed
  more than once even with single-use tokens. Its CapLease layer keeps durable, monotonic issuer
  state over the authorized action, the user confirmation and the remaining execution budget, with
  Issue-Prepare-Commit transitions, and is compared with a stateful server ledger. Duplicate
  external effects are prevented only together with an idempotent sink. It covers delegation only
  as a test scenario, with no multi-organization model, and the abstract does not say how an
  in-doubt call is resolved. Closest prior work to our F5 and digest idea. We differ in keeping
  signed evidence at each executing organization, a cross-organization `resolveIntent`, and not
  requiring an idempotent sink. Full text not read, so limitations are unchecked.
- **Where Does Exactly-Once Live?** (arXiv 2609.29095, Sep 2026). (abstract read; not in the
  guide) Empirical study of duplicate writes after timeouts: nine models, three harnesses, twelve
  injected fault modes. Reports that read-back verification works when the outcome is visible
  (0.5% duplicates on lost acknowledgements) but fails under late commits and redelivery (56% and
  74%), proves that verification alone cannot be exactly-once without a bound on in-flight time,
  and finds idempotency keys cut duplicates from 28% to 4%. Supports our premise that blind retry
  and read-back are not enough. It does not cover multi-hop cross-organization chains or signed
  receipts. Differences: we study protocol-level recovery in simulation, not real model behavior.
- **From Agent Loops to Structured Graphs** (arXiv 2604.11378, Apr 2026). (abstract read) Argues
  against the single-loop agent design and proposes a static-DAG "Structured Graph Harness" with
  immutable plan versions and an escalation protocol for recovery. The abstract does not mention
  non-idempotent retry or duplicate side effects, so this is probably NOT the paper the guide
  means. The April 2026 paper on non-deterministic node output and non-idempotent retry is still
  to be located.
- **A2ABreak: Systematic Security Analysis of the A2A Protocol** (arXiv 2609.10871, 2026).
  (found) Builds a finite-state model of the A2A lifecycle and reports eleven protocol-level
  weaknesses; secondary commentary says the protocol lacks a delegation context or chain-of-custody
  primitive. We add a `chain_id` in intent metadata, as an extension and not a core change.
- **Strabo: Declarative Specification and Implementation of Agentic Interaction Protocols**
  (arXiv 2606.05043, 2026). (found) States that A2A is mostly informally specified, with
  ambiguities such as whether a canceled task can resume, and proposes bridging it to a declarative
  protocol language. It does not verify A2A. Our TLA+ model covers only the recovery protocol,
  not the A2A state machine.
- **Classical roots.** Chandy-Lamport snapshots (consistent global state without a coordinator),
  two-phase commit in-doubt resolution (ask the coordinator what happened; our `resolveIntent` asks
  the executor instead), and sagas (Garcia-Molina and Salem, compensating transactions).
