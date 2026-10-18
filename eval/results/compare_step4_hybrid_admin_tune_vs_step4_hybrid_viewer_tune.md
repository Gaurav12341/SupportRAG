step4_hybrid_admin_tune -> step4_hybrid_viewer_tune

| Question type | n | dRecall@5 | dRecall@10 | dMRR |
|---|--:|--:|--:|--:|
| overall | 26 | -0.212 | -0.212 | -0.190 |
| error_message | 7 | -0.143 | -0.143 | -0.143 |
| symptom | 8 | -0.250 | -0.250 | -0.244 |
| version | 6 | -0.333 | -0.333 | -0.250 |
| cross_product | 5 | -0.100 | -0.100 | -0.100 |

Questions helped: 2, hurt: 6, unchanged: 18.

| Question | Type | First-hit rank before | after | Recall@10 before | after |
|---|---|--:|--:|--:|--:|
| sym-08 (helped) | symptom | 5 | 4 | 1.00 | 1.00 |
| x-01 (helped) | cross_product | 2 | 1 | 0.50 | 0.50 |
| err-09 (hurt) | error_message | 1 | miss | 1.00 | 0.00 |
| sym-06 (hurt) | symptom | 1 | miss | 1.00 | 0.00 |
| sym-07 (hurt) | symptom | 1 | miss | 1.00 | 0.00 |
| ver-01 (hurt) | version | 2 | miss | 1.00 | 0.00 |
| ver-06 (hurt) | version | 1 | miss | 1.00 | 0.00 |
| x-06 (hurt) | cross_product | 1 | miss | 0.50 | 0.00 |
