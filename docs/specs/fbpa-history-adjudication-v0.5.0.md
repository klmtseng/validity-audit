# FBPA historical results: hand adjudication (v0.5.0)

Input: `docs/specs/fbpa-history-v0.5.0.md` and `benchmarks/fbpa_history/results/pr-<n>.json` on branch
`feat/fbpa-probe`. First adjudication at HEAD `37919fe4f03dcfb567ad1d65419dc7ab18eadf4a`. **Revised for the
rerun at HEAD `6bea9a32a4f7b0d1667785f947e97b82671f58f8`** (see "Revision" below). Spec:
`docs/specs/probe-fail-before-pass-after.md` (§3, §3.4, §4, §7, §9).

The adjudicator did not build or run the probe. The probe's verdicts were treated as unverified input.

## Revision (rerun at 6bea9a3)

- The S2 table was rerun for all 21 PRs in a clean, deps-only venv: user site off, dev+quant extras. Each
  result records its `environment`: python 3.12.3, pytest 8.4.2, jsonschema 4.26.0, numpy 2.4.2,
  pandas 2.3.3, scipy 1.17.1.
- PR #5 now uses base `683d631c0024ab10858471fec59d176bd4f5d0a6`, because it was rebase-merged as two
  commits. The PR #5 rerun exposed a probe fail-open: the editable install's finder served submodules that
  were missing from the base package. It was fixed by the runtime module-origin audit (spec §2, amendment 6).
- New totals: 135 claims. demonstrated 34, base_passes 24, absence_only 35, inconclusive 42, fault 0.
- **Diff check.** Every claim in every PR other than #1 and #5 was compared old-vs-new (`57962e2` vs `HEAD`
  result JSON) on two levels:
  - verdict, base class and components;
  - every per-case base/head outcome, exception type, phase, `first_failure_line` and absence target.

  Result: **0 differences**, so every row adjudicated for those PRs below still stands.
- PR #1 changed (the fault became real verdicts). It is adjudicated in §A/§B/§C.
- PR #5 changed completely (37 claims: 23 absence_only, 14 inconclusive). Its old rows were measured
  against the wrong base (`9637208`). Those 2 base_passes and 3 demonstrated rows are **void and removed**.
  The new rows are checked in §C.

## Method

