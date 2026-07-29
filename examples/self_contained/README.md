# Self-contained v0.3 demonstration — compatibility path

The fixture was promoted to the scored golden case at
[`golden_cases/self_contained/doc-bundle-01`](../../golden_cases/self_contained/doc-bundle-01/).
The historical launcher remains available through the v0.3 release line:

```console
python examples/self_contained/run_demo.py
```

New callers should use:

```console
python golden_cases/self_contained/doc-bundle-01/run_case.py
```

The compatibility launcher is deprecated and scheduled for removal in v0.4.
