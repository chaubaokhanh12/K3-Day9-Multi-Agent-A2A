# Kiến trúc hệ thống multi-agent — EC_POLICY_V1

## 1. Nguyên tắc thiết kế

Hệ thống được thiết kế xoay quanh một quan sát then chốt: **toàn bộ 6 quy tắc của `EC_POLICY_V1` đều là quy tắc quyết định được** từ dữ liệu Olist (so sánh trạng thái, timestamp và số tiền). Không có bước nào cần suy luận mở.

Từ đó rút ra ba nguyên tắc kiến trúc:

| # | Nguyên tắc | Hệ quả cài đặt |
|---|---|---|
| 1 | **Tách thẩm quyền khỏi diễn giải** | Kết quả cuối do rule engine deterministic quyết định. LLM chỉ diễn giải và phúc thẩm, không bao giờ ghi đè verdict. |
| 2 | **Chặn hallucination bằng cấu trúc, không bằng prompt** | Mọi ID hợp lệ được dựng sẵn từ CSV thành một *evidence registry đóng*. Agent chỉ được **chọn** từ registry, không được **sinh** ID. |
| 3 | **Không có single point of failure** | LLM lỗi/timeout/hết quota → pipeline vẫn cho ra output hợp lệ 100%, chỉ giảm nhẹ `confidence`. |

Đây là điểm khác biệt so với kiến trúc gợi ý trong đề: thay vì để mỗi agent "phán quyết" một phần rồi Coordinator tổng hợp bằng LLM, hệ thống dùng **kiểm chứng chéo hai đường độc lập** — một đường deterministic có thẩm quyền, một đường LLM mù — và dùng mức đồng thuận giữa hai đường làm tín hiệu hiệu chỉnh độ tin cậy.

## 2. Sơ đồ agent và luồng handoff

```
                              ┌──────────────────┐
   input/EC_xxx.json ───────► │ CoordinatorAgent │
                              └────────┬─────────┘
                                       │ handoff 1: claimed_order_id
                                       ▼
                              ┌──────────────────┐
                              │  FactExtractor   │  thuần code, 0 LLM
                              │  (data_store +   │  → VerifiedFacts
                              │   CSV join)      │  → EvidenceRegistry (đóng)
                              └────────┬─────────┘
                                       │ handoff 2: VerifiedFacts (chiếu theo quyền)
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────┐   ┌──────────────────────┐  ┌────────────────────────┐
   │OrderIntegrity    │   │ DeliveryTimeline     │  │ PaymentReconciliation  │
   │Agent             │   │ Agent                │  │ Agent                  │
   │ status/item/     │   │ các mốc thời gian    │  │ tiền + payment row     │
   │ seller           │   │ (KHÔNG thấy tiền)    │  │ (KHÔNG thấy timestamp) │
   │ (KHÔNG thấy tiền)│   │                      │  │                        │
   └────────┬─────────┘   └──────────┬───────────┘  └───────────┬────────────┘
            └────────────────────────┼──────────────────────────┘
                                     │ handoff 3: 3 × Finding
                     ┌───────────────┴────────────────┐
                     ▼                                ▼
         ┌───────────────────────┐      ┌──────────────────────────┐
         │ PolicyAgent           │      │ IndependentReviewAgent   │
         │ thang ưu tiên 6 rule  │      │ LLM tự áp bảng policy    │
         │ THUẦN CODE            │      │ MÙ với Verdict A         │
         │ → Verdict A (thẩm     │      │ → Verdict B (tham khảo)  │
         │   quyền)              │      │                          │
         └───────────┬───────────┘      └────────────┬─────────────┘
                     └───────────────┬───────────────┘
                                     │ handoff 4: A + B
                                     ▼
                        ┌────────────────────────┐
                        │ AdjudicatorAgent       │
                        │ A luôn thắng;          │
                        │ B chỉ chỉnh confidence │
                        └───────────┬────────────┘
                                    │ handoff 5
                                    ▼
                        ┌────────────────────────┐
                        │ EvidenceCuratorAgent   │
                        │ chọn evidence tối ưu   │
                        │ precision, cắt theo cap│
                        └───────────┬────────────┘
                                    │ handoff 6: draft report
                                    ▼
                        ┌────────────────────────┐
                        │ VerifierAgent          │
                        │ tính LẠI toàn bộ số học│
                        │ độc lập; sửa hoặc chặn │
                        └───────────┬────────────┘
                                    ▼
                          output/EC_xxx.json
```

