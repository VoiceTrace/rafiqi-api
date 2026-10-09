# Rafiqi backend: architecture and database

Generated from source commit `ad0717cefe31da9b797e1234d94f887a15fde07a` on 2026-09-24 (initial baseline: latest `main`).

Scope: **13 application tables, 99 columns, 25 foreign keys, 25 API operations, 9 migrations**. PostgreSQL 16 is the local Compose target.

## Files

- [Complete database dictionary](../database-layout.md)
- [PostgreSQL schema SQL](../database-schema.sql)
- [Machine-readable schema](../database-schema.json)
- [Implemented API inventory](../api-layout.md)
- [JSON structures and behavior](../json-and-behavior.md)

## Evidence and boundaries

The schema was reconstructed from migration declarations without running their data operations, then checked against SQLAlchemy models for tables, columns, types, nullability, foreign keys, unique constraints, checks and indexes. SQL is reference DDL; deploy with Alembic so catalog seed data and version history are applied. The Alembic-owned `alembic_version` bookkeeping table is not one of the 13 application tables. No live database was inspected or modified.

The checked-in generator can refresh these files with the backend Python environment: `python scripts/generate_backend_layout.py`. Diagrams describe implemented behavior, rather than future product-plan features. Each diagram is also supplied as editable `.mmd` source.

## Backend architecture

[Mermaid source](../backend-architecture.mmd)

![diagram](./README-1.svg)

## Complete entity relationship diagram

[Mermaid source](../database-erd.mmd)

![diagram](./README-2.svg)

## Authentication

[Mermaid source](../authentication-flow.mmd)

![diagram](./README-3.svg)

## Review persistence flow

[Mermaid source](../review-flow.mmd)

![diagram](./README-4.svg)

## Review state transitions

[Mermaid source](../review-state.mmd)

![diagram](./README-5.svg)

## Migration history

[Mermaid source](../migration-history.mmd)

![diagram](./README-6.svg)
