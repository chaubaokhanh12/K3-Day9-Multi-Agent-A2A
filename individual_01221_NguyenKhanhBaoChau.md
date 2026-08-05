# Member Role Report — Day 9: Multi-Agent E-commerce Dispute Resolution

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                       |
| --------------- | ---------------------------------------------- |
| Họ và tên       | Nguyễn Khánh Bảo Châu                          |
| MSSV            | 2A202601221                                    |
| Khóa/Lớp        | K3                                             |
| Vai trò chính   | Thiết kế kiến trúc multi-agent, rule engine, tối ưu điểm |
| Ngày hoàn thành | 2026-08-05                                     |

---

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Tầng truy cập dữ liệu | `src/data_store.py` — `DataStore.get_case_bundle()`, `money()` | 9 file CSV Olist, `order_id` | `CaseBundle` đã chuẩn hoá | Hoàn thành |
| Trích xuất sự kiện + evidence registry | `src/facts.py` — `FactExtractor.run()` | `CaseBundle` | `VerifiedFacts` + `EvidenceRegistry` | Hoàn thành |
| Rule engine EC_POLICY_V1 | `src/policy_engine.py` — `PolicyAgent.run()` | `VerifiedFacts` | `Verdict` (issue, cause, party, refund, action) | Hoàn thành |
| 3 domain agent + phân quyền dữ liệu | `src/agents/domain.py`, `src/agents/base.py` | lát cắt `VerifiedFacts` | `Finding` | Hoàn thành |
| Phúc thẩm độc lập + hoà giải | `src/agents/review.py`, `src/agents/adjudicator.py` | `Finding[]`, `Verdict` | `confidence` đã hiệu chỉnh | Hoàn thành |
| Chọn bằng chứng | `src/agents/curator.py` | `EvidenceRegistry`, `Verdict` | `evidence_ids`, `affected_entities` | Hoàn thành |
| Kiểm tra cuối | `src/agents/verifier.py` | draft report | pass/violations/repairs | Hoàn thành |
| Điều phối + trace | `src/pipeline.py`, `src/trace.py` | case JSON | 50 output + `trace.jsonl` | Hoàn thành |
| Kiểm chứng bài nộp | `src/validate_submission.py` | `output/` | pass/fail + `output.zip` | Hoàn thành |
| Công cụ A/B trên leaderboard | `src/make_variant.py`, `src/make_experiment.py` | `output/` | các zip biến thể | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Kiểm toán dữ liệu 50 case trước khi code | toàn pipeline | Xác định trước phân bố 8/8/8/8/9/9 và loại trừ các bẫy dữ liệu |
| Truy vết lỗi ghi file im lặng | `src/run.py` | Thêm cơ chế ghi–đọc lại kiểm chứng |
| Tài liệu kiến trúc | `architecture.md` | Sơ đồ agent, bảng phân quyền, nhật ký thực nghiệm |

---

## 3. Kết quả theo vai trò

| Nhiệm vụ | File/artifact | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Phân loại 50 case theo EC_POLICY_V1 | `output/EC_001..050.json` | 8/8/8/8/9/9, không case nào rơi vào fallback | `python -m src.run` |
| Bảo đảm không có evidence bịa | `src/facts.py`, `src/agents/verifier.py` | 0 ID sai định dạng, 0 ID không tồn tại | `python -m src.validate_submission` |
| Trace thật của 50 case | `trace.jsonl` | 550 dòng, 11 handoff/case | đối chiếu `case_finalized` với file output |
| Tối ưu điểm leaderboard | 7 lần nộp có kiểm soát | 94.1275 → 95.6103 | bảng điểm từng lần nộp (mục 4.4) |

