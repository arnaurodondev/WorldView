# Chat-Quality Judge — Calibration Report

_computed_at_: `2026-06-25T22:51:47.605621+00:00`
_labels_: **39/39 labelled**

## ⛔ REJECT (bar: κ ≥ 0.7 AND zero false-PASS-on-fabrication)

- Cohen's κ: **0.5937** (< 0.7)
- Raw agreement: 0.7949
- Items compared: 39
- False-PASS on fabrication: **1 → gold_fabrication_09** ⛔

## Confusion matrix (human truth x machine)

| | machine PASS | machine FAIL |
|---|---|---|
| **human PASS** | 16 (TP) | 2 (false-FAIL) |
| **human FAIL** | 6 (FALSE-PASS) ⛔ FABRICATION | 15 (TN) |

## Per-dimension MAE (human vs judge dim)

| dimension | MAE |
|---|---|
| tool_use | 7.872 |
| grounding | 6.128 |
| framing | 5.641 |
| coherence | 8.231 |
