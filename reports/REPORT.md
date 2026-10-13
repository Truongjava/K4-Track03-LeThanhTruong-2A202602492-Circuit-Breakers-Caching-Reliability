# Lab 25B — Report

**Họ tên / nhóm:** Lê Thanh Trường · 2A202602492 · K4-Track03  **Commit:** `18cc181`  **Điểm tự động (`make grade`):** 84.0 / 88
(4 điểm còn lại là `slo_hidden` — giảng viên chấm trên dữ liệu ẩn; đã kiểm tra thủ công đạt trên seed 7/99/2026.)

> Mọi số dưới đây lấy từ `reports/gameday/*.json`, `reports/workflows.json`, `reports/slo.json`, `reports/cache/*.json`.

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | ✗ |
| G1 | yours | **1.0** | **4.776** | **1.062** | **0.002** | 2.101 | 0.0 | ✓ |
| G2 | naive | 0.456 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | ✗ |
| G2 | yours | **1.0** | **10.92** | **1.041** | **0.007** | 2.119 | **0.0** | ✓ |
| G3 | naive | 1.0 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | ✗ |
| G3 | yours | 1.0 | 4.66 | **1.060** | **0.034** | 2.145 | 0.0 | ✓ |
| G4 | naive | 1.0 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | ✗ |
| G4 | yours | 1.0 | **5.562** | 1.015 | 0.002 | 2.072 | 0.0 | ✓ |
| G5 | naive | 0.3699 | 5.359 | 17.03 | 16.03 | 2.124 | — | ✗ |
| G5 | yours | **0.8179** | 5.477 | **1.003** | **0.002** | 2.504 | — | ✓ |
| G6 | naive | 0.517 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | ✗ |
| G6 | yours | **1.0** | **5.961** | **1.055** | **0.019** | 2.189 | 0.0 | ✓ |

Naive thất bại cả **6/6** băng; client của tôi **6/6 PASS** (đã xác nhận trên seed 1–10 và 25/26/27).
Điểm đáng chú ý: amplification của naive cao gấp **9–17 lần** bản sửa (G2: 9.904 vs 1.041; G5: 17.03 vs 1.003) —
đó chính là retry storm được đo bằng số.

## 2. Cấu hình client và lý do

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| attempt_timeout_s | 8.0 | Thí nghiệm 2: đặt 30 s làm G6 tụt availability còn 0.9488 (alpha-eu `hang` → mỗi request treo đủ 30 s mới fail over, hết deadline). 8 s < 10 s `max_queue_wait_s` của provider nên không bao giờ tự bắn timeout lên request còn có cơ hội xong. |
| max_attempts_per_provider | 2 | Đủ để vượt một 529 đơn lẻ, nhưng một lần retry rồi fail over nhanh. Thí nghiệm 1 cho thấy tăng lên 5 (không có breaker) đẩy retry_ratio G2 lên 0.51 và recovery lên 22 s. |
| backoff_base_s / cap_s | 0.25 / 4.0 | Full jitter: trần 4 s nằm gọn trong deadline 30 s kể cả sau một retry; base 0.25 s đủ để hàng nghìn client tản ra (G1 `retry_after_violations` = 0). |
| retry_budget_ratio | 0.1 | Trần cứng ~10% retry (Finagle). G3 yêu cầu `retry_ratio ≤ 0.10` — đo được **0.034**; thí nghiệm 1 cho thấy tắt budget → 0.51. |
| breaker.window_size / min_calls | 20 / 10 | Cửa sổ 20 kết quả, cần tối thiểu 10 để tránh trip vì 2 lỗi lúc 3 giờ sáng. G3 (30% lỗi) trip sau ~10–20 mẫu — đủ nhanh cho một incident 3 phút. |
| breaker.failure_rate_threshold | 0.5 | 30% lỗi của G3 vượt ngưỡng khi cửa sổ tích đủ mẫu; G5 (400) không bao giờ trip vì 400 không tính vào breaker. |
| breaker.slow_call_s | 5.0 | G4 thêm đúng +5 s (`extra_latency_s: 5`); ngưỡng 5.0 bắt được suy giảm và trip theo `slow_call_rate`, cho p95 **5.562 s** (naive: 13.764 s). |
| breaker.open_duration_s | 10.0 | Đủ để provider nhả hàng đợi (G2), ngắn hơn incident 3 phút nên vẫn có probe định kỳ; recovery đo được = **0.0 s**. |
| breaker.half_open_max_probes | 2 | Chỉ 2 probe bay cùng lúc khi provider vừa hồi phục — không thả cả herd vào một deployment còn yếu (metastable failure). |
| breaker.half_open_successes | 2 | Đủ để phân biệt "hồi phục thật" với "vừa nhô lên"; tránh đóng breaker rồi mở lại liên tục. |

