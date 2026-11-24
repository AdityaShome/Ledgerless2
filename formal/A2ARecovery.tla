---------------------------- MODULE A2ARecovery ----------------------------
(* Chain A -> B -> C. Each agent has replicas with local durable stores.
   Each agent performs exactly one logical effect (one digest per agent);
   re-planned requests carry different request ids but the same digest.
   UseIntents = TRUE : write-ahead intents + digest dedup + resolveIntent.
   UseIntents = FALSE: request-id idempotency only (baseline).            *)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Replicas,    \* e.g. {1, 2}
          MaxReq,      \* number of distinct request ids per hop
          UseIntents,  \* BOOLEAN
          AllowCrash   \* BOOLEAN: crash only disables actions; off keeps safety runs small

Perms == Permutations(Replicas)

Agents == {"A", "B", "C"}
None   == "none"
Reqs   == 1..MaxReq

Parent(ag) == IF ag = "B" THEN "A" ELSE IF ag = "C" THEN "B" ELSE None

VARIABLES sent,       \* sent[ag]      : request ids the caller issued to ag
          delivered,  \* delivered[ag] : request ids that reached ag
          declared,   \* declared[ag][r] : intents durably written at replica r
          receipts,   \* receipts[ag][r] : receipts durably written at replica r
          tomb,       \* tomb[ag]      : request ids tombstoned (never execute)
          effects,    \* effects[ag]   : ground-truth effect counter
          alive,      \* alive[ag][r]
          acked       \* acked[ag]     : caller holds a verified receipt

vars == <<sent, delivered, declared, receipts, tomb, effects, alive, acked>>

AllReceipts(ag) == UNION {receipts[ag][r] : r \in Replicas}

Init ==
  /\ sent      = [ag \in Agents |-> {}]
  /\ delivered = [ag \in Agents |-> {}]
  /\ declared  = [ag \in Agents |-> [r \in Replicas |-> {}]]
  /\ receipts  = [ag \in Agents |-> [r \in Replicas |-> {}]]
  /\ tomb      = [ag \in Agents |-> {}]
  /\ effects   = [ag \in Agents |-> 0]
  /\ alive     = [ag \in Agents |-> [r \in Replicas |-> TRUE]]
  /\ acked     = [ag \in Agents |-> FALSE]

(* Caller sends (or re-plans and resends) a request with a fresh id.
   Delegation to ag requires the parent hop to have committed.
   With intents, the caller must first resolve every earlier attempt. *)
Send(ag, k) ==
  /\ k \in Reqs \ sent[ag]
  /\ IF Parent(ag) = None THEN TRUE ELSE AllReceipts(Parent(ag)) # {}
  /\ ~acked[ag]
  /\ (UseIntents => sent[ag] \subseteq tomb[ag])
  /\ sent' = [sent EXCEPT ![ag] = @ \cup {k}]
  /\ UNCHANGED <<delivered, declared, receipts, tomb, effects, alive, acked>>

(* Delivery; duplicate delivery is idempotent on the set, loss = never taken. *)
Deliver(ag, k) ==
  /\ k \in sent[ag]
  /\ delivered' = [delivered EXCEPT ![ag] = @ \cup {k}]
  /\ UNCHANGED <<sent, declared, receipts, tomb, effects, alive, acked>>

Declare(ag, r, k) ==
  /\ UseIntents
  /\ alive[ag][r]
  /\ k \in delivered[ag]
  /\ k \notin declared[ag][r]
  /\ declared' = [declared EXCEPT ![ag][r] = @ \cup {k}]
  /\ UNCHANGED <<sent, delivered, receipts, tomb, effects, alive, acked>>

(* Effect and local receipt commit atomically at replica r.
   Intents: dedup by digest across the agent's replicas (peer lookup / resolve).
   Baseline: dedup by request id in the local store only. *)
Execute(ag, r, k) ==
  /\ alive[ag][r]
  /\ k \in delivered[ag]
  /\ k \notin tomb[ag]
  /\ IF UseIntents
       THEN k \in declared[ag][r] /\ AllReceipts(ag) = {}
       ELSE ~\E x \in receipts[ag][r] : x.req = k
  /\ \E p \in (IF Parent(ag) = None THEN {None} ELSE AllReceipts(Parent(ag))) :
        receipts' = [receipts EXCEPT ![ag][r] =
                       @ \cup {[ag |-> ag, req |-> k, prev |-> p]}]
  /\ effects' = [effects EXCEPT ![ag] = @ + 1]
  /\ UNCHANGED <<sent, delivered, declared, tomb, alive, acked>>

(* Receipt reaches the caller; may never happen (F1/F2). *)
DeliverReceipt(ag) ==
  /\ AllReceipts(ag) # {}
  /\ ~acked[ag]
  /\ acked' = [acked EXCEPT ![ag] = TRUE]
  /\ UNCHANGED <<sent, delivered, declared, receipts, tomb, effects, alive>>

(* recovery/resolveIntent: report committed receipt, else durably tombstone. *)
Resolve(ag) ==
  /\ UseIntents
  /\ ~acked[ag]
  /\ sent[ag] # {}
  /\ (AllReceipts(ag) # {} \/ sent[ag] \ tomb[ag] # {})
  /\ IF AllReceipts(ag) # {}
       THEN /\ acked' = [acked EXCEPT ![ag] = TRUE]
            /\ UNCHANGED tomb
       ELSE /\ tomb' = [tomb EXCEPT ![ag] = @ \cup sent[ag]]
            /\ UNCHANGED acked
  /\ UNCHANGED <<sent, delivered, declared, receipts, effects, alive>>

Crash(ag, r) ==
  /\ AllowCrash
  /\ alive[ag][r]
  /\ alive' = [alive EXCEPT ![ag][r] = FALSE]
  /\ UNCHANGED <<sent, delivered, declared, receipts, tomb, effects, acked>>

Restart(ag, r) ==
  /\ ~alive[ag][r]
  /\ alive' = [alive EXCEPT ![ag][r] = TRUE]
  /\ UNCHANGED <<sent, delivered, declared, receipts, tomb, effects, acked>>

Next ==
  \E ag \in Agents :
     \/ \E k \in Reqs : Send(ag, k) \/ Deliver(ag, k)
     \/ \E r \in Replicas, k \in Reqs : Declare(ag, r, k) \/ Execute(ag, r, k)
     \/ DeliverReceipt(ag)
     \/ Resolve(ag)
     \/ \E r \in Replicas : Crash(ag, r) \/ Restart(ag, r)

Spec == Init /\ [][Next]_vars /\ \A ag \in Agents : WF_vars(Resolve(ag))

----------------------------------------------------------------------------
\* Invariants

NoDuplicateEffect == \A ag \in Agents : effects[ag] <= 1

NoLostEffect ==
  \A ag \in Agents :
    effects[ag] = Cardinality(UNION {{<<r, x>> : x \in receipts[ag][r]} : r \in Replicas})

ReceiptChainValid ==
  \A ag \in Agents : \A r \in Replicas : \A x \in receipts[ag][r] :
    IF Parent(ag) = None
      THEN x.prev = None
      ELSE x.prev \in AllReceipts(Parent(ag))

\* Liveness (needs UseIntents = TRUE and fair Resolve)
InDoubtResolves ==
  \A ag \in Agents, k \in Reqs :
    (k \in sent[ag]) ~> (k \in tomb[ag] \/ AllReceipts(ag) # {})

=============================================================================
