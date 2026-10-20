Same questions (40, the dev subset, tune split), two runs, verifier on:

- `baseline_run2`: 13/40 = 32.5% (95% CI 20.1-48.0%); verifier off: 16/40 = 40.0% (95% CI 26.3-55.4%)
- `p3_dev`: 33/40 = 82.5% (95% CI 68.0-91.3%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- difference: 20 questions (50.0 points)
- same outcome (correct or not) on 20 of 40 questions; correct in both 13, only in `baseline_run2` 0, only in `p3_dev` 20

| Failure category (verifier on) | `baseline_run2` | `p3_dev` |
|---|--:|--:|
| retrieval_miss | 6 | 2 |
| generation_error | 11 | 3 |
| verifier_false_refusal | 8 | 0 |
| unsafe_or_wrong_claim | 2 | 2 |