- (First pass) Recount from the JSON: 115 claims. demonstrated 33, base_passes 24, inconclusive 34, absence_only 7,
  fault 17 (all in PR #1). base_passes per PR: #5:2, #6:3, #10:3, #14:2, #15:2, #17:4, #23:8. This matches
  the orchestrator's recount.
- Every base_passes test was read at head and checked against the PR diff (`git show <sha>`) and the PR
  title and body (`gh pr view`).
- **Independent rerun of all 24 base_passes rows at base.** This used a scratch clone and separate
  worktrees at `<sha>^`, with every head `tests/` file copied over the base tree and base-only test files
  deleted (spec §1.2). The interpreter was a venv with no user site, run with `PYTHONNOUSERSITE=1` and
  `PYTHONPATH=<worktree>:~/.local/.../site-packages`. That path list does not process `.pth` files, so the
  editable install at `~/src/va-audit` is not visible. `validity_audit.__file__` was checked on
  each side and resolved inside the worktree. Everything ran under
  `systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0`.
  Result: **all 24 pass at base.** Every case passed and every pytest run exited 0. So the probe did not
  misjudge any of these rows.
- All 33 demonstrated rows were adjudicated, not just a sample. The `first_failure_line` stored in the
  JSON was used to see *which* assertion failed at base.
- One mutation check was run on PR #23 (see the per-PR section).

Classes for base_passes:

- `probe_wrong`: the test really fails at base.
- `weak_test`: the PR claims a fix and this test does not guard it.
- `characterization`: passing at base is expected.
- `unclear`: the evidence does not decide it.

Classes for demonstrated:

- `sound`: the base failure is the behaviour the PR changes.
- `weak_evidence`: the base failure comes only from a doc or file that head adds, from a version or
  identifier constant, or from message wording, while the behavioural outcome is the same at base.
- `probe_wrong`: the probe misjudged the row.

## A. base_passes rows (24; PR #5's two void rows removed, PR #1's two added)

| PR | node id | probe | class | reason |
|---|---|---|---|---|
| 1 | tests/test_golden_cases.py::test_case_ids_are_unique | base_passes | characterization | test_golden_cases.py:18. The three base cases already had distinct `case_id`s. The PR claims no id fix. (high) |
| 1 | tests/test_golden_cases.py::test_canonical_answer_keys_are_not_duplicated | base_passes | **weak_test** | test_golden_cases.py:54. PR #1 says it "converts the duplicate content-pipeline case into a metric-excluded alias", and at base `content-pipeline-2026-07.json` duplicates `study-forge-2026-07.json` in paraphrase ("110 items" vs "110 verbs", reordered fields). The test compares `json.dumps(expected_findings, sort_keys=True)` for exact equality, so it passed with the real duplicate present. It cannot catch the duplication the PR fixes. The fix's shape is covered only by `test_aliases_...`, which is weak evidence (§B). (high) |
| 6 | tests/test_golden_cases.py::test_findings_use_canonical_severity | base_passes | characterization | test_golden_cases.py:60. The loop now also covers `self_contained/*/case.json`, which head adds. At base that glob is empty, so the test passes over the historical cases only. This is a feature PR and claims no fix. (high) |
| 6 | tests/test_golden_cases.py::test_canonical_answer_keys_are_not_duplicated | base_passes | characterization | test_golden_cases.py:70. Same mechanism: the pass is vacuous over data that head adds. (high) |
| 6 | tests/test_golden_cases.py::test_external_keys_are_frozen_versioned_and_digest_pinned | base_passes | characterization | test_golden_cases.py:82. No base case has a `key` field, so the loop body never runs. It validates the new frozen key data. (high) |
| 10 | tests/test_benchmarks.py::test_injected_floor_baseline_is_preserved | base_passes | characterization | test_benchmarks.py:21. The only change is `pytest.importorskip("numpy")` plus a moved import. The onboarding fix lives in test code (spec §9 `test_paths` limitation) and only shows up without numpy. (high) |
| 10 | tests/test_benchmarks.py::test_legacy_injected_shim_matches_canonical_output | base_passes | characterization | test_benchmarks.py:36. Same as the row above: only the importorskip guard was added. (high) |
| 10 | tests/test_markdown_injection.py::test_single_line_md_title_does_not_produce_heading_outside_template | base_passes | **weak_test** | test_markdown_injection.py:155. The title is rendered after `- \`id\` — **gate** — `, so no line can ever start with `#`. The test only checks `ln.startswith("#")` (and `signature is None`). All 6 parametrized cases pass at base, which has no `_sanitize_md_title` at all. The leading-character escape (runtime.py `_MD_STRUCTURE_STARTS`, step 3) is therefore unguarded. The PR body says "the pre-patch code fails it", which is false for this test. (high) |
| 14 | tests/test_probe_challenges.py::test_probe_positive_control_clean_artifact_passes | base_passes | characterization | test_probe_challenges.py:12. A standing positive control. The PR says "Normal successful probe output is unchanged". (high) |
| 14 | tests/test_probe_challenges.py::test_probe_negative_control_broken_markdown_link_fails | base_passes | characterization | test_probe_challenges.py:23. A standing negative control for the broken-link detection that already existed. (high) |
| 15 | tests/test_benchmarks.py::test_duplicate_finding_ids_are_rejected | base_passes | characterization | test_benchmarks.py:88. A refactor from try/except to `pytest.raises`. Duplicate detection existed at base in `_unique_by_id`. (high) |
| 15 | tests/test_benchmarks.py::test_explicit_empty_findings_are_not_confused_with_missing_field | base_passes | characterization | test_benchmarks.py:95. Explicit `[]` was already accepted at base. The PR says it "preserves explicit empty lists". This is the positive half of the pair; the negative half is demonstrated. (high) |
| 17 | tests/test_runtime.py::test_review_import_positive_control_exact_claim_coverage_passes | base_passes | characterization | test_runtime.py:409. The PR body says "This PR does not change runtime semantics" (non_test_diff_count=1, docs only). (high) |
| 17 | tests/test_runtime.py::test_review_import_negative_control_missing_claim_result_fails_closed | base_passes | characterization | test_runtime.py:416. A standing control for a fail-closed invariant that already existed. No fix is claimed. (high) |
| 17 | tests/test_runtime.py::test_review_import_fault_control_unknown_finding_link_fails_closed | base_passes | characterization | test_runtime.py:436. Same as the row above. (high) |
| 17 | tests/test_runtime.py::test_review_import_negative_control_refuted_claim_without_finding_fails_closed | base_passes | characterization | test_runtime.py:456. Same as the row above. (high) |
| 23 | tests/test_policy.py::test_non_high_severity_unreproduced_advisory_class_stays_advisory | base_passes | characterization | test_policy.py:192. The boundary of the new severity rule: med/low stay advisory, as they did before. Both cases pass at base. (high) |
| 23 | tests/test_policy.py::test_refuted_claim_forces_advisory_class_to_fail | base_passes | characterization | test_policy.py:206. Only the fixture class changed (`novel-error-class` → `fitness`) because unknown classes are now rejected. The refutation→fail path already existed. (high) |
| 23 | tests/test_policy.py::test_active_waiver_preserves_original_policy_result | base_passes | characterization | test_policy.py:260. Adapter only: `contract(waiver_issuers=["owner"])` was added so the old behaviour survives the new issuer rule. (high) |
| 23 | tests/test_policy.py::test_expired_waiver_is_rejected | base_passes | characterization | test_policy.py:281. Adapter only, as in the row above. (high) |
| 23 | tests/test_policy.py::test_waiver_cannot_turn_unattempted_blocker_into_pass | base_passes | characterization | test_policy.py:322. Adapter only, as in the row above. (high) |
| 23 | tests/test_policy.py::test_waiver_unknown_target_is_reported_before_issuer_check | base_passes | characterization | test_policy.py:427. Base already raised "waiver requests reference unknown findings" (base policy.py:127-129) and had no issuer check. The ordering only means something relative to the new check. At head the test does guard a future reordering. (medium) |
| 23 | tests/test_policy.py::test_refuted_advisory_class_finding_fails_regardless_of_severity | base_passes | characterization | test_policy.py:487. Its own comment says "Documents the current behavior of the refutation path". (high) |
| 23 | tests/test_policy.py::test_summary_names_only_the_blocking_class_cause_when_alone | base_passes | characterization | test_policy.py:531. The negative half of a pair. The old summary contains "blocking-class finding lacks completed reproduction" and never mentions high severity. The positive half (`test_summary_distinguishes_...`) is demonstrated. (medium) |

## B. demonstrated rows (34; all adjudicated, of which 5 are B_FAIL_EXC; PR #5's three void rows removed, PR #1's four added)

| PR | node id | base class | class | reason |
|---|---|---|---|---|
| 1 | tests/test_golden_cases.py::test_aliases_are_excluded_and_point_to_canonical_case | B_FAIL_ASSERT | weak_evidence | test_golden_cases.py:23. The first failing line is `assert aliases`: the alias record is data that head adds. The base duplicate is not detected as a duplicate, and the alias content checks never run at base. (medium) |
| 1 | tests/test_golden_cases.py::test_canonical_cases_reference_public_domain_packs | B_FAIL_ASSERT | sound | test_golden_cases.py:35. At base, two cases referenced `fitness`, which has no `domains/fitness.md`. Head removes the dangling reference, a real data-integrity fix. (high) |
| 1 | tests/test_golden_cases.py::test_findings_use_canonical_severity | B_FAIL_ASSERT | sound | test_golden_cases.py:45. Base data held `medium`/`P1`/`advisory` severities, which is exactly the silently mis-ranked vocabulary the PR names. Head normalises them. (high) |
| 1 | tests/test_markdown_links.py::test_relative_markdown_links_resolve_from_the_linking_file | B_FAIL_ASSERT | sound | test_markdown_links.py. Base docs had broken relative links. The PR claims "fixes repository-relative documentation links". (high) |
| 7 | tests/test_policy.py::test_explicit_advisory_error_class_passes | B_FAIL_ASSERT (1/2) | sound | test_policy.py:126. The `fitness` case: fitness was unclassified at base (needs_review). Head adds `"fitness": "advisory"` to policy.py. (high) |
| 7 | tests/test_release_docs.py::test_architecture_svg_is_parseable_and_names_all_layers_and_modes | B_FAIL_EXC (FileNotFoundError) | weak_evidence | test_release_docs.py:41. `docs/architecture.svg` is added by head. This is a pure absence failure (spec §9 limitation). (high) |
| 7 | tests/test_release_docs.py::test_documented_attestation_is_schema_valid_and_reproduced | B_FAIL_EXC (FileNotFoundError) | weak_evidence | test_release_docs.py:13. `docs/attestation-example.json` is added by head. (high) |
| 7 | tests/test_release_docs.py::test_fitness_policy_and_readme_table_agree | B_FAIL_EXC (KeyError 'fitness') | sound | test_release_docs.py:57. The KeyError is on `ERROR_CLASS_EFFECTS["fitness"]`, a policy-table entry that head adds. That entry is the behavioural change (it is the same fact the policy test above checks). This is close to absence, but the missing item is data, not a symbol. (medium) |
| 7 | tests/test_release_docs.py::test_legacy_shim_window_is_documented | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:65. Checks for a README string that head adds. (high) |
| 7 | tests/test_release_docs.py::test_readme_quickstart_commands_are_ci_commands | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:30. Checks for a README string that head adds. (high) |
| 10 | tests/test_markdown_injection.py::test_inline_injection_vectors_rendered_as_literal_text | B_FAIL_ASSERT (4/4) | sound | test_markdown_injection.py:211. At base, raw `](http` and other inline syntax reach attestation.md. Head escapes it. (high) |
| 10 | tests/test_markdown_injection.py::test_title_with_newline_is_rejected_by_schema | B_FAIL_ASSERT (3/3) | sound | test_markdown_injection.py:188. "DID NOT RAISE": the base schema had no single-line pattern. (high) |
| 10 | tests/test_markdown_injection.py::test_unicode_line_separators_rejected_by_schema | B_FAIL_ASSERT (5/5) | sound | test_markdown_injection.py:271. The base schema did not reject U+2028 and similar characters. (high) |
| 13 | tests/test_release_docs.py::test_development_version_and_readme_maturity_agree | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:43. A version constant (`'0.3.0' == '0.4.0.dev0'`). (high) |
| 13 | tests/test_release_docs.py::test_verifier_challenge_contract_names_all_three_controls | B_FAIL_EXC (FileNotFoundError) | weak_evidence | test_release_docs.py:52. `protocol/VERIFIER_CHALLENGES.md` is added by head. (high) |
| 14 | tests/test_probe_challenges.py::test_probe_fault_control_missing_non_markdown_artifact_fails_closed | B_FAIL_ASSERT | sound | test_probe_challenges.py:37. At base `run_probes` reported `artifact_readable: pass` for a missing file. This is exactly the bug the PR describes. (high) |
| 14 | tests/test_probe_challenges.py::test_probe_fault_control_non_utf8_markdown_fails_closed | B_FAIL_EXC (UnicodeDecodeError) | sound | test_probe_challenges.py:51. The exception comes from `run_probes`. At base, `markdown.read_text(encoding="utf-8")` (4234d70^ probes.py:14) crashes out of the check path, which is the documented bug. (high) |
| 15 | tests/test_benchmarks.py::test_scorer_fault_control_missing_denominator_fields_fail_closed | B_FAIL_ASSERT (3/3) | sound | test_benchmarks.py:119. At base `.get(field, [])` silently scored an omitted field. (high) |
| 16 | tests/test_release_docs.py::test_architecture_svg_is_parseable_and_names_v04_flow_and_challenge_loop | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:65. Checks for SVG text that head adds. This is a docs-only PR. (high) |
| 18 | tests/test_release_docs.py::test_architecture_svg_is_parseable_and_names_v04_flow_and_challenge_loop | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:67. Checks for SVG text. (high) |
| 18 | tests/test_release_docs.py::test_release_version_and_readme_maturity_agree | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:43. A version constant. (high) |
| 23 | tests/test_policy.py::test_policy_id_is_versioned | B_FAIL_ASSERT | weak_evidence | test_policy.py:79. An identifier constant (v0.3.0 → v0.5.0). (high) |
| 23 | tests/test_policy.py::test_unclassified_error_class_is_rejected | B_FAIL_ASSERT (3/3) | sound | test_policy.py:120. Base returned needs_review and did not raise. Head raises `PolicyError`. (high) |
| 23 | tests/test_policy.py::test_unclassified_error_class_lists_all_violations_at_once | B_FAIL_ASSERT | sound | test_policy.py:146. Base did not raise at all. This is real, but it shows "rejects", not "lists all at once". (medium) |
| 23 | tests/test_policy.py::test_high_severity_unreproduced_advisory_class_needs_review | B_FAIL_ASSERT (3/3) | sound | test_policy.py:177. gate_effect was advisory at base and is none at head, so this part is real. But the status assertion is confounded: `claims("inconclusive")` already gives needs_review at base. (medium) |
| 23 | tests/test_policy.py::test_unclassified_error_class_cannot_be_waived | B_FAIL_ASSERT | weak_evidence | test_policy.py:300. Base also refused, with "has an unclassified error class and cannot be waived". Only the regex changed (`error class` → `error_class`). (high) |
| 23 | tests/test_policy.py::test_waiver_without_declared_issuers_is_rejected | B_FAIL_ASSERT | sound | test_policy.py:341. Base had no issuer check, so the waiver was accepted. (high) |
| 23 | tests/test_policy.py::test_waiver_issuer_not_in_contract_list_is_rejected | B_FAIL_ASSERT | sound | test_policy.py:360. Same mechanism as the row above. (high) |
| 23 | tests/test_policy.py::test_waiver_issuers_non_list_type_is_rejected | B_FAIL_ASSERT | sound | test_policy.py:406. Same mechanism as the row above. (high) |
| 23 | tests/test_policy.py::test_high_severity_unreproduced_explicit_none_override_still_needs_review | B_FAIL_ASSERT (3/3) | weak_evidence | test_policy.py:454. The first failing assertion is the summary text. At base, status was already needs_review (inconclusive claim) and gate_effect was already none (override). The behaviour named in the test is not discriminated. (high) |
| 23 | tests/test_policy.py::test_summary_distinguishes_blocking_class_and_high_severity_causes | B_FAIL_ASSERT | sound | test_policy.py:505. The asserted output is the new summary text, which is the feature under test. Status was needs_review at base because of finding-1. (medium) |
| 23 | tests/test_runtime.py::test_finalize_retains_transcript_and_validates_attestation | B_FAIL_ASSERT | weak_evidence | test_runtime.py:237. The only failing line at base is the `policy_id` constant. (high) |
| 23 | tests/test_runtime.py::test_unclassified_reviewer_finding_is_rejected | B_FAIL_ASSERT | sound | test_runtime.py:320. At base, finalize returned needs_review. Head raises `AuditRuntimeError`. (high) |
| 24 | tests/test_release_docs.py::test_release_version_and_readme_maturity_agree | B_FAIL_ASSERT | weak_evidence | test_release_docs.py:43. A version constant. (high) |

## C. PR #1, PR #2 and PR #5

**PR #1.**

- *First run:* 17 × F_ENV_IMPORT. That run's interpreter could see the editable install. Base `effbfc2` has
  no `validity_audit/`, so the canary resolved it to `~/src/va-audit`, and the run-wide canary
  faulted every claim. This was correct per spec §2 and fails closed. It was broader than necessary, since
  6 of the 17 claims never import `validity_audit`.
- *Rerun in the clean venv:* absence_only 7, demonstrated 4, inconclusive 4, base_passes 2. This matches the
  adjudicator's own earlier clean-env rerun.
  - The 7 absence_only are ledger tests that import the new `validity_audit.ledger`.
  - The 4 inconclusive (`b_collateral`) are subprocess CLI tests in the same module, which cannot be
    collected at base.
  - The 2 base_passes and 4 demonstrated are adjudicated in §A/§B.

**PR #2 (22 × inconclusive:b_collateral).**

- The module level of `tests/test_schemas.py` loads `schemas/task_contract.schema.json`, which this PR adds.
- At base, collection fails with `FileNotFoundError`. This was verified in a scratch worktree: pytest exit 2,
  "1 error during collection".
- Spec §3.1: collection-phase failures never count as failing before. So `inconclusive` is **correct per
  spec**.
- The clean-environment rerun gives the same 22 inconclusive, so the environment plays no part.
- The label is the only weak point. "b_collateral" suggests an import attribution, but here there is no
  import target, because the failure is a whole-file data absence.
- The PR is a feature (it adds schemas) and claims no fix, so the result is n.a.

**PR #5 (rerun against base `683d631`; 37 claims).**

- Base tree: `validity_audit/` has only `__init__.py` and `ledger.py`.
- Every claimed module is absent. This was verified in a scratch worktree with the clean venv:
  `importlib.util.find_spec` returns None for `validity_audit.{cli,policy,runtime,digests,schemas}`.
- Collecting the head tests on base fails in all four modules (pytest exit 2):
  - test_cli: `cannot import name 'cli' from 'validity_audit'`;
  - test_policy: `No module named 'validity_audit.policy'`;
  - test_runtime: `No module named 'validity_audit.digests'`;
  - test_schema_resources: `No module named 'validity_audit.schemas'`.

Counts by reason:

| reason | count |
|---|---|
| absence_only, target `validity_audit.cli` | 5 |
| absence_only, target `validity_audit.policy` | 14 |
| absence_only, target `validity_audit.digests` | 2 |
| absence_only, target `validity_audit.schemas` | 2 |
| `inconclusive:b_collateral` (all in test_runtime.py) | 14 |

All 37 rows were checked against an AST walk of each test, following helper calls:

- **Every absence_only row** references a name bound from the attributed missing module. Examples:
  `cli` in all 5 test_cli tests; `evaluate_policy`, `POLICY_ID` or `PolicyError` in the 14 test_policy
  tests; `sha256_file` in `test_prepare_emits_digest_bound_bundle_and_state` and
  `test_finalize_retains_transcript_and_validates_attestation`; `SCHEMA_FILES`, `load_schema` or
  `schema_bytes` in both test_schema_resources tests.
- **Every b_collateral row** references no name from `validity_audit.digests`, the only target Python
  reports for test_runtime.py (line 8 is its first failing import). Examples:
  `test_artifact_change_voids_prepared_run`, `test_finalize_cannot_run_twice` and
  `test_policy_engine_is_sole_gate_effect_writer`.

So every label is **correct per spec §3.1**. A sample of 8+ rows was opened against the base tree:
test_cli ×2, test_policy ×3, test_runtime ×4 (2 absence, 2 collateral), test_schema_resources ×1. All are
sound as labelled.

One substantive note: the 14 collateral rows use `prepare_run`/`finalize_run`/`AuditRuntimeError` from
`validity_audit.runtime`, which is equally absent at base. They are collateral only because Python stops at
the first failing import. In substance they are absence failures too.

**PR #5 conclusion:**

- The probe **cannot** say whether PR #5's tests prove its fix. Everything they exercise (cli, policy,
  runtime, digests, schemas) is new in this PR, so 23 rows are absence-only and 14 are collateral of
  absence. The right label is n.a. (undecidable by FBPA), not "no".