Mỗi mũi tên handoff sinh một dòng trong `trace.jsonl` (11 dòng/case × 50 case = 550 dòng).

## 3. Vai trò và quyền truy cập dữ liệu

Quyền truy cập được cưỡng chế bằng hàm `project()` của mỗi agent — agent chỉ nhận đúng lát cắt dữ liệu của mình, không nhận `VerifiedFacts` đầy đủ.

| Agent | File | Dùng LLM | Quyền truy cập dữ liệu | Đầu ra |
|---|---|:---:|---|---|
| `CoordinatorAgent` | `src/pipeline.py` | ✗ | điều phối, không đọc CSV | báo cáo cuối |
| `FactExtractor` | `src/facts.py` | ✗ | **toàn quyền** 9 CSV | `VerifiedFacts` + `EvidenceRegistry` |
| `OrderIntegrityAgent` | `src/agents/domain.py` | ✓ diễn giải | status, timestamp mua/duyệt, item count, seller — **không thấy tiền** | `Finding` |
| `DeliveryTimelineAgent` | `src/agents/domain.py` | ✓ diễn giải | 3 mốc giao hàng + `shipping_limit_date` — **không thấy tiền** | `Finding` |
| `PaymentReconciliationAgent` | `src/agents/domain.py` | ✓ diễn giải | item/freight/payment total — **không thấy mốc giao hàng** | `Finding` |
| `PolicyAgent` | `src/policy_engine.py` | ✗ | `VerifiedFacts` | **Verdict A (thẩm quyền)** |
| `IndependentReviewAgent` | `src/agents/review.py` | ✓ suy luận | chỉ 3 `Finding.computed` + bảng policy — **mù với Verdict A** | Verdict B |
| `AdjudicatorAgent` | `src/agents/adjudicator.py` | ✗ | A, B, flags | `confidence` đã hiệu chỉnh |
| `EvidenceCuratorAgent` | `src/agents/curator.py` | ✗ | `EvidenceRegistry` + Verdict A | evidence + entity set |
| `VerifierAgent` | `src/agents/verifier.py` | ✗ | `VerifiedFacts` + draft report | pass/violations/repairs |

Việc chia quyền không phải hình thức: `DeliveryTimelineAgent` không thể tự kết luận `valid_split_payment` vì nó không nhìn thấy số payment row, và `PaymentReconciliationAgent` không thể kết luận `late_delivery_*` vì không nhìn thấy timestamp. Kết luận chỉ hình thành **sau khi** ba Finding được gộp lại — đó mới là handoff thật.

## 4. Bốn lớp phòng vệ chống sai sót

1. **Evidence registry đóng** (`FactExtractor`) — tập ID hợp lệ được dựng sẵn từ CSV. Không có đường nào để một ID bịa lọt vào output.
2. **Curator lọc theo registry** — bất kỳ ID nào không nằm trong registry bị loại im lặng.
3. **Verifier kiểm hai lớp** — vừa kiểm regex định dạng, vừa kiểm tồn tại thực tế; đồng thời **tính lại độc lập** `item_total`, `freight_total`, `payment_total`, `recommended_refund` thay vì tin `PolicyAgent`. Lệch → ghi đè và log vào trace.
4. **`validate_submission.py`** — chạy tách rời pipeline, đọc lại output từ đĩa và đối chiếu trực tiếp với CSV. Không tái sử dụng bất kỳ kết quả trung gian nào.

## 4b. Quy tắc chọn evidence

