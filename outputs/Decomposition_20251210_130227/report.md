# Evaluation Report: Decomposition

**Date**: 2025-12-10 13:02:27
**Questions Evaluated**: 200
**Errors**: 1
**NOT_FOUND Fallback Used**: 1 questions (0.5%)

---

## Summary

### Answer Quality

| Metric | Value |
|--------|-------|
| Exact Match (EM) | 0.6450 |
| F1 Score | 0.7627 |
| Precision | 0.7850 |
| Recall | 0.7727 |

### Retrieval Quality

| Metric | Value |
|--------|-------|
| Gold Paragraph Recall | 0.9300 |
| Gold Paragraph Precision | 0.5050 |
| Gold Paragraph F1 | 0.6393 |
| Gold Hit Rate | 0.9950 |

### First Retrieval Quality

| Metric | Value |
|--------|-------|
| First Retrieval Recall | 0.5325 |
| First Retrieval Precision | 0.5325 |
| First Retrieval F1 | 0.5325 |
| First Retrieval Hit Rate | 0.9050 |

### Token Efficiency

| Metric | Value |
|--------|-------|
| Total Tokens | 524,101 |
| Avg Tokens/Question | 2620.5 |
| F1 per 1K Tokens | 0.2910 |
| EM per 1K Tokens | 0.3147 |

### Timing

| Metric | Value |
|--------|-------|
| Total Time | 951.19s |
| Avg Time/Question | 4.76s |

---

## By Question Type

| Type | Count | EM | F1 | Gold Recall |
|------|-------|----|----|-------------|
| Comparison | 36 | 0.6944 | 0.7495 | 0.9306 |
| Bridge | 164 | 0.6341 | 0.7656 | 0.9299 |

---

## Errors

**Total Errors**: 1

1. **Q**: Where did recording sessions take place for the Michael Jackson hit "Beat It"?...
   **Error**: API error occurred: Status 503. Body: {"object":"error","message":"Internal server error","type":"unreachable_backend","param":null,"code":"1100"}
