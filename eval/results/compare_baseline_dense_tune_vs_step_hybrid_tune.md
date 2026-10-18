baseline_dense_tune -> step_hybrid_tune

| Question type | n | dRecall@5 | dRecall@10 | dMRR |
|---|--:|--:|--:|--:|
| overall | 26 | -0.038 | +0.000 | +0.062 |
| error_message | 7 | +0.000 | +0.000 | +0.000 |
| symptom | 8 | +0.000 | +0.000 | +0.077 |
| version | 6 | -0.167 | +0.000 | +0.031 |
| cross_product | 5 | +0.000 | +0.000 | +0.160 |

Questions helped: 7, hurt: 4, unchanged: 15.

| Question | Type | First-hit rank before | after | Recall@10 before | after |
|---|---|--:|--:|--:|--:|
| sym-02 (helped) | symptom | 4 | 2 | 1.00 | 1.00 |
| sym-05 (helped) | symptom | 2 | 1 | 1.00 | 1.00 |
| sym-06 (helped) | symptom | 3 | 1 | 1.00 | 1.00 |
| ver-02 (helped) | version | 5 | 4 | 1.00 | 1.00 |
| ver-04 (helped) | version | 3 | 1 | 1.00 | 1.00 |
| x-05 (helped) | cross_product | 2 | 1 | 0.50 | 0.50 |
| x-06 (helped) | cross_product | 5 | 1 | 0.50 | 0.50 |
| sym-08 (hurt) | symptom | 1 | 5 | 1.00 | 1.00 |
| ver-01 (hurt) | version | 1 | 2 | 1.00 | 1.00 |
| ver-07 (hurt) | version | 5 | 6 | 1.00 | 1.00 |
| x-01 (hurt) | cross_product | 1 | 2 | 0.50 | 0.50 |
