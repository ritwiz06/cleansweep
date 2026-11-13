# LLM judge panel

Judges: `judge_a`, `judge_b`, `judge_c`; 6 items of the blinded packet, 3 votes each at temperature 0.3, majority per judge (else debatable) and per panel (else debatable). LLM-judged: no human checked these labels (pre-registration Deviation 9). Kappa CIs: 95% bootstrap over items; rates: Wilson 95%.

## Agreement between the judges

| Subset | Fleiss' kappa, 3 labels | Fleiss' kappa, wrong vs not wrong |
|---|---|---|
| all | 0.109 [-0.35, 0.325] (n=6) | 0.1 [-0.403, 0.556] (n=6) |
| diff audit | 0.155 [-0.25, 0.375] (n=5) | 0.196 [-0.389, 0.732] (n=5) |
| diff audit (LLM-judged) | 0.0 [-0.5, 0.0] (n=3) | -0.0 [-0.5, 1.0] (n=3) |
| diff audit (confirmed) | 0.25 [-0.5, 1.0] (n=2) | 0.25 [-0.5, 1.0] (n=2) |
| review sheet | -0.5 [-0.5, -0.5] (n=1) | -0.5 [-0.5, -0.5] (n=1) |
| calibration sheets | -0.038 [-0.5, -0.038] (n=3) | -0.5 [-0.5, -0.5] (n=3) |

## Agreement with the recorded labels (Cohen's kappa)

| Who | all, 3 labels | all, wrong vs not wrong | diff audit (LLM-judged), wrong vs not wrong | calibration sheets, 3 labels |
|---|---|---|---|---|
| judge_a | 1.0 [1.0, 1.0] (n=6) | 1.0 [1.0, 1.0] (n=6) | 1.0 [1.0, 1.0] (n=3) | 1.0 [1.0, 1.0] (n=3) |
| judge_b | 0.455 [-0.333, 1.0] (n=6) | 0.25 [-0.5, 1.0] (n=6) | 0.0 [0.0, 1.0] (n=3) | 0.5 [0.0, 1.0] (n=3) |
| judge_c | 0.25 [-0.071, 0.714] (n=6) | 0.4 [0.0, 1.0] (n=6) | 0.4 [0.0, 1.0] (n=3) | 0.143 [0.0, 1.0] (n=3) |
| panel | 1.0 [1.0, 1.0] (n=6) | 1.0 [1.0, 1.0] (n=6) | 1.0 [1.0, 1.0] (n=3) | 1.0 [1.0, 1.0] (n=3) |

## Validity on the confirmed verdicts (wrong vs not wrong)

| Who | Accuracy | Sensitivity | Specificity |
|---|---|---|---|
| judge_a | 1.0 [0.342, 1.0] (n=2) | 1.0 [0.207, 1.0] (n=1) | 1.0 [0.207, 1.0] (n=1) |
| judge_b | 0.5 [0.095, 0.905] (n=2) | 1.0 [0.207, 1.0] (n=1) | 0.0 [0.0, 0.793] (n=1) |
| judge_c | 1.0 [0.342, 1.0] (n=2) | 1.0 [0.207, 1.0] (n=1) | 1.0 [0.207, 1.0] (n=1) |
| panel | 1.0 [0.342, 1.0] (n=2) | 1.0 [0.207, 1.0] (n=1) | 1.0 [0.207, 1.0] (n=1) |

## The reading tier

The panel agrees with 2 of 2 reading-tier verdicts on 3 labels and 2 of 2 on wrong vs not wrong. Overturned (the panel's label differs from the recorded one):

| Item | Edit | Recorded | Panel | judge_a | judge_b | judge_c |
|---|---|---|---|---|---|---|
| none | | | | | | |
