**Accuracy: 26/70 = 37.1% (95% CI 26.8-48.9%)** on tune (70 questions: 58 answerable, 12 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 37.1% | 37.1% |
| Answerable answered correctly | 16 of 58 | 26 of 58 |
| Answerable partially correct (not counted as correct) | 6 of 58 | 8 of 58 |
| Answerable incorrect | 7 of 58 | 24 of 58 |
| Answerable refused (false refusals) | 29 of 58 | 0 of 58 |
| Unanswerable refused (correct) | 10 of 12 | 0 of 12 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 16 | 5 | 9 |
| symptom | 17 | 2 | 5 |
| version | 14 | 8 | 11 |
| cross_product | 11 | 1 | 1 |
| unanswerable | 12 | 10 | 0 |

**Failure breakdown** (44 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 11 |
| generation_error | 20 |
| verifier_false_refusal | 10 |
| unsafe_or_wrong_claim | 3 |

Of the 20 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 38 of 58 answerable questions. Shown answers with a wrong or dangerous claim: 6.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 1 | 0 | 1971 | 492 | 2463 | 2463 |
| groq/qwen/qwen3.8-27b | 87 | 34 | 52349 | 9349 | 61698 | 39973 |
| local/qwen2.5-3b-instruct | 69 | 0 | 129278 | 9552 | 138830 | 138830 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 5, max_context_chars 8000. Answer providers: {'local': 69, 'groq': 1}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: run2.
