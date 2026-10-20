Same questions (70, tune split), two runs, verifier on:

- `baseline`: 21/70 = 30.0% (95% CI 20.5-41.5%); verifier off: 28/70 = 40.0% (95% CI 29.3-51.7%)
- `baseline_run2`: 26/70 = 37.1% (95% CI 26.8-48.9%); verifier off: 26/70 = 37.1% (95% CI 26.8-48.9%)
- difference: 5 questions (7.1 points)
- same outcome (correct or not) on 63 of 70 questions; correct in both 20, only in `baseline` 1, only in `baseline_run2` 6

| Failure category (verifier on) | `baseline` | `baseline_run2` |
|---|--:|--:|
| retrieval_miss | 12 | 11 |
| generation_error | 18 | 20 |
| verifier_false_refusal | 15 | 10 |
| unsafe_or_wrong_claim | 4 | 3 |