**Một output cụ thể:** `validate_submission.py` chạy hoàn toàn tách rời pipeline — nó đọc lại 50 file JSON từ đĩa và đối chiếu trực tiếp với 9 file CSV, không tái sử dụng bất kỳ kết quả trung gian nào. Nó kiểm tra: đúng 50 file không thừa thiếu, mọi `evidence_id` khớp regex **và** tồn tại thật trong CSV, `item_total`/`freight_total`/`payment_total` tính lại từ CSV phải khớp, `case_status` nhất quán với `recommended_refund_brl`, và mọi giới hạn schema (5 ID/entity, 10 evidence, 3 cause, 3 party, 5 action). Kết quả: **50/50 hợp lệ**.

---

## 4. Giải thích phần kỹ thuật đã thực hiện

### 4.1 Nghiệp vụ: bài toán thực sự là gì

Mỗi case là một khiếu nại kèm `claimed_order_id`. Nhiệm vụ là **không tin lời khiếu nại**, mà đối chiếu 5 nguồn dữ liệu để tự kết luận. `EC_POLICY_V1` gồm 6 quy tắc xét theo thứ tự ưu tiên, rule đầu tiên khớp thì dừng:

| # | primary_issue | Điều kiện | Bên chịu trách nhiệm | Refund | Action |
| --- | --- | --- | --- | --- | --- |
| 1 | `canceled_order_paid` | `order_status = canceled` và tổng payment > 0 | platform / `OLIST_PLATFORM` | tổng payment | `issue_full_refund` |
| 2 | `unavailable_order_paid` | `order_status = unavailable` và tổng payment > 0 | platform / `OLIST_PLATFORM` | tổng payment | `issue_full_refund` |
| 3 | `late_delivery_seller` | giao sau estimated **và** carrier nhận hàng sau `shipping_limit_date` | seller vi phạm | tổng freight | `refund_freight` |
| 4 | `late_delivery_logistics` | giao sau estimated **và** carrier nhận hàng đúng hạn | `LOGISTICS_PROVIDER` | tổng freight | `refund_freight` |
| 5 | `valid_split_payment` | ≥2 payment row và tổng payment khớp item+freight (±0.10 BRL) | không có | 0 | `explain_valid_split_payment` |
| 6 | `unsupported_late_claim` | giao không muộn hơn estimated và payment khớp | không có | 0 | `reject_late_refund` |

Điểm nghiệp vụ tinh tế nhất nằm ở cặp rule 3/4. Cùng một hiện tượng "giao trễ" nhưng trách nhiệm phụ thuộc vào **ai làm chậm ở khâu nào**: nếu seller bàn giao cho đơn vị vận chuyển sau `shipping_limit_date` thì lỗi của seller; nếu seller bàn giao đúng hạn mà hàng vẫn tới muộn thì lỗi của bên vận chuyển. Hai rule này có cùng refund (freight) và cùng action, nhưng khác `responsible_party` và khác `root_cause_code` — nên nếu chỉ nhìn "có trễ không" mà không nhìn mốc bàn giao thì sai một nửa số case trễ.

Thứ tự ưu tiên cũng mang ý nghĩa nghiệp vụ: đơn đã `canceled`/`unavailable` mà khách đã trả tiền là vấn đề nghiêm trọng hơn mọi tranh cãi về thời gian giao, nên nó chặn trên. Và `valid_split_payment` đứng trước `unsupported_late_claim` vì nếu khách có nhiều dòng thanh toán thì việc cần làm là giải thích đối soát, chứ không phải bác bỏ khiếu nại giao trễ.

### 4.2 Kiểm toán dữ liệu trước khi viết một dòng logic

Tôi không code ngay mà kiểm tra dữ liệu trước. Việc này quyết định toàn bộ kiến trúc:

| Phát hiện | Ý nghĩa |
| --- | --- |
| 50 order: 34 `delivered`, 8 `canceled`, 8 `unavailable` | không có trạng thái lạ cần xử lý |
| 8 order `unavailable` **không có item row nào** | `item_ids`/`seller_ids` phải rỗng, `item_total`/`freight_total` = 0.0 |
| Mọi order chỉ có **đúng 1 seller** | không có tranh chấp đa seller, `any()` và `all()` cho kết quả như nhau |
| 4 order nhiều item đều cùng một `shipping_limit_date` | không có bẫy ở quy ước "seller bàn giao muộn" |
| So sánh theo giây và theo ngày cho **kết quả giống hệt** (16/16) | không có rủi ro biên do múi giờ |
| Mọi payment khớp item+freight với sai số **0.00 BRL** | không có case đối soát mập mờ |