Sơ đồ quyết định của `on_error`:

```
on_error(attempt, err)                          [err đã có kind = classify(err)]
│
├─ CLIENT_ERROR (400/401/403/404/422)
│     breaker.release()  ← KHÔNG tính vào health, KHÔNG retry, KHÔNG fail over
│     └─► GiveUp("client_error")                (G5: client_error_retries = 0)
│
├─ QUOTA_EXHAUSTED (429 insufficient_quota)
│     breaker.release() ; cooldown[provider] = now + quota_cooldown_s (300 s)
│     └─► fail over NGAY sang provider kế tiếp   (G5: A hết quota → alpha-eu gánh)
│
├─ RATE_LIMITED (429 rate_limit_exceeded)
│     breaker.release() ; cooldown[provider] = now + retry_after
│     └─► fail over NGAY (delay = 0)             (G1: alpha 12 rps → spill sang alpha-eu)
│
└─ OVERLOADED / SERVER_ERROR / TIMEOUT    ← transient
      breaker.on_failure()  → có thể trip breaker ngay
      tries += 1
      ├─ tries < max_attempts_per_provider
      │    AND budget.try_acquire_retry(now)  → Send(SAME provider, delay = full_jitter(tries),
      │                                              tôn trọng retry_after nếu có)
      └─ ngược lại → idx += 1, tries = 0, fail over (delay = 0)

_route(): duyệt ladder từ idx, bỏ qua provider đang cooldown HOẶC breaker trả permit = None.
          Ladder cạn → nếu có cooldown rate-limit ≤ 5 s và kịp deadline thì chờ, else GiveUp.
```

Hai điều then chốt: (a) breaker chỉ nhận tín hiệu *sức khoẻ provider* (`counts_toward_breaker`), cooldown chỉ
nhận tín hiệu *hạn mức của mình* — trộn hai thứ này là lỗi phổ biến nhất; (b) mọi permit đều được `release()`
trên đường không-tính-health, nếu không slot HALF-OPEN sẽ rò rỉ.

## 3. Ba thí nghiệm (mỗi cái 3–5 câu + số)

### 1. Retry budget là lớp phòng thủ cuối

Giả lập breaker hỏng (`breaker.min_calls: 1000000000` → không bao giờ trip) và `max_attempts_per_provider: 5`:

| | G2 availability | G2 amplification | G2 retry_ratio | G2 recovery | G3 retry_ratio |
|---|---:|---:|---:|---:|---:|
| (a) budget ON (`ratio=0.1`) | 0.9987 | 1.38 | 0.058 | 0.0 s | 0.068 |
| (b) budget OFF (`ratio=100`, `max_tokens=1e9`) | 0.9636 | **1.69** | **0.51** | **22.0 s** | **0.159** |

Không có budget, mỗi call được retry 5 lần bất kể tải: retry_ratio nhảy từ 0.058 lên 0.51 (gấp ~9 lần), amplification
1.38 → 1.69 và provider mất thêm **22 giây** mới hồi phục — đúng cơ chế metastable: retry của chính mình giữ hàng đợi đầy.
Thú vị là ngay cả khi breaker hỏng, availability G2 vẫn 0.9987 → **budget một mình đã cứu được băng này**.
Khi breaker hoạt động đúng thì budget ít quan trọng hơn (retry_ratio 0.007 ở cấu hình chuẩn), nhưng vẫn nên có cả hai vì
chúng chặn hai thứ khác nhau: breaker là *phản ứng theo provider* (chậm, cần tích luỹ bằng chứng), budget là *trần cứng
theo tải* áp dụng ngay từ request đầu tiên và không phụ thuộc việc phát hiện sự cố — nếu ai đó chỉnh sai threshold
hoặc incident lạ chưa từng gặp, budget vẫn giữ retry ≤ 10%.

