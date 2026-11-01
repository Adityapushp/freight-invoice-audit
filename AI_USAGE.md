# AI usage disclosure

## Tool
Claude (Anthropic), via the claude.ai chat interface. One continuous conversation covered design, code, debugging on my machine, and git workflow.

## Where AI accelerated my work
- Proper structuring the architecture: schema -> generator -> auditor -> validator -> exporters -> CLI.
- Correcting the implementation of few modules in `freight_audit/`, the 24 tests, and the data-dictionary generator.
- Producing the list of negative tests (corrupt a PK, FK, enum, total, lifecycle step, date, credit amount, label column) to prove the validator catches errors.
- Walking me through setup, virtualenv repair, and a small-commit git history.

## Where I relied on it heavily
- Testing the cases which helped me to find the errors or any issues occured during the full check of the project.
- The choice of anomaly types beyond the five required, and the injection rates.

## What I personally did, checked and found
- Ran the project locally on Windows (Git Bash): generated starter and full datasets, ran `validate`, `audit`, `repro` and `pytest` (14/14 checks, 24/24 tests).
- Found, by running on Windows, that the manifest checksums differed from the Linux ones because of CRLF line endings and backslash paths. The AI fixed the writers (LF output, forward-slash paths). After the fix my full-dataset `manifest.json` was byte-identical to the one generated on Linux.
- Repaired a broken `.venv` and fixed a nested-folder mistake while setting up.
- Added `.gitattributes` to pin LF endings and built the history as small commits.
- Inspected sample rows against `ground_truth.csv`: [ ] done  [ ] not yet  (tick honestly)
- Read and can explain `pricing.py` and `audit.py::expected_charges`: [ ] yes  [ ] partly
- Changes I made myself to the code or parameters: [none / list them]

## Bugs found during the build (for transparency)
- UNKNOWN_SHIPMENT ground-truth expected total was initially the real shipment's charge instead of 0.
- Credit-overstatement injection could round to no overstatement on tiny credits; now only credits >= $1.00 are eligible.
- Credit notes could be created before their DRAFT event fell inside the as-of date.
- The validator crashed on corrupted reference data instead of reporting a failed check.
- README row count was stale (283,657); correct value is 282,415.
- Windows-only: CRLF line endings and backslash paths changed file checksums (fixed).

## Limits of validation
Tests prove internal consistency, determinism and cross-OS reproducibility. They do not prove realism against real carrier invoices. The auditor's F1 = 1.0 reflects that it implements the same documented rules the generator violates; it is not a real-world accuracy claim (see README, Limitations).