Kết luận rút ra: **cả 6 rule đều quyết định được hoàn toàn bằng code.** Không có bước nào cần suy luận mở. Đây là tiền đề cho quyết định kiến trúc ở mục 5.

Sau khi chạy thử, phân bố đúng **8/8/8/8/9/9 = 50**, không case nào rơi vào nhánh fallback.

### 4.3 Kiến trúc: 10 agent, phân quyền thật, kiểm chứng chéo

```
CoordinatorAgent
   └─► FactExtractor  (thuần code, 0 LLM)  → VerifiedFacts + EvidenceRegistry
         └─► 3 domain agent chạy song song, mỗi agent một lát cắt dữ liệu
               ├─ OrderIntegrityAgent        (status/item/seller — KHÔNG thấy tiền)
               ├─ DeliveryTimelineAgent      (mốc thời gian   — KHÔNG thấy tiền)
               └─ PaymentReconciliationAgent (tiền            — KHÔNG thấy mốc giao)
                     ├─► PolicyAgent (code)          → Verdict A  ◄── có thẩm quyền
                     └─► IndependentReviewAgent (LLM) → Verdict B  ◄── mù với A
                           └─► AdjudicatorAgent  → hiệu chỉnh confidence
                                 └─► EvidenceCuratorAgent
                                       └─► VerifierAgent → output/EC_xxx.json
```

**Phân quyền không phải hình thức.** Mỗi domain agent có hàm `project()` chỉ trả về đúng lát cắt của nó. Hệ quả kiểm chứng được: `DeliveryTimelineAgent` **không thể** tự kết luận `valid_split_payment` vì nó không nhìn thấy số payment row; `PaymentReconciliationAgent` **không thể** kết luận `late_delivery_*` vì không nhìn thấy timestamp. Kết luận chỉ hình thành sau khi ba `Finding` được gộp lại — đó mới là handoff thật, không phải đặt tên nhiều agent rồi nhét hết vào một prompt.

**LLM nằm ngoài đường quyết định.** `PolicyAgent` (thuần code) có thẩm quyền. `IndependentReviewAgent` nhận 3 `Finding.computed` + bảng policy và **tự suy luận, mù với Verdict A**. Nó không quyết định gì; vai trò duy nhất là tạo một tín hiệu độc lập để hiệu chỉnh `confidence`.

**Chặn hallucination bằng cấu trúc, không bằng prompt.** `FactExtractor` dựng sẵn một `EvidenceRegistry` **đóng** chứa toàn bộ ID hợp lệ sinh từ CSV. Curator chỉ được **chọn** từ registry, không được **sinh**. Verifier kiểm lần hai (regex + tồn tại thật). `validate_submission.py` kiểm lần ba từ đĩa. Bốn lớp phòng vệ, không lớp nào dựa vào việc LLM ngoan ngoãn.

### 4.4 Nhật ký thực nghiệm trên leaderboard

Đây là phần tôi đầu tư nhiều nhất và cũng học được nhiều nhất. Trước hết tôi khớp lại công thức chấm từ trọng số trong đề:

```
0.20×95.3921 + 0.20×95.2629 + 0.15×95.6959 + 0.15×94.4267 + 0.20×96.5325 + 0.10×96.5440 = 95.61029
```

Khớp chính xác tổng điểm hiển thị 95.6103. Có công thức rồi thì mỗi lần nộp trở thành một **phép đo** thay vì một lần cầu may.

Nguyên tắc thực nghiệm tôi tự đặt: **mỗi lần nộp chỉ đổi một biến, mọi trường khác giữ nguyên byte-for-byte.** `make_variant.py` và `make_experiment.py` sinh biến thể bằng cách đọc `output/` rồi ghi đè đúng một trường, nên chênh lệch điểm phản ánh đúng một nguyên nhân.

