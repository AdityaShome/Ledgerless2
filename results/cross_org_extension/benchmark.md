Local adapter benchmark (simulated faults; no HTTP or LLM latency).

| Scenario | Adapter | Duplicates | Lost | Wrong task | Quarantine | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| duplicate_execution | ledgerless | 0 | 0 | 0 | 0% | 4.415 | 11.233 |
| duplicate_execution | default_sdk | 0 | 0 | 0 | 0% | 2.090 | 10.915 |
| duplicate_execution | temporal_bridge_sim | 0 | 0 | 0 | 0% | 1.871 | 2.680 |
| duplicate_execution | mesh_quarantine_sim | 0 | 0 | 0 | 0% | 3.590 | 30.436 |
| lost_event | ledgerless | 0 | 0 | 0 | 0% | 3.855 | 15.987 |
| lost_event | default_sdk | 30 | 0 | 0 | 0% | 1.758 | 4.813 |
| lost_event | temporal_bridge_sim | 0 | 0 | 0 | 0% | 1.839 | 4.903 |
| lost_event | mesh_quarantine_sim | 0 | 0 | 0 | 100% | 2.204 | 6.838 |
| lost_request | ledgerless | 0 | 0 | 0 | 0% | 2.439 | 4.042 |
| lost_request | default_sdk | 0 | 0 | 0 | 0% | 0.883 | 1.505 |
| lost_request | temporal_bridge_sim | 0 | 0 | 0 | 0% | 0.980 | 10.162 |
| lost_request | mesh_quarantine_sim | 0 | 30 | 0 | 100% | 0.039 | 0.143 |
| wrong_task_recovery | ledgerless | 0 | 0 | 0 | 100% | 1.883 | 2.681 |
| wrong_task_recovery | default_sdk | 0 | 0 | 30 | 0% | 1.030 | 1.755 |
| wrong_task_recovery | temporal_bridge_sim | 0 | 0 | 0 | 0% | 0.739 | 1.936 |
| wrong_task_recovery | mesh_quarantine_sim | 0 | 0 | 0 | 100% | 1.944 | 8.403 |
| recovery_time | ledgerless | 0 | 0 | 0 | 0% | 0.111 | 0.316 |
| recovery_time | default_sdk | 0 | 0 | 0 | 0% | 0.008 | 0.011 |
| recovery_time | temporal_bridge_sim | 0 | 0 | 0 | 0% | 0.008 | 0.010 |
| recovery_time | mesh_quarantine_sim | 0 | 0 | 0 | 100% | 0.008 | 0.010 |
