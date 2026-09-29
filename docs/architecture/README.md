# Architecture Documentation

This directory contains system architecture specifications, design blueprints, data model contracts, and formal invariants for the savings and investment platform.

## Architecture Documents

| Document | Area | Status | Description |
| :--- | :--- | :--- | :--- |
| [Unified Ledger Schema](unified_ledger_schema.md) | Core Ledger / Accounting Engine | **In Review** | Mathematical parity invariant, unified allocation schema (`TransactionEvent`, `LedgerEntry`), composite index design, sub-10ms query templates, and multi-currency constraints. |

---

## Architectural Principles

1. **Parity Rule**: Every atomic slice of money binds physical location (`physical_account_id`), virtual objective (`virtual_account_id`), and legal ownership (`user_id`). Across any currency, the sum of all physical account balances strictly equals the sum of all virtual goal balances.
2. **Immutability**: Ledger entries are write-once and append-only. Balance modifications occur solely through new offsetting or true-up ledger entries.
3. **Decimal Precision**: All currency quantities are stored with `NUMERIC(18, 2)` precision. Floating-point arithmetic is prohibited across all data and service layers.
4. **Data Isolation**: Allocator roles have strict privacy boundaries; balance queries are filtered to only expose the caller's allocated share.