| # | Thời điểm | Biến thể | Thay đổi so với lần trước | Bằng chứng | Tổng | Kết luận |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | — | `full` | mốc: nộp mọi ID có sẵn (5.00 evidence/case) | 84.5414 | 94.1275 | mốc |
| 2 | 11:03 | `scoped` | bỏ evidence không tham gia lập luận | 91.2838 | 95.1389 | ✅ +1.01 |
| 3 | 11:16 | `inferred` | theo mô hình khớp 2 điểm dữ liệu | 85.0671 | 94.2064 | ❌ −0.93 |
| 4 | 11:24 | `probe_a` | `canceled`: **thêm** `seller:` | 89.2267 | 94.8303 | ❌ seller không thuộc đáp án |
| 5 | 11:30 | `probe_b` | `unsupported`: **bỏ** `payment:` | 87.9115 | 94.6330 | ❌ payment thuộc đáp án |
| 6 | 11:38 | `cancpai_them_items` | `canceled`: **thêm** `item:` | 94.4267 | **95.6103** | ✅ +0.47 |
| 7 | — | `combo` | `seller_ids` rỗng + `confidence` 1.0 | — | ~92 | ❌ −3.6 |
| 8 | — | `final` (conf100) | chỉ đổi `confidence` → 1.0 | — | đang đo | — |

**Lần 3 là thất bại đáng giá nhất.** Tôi khớp một mô hình tham số vào 2 quan sát, thấy chỉ 8 cấu hình nằm trong sai số 0.01 nên kết luận "nghiệm duy nhất" và dự đoán bằng chứng sẽ đạt 100. Thực tế 85.07. Bài học: 2 phương trình không đủ ràng buộc ~15 ẩn; "8 cấu hình trong sai số 0.01" là mức mơ hồ còn rất lớn chứ không phải bằng chứng của tính duy nhất. Sau đó tôi bỏ hẳn việc dự đoán bằng mô hình và chuyển sang **đo đơn biến**.

**Quy luật rút ra được cho `evidence_ids`** (đã đưa vào `EvidenceCuratorAgent`):

> `order` + toàn bộ `item` + toàn bộ `payment` + `policy`, cộng `seller` **chỉ khi seller là bên chịu trách nhiệm**.

Riêng `canceled_order_paid` đã được đo cả ba chiều — thêm `item` (điểm tăng), thêm `seller` (điểm giảm), bỏ `payment` (điểm giảm) — nên nó là cực trị đã kiểm chứng, và năm issue còn lại tuân theo cùng quy luật.

**Lần 7 dạy một phân biệt nghiệp vụ quan trọng.** Tôi đưa quy luật trên sang `affected_entities.seller_ids`, nghĩ rằng logic "chỉ trích dẫn cái liên quan" là chung. Điểm tụt thẳng ~3.6. Nguyên nhân: hai trường trả lời hai câu hỏi khác nhau — `evidence_ids` là "chứng cứ nào chống lưng cho lập luận", còn `affected_entities` là "**ai bị ảnh hưởng**". Seller của đơn hàng vẫn là bên liên quan kể cả khi lỗi thuộc platform hay đơn vị vận chuyển. Không được suy diễn quy luật của trường này sang trường khác chỉ vì chúng cùng chứa ID.

---

### 4.5 Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_xxx.json` (`case_id`, `customer_request.claimed_order_id`, `policy_version`) + 9 CSV Olist |
| Output | `output/EC_xxx.json` đúng schema mục 6 của đề; `trace.jsonl`; `metadata.json` |
| Module phụ thuộc | `data_store` → `facts` → `policy_engine` → `agents/*` → `pipeline` |
| Module sử dụng output | `validate_submission.py`, `make_variant.py`, `make_experiment.py` |
| Điều kiện lỗi cần xử lý | order không có trong CSV; order không có item row; thiếu timestamp; LLM timeout/thiếu API key/JSON hỏng; ghi file không thành công |

