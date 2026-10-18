| Step | Kept | Recall@5 | Recall@10 | MRR | MRR error_message | MRR symptom | MRR version | MRR cross_product | Median ms |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 0. Baseline: dense only, fixed 500-token chunks | - | 0.904 | 0.904 | 0.763 | 0.905 | 0.760 | 0.622 | 0.740 | 124 |
| 1. Heading-aware chunks, dense only | no | 0.808 | 0.865 | 0.753 | 0.857 | 0.733 | 0.854 | 0.515 | 128 |
| 2. Fixed chunks + BM25 merged with RRF (hybrid) | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 125 |
| 3. Hybrid + cross-encoder rerank (top 30, keep best 5) | no | 0.904 | 0.904 | 0.822 | 0.929 | 0.792 | 0.722 | 0.840 | 3197 |
| 4a. Hybrid, admin (all levels, all products) | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 122 |
| 4b. Hybrid, member licensed for all 4 products | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 124 |
| 4c. Hybrid, member licensed for github only | yes | 0.673 | 0.712 | 0.644 | 0.762 | 0.594 | 0.403 | 0.850 | 127 |
| 4d. Hybrid, public (not logged in) | yes | 0.654 | 0.692 | 0.635 | 0.762 | 0.594 | 0.403 | 0.800 | 126 |
| Re-test: heading chunks + hybrid (admin) | - | 0.846 | 0.885 | 0.770 | 0.857 | 0.854 | 0.640 | 0.667 | n/a |
| Re-test: heading chunks + hybrid + rerank (admin) | - | 0.865 | 0.904 | 0.855 | 1.000 | 0.875 | 0.663 | 0.850 | n/a |
