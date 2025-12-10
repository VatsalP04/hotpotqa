# Evaluation Report: SimpleCoT

**Date**: 2025-12-10 13:14:38
**Questions Evaluated**: 200
**Errors**: 1

---

## Summary

### Answer Quality

| Metric | Value |
|--------|-------|
| Exact Match (EM) | 0.5150 |
| F1 Score | 0.6892 |
| Precision | 0.6892 |
| Recall | 0.7422 |

### Retrieval Quality

| Metric | Value |
|--------|-------|
| Gold Paragraph Recall | 0.7825 |
| Gold Paragraph Precision | 0.5233 |
| Gold Paragraph F1 | 0.6270 |
| Gold Hit Rate | 0.9900 |

### First Retrieval Quality

| Metric | Value |
|--------|-------|
| First Retrieval Recall | 0.7825 |
| First Retrieval Precision | 0.5233 |
| First Retrieval F1 | 0.6270 |
| First Retrieval Hit Rate | 0.9900 |

### Token Efficiency

| Metric | Value |
|--------|-------|
| Total Tokens | 268,577 |
| Avg Tokens/Question | 1342.9 |
| F1 per 1K Tokens | 0.5133 |
| EM per 1K Tokens | 0.4040 |

### Timing

| Metric | Value |
|--------|-------|
| Total Time | 727.65s |
| Avg Time/Question | 3.64s |

---

## By Question Type

| Type | Count | EM | F1 | Gold Recall |
|------|-------|----|----|-------------|
| Comparison | 36 | 0.6389 | 0.7403 | 0.7639 |
| Bridge | 164 | 0.4878 | 0.6780 | 0.7866 |

---

## Errors

**Total Errors**: 1

1. **Q**: Which American popular music and country music singer recorded J. D. Souther song ...
   **Error**: API error occurred: Status 503. Body: {"object":"error","message":"Internal server error","type":"unreachable_backend","param":null,"code":"1100"}
