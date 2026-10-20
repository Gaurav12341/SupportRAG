Same questions (40, the dev subset, tune split), two runs, verifier on:

- `baseline`: 11/40 = 27.5% (95% CI 16.1-42.8%); verifier off: 17/40 = 42.5% (95% CI 28.5-57.8%)
- `p2_dev`: 18/40 = 45.0% (95% CI 30.7-60.2%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- difference: 7 questions (17.5 points)
- same outcome (correct or not) on 31 of 40 questions; correct in both 10, only in `baseline` 1, only in `p2_dev` 8

| Failure category (verifier on) | `baseline` | `p2_dev` |
|---|--:|--:|
| retrieval_miss | 6 | 2 |
| generation_error | 11 | 5 |
| verifier_false_refusal | 10 | 15 |
| unsafe_or_wrong_claim | 2 | 0 |
