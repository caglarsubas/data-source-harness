# Phase-4 verification gates

Run the complete chain with:

```bash
make phase4
```

| Gate | Required evidence |
|---|---|
| Preview | both industry actions expose bounded effects before mutation |
| Capability negotiation | both labs declare the bounded operation, compensation, idempotency and conditional-write support |
| Authorization | unauthorized false-allow rate is zero; policy is checked at preview and execution |
| Approval | high-risk execution without a valid human approval is denied |
| Conditional write | stale source version/value preconditions produce no side effect |
| Idempotency | replay produces one source mutation; key reuse with another digest is rejected |
| Compensation | white-goods appointment and cold-chain incident state are restored |
| Saga | a later conditional-write failure compensates the earlier successful step in reverse order |
| Postconditions | successful connectors explicitly confirm the intended state and source version |
| Audit | both hash chains verify and contain no raw action values |
| Failure injection | connector outages produce failed receipts; telemetry outages retain audit and replay safety |
| Semantic memory | unreviewed/self-reviewed promotion is denied; approved memory obeys agent scope |
| Delegation | exact A2A-facing mapping succeeds; extra fields fail; connector ABI has zero protocol tokens |
| Regression | all Phase-0 through Phase-3 gates rerun first |

These gates do not establish durable crash recovery, live A2A interoperability, production connector behavior, deployment runtime proof or stakeholder acceptance.