### 2. `attempt_timeout_s: 30`

| | G4 p95 | G6 availability | G6 p95 |
|---|---:|---:|---:|
| timeout = 8 s | 5.562 | **1.0** | 5.961 |
| timeout = 30 s | 5.608 | **0.9488** | 5.315 |

G6 có `alpha-eu` bị `hang` (provider không bao giờ trả lời). Với timeout 30 s, mỗi request rơi vào alpha-eu treo hết
30 s — bằng luôn deadline của user — nên fail over xong thì hết giờ: availability sụp từ 1.0 xuống 0.9488 (mất ~5% user).
G4 không đổi nhiều vì alpha chỉ chậm thêm 5 s, dưới cả hai ngưỡng. Timeout "đúng" phải nhỏ hơn thời gian user còn kiên nhẫn
*còn lại* sau khi trừ backoff, và nhỏ hơn ngưỡng mà provider bắt đầu shed tải (`max_queue_wait_s = 10 s`) — nếu không,
ta bỏ một request còn cơ hội thành công để đổi lấy một attempt chắc chắn chết. 8 s = 10 s (queue shed) − 2 s đệm là
điểm cân bằng; nó cũng để lại ≥ 1 s cho lần fail over cuối (`min_time_left_s`).

### 3. Bỏ lọc tool calling khỏi `ladder()`

Chạy G6 khi `ladder()` trả về nguyên `self.order` (không lọc `supports_tools`):

| | availability | incompatible_routes |
|---|---:|---:|
| có lọc (đúng) | 1.0 | 0 |
| bỏ lọc | 0.9019 | **234** |

Trong sự cố, alpha (503) và alpha-eu (treo) đều chết, beta bị hạ rate limit → ladder trôi tới `gamma-mini`. Model C-mini
không có tool calling, nên 234 lượt *user tưởng mình đã được phục vụ* thực chất nhận về một câu trả lời chat không có
kết quả tool — với một agent hoàn tiền, đó là một refund không được gọi nhưng user được bảo là xong. Nói bằng ngôn ngữ
product: **10% khách hàng được "phục vụ" bằng một câu trả lời sai nghiêm trọng**, và tỉ lệ lỗi đó còn tệ hơn cả việc
báo "hệ thống bận, thử lại sau" — vì nó phá vỡ niềm tin và tạo ticket hỗ trợ mà không ai biết nguyên nhân. Với reliability
layer, "đúng nhưng chậm" luôn thắng "nhanh nhưng sai": thà GiveUp còn hơn định tuyến một tool call vào model không
hiểu tool.

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 | 81 | **128** | **81** | 0 | 1 574 200 ¢ | 1.123 |
| yours | 1.0 | 66 | **0** | **0** | **0** | **0** | **0.303** |

Naive hoàn tiền trùng 128 lần (overpaid 15 742 000 ₫ nếu tính theo cent-đơn-vị thật) và gửi trùng 81 email, chỉ vì
retry không có key. Bản của tôi: 0 trùng, 0 mất, và `wasted_llm_per_crash` 0.303 ≤ 0.6 (naive: 1.123 — mỗi lần crash
làm lại cả `classify` lẫn `summarize`).

**Vì sao chỉ idempotency key là chưa đủ:** key ngăn *side effect trùng*, nhưng không ngăn *công việc trùng*. Sau một
`WorkerCrash`, worker mới không biết `issue_refund` đã chạy; key cứu được tiền (payment de-dup), nhưng workflow vẫn
gọi lại `llm.classify`, `orders.get` và phải chờ payment trả lại kết quả cũ — `wasted_llm_calls` tăng vô ích, và nếu
service downstream không hỗ trợ idempotency thì lỗi thật. **Chỉ checkpoint cũng chưa đủ:** checkpoint chỉ được ghi *sau*
khi step trả về. Cửa sổ nguy hiểm nằm giữa "side effect đã xảy ra" và "checkpoint đã ghi" — worker chết đúng lúc đó
(`crash_after_commit = 1.0` trong `test_crash_after_payment_does_not_pay_twice`) thì checkpoint không tồn tại, và
worker mới sẽ chạy lại step; không có key, đó là **lần hoàn tiền thứ hai**.

