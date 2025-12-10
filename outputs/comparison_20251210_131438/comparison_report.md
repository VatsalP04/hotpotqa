# Method Comparison Report

**Date**: 2025-12-10 13:14:38
**Methods Compared**: IRCoT, Decomposition, SimpleCoT

---

## Summary Table

| Method | EM | F1 | Gold Recall | First Ret. Recall | Tokens | F1/1kT | Time |
|--------|----|----|-------------|-------------------|--------|--------|------|
| IRCoT | 0.5200 | 0.6526 | 0.9300 | 0.7050 | 830,670 | 0.1571 | 1075.3s |
| Decomposition | 0.6450 | 0.7627 | 0.9300 | 0.5325 | 524,101 | 0.2910 | 951.2s |
| SimpleCoT | 0.5150 | 0.6892 | 0.7825 | 0.7825 | 268,577 | 0.5133 | 727.7s |

---

## Detailed Metrics

### IRCoT

#### Answer Quality
- Exact Match: 0.5200
- F1 Score: 0.6526
- Precision: 0.6563
- Recall: 0.7256

#### Retrieval Quality
- Gold Paragraph Recall: 0.9300
- Gold Paragraph Precision: 0.4062
- Gold Paragraph F1: 0.5580
- Gold Hit Rate: 0.9900

#### First Retrieval Quality
- First Retrieval Recall: 0.7050
- First Retrieval Precision: 0.7050
- First Retrieval Hit Rate: 0.9650

#### Efficiency
- Avg Tokens/Question: 4153.4
- F1 per 1K Tokens: 0.1571
- Avg Time/Question: 5.38s

#### By Question Type
- Comparison (36): EM=0.2778, F1=0.3874
- Bridge (164): EM=0.5732, F1=0.7108

### Decomposition

#### Answer Quality
- Exact Match: 0.6450
- F1 Score: 0.7627
- Precision: 0.7850
- Recall: 0.7727

#### Retrieval Quality
- Gold Paragraph Recall: 0.9300
- Gold Paragraph Precision: 0.5050
- Gold Paragraph F1: 0.6393
- Gold Hit Rate: 0.9950

#### First Retrieval Quality
- First Retrieval Recall: 0.5325
- First Retrieval Precision: 0.5325
- First Retrieval Hit Rate: 0.9050

#### Efficiency
- Avg Tokens/Question: 2620.5
- F1 per 1K Tokens: 0.2910
- Avg Time/Question: 4.76s

#### By Question Type
- Comparison (36): EM=0.6944, F1=0.7495
- Bridge (164): EM=0.6341, F1=0.7656

### SimpleCoT

#### Answer Quality
- Exact Match: 0.5150
- F1 Score: 0.6892
- Precision: 0.6892
- Recall: 0.7422

#### Retrieval Quality
- Gold Paragraph Recall: 0.7825
- Gold Paragraph Precision: 0.5233
- Gold Paragraph F1: 0.6270
- Gold Hit Rate: 0.9900

#### First Retrieval Quality
- First Retrieval Recall: 0.7825
- First Retrieval Precision: 0.5233
- First Retrieval Hit Rate: 0.9900

#### Efficiency
- Avg Tokens/Question: 1342.9
- F1 per 1K Tokens: 0.5133
- Avg Time/Question: 3.64s

#### By Question Type
- Comparison (36): EM=0.6389, F1=0.7403
- Bridge (164): EM=0.4878, F1=0.6780
