| Question type | n | Recall@5 | Recall@10 | MRR |
|---|--:|--:|--:|--:|
| overall | 26 | 0.827 | 0.885 | 0.864 |
| error_message | 7 | 1.000 | 1.000 | 0.905 |
| symptom | 8 | 0.875 | 0.875 | 0.812 |
| version | 6 | 0.833 | 1.000 | 0.771 |
| cross_product | 5 | 0.500 | 0.600 | 1.000 |

Passage-level (overall): p_recall@5 0.673, p_recall@10 0.712, p_mrr 0.652, ctx_recall 0.635. Average chunk: 1870 characters.

Query plan rewrite by groq: routing exact 1.000, found all products 1.000, named a wrong product 0.000, median plan time 0.68 s.

Split: tune. Mode: hybrid. Role: admin. Chunking: fixed. Median search time: 230 ms. Unanswerable questions skipped (no relevant page): 4.
