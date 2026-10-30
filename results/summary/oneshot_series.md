| target set | variant | n | lines removed (mean, 95% CI) | hidden changed | hidden changed (mean, 95% CI) | McNemar p vs gatekeeper | Wilcoxon p (lines) vs gatekeeper |
|---|---|---|---|---|---|---|---|
| swebench_t1 | one_shot_llm | 10 | 30.2 [8.4, 62.3] | 3/10 | 0.30 [0.00, 0.60] | 0.25 | 0.5 |
| swebench_t1 | one_shot_compile | 10 | 24.1 [2.9, 57.9] | 0/10 | 0.00 [0.00, 0.00] | 1.0 | 0.125 |
| swebench_t1 | one_shot_retry | 10 | 30.3 [8.5, 62.4] | 0/10 | 0.00 [0.00, 0.00] | 1.0 | 0.625 |
| swebench_t1 | cleansweep-gatekeeper | 10 | 57.0 [13.3, 122.9] | 0/10 | 0.00 [0.00, 0.00] | -- | -- |
| swebench_t2 | one_shot_llm | 57 | 30.1 [21.0, 41.0] | 9/57 | 0.16 [0.07, 0.26] | 0.0039 | 0.7049 |
| swebench_t2 | one_shot_compile | 57 | 27.8 [19.0, 38.9] | 2/57 | 0.04 [0.00, 0.09] | 0.5 | 0.0869 |
| swebench_t2 | one_shot_retry | 57 | 30.1 [21.0, 41.0] | 5/57 | 0.09 [0.02, 0.18] | 0.0625 | 0.7287 |
| swebench_t2 | cleansweep-gatekeeper | 57 | 37.4 [25.7, 53.5] | 0/57 | 0.00 [0.00, 0.00] | -- | -- |