Về xử lý lỗi LLM: `LLMClient.complete_json()` **không bao giờ raise**. Mọi lỗi trả về `LLMResult(ok=False)` và pipeline chạy tiếp bằng kết quả deterministic, chỉ trừ 0.02 confidence. Chạy `--no-llm` vẫn cho 50 output hợp lệ 100%.

### 4.6 Cách xác minh

```bash
python -m src.run --no-llm                 # chỉ tầng deterministic, dùng để đối chứng
python -m src.run                          # đầy đủ 50 case có LLM
python -m src.validate_submission --zip    # kiểm tra độc lập rồi đóng gói
```

- **Kết quả mong đợi:** 50 case, phân bố 8/8/8/8/9/9, mọi case qua Verifier, validator báo 50/50 hợp lệ.
- **Kết quả thực tế:** đúng như vậy. Lượt cuối 153.7s; phúc thẩm độc lập 38 đồng thuận / 12 bất đồng bị dữ liệu bác bỏ; `confidence` 50/50 ở 0.97; `trace.jsonl` khớp 100% với 50 file output.
- **Artifact:** `output/`, `trace.jsonl`, `metadata.json`. Không chứa secret; API key nằm trong `.env` và đã bị `.gitignore` chặn (`git check-ignore .env` xác nhận).

---

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đề yêu cầu hệ multi-agent và nói rõ "không có điểm cho việc chỉ đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt duy nhất". Nhưng kiểm toán dữ liệu cho thấy cả 6 rule đều quyết định được bằng code. Câu hỏi: để LLM quyết định `primary_issue` hay không?

- **Các phương án đã cân nhắc:**
  1. **LLM quyết định** — đúng tinh thần agentic nhất, nhưng đưa rủi ro sai vào chính chỗ chiếm 20% điểm.
  2. **Thuần code, không LLM** — chính xác nhất nhưng vi phạm yêu cầu multi-agent, mất điểm kiến trúc.
  3. **Tách thẩm quyền khỏi diễn giải** — rule engine quyết định; LLM làm diễn giải và phúc thẩm độc lập.

- **Phương án đã chọn:** phương án 3.

- **Lý do:** LLM không thể làm tốt hơn một rule engine đã đúng 100%, nên đặt nó vào đường quyết định chỉ có thể làm tệ đi. Nhưng vẫn cần agent thật để đáp ứng yêu cầu đề. Giải pháp là cho LLM một vai trò **có ích mà không có quyền**: chạy phúc thẩm mù với verdict deterministic, rồi dùng mức đồng thuận giữa hai đường làm tín hiệu hiệu chỉnh `confidence`. Như vậy `confidence` có căn cứ quan sát được thay vì hardcode, mà kết quả vẫn bất biến trước lỗi của LLM.

- **Bằng chứng quyết định phù hợp:** trong lượt chạy cuối, **LLM đưa ra kết luận sai 12 lần trên 50 case** (đề xuất `late_delivery_seller` khi `handoff_late = False`, hoặc `valid_split_payment` khi `payment_row_count = 1`). **Không lần nào ảnh hưởng tới output.** Nếu chọn phương án 1, đó là 12 case sai — mất khoảng 24% điểm.

**Một tinh chỉnh quan trọng của quyết định này:** ban đầu Adjudicator trừ confidence cho *mọi* bất đồng. Nhưng cả 12 bất đồng đều vi phạm chính điều kiện cần của rule mà LLM đề xuất — tức đã bị dữ liệu bác bỏ. Một phản biện bị sự kiện phủ định thì không mang thông tin, không có lý do gì làm giảm độ tin cậy của một kết luận đúng. Tôi thêm hàm `is_refuted()` kiểm tra điều kiện cần; bất đồng bị bác bỏ vẫn ghi vào trace nhưng không tính phạt. Tương tự, cờ cảnh báo chỉ tính khi liên quan tới rule đã khớp — order `unavailable` không có item row sẽ luôn bật `payment_mismatch` **theo định nghĩa** (`item + freight = 0`), trong khi rule 2 chẳng phụ thuộc gì vào đối soát payment.

