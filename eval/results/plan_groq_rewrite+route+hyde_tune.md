| Question type | n | Recall@5 | Recall@10 | MRR |
|---|--:|--:|--:|--:|
| overall | 26 | 0.827 | 0.904 | 0.864 |
| error_message | 7 | 1.000 | 1.000 | 0.929 |
| symptom | 8 | 0.875 | 0.875 | 0.792 |
| version | 6 | 0.833 | 1.000 | 0.774 |
| cross_product | 5 | 0.500 | 0.700 | 1.000 |

Passage-level (overall): p_recall@5 0.654, p_recall@10 0.788, p_mrr 0.629, ctx_recall 0.615. Average chunk: 1870 characters.

Query plan rewrite,route,hyde by groq: routing exact 1.000, found all products 1.000, named a wrong product 0.000, median plan time 0.68 s.

Split: tune. Mode: hybrid. Role: admin. Chunking: fixed. Median search time: 260 ms. Unanswerable questions skipped (no relevant page): 4.