- The only fix-like part is the second commit ("Close PR 3 fail-open review gaps", `9637208..74172ab`).
  The first, void adjudication measured that commit alone. In that range:
  - the policy vocabulary and unclassified→needs_review fixes failed before and passed after;
  - the unclassified-waiver test differed only in message wording.

  That evidence is now outside the S2 table's scope and is kept here only as background.

## D. Per-PR conclusion ("do the tests prove the fix?")

| PR | conclusion | note |
|---|---|---|
| 1 | partially | The golden-case severity normalisation, dangling-pack and doc-link fixes are demonstrated soundly. The dedup→alias fix has only weak evidence plus a weak_test. The headline ledger severity-ranking fix is absence-only (the tests import the new `validity_audit.ledger`; the legacy-entry-point tests that would exercise base `protocol/ledger.py` cannot be collected at base, so they are `b_collateral`). |
| 2 | n.a. | Feature (schemas). All 22 are collection-level inconclusive. |
| 4, 8, 11, 12, 19, 20, 21 | n.a. | No test files changed. |
| 5 | n.a. (undecidable) | All 37 claims exercise modules that are new in this PR (23 absence_only, 14 collateral of absence). |
| 6 | n.a. | Feature (benchmark harness). There are 5 absence_only rows; the 3 base_passes are vacuous data checks. |
| 7 | n.a. | Docs PR. The one behavioural change (`fitness` → advisory) is demonstrated soundly; the 4 docs tests are weak evidence. |
| 10 | partially | See the PR #10 note below the table. |
| 13 | n.a. | Version bump and docs contract. Both tests are weak evidence. |
| 14 | **yes** | Both fail-closed fixes are demonstrated soundly. The controls are characterization. |
| 15 | partially | The missing-field fault is demonstrated. The added record-shape and identifier validation (score.py `_unique_by_id` dict check, `_claim_links` claim_id/finding_ids checks) has no test. |
| 16 | n.a. | Docs/SVG PR. Its test is weak evidence. |
| 17 | n.a. | No runtime change. All 4 tests are characterization. |
| 18 | n.a. | Release prep. Both tests are weak evidence. |
| 23 | partially | See the PR #23 note below the table. |
| 24 | n.a. | Release prep. Its test is weak evidence. |