**Nếu ghi checkpoint *trước* khi gọi payment:** worker mới tin rằng refund đã xong và bỏ qua step → `refund_id`
không bao giờ tồn tại, `lookup` trả về `None`, `send_email` crash với KeyError, và quan trọng hơn: **tiền không bao
giờ được hoàn nhưng hệ thống báo "done"** — mất tiền của khách (lost_refunds), loại lỗi tệ hơn cả trùng tiền vì
không thể phát hiện bằng đối soát ledger. Thứ tự đúng là: gọi trước, checkpoint sau, và key ổn định để lần chạy
lại sau crash là *idempotent* chứ không phải *trùng*.

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter | Burn-rate alerter | Độ trễ phát hiện |
|---|---|---|---:|---:|
| checkout_bug | page | ✓ page | ✓ page | 27 min |
| provider_outage | page | ✓ page (0 min) | ✓ page | 4 min |
| deploy_blip | none | ✗ **page sai** | ✓ không page | — |
| slow_leak | ticket | ✗ không phát hiện | ✓ ticket | 1337 min |
| degraded_evening | page | ✓ page (214 min) | ✓ page | 291 min |
| night_spike | none | ✗ **page sai** | ✓ không page | — |
| small_bump | none | ✗ **page sai** | ✓ không page | — |

Naive: 7 page, **3 false page**. Burn-rate: 3 page + 1 ticket, **0 false page**, đúng mọi sự cố trong hạn.

Error budget 30 ngày: **đã tiêu 42.95%, còn 57.05%** → **không** đóng băng release
(`availability = 0.997853`, `bad = 55 618 / 129 508.8` cho phép).

`small_bump` (20 phút ở 12% lỗi) **không nên** đánh thức ai lúc 11 giờ trưa vì nó tiêu rất ít budget: 12% × 20 phút
là khoảng 1% ngân sách tháng — một người bị gọi dậy lúc 11 giờ trưa cho sự kiện đã tự hết trong 20 phút là một
người mất buổi làm việc tiếp theo. Quy tắc 5 phút của naive không phân biệt được "đang cháy" với "vừa loé lên":
nó chỉ nhìn tỉ lệ lỗi, không nhìn *tốc độ tiêu budget*. Luật `budget_leak_10pct_3d` (cửa sổ 3 ngày, ngưỡng 1×)
chỉ ticket — đúng cách xử lý một rò rỉ chậm: có người nhìn vào trong giờ làm việc. Điều này chính là lý do cần
**hai cửa sổ**: cửa sổ ngắn (5 m / 30 m / 6 h) trả lời "còn đang xảy ra không?" để tự tắt nhanh sau khi hồi phục
(page `fast_burn` kết thúc ~6 phút sau khi sự cố hết), cửa sổ dài (1 h / 6 h / 3 d) trả lời "có đáng để đánh thức
ai không?".

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình: `reports/gameday/G2_overload_storm.png`; số liệu: `reports/gameday/naive_G2_overload_storm_timeseries.csv`.*

**Tóm tắt:** Lúc t=120 s, deployment `alpha` mất 75% năng lực trong 3 phút; client v1 không có breaker và retry 3 tầng
chồng nhau đã biến sự cố 3 phút thành sự cố 5,5 phút, trong đó **1 285 / 2 362 lượt user (54,4%) thất bại** và p95 vượt
15 s. Đây là một metastable failure: provider đã hồi phục từ t=300 s nhưng hệ thống chỉ trở lại bình thường sau t=455 s,
vì chính lượng retry của client giữ hàng đợi provider quá tải.

**Ảnh hưởng:** 2 362 lượt user, 1 285 thất bại (availability 45,6%), p95 15,034 s (SLO user 30 s — vẫn trong, nhưng
success ratio = 0 suốt 150 s liên tục). Error budget tháng giả định chỉ có sự cố này: băng chạy 600 s ở 4 turn/s ≈
2 362 lượt, còn một tháng ở cùng tải là 4 × 2 592 000 = 10 368 000 lượt ⇒ budget 0,5% ≈ 51 840 lượt; **1 285 lượt hỏng
≈ 2,5% budget tháng** — từ một sự cố khởi nguồn chỉ 3 phút và không có tổn thất hạ tầng thật. Chi phí: 4 983 đơn vị
cho 1 077 lượt thành công = **4,627/lượt**, gấp 2,2 lần bản sửa (2,119).

**Timeline** (giây ảo — lấy từ CSV):