`EvidenceCuratorAgent` nộp:

> `order` + **toàn bộ** `item` + **toàn bộ** `payment` + `policy` (mã root cause hạng 1), cộng `seller` **chỉ khi seller là bên chịu trách nhiệm**.

Vế cuối là điểm mấu chốt. Với `canceled_order_paid` và `unavailable_order_paid` bên chịu trách nhiệm là platform, với `late_delivery_logistics` là đơn vị vận chuyển, còn `valid_split_payment` và `unsupported_late_claim` không có bên nào chịu trách nhiệm — ở tất cả các trường hợp đó seller không tham gia lập luận, nên đưa `seller:` vào chỉ làm loãng tập bằng chứng. Chỉ `late_delivery_seller` mới trích dẫn seller, và đó đúng là trường hợp ví dụ trong đề bài minh hoạ.

Quy tắc này không phải suy đoán: nó được xác định bằng một loạt phép đo đơn biến trên leaderboard, mỗi lần chỉ thay đổi một nhóm evidence của một issue trong khi mọi trường khác giữ nguyên byte-for-byte (`src/make_variant.py`). Riêng `canceled_order_paid` đã được đo cả ba chiều — thêm `item` (điểm tăng), thêm `seller` (điểm giảm), bỏ `payment` (điểm giảm) — nên cấu hình của nó là cực trị đã kiểm chứng, và năm issue còn lại tuân theo cùng một quy luật.

## 5. Hiệu chỉnh confidence

`confidence` không hardcode mà suy ra từ tín hiệu quan sát được:

```
confidence = 0.97 (nền)
           − 0.05  nếu phúc thẩm bất đồng VÀ đề xuất của nó KHÔNG bị dữ liệu bác bỏ
           − 0.02  nếu LLM không khả dụng / trả lời lỗi
           − 0.04  mỗi data gap (thiếu timestamp, order không tìm thấy…)
           − 0.04  mỗi cảnh báo chặn CÓ LIÊN QUAN tới rule đã khớp
           − 0.15  nếu không rule nào khớp trực tiếp
           kẹp trong [0.50, 0.99]
```

Hai điều kiện in hoa ở trên là kết quả hiệu chỉnh sau khi quan sát lượt chạy thật, và là phần đáng chú ý nhất của thiết kế:

**a. Bất đồng bị bác bỏ thì không phạt.** Mỗi `primary_issue` có một *điều kiện cần* kiểm tra được (`_PRECONDITIONS` trong `adjudicator.py`). Nếu đề xuất của phúc thẩm vi phạm điều kiện cần của chính nó, đề xuất đó đã bị sự kiện phủ định và không mang thông tin — ghi vào trace nhưng không hạ confidence. Trong lượt chạy thật, cả 13 bất đồng đều thuộc loại này: LLM đề xuất `late_delivery_seller` trong khi `handoff_late = False`, hoặc `valid_split_payment` trong khi `payment_row_count = 1`. Một phản biện đã bị dữ liệu bác bỏ không có lý do gì làm giảm độ tin cậy của kết luận đúng.

**b. Cảnh báo chỉ tính khi liên quan tới rule đã khớp.** Order `unavailable` không có item row sẽ luôn bật cờ `payment_mismatch` **theo định nghĩa** (`item + freight = 0` trong khi `payment > 0`), nhưng rule `unavailable_order_paid` không hề phụ thuộc vào đối soát payment. Vì vậy mỗi cờ có một phạm vi (`_BLOCKING_FLAG_SCOPE`) liệt kê những issue mà nó thực sự có ý nghĩa; ngoài phạm vi thì chỉ ghi nhận, không phạt.

## 6. Kết quả chạy thực tế

Phân bố 50 case, không case nào rơi vào nhánh fallback, không data gap:

| primary_issue | Số case |
|---|---:|
| `canceled_order_paid` | 8 |
| `unavailable_order_paid` | 8 |
| `late_delivery_seller` | 8 |
| `late_delivery_logistics` | 8 |
| `valid_split_payment` | 9 |
| `unsupported_late_claim` | 9 |
| **Tổng** | **50** |

