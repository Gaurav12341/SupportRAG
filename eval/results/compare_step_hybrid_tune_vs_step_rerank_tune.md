step_hybrid_tune -> step_rerank_tune

| Question type | n | dRecall@5 | dRecall@10 | dMRR |
|---|--:|--:|--:|--:|
| overall | 26 | +0.038 | +0.000 | -0.003 |
| error_message | 7 | +0.000 | +0.000 | +0.024 |
| symptom | 8 | +0.000 | +0.000 | -0.046 |
| version | 6 | +0.167 | +0.000 | +0.069 |
| cross_product | 5 | +0.000 | +0.000 | -0.060 |

Questions helped: 7, hurt: 5, unchanged: 14.

| Question | Type | First-hit rank before | after | Recall@10 before | after |
|---|---|--:|--:|--:|--:|
| err-05 (helped) | error_message | 3 | 2 | 1.00 | 1.00 |
| sym-02 (helped) | symptom | 2 | 1 | 1.00 | 1.00 |
| sym-08 (helped) | symptom | 5 | 1 | 1.00 | 1.00 |
| ver-01 (helped) | version | 2 | 1 | 1.00 | 1.00 |
| ver-02 (helped) | version | 4 | 2 | 1.00 | 1.00 |
| ver-07 (helped) | version | 6 | 2 | 1.00 | 1.00 |
| x-01 (helped) | cross_product | 2 | 1 | 0.50 | 0.50 |
| sym-01 (hurt) | symptom | 1 | 2 | 1.00 | 1.00 |
| sym-05 (hurt) | symptom | 1 | 2 | 1.00 | 1.00 |
| sym-07 (hurt) | symptom | 1 | 3 | 1.00 | 1.00 |
| ver-06 (hurt) | version | 1 | 3 | 1.00 | 1.00 |
| x-06 (hurt) | cross_product | 1 | 5 | 0.50 | 0.50 |
