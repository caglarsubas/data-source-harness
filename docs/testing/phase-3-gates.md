# Phase-3 verification gates

Run the complete Phase-0 through Phase-3 chain with:

```bash
make phase3
```

| Gate | Required evidence |
|---|---|
| Generator | two runs are byte-identical and reproduce all committed fixtures |
| Relationships | every container, reading and incident reference resolves |
| Scaffold | all declared OpenAPI operations are captured; generated source compiles; profile validates |
| Package integrity | payload checksums and the manifest/SBOM signature verify offline |
| Negative verification | a mismatched signer identity and tampered archive are rejected |
| SBOM | every connector payload file has a SHA-256 CycloneDX component |
| Contract reuse | the 14 current schemas equal the frozen Phase-2 SHA-256 map |
| Portability | public core source contains no first-pilot tokens |
| Pilot scenario | representative synthetic temperature excursions are detected |
| Regression | all Phase-0, Phase-1 and Phase-2 gates rerun first |

The certificate does not substitute for live integration, production deployment, asymmetric/HSM-backed signing or stakeholder acceptance.