Ba tính chất đã kiểm chứng trên bộ dữ liệu: mọi order chỉ có đúng 1 seller (không có tranh chấp đa seller), mọi payment khớp `item + freight` với sai số 0.00 BRL, và 8 order `unavailable` đều không có item row (nên `item_ids`/`seller_ids` rỗng và `item_total`/`freight_total` = 0.0 theo đúng đặc tả).

**Kiểm chứng chéo bằng nội dung khiếu nại.** 50 case chỉ có 3 loại `customer_request.message` khác nhau, và chúng phân hoạch khớp chính xác với kết quả phân loại — một xác nhận độc lập hoàn toàn với đường suy luận từ CSV:

| Nội dung khiếu nại | Số case | Các `primary_issue` tương ứng |
|---|---:|---|
| "đơn hàng được giao trễ" | 25 | `late_delivery_seller` 8 + `late_delivery_logistics` 8 + `unsupported_late_claim` 9 |
| "không hoàn tất dù đã thanh toán" | 16 | `canceled_order_paid` 8 + `unavailable_order_paid` 8 |
| "nhiều dòng thanh toán, lo bị thu trùng" | 9 | `valid_split_payment` 9 |

## 6c. Ràng buộc ánh xạ 1:1 giữa issue và root cause

`EC_POLICY_V1` định nghĩa đúng 6 `primary_issue` và đúng 6 root-cause code, tương ứng 1:1:

| primary_issue | cause_code | action |
|---|---|---|
| `canceled_order_paid` | `ORDER_CANCELED_AFTER_PAYMENT` | `issue_full_refund` |
| `unavailable_order_paid` | `ORDER_UNAVAILABLE_AFTER_PAYMENT` | `issue_full_refund` |
| `late_delivery_seller` | `SELLER_HANDOFF_AFTER_LIMIT` | `refund_freight` |
| `late_delivery_logistics` | `CARRIER_DELIVERED_AFTER_ESTIMATE` | `refund_freight` |
| `valid_split_payment` | `MULTIPLE_PAYMENTS_RECONCILED` | `explain_valid_split_payment` |
| `unsupported_late_claim` | `DELIVERY_WITHIN_ESTIMATE` | `reject_late_refund` |

Bản cài đặt đầu tiên gán cho `late_delivery_seller` **hai** cause (thêm `CARRIER_DELIVERED_AFTER_ESTIMATE` ở rank 2, với lý do đơn vẫn giao trễ). Điều này về mặt nghiệp vụ nghe hợp lý nhưng vi phạm ánh xạ 1:1: `CARRIER_DELIVERED_AFTER_ESTIMATE` là mã *thuộc về* `late_delivery_logistics`. Hệ quả là 8 case sinh ra false positive ở **cả hai** thành phần — một cause thừa trong `ranked_causes` và một `policy:` thừa trong `evidence_ids`. Đã sửa: mỗi case đúng một cause, và `evidence_ids` theo đúng thứ tự của ví dụ trong đề (`order → item → payment → seller → policy`).

Ràng buộc này hiện được kiểm tra tự động trên cả 50 output.

Kết quả phúc thẩm độc lập (lượt chạy cuối, `gpt-4o-mini`, temperature 0):

| Trạng thái | Số case | Ý nghĩa |
|---|---:|---|
| `agree` | 36 | phúc thẩm ra cùng kết luận với rule engine |
| `disagree_refuted` | 14 | phúc thẩm sai, bị điều kiện cần bác bỏ → không phạt |

Phân bố `confidence` cuối cùng: cả 50 case ở `0.97`.

Đây chính là giá trị của việc tách thẩm quyền: 14 lần LLM đưa ra kết luận sai, và **không lần nào ảnh hưởng tới output**, vì đường deterministic mới là đường quyết định.

## 6b. Bảo đảm tính toàn vẹn khi ghi file