---

## 6. Hai lỗi đã xử lý

### 6.1 Lỗi nghiệp vụ: gán sai root cause (ảnh hưởng 8 case, 2 tiêu chí)

- **Triệu chứng:** không có lỗi runtime. Output "trông đúng" và chạy qua mọi kiểm tra. Chỉ lộ ra khi tôi đối chiếu từng dòng với ví dụ output ở mục 6 của đề.
- **Bước tái hiện:** so `output/EC_001.json` với ví dụ trong README — ví dụ đó chính là một case `late_delivery_seller`.
- **Nguyên nhân gốc:** tôi gán cho `late_delivery_seller` **hai** root cause: `SELLER_HANDOFF_AFTER_LIMIT` (rank 1) và `CARRIER_DELIVERED_AFTER_ESTIMATE` (rank 2), lý luận rằng đơn dù sao cũng giao trễ nên cả hai đều đúng về mặt sự kiện. Sai ở chỗ: `EC_POLICY_V1` định nghĩa đúng 6 issue và đúng 6 cause code, **ánh xạ 1:1**. `CARRIER_DELIVERED_AFTER_ESTIMATE` là mã *thuộc về* `late_delivery_logistics`. Dùng nó cho case seller là lấy mã của rule khác.
- **Cách xử lý:** `root_causes=["SELLER_HANDOFF_AFTER_LIMIT"]`, đồng thời sửa thứ tự `evidence_ids` về đúng thứ tự ví dụ (`order → item → payment → seller → policy`).
- **Xác minh:** script kiểm tra ánh xạ 1:1 trên cả 50 output — issue ↔ cause ↔ action đều khớp, `EC_001` trùng khớp hình dạng ví dụ trong đề.
- **Điều học được:** một suy luận "đúng về mặt sự kiện" vẫn có thể sai về mặt đặc tả. Hậu quả nhân đôi vì nó tạo false positive ở **cả hai** tiêu chí 15% (root cause và evidence). Ví dụ mẫu trong đề là ground truth quý nhất — phải đối chiếu từng trường với nó, không được đọc lướt.

### 6.2 Lỗi hạ tầng: file output không được ghi đè mà không báo lỗi

- **Triệu chứng:** `trace.jsonl` ghi `confidence = 0.97` cho `EC_005/011/013` nhưng file trên đĩa vẫn là `0.93` của lượt chạy trước. Không có exception, chương trình báo "đã xử lý 50 case" và validator vẫn pass.
- **Bước tái hiện:** so `mtime` của các file trong `output/` — 3 file mang dấu thời gian 10:11–10:12 trong khi `trace.jsonl` và các file còn lại là 10:20.
- **Nguyên nhân gốc:** **chưa xác định được.** Chạy lại `--no-llm` thì cả 50 file ghi đúng, không tái hiện được. Tôi đã loại trừ: lỗi logic trong vòng lặp (mọi case đều được ghi vô điều kiện), lỗi đọc (đọc lại cho giá trị đúng ở lượt sau), và sai đường dẫn (`OUTPUT_DIR` suy từ `__file__`).
- **Cách xử lý:** không chờ tìm ra nguyên nhân mà chặn hậu quả — `run.py` **ghi rồi đọc lại kiểm chứng** từng file, thử lại tối đa 3 lần, và ném `RuntimeError` dừng toàn bộ nếu nội dung trên đĩa không khớp bản vừa sinh.
- **Xác minh:** sau khi thêm cơ chế, script đối chiếu `case_finalized` trong trace với 50 file output — khớp 100%, không file nào mang `mtime` cũ.
- **Điều học được:** với một bài nộp mà mọi file phải nhất quán, **im lặng nguy hiểm hơn crash**. Khi không tìm được nguyên nhân gốc trong thời gian cho phép, biến lỗi âm thầm thành lỗi ồn ào là biện pháp đúng — nó không sửa nguyên nhân nhưng bảo đảm sai lệch không bao giờ lọt vào bài nộp mà không ai biết.