| t | Sự kiện | Bằng chứng (số) |
|---:|---|---|
| 120 | alpha mất 75% năng lực | `attempts_alpha` 5 → 163 trong vòng ~30 s; bắt đầu xuất hiện 529 |
| 120–300 | Retry storm: naive chỉ có một provider duy nhất (không fail over) | alpha nhận **135–184 attempt/s** trong khi `calls_ok` = **0**; `overloaded_error` 3 194 |
| 300 | alpha hồi phục hoàn toàn (hết effect) | effect kết thúc theo cấu hình băng |
| 300–455 | **Hệ thống vẫn chưa hồi phục** — vì sao? | `calls_ok` vẫn 0 ở t=310/320/350/400/420; alpha nhận 17–53 attempt/s toàn request đã hết deadline |
| 455 | success ratio mới trở lại 1.0 | `recovery_s = 155.0` tính từ t=300 |
| 655 | Hệ thống về baseline | retry_ratio 8.904, amplification 9.904 |

**Trigger vs root cause.** *Trigger* là việc alpha mất 75% GPU lúc t=120 — một sự kiện hạ tầng bình thường, sẽ tự hết
sau 3 phút. *Root cause* là bản chất retry của client v1: ba tầng retry chồng nhau (app 4 × gateway 3 × SDK 3 = tối đa
**36 attempt/call**), delay cố định không jitter, không phân loại lỗi, không tôn trọng `retry-after`, không breaker,
không deadline awareness. **Vì sao provider hồi phục mà hệ thống vẫn sập:** vòng lặp tự duy trì gồm bốn mắt xích —
(1) mỗi request bị timeout vẫn tiếp tục chiếm server slot của provider (simulator mô hình hoá đúng: *"Requests are not
cancelled when the client times out — the server keeps working on them"*); (2) request chết được retry 35 lần nữa;
(3) các retry đến cùng một lúc (delay cố định 0,2 s, không jitter) nên luôn vượt `max_queue_wait_s = 10 s` và bị shed
bằng 529; (4) mỗi 529 lại sinh thêm một retry. Công suất provider bị tiêu vào **34475 attempt** cho **2362 logical call**
— gấp 14,6 lần công việc hữu ích — nên hàng đợi không bao giờ rút ngắn dù GPU đã trở lại. Bằng chứng bổ sung: tổng
`errors_by_code.rate_limit_exceeded = 26298` trên toàn băng, tức phần lớn "sự cố" không phải do provider hỏng, mà do
chính throughput retry của client vượt rate limit 20 rps của tenant (naive bắn trung bình 57 attempt/s vào alpha, cao
điểm 250/s).

**Điều gì giúp / điều gì làm tệ hơn.** Giúp: retry có jitter (phá vỡ tính đồng bộ của các đợt retry), fail over khỏi
provider đang hỏng (naive không bao giờ rời alpha, dù beta và gamma-mini hoàn toàn khoẻ), breaker (chặn attempt thứ 5
trở đi), và deadline awareness (đừng gửi request không còn kịp). Làm tệ hơn: ba tầng retry không ai sở hữu, retry
trên mọi loại lỗi kể cả 400, và việc không có jitter khiến hàng nghìn client retry đồng loạt.

**Action items**

| # | Hành động | Loại (prevent / detect / mitigate) | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Hợp nhất retry về **một tầng duy nhất trong client**, tắt retry ở SDK và gateway | prevent | Platform | `make grade` tape G2: amplification ≤ 1,6 (nay 1,041) |
| 2 | Thêm **circuit breaker + failover ladder** có kiểm tra capability | mitigate | Agent team | G2 `recovery_s ≤ 30 s` (nay 0,0 s); G6 `incompatible_routes = 0` |
| 3 | Alert **burn-rate 2 cửa sổ** thay ngưỡng 5 phút, và dashboard `success ratio` chứ không `attempts` | detect | SRE | `make slo`: 0 false page; page G2 trong 4 phút (test tương đương) |
| 4 | Diễn tập Game Day định kỳ băng G2 với **bản băng ẩn** | prevent | SRE + Agent team | Mọi seed 1–10 PASS |

## 7. Một điểm yếu còn lại

Trong G2, p95 của tôi là **10,92 s** — vượt ngưỡng 10 s nếu băng có check `latency_p95_s_max` (G4 mới có check đó, G2
thì không). Nguyên nhân: `slow_call_s = 5.0` nằm đúng trên mức trễ thực tế của alpha khi mất 75% năng lực (hàng đợi dài,
~5–9 s), nên breaker chỉ trip *sau khi* cửa sổ 20 mẫu tích đủ; trong khoảng đó người dùng vẫn phải chờ. Cải thiện:
(a) đưa `slow_call_s` xuống ~3,5 s và giảm `window_size`/`min_calls` xuống 10/6 để phát hiện suy giảm sớm hơn — đánh đổi
là tăng nguy cơ trip vì nhiễu (cần đo lại trên G3/G4 để chắc chắn không trip nhầm lúc bình thường); hoặc (b) tốt hơn,
theo dõi **p95 latency theo cửa sổ** thay vì đếm tỉ lệ slow-call, vì ngưỡng nhị phân `latency >= 5 s` bỏ lỡ tín hiệu
khi phân bố trễ dịch chuyển dần dần (từ 4 s lên 4,9 s không có mẫu nào vượt ngưỡng nhưng trải nghiệm user đã xấu rõ rệt).
Với một agent có deadline 30 s cho cả hai bước, ngân sách cho bước `tool` chỉ ~15 s, nên trip ở 3,5 s vẫn còn dư biên an toàn.

## 8. Cache (Part G)

Số từ `reports/cache/*.json` (`make cache`), seed 25:

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.8373 | 0.8424 | 0.0 | 0 | 0 | 0 | 1.386 | ✗ |
| cached (của bạn) | **0.9124** | **0.9645** | **0.652** | 157 | **0** | **3** | **0.915** | ✓ |

Cache nâng `faq_availability` từ 0.8424 → 0.9645 và giảm 34% chi phí mỗi lượt, mà vẫn giữ 0 câu trả lời sai.

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| similarity_threshold | 0.92 | Đo trực tiếp catalog: các paraphrase *cùng* intent có cosine ≥ **0,9507**, các cặp intent *gần nhau* (refund_policy↔refund_time, shipping_fee_city↔province) chỉ tới **0,8616**. 0,92 nằm giữa hai cụm với biên ~0,03 mỗi phía. 0,80 → 175 `other_question`; 0,97 → hit chỉ 0,579 (mất paraphrase hợp lệ). |
| ttl_s | 60 | Sai lệch *không báo trước* chỉ bị chặn bởi TTL: ttl=30 → outdated 2 (nhưng hit 0,592); ttl=60 → outdated **3**, hit **0,652**; ttl=300 → outdated **95** (> ngưỡng 15). |
| max_stale_s | 300 | Cửa sổ stale phải phủ sự cố provider dài nhất: C1 sập toàn bộ provider 240→360 s = **120 s**, còn cộng thêm thời gian cache còn lại trước đó. `max_stale_s=0` → faq_availability sụp 0,9645 → **0,8733** (FAIL). 300 s cho biên gấp 2,5 lần. |
| max_entries | 500 | Catalog chỉ có 22 intent × ~3 paraphrase ≈ 66 câu + biến thể, rộng rãi so với LRU cap. |

### Thí nghiệm

**1. Ngưỡng.** `threshold = 0,80` cho **175 `wrong_answers`** (toàn bộ là `other_question`), faq_availability chỉ 0,8605
(người dùng nhận câu trả lời *sai chủ đề*, bị tính là thất bại) và cost 0,978; `0,92` → 0 wrong, hit 0,652, cost 0,915;
`0,97` → 0 wrong nhưng hit tụt còn 0,579, cost 0,965. Các cặp bị trả nhầm ở 0,80 chính là những cặp "gần mà khác" mà
catalog cố ý dựng: **refund_policy ↔ refund_time** ("chính sách hoàn tiền thế nào?" vs "bao lâu thì nhận được tiền hoàn?",
cosine 0,86) và **shipping_fee_city ↔ shipping_fee_province** ("phí ship nội thành" vs "phí ship đi tỉnh") — trả lời
chính sách hoàn tiền cho người hỏi *thời gian* hoàn tiền là sai về mặt nghiệp vụ, dù câu trả lời đọc lên rất hợp lý.
Đây là lý do threshold phải được đặt từ **phân bố cosine thật** chứ không phải cảm tính.

**2. TTL.** ttl = 30/60/300 → hit 0,592/0,652/0,731 và `outdated_answers` 2/3/**95**. Webhook **không** giúp được gì cho
`outdated_answers` vì theo định nghĩa của băng, `silent_updates` (t=480 s, bảng phí ship) là thay đổi **không có webhook**:
không ai gọi `on_content_update("policy/shipping")`, nên cache không có cách nào *biết* — nó chỉ có thể *giới hạn thời gian
sống* của những câu trả lời cũ. Webhook xử lý được t=150 (`policy/refund`, và nếu thiếu nó thì `wrong_answers` sẽ có
`ignored_invalidation`); TTL là lớp duy nhất giới hạn thiệt hại khi nguồn thay đổi mà không báo. 60 s là điểm cân bằng:
đủ dài để có hit ratio cao, đủ ngắn để cửa sổ "trả lời lỗi thời" chỉ ~1 phút.

**3. Stale-if-error.** `max_stale_s = 0` → `faq_availability` từ **0,9645 xuống 0,8733** (dưới ngưỡng 0,93), `stale_served`
về 0. Trong 120 giây mọi provider sập, mỗi lượt FAQ hoặc được trả lời từ cache cũ hoặc thất bại — không có đường thứ ba.
Trong lúc đó `wrong_answers` vẫn là 0 vì entry stale vẫn thoả mọi điều kiện an toàn (scope prompt_version, còn trong
`ttl_s + max_stale_s`, không cá nhân, chưa bị invalidate). Điều này cho thấy stale-if-error **không** phải là "tắt kiểm tra
an toàn": nó chỉ nới *thời gian* chứ không nới *điều kiện đúng*. Một chi tiết đáng chú ý là `_or_stale` tra cứu lại cache
**tại thời điểm GiveUp** thay vì dùng kết quả đã tra ở `start` — cần thiết vì webhook có thể đã bắn trong lúc call đang
bay (test `test_content_update_invalidates_even_for_stale_use` kiểm đúng kịch bản này).

### Trả lời

**Vì sao câu hỏi cá nhân không được cache, kể cả khi cache theo từng user?** Vì câu trả lời đúng còn phụ thuộc *thời gian*,
không chỉ người. "Đơn #48213 của tôi đang ở đâu?" có câu trả lời hợp lệ trong lúc đang giao, nhưng 20 phút sau — khi
shipper đã cập nhật trạng thái — cùng user, cùng embedding, cùng scope prompt_version lại là câu trả lời *sai*. Cache
theo `user_id` chỉ chặn được rò rỉ dữ liệu (`other_user`), không chặn được việc trả lời một câu hỏi về trạng thái đã
thay đổi; và TTL ngắn thì không đủ, vì các webhook cập nhật trạng thái đơn hàng đến liên tục với tần suất không đoán
trước. Nghiệp vụ ở đây là "đọc đúng trạng thái hiện tại", nên `lookup()` trả `None` ngay từ đầu cho `req.personal`
(allowlist, không phải blocklist) — an toàn hơn nhiều so với việc cố phát hiện *khi nào* dữ liệu cá nhân thay đổi.

**Trong lúc mọi provider sập, dashboard vẫn xanh nhờ cache. Alert dựa trên số nào?** Không dùng availability tổng
(0,9124 — trông ổn) mà dùng **`cache_hit_ratio` kèm `stale_served` và tỉ lệ call thực sự tới được provider**. Tín hiệu
phân biệt "hệ thống khoẻ" với "hệ thống đang trả lời bằng cache cũ" là **độ trễ giải quyết từ provider (`provider_attempts`)
và `stale_served > 0`**: stale chỉ được phục vụ khi inner client đã `GiveUp` — nghĩa là *một user thật đã không được
phục vụ đúng*. Alert đúng nên là: `stale_served` tăng liên tục trong ≥ 2 phút → page (đây là "đang cháy" nhưng bằng
chứng bị chôn), và `faq_availability` chỉ là SLO phụ. Nói cách khác, cache làm *triệu chứng* biến mất chứ không làm
*nguyên nhân* biến mất — SLO phải dùng chỉ số đo khả năng phục vụ tươi (`provider error rate / attempt`) chứ không
phải chỉ số đo sự hài lòng của user sau khi đã che.
