# LLM judge panel

Judges: `gpt-oss-120b`, `llama4-maverick-17b`, `gemma4-31b-it`; 100 items of the blinded packet, 3 votes each at temperature 0.3, majority per judge (else debatable) and per panel (else debatable). LLM-judged: no human checked these labels (pre-registration Deviation 9). Kappa CIs: 95% bootstrap over items; rates: Wilson 95%.

## Agreement between the judges

| Subset | Fleiss' kappa, 3 labels | Fleiss' kappa, wrong vs not wrong |
|---|---|---|
| all | 0.382 [0.271, 0.494] (n=100) | 0.477 [0.346, 0.599] (n=100) |
| diff audit | 0.417 [0.276, 0.547] (n=70) | 0.539 [0.389, 0.676] (n=70) |
| diff audit (LLM-judged) | 0.424 [0.245, 0.572] (n=52) | 0.589 [0.402, 0.743] (n=52) |
| diff audit (confirmed) | 0.282 [-0.014, 0.577] (n=18) | 0.262 [-0.03, 0.571] (n=18) |
| review sheet | 0.164 [-0.033, 0.354] (n=30) | 0.169 [-0.093, 0.418] (n=30) |
| calibration sheets | 0.261 [0.074, 0.424] (n=40) | 0.324 [0.074, 0.54] (n=40) |

## Agreement with the recorded labels (Cohen's kappa)

| Who | all, 3 labels | all, wrong vs not wrong | diff audit (LLM-judged), wrong vs not wrong | calibration sheets, 3 labels |
|---|---|---|---|---|
| gpt-oss-120b | 0.38 [0.222, 0.522] (n=100) | 0.408 [0.226, 0.566] (n=100) | 0.383 [0.181, 0.611] (n=52) | 0.213 [0.004, 0.435] (n=40) |
| llama4-maverick-17b | 0.287 [0.146, 0.424] (n=100) | 0.345 [0.163, 0.508] (n=100) | 0.586 [0.337, 0.799] (n=52) | 0.084 [-0.128, 0.278] (n=40) |
| gemma4-31b-it | 0.414 [0.258, 0.564] (n=100) | 0.478 [0.302, 0.644] (n=100) | 0.606 [0.378, 0.807] (n=52) | 0.328 [0.097, 0.548] (n=40) |
| panel | 0.373 [0.224, 0.516] (n=100) | 0.455 [0.269, 0.62] (n=100) | 0.641 [0.411, 0.843] (n=52) | 0.254 [0.01, 0.478] (n=40) |

## Validity on the confirmed verdicts (wrong vs not wrong)

| Who | Accuracy | Sensitivity | Specificity |
|---|---|---|---|
| gpt-oss-120b | 0.611 [0.386, 0.797] (n=18) | 0.833 [0.552, 0.953] (n=12) | 0.167 [0.03, 0.564] (n=6) |
| llama4-maverick-17b | 0.611 [0.386, 0.797] (n=18) | 0.583 [0.32, 0.807] (n=12) | 0.667 [0.3, 0.903] (n=6) |
| gemma4-31b-it | 0.611 [0.386, 0.797] (n=18) | 0.833 [0.552, 0.953] (n=12) | 0.167 [0.03, 0.564] (n=6) |
| panel | 0.611 [0.386, 0.797] (n=18) | 0.75 [0.468, 0.911] (n=12) | 0.333 [0.097, 0.7] (n=6) |

## The reading tier

The panel agrees with 28 of 40 reading-tier verdicts on 3 labels and 31 of 40 on wrong vs not wrong. Overturned (the panel's label differs from the recorded one):

| Item | Edit | Recorded | Panel | gpt-oss-120b | llama4-maverick-17b | gemma4-31b-it |
|---|---|---|---|---|---|---|
| 5 | 5204d0f8cc4a | fine | debatable | wrong | fine | debatable |
| 13 | f39f4e9b0abd | debatable | wrong | wrong | wrong | wrong |
| 24 | 2da322d02869 | fine | wrong | wrong | fine | wrong |
| 25 | 4e7f02206d11 | debatable | wrong | wrong | wrong | wrong |
| 27 | 07ed9c5ac355 | fine | wrong | wrong | wrong | wrong |
| 28 | f8c78f2d0264 | debatable | fine | debatable | fine | fine |
| 30 | 95aec87ffd7d | wrong | fine | fine | fine | fine |
| 50 | 63364bb04155 | debatable | fine | wrong | fine | fine |
| 59 | 0debddd2713a | fine | wrong | wrong | wrong | wrong |
| 87 | 3525ce98fdfe | fine | wrong | wrong | fine | wrong |
| 94 | c8db0315fcc0 | debatable | wrong | wrong | debatable | wrong |
| 96 | 97f8e846fdd9 | wrong | debatable | fine | debatable | debatable |
