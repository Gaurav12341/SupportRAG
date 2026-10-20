**Accuracy: 21/70 = 30.0% (95% CI 20.5-41.5%)** on tune (70 questions: 58 answerable, 12 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 30.0% | 40.0% |
| Answerable answered correctly | 12 of 58 | 27 of 58 |
| Answerable partially correct (not counted as correct) | 5 of 58 | 10 of 58 |
| Answerable incorrect | 9 of 58 | 21 of 58 |
| Answerable refused (false refusals) | 32 of 58 | 0 of 58 |
| Unanswerable refused (correct) | 9 of 12 | 1 of 12 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 16 | 5 | 8 |
| symptom | 17 | 2 | 8 |
| version | 14 | 5 | 11 |
| cross_product | 11 | 0 | 0 |
| unanswerable | 12 | 9 | 1 |

**Failure breakdown** (49 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 12 |
| generation_error | 18 |
| verifier_false_refusal | 15 |
| unsafe_or_wrong_claim | 4 |

Of the 18 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 38 of 58 answerable questions. Shown answers with a wrong or dangerous claim: 6.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 4 | 4 | 7587 | 1259 | 8846 | 0 |
| groq/qwen/qwen3.8-27b | 84 | 84 | 49776 | 8643 | 58419 | 0 |
| local/qwen2.5-3b-instruct | 66 | 66 | 124097 | 8040 | 132137 | 0 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 5, max_context_chars 8000. Answer providers: {'local': 66, 'groq': 4}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: (none).
