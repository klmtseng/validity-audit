# Self-contained scored golden case

`doc-bundle-01` promotes the original v0.3 self-contained demonstration into a complete public-key
regression case. It contains its target artifacts, task contract, reviewer transcript and output,
frozen versioned key, expected unsigned attestation, and explicit scoring rules.

From the repository root:

```bash
python golden_cases/self_contained/doc-bundle-01/run_case.py
```

The runner uses fixed ids and timestamps, writes only to a temporary directory below
`.validity-audit/`, verifies the complete unsigned attestation, scores the reviewer output against
`key-v1.json`, and removes the temporary run directory.

It uses no network and no API key. The checked-in reviewer output is deliberately primed fixture
data, so the resulting score is a regression check rather than cold-review evidence.
