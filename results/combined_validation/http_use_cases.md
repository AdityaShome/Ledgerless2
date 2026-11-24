# Real HTTP use-case validation

Synthetic effects with idempotent per-organization providers. No live LLMs or real transactions.

Predeclared recovery-metadata budget: 65536 bytes per hop.
Bytes are JSON bodies and recovery metadata; transport headers and dashboard polling are excluded.

| Use case | Fault | Status | Duplicates | Uncompleted | ms | Budget |
|---|---|---|---:|---:|---:|---|
| commerce | clean | completed | 0 | 0 | 372.689 | True |
| commerce | crash_after_commit | completed | 0 | 0 | 468.205 | True |
| commerce | lost_response | completed | 0 | 0 | 578.288 | True |
| commerce | duplicate_delivery | completed | 0 | 0 | 650.131 | True |
| commerce | replica_failover | completed | 0 | 0 | 534.622 | True |
| commerce | replan_same_effect | completed | 0 | 0 | 626.016 | True |
| commerce | transient_partition | completed | 0 | 0 | 605.651 | True |
| commerce | permanent_partition | quarantine | 0 | 0 | 363.906 | True |
| commerce | forged_receipt | quarantine | 0 | 0 | 267.386 | True |
| commerce | upstream_abort | compensated | 0 | 0 | 320.342 | True |
| commerce | changed_action | quarantine | 0 | 0 | 368.566 | True |
| logistics | clean | completed | 0 | 0 | 316.002 | True |
| logistics | crash_after_commit | completed | 0 | 0 | 449.89 | True |
| logistics | lost_response | completed | 0 | 0 | 628.675 | True |
| logistics | duplicate_delivery | completed | 0 | 0 | 613.713 | True |
| logistics | replica_failover | completed | 0 | 0 | 520.322 | True |
| logistics | replan_same_effect | completed | 0 | 0 | 646.96 | True |
| logistics | transient_partition | completed | 0 | 0 | 597.336 | True |
| logistics | permanent_partition | quarantine | 0 | 0 | 361.146 | True |
| logistics | forged_receipt | quarantine | 0 | 0 | 275.302 | True |
| logistics | upstream_abort | compensated | 0 | 0 | 341.762 | True |
| logistics | changed_action | quarantine | 0 | 0 | 357.411 | True |
| healthcare | clean | completed | 0 | 0 | 319.435 | True |
| healthcare | crash_after_commit | completed | 0 | 0 | 454.484 | True |
| healthcare | lost_response | completed | 0 | 0 | 551.274 | True |
| healthcare | duplicate_delivery | completed | 0 | 0 | 606.457 | True |
| healthcare | replica_failover | completed | 0 | 0 | 511.658 | True |
| healthcare | replan_same_effect | completed | 0 | 0 | 623.474 | True |
| healthcare | transient_partition | completed | 0 | 0 | 605.094 | True |
| healthcare | permanent_partition | quarantine | 0 | 0 | 345.776 | True |
| healthcare | forged_receipt | quarantine | 0 | 0 | 263.0 | True |
| healthcare | upstream_abort | compensated | 0 | 0 | 313.065 | True |
| healthcare | changed_action | quarantine | 0 | 0 | 355.432 | True |
| marketplace | clean | completed | 0 | 0 | 314.156 | True |
| marketplace | crash_after_commit | completed | 0 | 0 | 525.74 | True |
| marketplace | lost_response | completed | 0 | 0 | 552.507 | True |
| marketplace | duplicate_delivery | completed | 0 | 0 | 601.863 | True |
| marketplace | replica_failover | completed | 0 | 0 | 502.786 | True |
| marketplace | replan_same_effect | completed | 0 | 0 | 627.546 | True |
| marketplace | transient_partition | completed | 0 | 0 | 607.947 | True |
| marketplace | permanent_partition | quarantine | 0 | 0 | 347.379 | True |
| marketplace | forged_receipt | quarantine | 0 | 0 | 260.31 | True |
| marketplace | upstream_abort | compensated | 0 | 0 | 315.791 | True |
| marketplace | changed_action | quarantine | 0 | 0 | 370.907 | True |
| travel | clean | completed | 0 | 0 | 331.852 | True |
| travel | crash_after_commit | completed | 0 | 0 | 461.432 | True |
| travel | lost_response | completed | 0 | 0 | 568.261 | True |
| travel | duplicate_delivery | completed | 0 | 0 | 616.16 | True |
| travel | replica_failover | completed | 0 | 0 | 533.615 | True |
| travel | replan_same_effect | completed | 0 | 0 | 631.673 | True |
| travel | transient_partition | completed | 0 | 0 | 598.008 | True |
| travel | permanent_partition | quarantine | 0 | 0 | 364.52 | True |
| travel | forged_receipt | quarantine | 0 | 0 | 263.688 | True |
| travel | upstream_abort | compensated | 0 | 0 | 326.392 | True |
| travel | changed_action | quarantine | 0 | 0 | 356.043 | True |
