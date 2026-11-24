-------------------------- MODULE A2ARecovery_cut --------------------------
(* Refines the original bounded chain model with causal checkpoint knowledge.
   Propagation is asynchronous: observers need not have equal vectors. *)
EXTENDS A2ARecovery

VARIABLE cuts
cutVars == <<sent, delivered, declared, receipts, tomb, effects, alive, acked, cuts>>

ZeroCut == [hop \in Agents |-> 0]
Join(left, right) == [hop \in Agents |->
    IF left[hop] >= right[hop] THEN left[hop] ELSE right[hop]]

(* A hop's linked receipt certifies its ancestors in this linear chain. *)
Ancestors(ag) == IF ag = "A" THEN {"A"}
                 ELSE IF ag = "B" THEN {"A", "B"} ELSE Agents
Publication(ag) == [hop \in Agents |-> IF hop \in Ancestors(ag) THEN 1 ELSE 0]

InitCut == Init /\ cuts = [ag \in Agents |-> ZeroCut]
BaseStep == Next /\ UNCHANGED cuts
PublishCut(ag) ==
    /\ AllReceipts(ag) # {}
    /\ cuts' = [cuts EXCEPT ![ag] = Join(@, Publication(ag))]
    /\ UNCHANGED vars
CutPropagate(ag, ag2) ==
    /\ cuts' = [cuts EXCEPT ![ag2] = Join(@, cuts[ag])]
    /\ UNCHANGED vars

NextCut == BaseStep \/ (\E ag \in Agents : PublishCut(ag))
                    \/ (\E ag, ag2 \in Agents : CutPropagate(ag, ag2))
SpecCut == InitCut /\ [][NextCut]_cutVars

CutType == cuts \in [Agents -> [Agents -> 0..1]]
(* Downward closure: observing a child requires its delegation ancestors. *)
CutConsistency == \A ag \in Agents :
    /\ (cuts[ag]["C"] = 1 => cuts[ag]["B"] = 1)
    /\ (cuts[ag]["B"] = 1 => cuts[ag]["A"] = 1)
    /\ \A hop \in Agents : cuts[ag][hop] <= Cardinality(AllReceipts(hop))
NoDuplicateEffectCut == NoDuplicateEffect
CutMonotonic == \A ag, hop \in Agents : cuts'[ag][hop] >= cuts[ag][hop]
CutNeverRegresses == [][CutMonotonic]_cutVars
=============================================================================
