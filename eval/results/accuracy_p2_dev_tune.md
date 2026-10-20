**Accuracy: 18/40 = 45.0% (95% CI 30.7-60.2%)** on tune (dev subset) (40 questions: 33 answerable, 7 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 45.0% | 82.5% |
| Answerable answered correctly | 11 of 33 | 26 of 33 |
| Answerable partially correct (not counted as correct) | 1 of 33 | 3 of 33 |
| Answerable incorrect | 0 of 33 | 3 of 33 |
| Answerable refused (false refusals) | 21 of 33 | 1 of 33 |
| Unanswerable refused (correct) | 7 of 7 | 7 of 7 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 9 | 4 | 9 |
| symptom | 10 | 2 | 7 |
| version | 8 | 5 | 8 |
| cross_product | 6 | 0 | 2 |
| unanswerable | 7 | 7 | 7 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 28 | 24 |
| partial | 4 | 2 |
| none | 8 | 7 |

**Failure breakdown** (22 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 2 |
| generation_error | 5 |
| verifier_false_refusal | 15 |
| unsafe_or_wrong_claim | 0 |

Of the 5 generation errors, 1 were the model refusing by itself. Evidence fully inside the context for 25 of 33 answerable questions. Shown answers with a wrong or dangerous claim: 0.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 40 | 40 | 131804 | 9413 | 141217 | 0 |
| groq/qwen/qwen3.8-27b | 44 | 44 | 27570 | 3606 | 31176 | 0 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 40}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: (none).
