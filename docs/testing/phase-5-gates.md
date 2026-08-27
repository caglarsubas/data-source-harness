# Phase-5 verification gates

Run the complete regression and certification chain with:

```bash
make phase5
```

| Gate | Required evidence |
|---|---|
| Write-ahead state | `executing` is durable before source dispatch |
| Unknown outcome | injected post-dispatch failure becomes `reconciliation-required` |
| Blind replay | a restarted gateway rejects `execute` before connector invocation |
| Source reconciliation | idempotency/postcondition evidence produces a `recovered` receipt |
| Duplicate safety | each white-goods and cold-chain action has exactly one source effect |
| Journal restart | pending state survives reopening the SQLite journal |
| Journal integrity | the persistent metadata event chain verifies |
| Payload privacy | raw action and precondition values are absent from the journal database |
| Tool scope | each agent lists only its tool; an outsider lists none |
| Catalog pinning | changed tool metadata rejects the stale digest |
| Protocol isolation | connector source contains zero northbound/JSON-RPC coupling tokens |
| Air gap | the complete Phase-5 certificate records zero socket-connect attempts |
| Regression | the complete Phase-0 through Phase-4 certificate chain remains green |

The certificate exercises a deterministic post-dispatch crash-window hook and
reopens the journal with a new gateway instance. It does not simulate abrupt
kernel or power loss, prove multi-node coordination, certify an official MCP/A2A
server, deploy to OpenShift or record stakeholder acceptance.
