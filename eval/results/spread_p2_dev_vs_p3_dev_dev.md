Same questions (40, the dev subset, tune split), two runs, verifier on:

- `p2_dev`: 18/40 = 45.0% (95% CI 30.7-60.2%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- `p3_dev`: 33/40 = 82.5% (95% CI 68.0-91.3%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- difference: 15 questions (37.5 points)
- same outcome (correct or not) on 25 of 40 questions; correct in both 18, only in `p2_dev` 0, only in `p3_dev` 15

| Failure category (verifier on) | `p2_dev` | `p3_dev` |
|---|--:|--:|
| retrieval_miss | 2 | 2 |
| generation_error | 5 | 3 |
| verifier_false_refusal | 15 | 0 |
| unsafe_or_wrong_claim | 0 | 2 |
