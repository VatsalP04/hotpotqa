# Evaluation Report: IRCoT

**Date**: 2025-12-10 12:46:34
**Questions Evaluated**: 200
**Errors**: 2

---

## Summary

### Answer Quality

| Metric | Value |
|--------|-------|
| Exact Match (EM) | 0.5200 |
| F1 Score | 0.6526 |
| Precision | 0.6563 |
| Recall | 0.7256 |

### Retrieval Quality

| Metric | Value |
|--------|-------|
| Gold Paragraph Recall | 0.9300 |
| Gold Paragraph Precision | 0.4062 |
| Gold Paragraph F1 | 0.5580 |
| Gold Hit Rate | 0.9900 |

### First Retrieval Quality

| Metric | Value |
|--------|-------|
| First Retrieval Recall | 0.7050 |
| First Retrieval Precision | 0.7050 |
| First Retrieval F1 | 0.7050 |
| First Retrieval Hit Rate | 0.9650 |

### Token Efficiency

| Metric | Value |
|--------|-------|
| Total Tokens | 830,670 |
| Avg Tokens/Question | 4153.4 |
| F1 per 1K Tokens | 0.1571 |
| EM per 1K Tokens | 0.1518 |

### Timing

| Metric | Value |
|--------|-------|
| Total Time | 1075.31s |
| Avg Time/Question | 5.38s |

---

## By Question Type

| Type | Count | EM | F1 | Gold Recall |
|------|-------|----|----|-------------|
| Comparison | 36 | 0.2778 | 0.3874 | 0.8611 |
| Bridge | 164 | 0.5732 | 0.7108 | 0.9451 |

---

## Errors

**Total Errors**: 2

1. **Q**: What is the shared country of ancestry between Art Laboe and Scout Tufankjian?...
   **Error**: API error occurred: Status 503. Body: {"object":"error","message":"Internal server error","type":"unreachable_backend","param":null,"code":"1100"}

2. **Q**: What is the nationality of the scientist who invented in Tribometer?...
   **Error**: API error occurred: Status 503. Body: {"object":"error","message":"Internal server error","type":"unreachable_backend","param":null,"code":"1100"}