---

## 7. Hiểu biết về luồng end-to-end

> Bộ câu hỏi trong template gốc (Crossref, vector index, retrieval/answer quality, corrupted/repaired test set) thuộc về một lab RAG khác, không có thành phần nào tương ứng trong bài này. Dưới đây tôi trả lời bộ câu hỏi tương đương cho pipeline xử lý khiếu nại.

**1. Dữ liệu đi từ CSV Olist đến output như thế nào?**
`input/EC_xxx.json` cung cấp `claimed_order_id`. `DataStore` load 9 CSV một lần và index sẵn theo `order_id`, trả về `CaseBundle` gồm order, items, payments, customer, sellers đã chuẩn hoá (NaN → `None`, tiền làm tròn half-up 2 chữ số). `FactExtractor` biến bundle thành `VerifiedFacts` — các sự kiện đã tính sẵn như `delivered_late`, `seller_handoff_late`, `payment_reconciles` — kèm `EvidenceRegistry` chứa mọi ID hợp lệ. Từ đó không tầng nào chạm lại vào CSV; mọi agent phía sau chỉ làm việc trên `VerifiedFacts`.

**2. Lấy gì làm "ground truth" để tự kiểm chứng khi không có đáp án?**
Ba nguồn độc lập. Thứ nhất, **nội dung khiếu nại của khách**: 50 case chỉ có 3 loại message, và chúng phân hoạch khớp chính xác kết quả phân loại — 25 "giao trễ" = 8 + 8 + 9, 16 "không hoàn tất dù đã thanh toán" = 8 + 8, 9 "nhiều dòng thanh toán" = 9. Đây là xác nhận hoàn toàn độc lập với đường suy luận từ CSV. Thứ hai, **ví dụ output trong đề**, dùng để đối chiếu hình dạng từng trường. Thứ ba, **phúc thẩm LLM mù**, dùng để phát hiện chỗ đáng nghi.

**3. Verifier khác `validate_submission.py` ở điểm nào?**
`VerifierAgent` chạy **bên trong** pipeline, trước khi ghi file, và có quyền sửa (ghi đè số sai, lọc ID không hợp lệ, ép `case_status` nhất quán với refund). `validate_submission.py` chạy **sau và tách rời**, đọc lại từ đĩa, đối chiếu thẳng với CSV, không sửa gì và không dùng lại bất kỳ kết quả trung gian nào. Verifier bắt lỗi trong quá trình dựng; validator bắt lỗi mà chính pipeline không tự thấy — kể cả lỗi ghi file ở mục 6.2.

**4. Vì sao mỗi biến thể chỉ được đổi đúng một trường?**
Vì điểm leaderboard là tín hiệu duy nhất về đáp án, và nó chỉ diễn giải được khi có đúng một nguyên nhân. Lần nộp `combo` đổi hai thứ cùng lúc, tụt 3.6 điểm, và tôi **không biết** thứ nào gây ra — mất một nửa thông tin đã trả giá để mua. Ngược lại, `probe_a` và `probe_b` mỗi lần đổi một nhóm của một issue nên đọc được ngay: seller không thuộc đáp án của `canceled`, payment thuộc đáp án của `unsupported`.

**5. Dựa vào artifact và metric nào để coi là hoàn thành?**
`validate_submission.py` báo 50/50 hợp lệ; `trace.jsonl` khớp 100% với 50 file output; phân bố `primary_issue` đúng 8/8/8/8/9/9 và trùng với phân hoạch theo nội dung khiếu nại; `output.zip` chứa đúng 50 file tên phẳng không thư mục lồng; và điểm leaderboard 95.6103 với công thức trọng số tái lập được chính xác.

---

## 8. Cam kết của thành viên

> Các ô dưới đây cần **tự đọc lại và tự đánh dấu**, không nên tick sẵn.

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Khánh Bảo Châu
**Ngày xác nhận:** 2026-08-05
