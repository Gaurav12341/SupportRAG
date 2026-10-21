**Accuracy: 32/40 = 80.0% (95% CI 65.2-89.5%)** on tune (dev subset) (40 questions: 33 answerable, 7 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 80.0% | 80.0% |
| Answerable answered correctly | 25 of 33 | 25 of 33 |
| Answerable partially correct (not counted as correct) | 3 of 33 | 3 of 33 |
| Answerable incorrect | 5 of 33 | 5 of 33 |
| Answerable refused (false refusals) | 0 of 33 | 0 of 33 |
| Unanswerable refused (correct) | 7 of 7 | 7 of 7 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 9 | 9 | 9 |
| symptom | 10 | 7 | 7 |
| version | 8 | 8 | 8 |
| cross_product | 6 | 1 | 1 |
| unanswerable | 7 | 7 | 7 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 30 | 25 |
| partial | 3 | 0 |
| none | 7 | 7 |

**Retry (stage 16)** ran for 12 questions (5 answerable, 7 unanswerable): 8 of them correct afterwards (unanswerable ones still refused: 7 of 7).

**Failure breakdown** (8 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 2 |
| generation_error | 4 |
| verifier_false_refusal | 0 |
| unsafe_or_wrong_claim | 2 |

Of the 4 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 25 of 33 answerable questions. Shown answers with a wrong or dangerous claim: 3.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 52 | 40 | 175465 | 11655 | 187120 | 45903 |
| groq/openai/gpt-oss-20b | 45 | 29 | 55523 | 8010 | 63533 | 16107 |
| groq/qwen/qwen3.8-27b | 66 | 62 | 42637 | 5932 | 48569 | 3456 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 40}. Verifier: llm (openai/gpt-oss-20b), used for: {'llm': 33, '': 7}. Judge qwen/qwen3.8-27b (prompt v2). Retry: on. Answer salt: (none).
