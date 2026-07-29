# Self-contained v0.3 demonstration

This fixture exercises the complete provider-neutral path:

1. validate one task contract;
2. snapshot and digest two artifacts;
3. run deterministic probes;
4. emit a cold-review bundle;
5. import structured reviewer output and retain the raw transcript;
6. apply the versioned policy;
7. emit an unsigned attestation and compare it with a frozen expected record.

From the repository root, after installing the development dependencies:

```bash
python examples/self_contained/run_demo.py
```

The script uses fixed run timestamps and ids, writes only below the ignored
`.validity-audit/` directory, compares the complete attestation, and removes its temporary
run directory before exiting.
