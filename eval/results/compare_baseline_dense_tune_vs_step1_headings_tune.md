baseline_dense_tune -> step1_headings_tune

| Question type | n | dRecall@5 | dRecall@10 | dMRR |
|---|--:|--:|--:|--:|
| overall | 26 | -0.096 | -0.038 | -0.011 |
| error_message | 7 | -0.143 | -0.143 | -0.048 |
| symptom | 8 | +0.000 | +0.000 | -0.027 |
| version | 6 | -0.167 | +0.000 | +0.232 |
| cross_product | 5 | -0.100 | +0.000 | -0.225 |

Questions helped: 5, hurt: 8, unchanged: 13.

| Question | Type | First-hit rank before | after | Recall@10 before | after |
|---|---|--:|--:|--:|--:|
| err-05 (helped) | error_message | 3 | 1 | 1.00 | 1.00 |
| sym-02 (helped) | symptom | 4 | 1 | 1.00 | 1.00 |
| sym-05 (helped) | symptom | 2 | 1 | 1.00 | 1.00 |
| ver-04 (helped) | version | 3 | 1 | 1.00 | 1.00 |
| ver-07 (helped) | version | 5 | 1 | 1.00 | 1.00 |
| err-09 (hurt) | error_message | 1 | miss | 1.00 | 0.00 |
| sym-01 (hurt) | symptom | 1 | 3 | 1.00 | 1.00 |
| sym-06 (hurt) | symptom | 3 | 5 | 1.00 | 1.00 |
| sym-07 (hurt) | symptom | 1 | 3 | 1.00 | 1.00 |
| ver-02 (hurt) | version | 5 | 8 | 1.00 | 1.00 |
| x-02 (hurt) | cross_product | 1 | 4 | 0.50 | 0.50 |
| x-05 (hurt) | cross_product | 2 | 5 | 0.50 | 0.50 |
| x-06 (hurt) | cross_product | 5 | 8 | 0.50 | 0.50 |
