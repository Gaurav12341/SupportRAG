| Question type | n | Recall@5 | Recall@10 | MRR |
|---|--:|--:|--:|--:|
| overall | 26 | 0.865 | 0.904 | 0.825 |
| error_message | 7 | 1.000 | 1.000 | 0.905 |
| symptom | 8 | 1.000 | 1.000 | 0.838 |
| version | 6 | 0.833 | 1.000 | 0.653 |
| cross_product | 5 | 0.500 | 0.500 | 0.900 |

Passage-level (overall): p_recall@5 0.712, p_recall@10 0.750, p_mrr 0.612, ctx_recall 0.635. Average chunk: 1880 characters.

Query plan route by groq: routing exact 1.000, found all products 1.000, named a wrong product 0.000, median plan time 0.68 s.

Split: tune. Mode: hybrid. Role: admin. Chunking: fixed. Median search time: 153 ms. Unanswerable questions skipped (no relevant page): 4.