**PR #10 (partially).**

- The inline-injection and schema single-line fixes are demonstrated (3 sound).
- The leading-character escape is guarded only by a **weak_test**.
- The version identity change has no test in this PR.
- The numpy onboarding fix cannot be observed with numpy installed.
- The README overclaim fix is docs-only.

**PR #23 (partially).**

- The error_class rejection and the waiver_issuers rules are demonstrated soundly.
- For the severity rule, gate_effect (advisory→none) and the summary text are demonstrated. But the headline
  breaking change, "High + unreproduced advisory findings: `pass` → `needs_review`", is **not guarded**.
- Mutation check at head `3e2ddda`: removing `pending_high_severity_unreproduced` from the status condition
  (policy.py:244) leaves the full suite at **174 passed**. A lone high/unreproduced `fitness` finding with
  supported claims then yields `status pass` (head: `needs_review`).
- Every high-severity test also carries an inconclusive claim or a second blocking finding, and either of
  those already forces needs_review.

## E. Totals (after the rerun at 6bea9a3)

base_passes (24):

| class | count |
|---|---|
| probe_wrong | 0 |
| weak_test | 2 (PR #10 single-line title; PR #1 duplicate-key check) |
| characterization | 22 |
| unclear | 0 |

demonstrated (34 of 34 adjudicated):

| class | count | of which B_FAIL_EXC |
|---|---|---|
| sound | 19 | 2 |
| weak_evidence | 15 | 3 |
| probe_wrong | 0 | 0 |

The 15 weak_evidence rows break down as follows:

- 8 doc, file or data record added by head (README, SVG, docs/*.json, VERIFIER_CHALLENGES.md, the PR #1
  alias record);
- 5 version or policy-id constant;
- 1 message-regex rewording;
- 1 confounded behavioural assertion.

None of them is a probe error. Spec §9 already states these limitations, and the S2 table should flag them.

PR #5 rows (absence_only 23 and inconclusive 14) were checked for label correctness, not for fix coverage.
All 37 are correct per spec §3.1.

The independent base reruns for the first pass were done before the rerun. The base_passes rows outside
PR #1 are unchanged at case level, so those reruns still apply.
