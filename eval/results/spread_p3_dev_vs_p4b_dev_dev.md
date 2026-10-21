Same questions (40, the dev subset, tune split), two runs, verifier on:

- `p3_dev`: 33/40 = 82.5% (95% CI 68.0-91.3%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- `p4b_dev`: 32/40 = 80.0% (95% CI 65.2-89.5%); verifier off: 32/40 = 80.0% (95% CI 65.2-89.5%)
- difference: 1 questions (2.5 points)
- same outcome (correct or not) on 37 of 40 questions; correct in both 31, only in `p3_dev` 2, only in `p4b_dev` 1

| Failure category (verifier on) | `p3_dev` | `p4b_dev` |
|---|--:|--:|
| retrieval_miss | 2 | 2 |
| generation_error | 3 | 4 |
| verifier_false_refusal | 0 | 0 |
| unsafe_or_wrong_claim | 2 | 2 |
