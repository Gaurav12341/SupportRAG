**Accuracy: 30/38 = 78.9% (95% CI 63.7-88.9%)** on holdout (38 questions: 26 answerable, 12 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 78.9% | 78.9% |
| Answerable answered correctly | 18 of 26 | 18 of 26 |
| Answerable partially correct (not counted as correct) | 3 of 26 | 3 of 26 |
| Answerable incorrect | 4 of 26 | 4 of 26 |
| Answerable refused (false refusals) | 1 of 26 | 1 of 26 |
| Unanswerable refused (correct) | 12 of 12 | 12 of 12 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 8 | 7 | 7 |
| symptom | 7 | 5 | 5 |
| version | 6 | 6 | 6 |
| cross_product | 5 | 0 | 0 |
| unanswerable | 12 | 12 | 12 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 21 | 18 |
| partial | 4 | 0 |
| none | 13 | 12 |

**Failure breakdown** (8 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 3 |
| generation_error | 3 |
| verifier_false_refusal | 0 |
| unsafe_or_wrong_claim | 2 |

Of the 3 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 19 of 26 answerable questions. Shown answers with a wrong or dangerous claim: 2.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 38 | 0 | 124395 | 8515 | 132910 | 132910 |
| groq/openai/gpt-oss-20b | 25 | 0 | 39200 | 3775 | 42975 | 42975 |
| groq/qwen/qwen3.8-27b | 50 | 24 | 32317 | 4678 | 36995 | 19458 |

Split: holdout. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 38}. Verifier: llm (openai/gpt-oss-20b), used for: {'llm': 25, '': 13}. Judge qwen/qwen3.8-27b (prompt v2). Retry: off. Answer salt: (none).