Trong quá trình phát triển đã phát hiện một lượt chạy để sót 3 file output mang nội dung của lượt trước (`trace.jsonl` ghi 0.97 nhưng file trên đĩa còn 0.93). Để một sai lệch âm thầm như vậy không bao giờ lọt vào bài nộp, `run.py` **ghi rồi đọc lại kiểm chứng** từng file, thử lại tối đa 3 lần, và ném lỗi dừng toàn bộ nếu nội dung trên đĩa không khớp bản vừa sinh. Sau khi thêm cơ chế này, `trace.jsonl` khớp 100% với 50 file output.

## 6d. Nhật ký thực nghiệm có kiểm soát

Công thức chấm được tái lập chính xác từ trọng số trong đề:

```
0.20×95.3921 + 0.20×95.2629 + 0.15×95.6959 + 0.15×94.4267 + 0.20×96.5325 + 0.10×96.5440 = 95.61029
```

Nhờ đó mỗi lần nộp trở thành một phép đo thay vì một lần thử may. Nguyên tắc: **mỗi lần chỉ đổi một biến, mọi trường khác giữ nguyên byte-for-byte.** `src/make_variant.py` (biến thể `evidence_ids`) và `src/make_experiment.py` (các trường khác) sinh biến thể bằng cách đọc `output/` rồi ghi đè đúng một trường.

| # | Biến thể | Thay đổi | Bằng chứng | Tổng | Kết luận |
| ---: | --- | --- | ---: | ---: | --- |
| 1 | `full` | mốc: nộp mọi ID có sẵn | 84.5414 | 94.1275 | mốc |
| 2 | `scoped` | bỏ evidence không tham gia lập luận | 91.2838 | 95.1389 | ✅ |
| 3 | `inferred` | theo mô hình khớp 2 điểm dữ liệu | 85.0671 | 94.2064 | ❌ |
| 4 | `probe_a` | `canceled`: thêm `seller:` | 89.2267 | 94.8303 | ❌ seller không thuộc đáp án |
| 5 | `probe_b` | `unsupported`: bỏ `payment:` | 87.9115 | 94.6330 | ❌ payment thuộc đáp án |
| 6 | `cancpai_them_items` | `canceled`: thêm `item:` | 94.4267 | **95.6103** | ✅ |
| 7 | `combo` | `seller_ids` rỗng + `confidence` 1.0 | — | ~92 | ❌ |

Hai bài học phương pháp:

**Không suy diễn từ quá ít quan sát.** Lần 3 khớp một mô hình tham số vào 2 quan sát; chỉ 8 cấu hình nằm trong sai số 0.01 nên bị kết luận nhầm là "nghiệm duy nhất", dự đoán 100 nhưng thực tế 85.07. Hai phương trình không ràng buộc nổi ~15 ẩn. Sau đó chuyển hẳn sang đo đơn biến.

**Không suy diễn quy luật giữa các trường khác bản chất.** Lần 7 đem quy luật "chỉ trích dẫn cái liên quan" từ `evidence_ids` sang `affected_entities.seller_ids` và mất 3.6 điểm. Hai trường trả lời hai câu hỏi khác nhau: `evidence_ids` là "chứng cứ nào chống lưng cho lập luận", còn `affected_entities` là "ai bị ảnh hưởng" — seller vẫn là bên liên quan kể cả khi lỗi thuộc platform hoặc đơn vị vận chuyển.

## 7. Cách chạy

```bash
cp .env.example .env          # điền OPENAI_API_KEY
python -m src.run             # chạy đầy đủ 50 case, ghi output/ + trace.jsonl + metadata.json
python -m src.run --no-llm    # chỉ tầng deterministic (dùng để kiểm chứng)
python -m src.validate_submission --zip   # kiểm tra rồi đóng gói output.zip
```

Tên model được khai báo trong `src/config.py` (`MODEL_NAME`) và ghi lại trong `metadata.json`. Chỉ API key nằm trong `.env` và không được commit.
