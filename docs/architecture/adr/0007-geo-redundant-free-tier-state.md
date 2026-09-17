# ADR-0007: Geo-Redundant State & Zero-Cost Free Tier Infrastructure

**Status:** Proposed (Pending Operator Review)  
**Date:** 2026-09-02  

## Context

Universal Brain requires 24/7 background operation, relational state tracking, and vector search, but operating commercial managed databases and high-memory cloud VMs creates unacceptable recurring overhead ($100–$300+/month). Running on free-tier infrastructure (Oracle Cloud Always Free) is viable but carries the risk of instance termination or abrupt disk loss.

## Decision

We adopt a **4-Tier Geo-Redundant Architecture** running on free cloud resources with off-site replication:
1. **Compute Host:** Deploy the Sovereign Kernel on Oracle Cloud Always Free (4 ARM cores, 24GB RAM).
2. **Real-Time Replication:** Stream state-changing events in real time to an append-only `journal.jsonl` stored on off-site cloud storage (Google Drive).
3. **Periodic Snapshots:** Run automated, encrypted database dumps (`pg_dump`) every 6 hours and push them to a private GitHub repository.
4. **Vector Co-Location:** Store embeddings directly inside PostgreSQL as `pgvector` or `JSONB` columns rather than maintaining standalone binary vector database directories, ensuring vectors travel with the database snapshot.
5. **Cold Storage Mounts:** Mount large knowledge files and datasets from Google Drive via `rclone`.

## Consequences

- **Positive:** Reduces cloud infrastructure cost to **$0.00/month**.
- **Positive:** Eliminates Single Points of Failure (SPOF): if the Oracle VM terminates, a replacement VM can restore the database from the 6-hour GitHub dump and replay the Google Drive journal to achieve an RPO of 0 seconds.
- **Negative / Complexity:** Requires maintaining the `memory_replicator` daemon, rclone mount configs, and off-site credentials.
