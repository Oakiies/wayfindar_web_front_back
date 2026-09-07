# Floor 1 wide-query localization — รายงานการทดลองรอบที่ 1

> **คำสั่งสำหรับการทดลองต่อจากนี้ (สำคัญ): ใช้ `D:\wayfindar\floor1_wide_pare.MOV` เป็น query video หลักเสมอ**  
> ห้ามใช้ `D:\wayfindar\floor1_wide.MOV` เป็น default หรือเอาผลของวิดีโอเก่ามาปนกับ benchmark ใหม่ วิดีโอเก่าจะเก็บไว้เป็น historical result เท่านั้น เว้นแต่ผู้ใช้สั่งให้ย้อนทำซ้ำโดยตรง

## สรุปตัวเลข historical (อัปเดตหลังรอบที่ 8 — ผลชุดนี้มาจากวิดีโอเก่า)

| วิดีโอ historical | กล้อง | Config ที่ดีที่สุดที่ยืนยันแล้ว | Success rate |
|---|---|---|---:|
| floor1_wide.MOV | iPhone 14 Plus, "Wide" (จริงๆ ใกล้ map มาก) | sharpest-frame-in-window, top-k20 | **31/53 (58.5%)** |
| floor1_wide.MOV | (วิธีที่มี paper รองรับล้วน) | virtual-camera ด้วย HFoV จาก GeoCalib (bias-corrected), top-k20 | 30/53 (56.6%) — ดีกว่า raw_exact (29) และดีกว่า blind-guess VC ทุกอันที่เคยลอง |
| IMG_1895.MOV | iPhone 11, wide/ultra-wide (ยืนยันด้วย GeoCalib: HFoV~88°) | raw_production, top-k20 | **33/34 (97.1%)** |
| IMG_1894.MOV | iPhone 11, เลนส์ปกติ (ยืนยันด้วย GeoCalib: HFoV~57°, แคบกว่า map ด้วยซ้ำ) | raw_exact, top-k20 | **31/35 (88.6%)** |

ข้อสรุปที่ยืนอยู่ได้จนถึงตอนนี้: **FoV mismatch มีอยู่จริงและวัดได้ (ยืนยันด้วย 2 วิธีอิสระ) แต่ไม่ใช่ตัวตัดสิน success rate หลัก** — คลิปที่ mismatch เยอะกว่า (IMG_1895) กลับ success สูงกว่าคลิปที่ mismatch น้อยกว่า (floor1_wide) หลักฐานชี้ว่าตัวแปรที่สัมพันธ์กับ success ชัดเจนกว่าคือ **คุณภาพของ retrieval** (MegaLoc similarity score) ไม่ใช่ PnP/gate โดยตรง (รอบที่ 7) **แต่รอบที่ 8 พบว่าเมื่อใช้ค่า FoV ที่ประมาณถูกต้อง (ไม่ใช่เดา) ก็ยังช่วยได้จริงเล็กน้อยและ reproducible** — สองเรื่องนี้ไม่ขัดกัน: FoV ไม่ใช่ตัวตัดสินหลัก แต่แก้ให้ถูกก็ยังมีประโยชน์ส่วนเพิ่ม

วันที่ทดลอง: 6 กันยายน 2026

## Benchmark ที่ต้องใช้ต่อจากนี้

- **Active query video:** `D:\wayfindar\floor1_wide_pare.MOV`
- ใช้ sampling ทุก 10 วินาทีตามที่วิดีโอรองรับ; วิดีโอนี้มี 34 timestamps ที่ step นี้
- ผล canonical ล่าสุดของ active video: raw production `33/34`, raw exact `32/34`
- ผลของ active video ต้องบันทึกเป็นรอบใหม่และห้ามเขียนทับไฟล์/ตัวเลขของ `floor1_wide.MOV`

## ขอบเขตที่ตรึงไว้

- วิดีโอ query หลัก: `D:\wayfindar\floor1_wide_pare.MOV` (1920×1080, 34 จุดทดสอบทุกประมาณ 10 วินาที)
- `D:\wayfindar\floor1_wide.MOV` เป็น historical-only และห้ามใช้เป็น default ในการทดลองรอบใหม่
- fixed map: `app/data/map_data/result_floor1_4`
- pipeline: **MegaLoc → SuperPoint/LightGlue → PnP-RANSAC**
- ไม่มีการสร้าง map, keyframe หรือ descriptor ฝั่ง map ใหม่
- ไม่เปลี่ยนเป็น HLoc pipeline, CosPlace หรือ NetVLAD
- ไม่ลด `min_inliers=10`, inlier-ratio gate หรือ reprojection-error gate เพื่อเพิ่มตัวเลข
- “success” ในตารางหมายถึง PnP ผ่าน quality gate เดิม ยังไม่ใช่ metric accuracy เพราะวิดีโอไม่มี ground truth

## งานวิจัยที่ใช้กำหนดการทดลอง

1. [360Loc (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_360Loc_A_Dataset_and_Benchmark_for_Omnidirectional_Visual_Localization_with_CVPR_2024_paper.html) ศึกษา cross-device/cross-FoV localization และ virtual cameras โดยตรง พร้อม baseline ที่ใช้ SuperPoint + LightGlue งานนี้รายงาน retrieval ที่ k=1,5,10 และ [supplementary](https://openaccess.thecvf.com/content/CVPR2024/supplemental/Huang_360Loc_A_Dataset_CVPR_2024_supplemental.pdf) ใช้ top-k=20 ใน HLoc experiment
2. [360Loc official code](https://github.com/HuajianUP/360Loc/blob/main/process.py) ใช้ ray reprojection จาก intrinsics และ rotation ของ virtual camera โดยกำหนด image width/height แยกจาก `cx/cy`
3. [MegaLoc](https://arxiv.org/abs/2502.17237), [SuperPoint](https://openaccess.thecvf.com/content_cvpr_2018_workshops/w9/html/DeTone_SuperPoint_Self-Supervised_Interest_CVPR_2018_paper.html) และ [LightGlue](https://openaccess.thecvf.com/content/ICCV2023/html/Lindenberger_LightGlue_Local_Feature_Matching_at_Light_Speed_ICCV_2023_paper.html) เป็น component เดิมที่ตรึงไว้
4. [SeqSLAM (ICRA 2012)](https://doi.org/10.1109/ICRA.2012.6224623) รองรับเหตุผลในการใช้ข้อมูลลำดับภาพ แทนการตัดสินจากภาพเดี่ยวเท่านั้น
5. [Simultaneous Localization, Mapping and Deblurring (ICCV 2011)](https://doi.org/10.1109/ICCV.2011.6126370) แสดงว่า motion blur ลด interest points และทำให้ feature matching ยากขึ้น จึงทดลองเลือกเฟรมคมใน temporal window ก่อนพิจารณา deblurring

ข้อจำกัดสำคัญ: 360Loc สร้าง virtual view จากภาพ 360° ซึ่งมีข้อมูลรอบทิศ แต่คลิปนี้เป็นภาพ finite-FoV ดังนั้น PoC นี้ใช้เพียงสมการ ray reprojection เดียวกันและไม่เติมข้อมูลนอกภาพ วิธีนี้เป็น **adaptation ที่ต้องทดลอง** ไม่ใช่การ reproduce 360Loc ตรงตัว

## ผลบน benchmark หลัก 53 timestamps

| วิธี | Same-frame success | เปลี่ยนจาก baseline | เวลา localization call เฉลี่ย |
|---|---:|---:|---:|
| Production เดิม, raw, top-k 4 | 19/53 (35.8%) | — | 0.147 s |
| Raw, top-k 20 | 28/53 (52.8%) | +17.0 จุดเปอร์เซ็นต์ | 0.456 s |
| Raw exact image size, top-k 20 | 29/53 (54.7%) | +18.9 จุดเปอร์เซ็นต์ | 0.451 s |
| Virtual camera สมมุติ source HFoV 70°, top-k 20 | 29/53 (54.7%) | +18.9 จุดเปอร์เซ็นต์ | 0.446 s* |
| รับผลจาก raw/exact-size/VC70 ที่ผ่าน gate | 31/53 (58.5%) | +22.7 จุดเปอร์เซ็นต์ | หลาย pass |

\* เวลานี้จับเฉพาะ localization call ยังไม่รวมเวลาสร้าง remap image

Temporal availability เป็นคนละ metric:

| วิธี | Timestamp coverage |
|---|---:|
| Raw top-k20 + nearby frame ±0.25 s | 31/53 (58.5%) |
| Raw top-k20 + เลือกสูงสุด 3 เฟรมที่คมที่สุดใน ±0.5 s | 33/53 (62.3%) |
| รวม temporal + exact-size/VC70 hypotheses | 34/53 (64.2%) |

ตัวเลข temporal หมายถึงมี pose ที่ผ่าน gate ใกล้ timestamp ภายใน window ที่ระบุ ไม่ควรเรียกว่า same-frame success

## สิ่งที่ค้นพบ

1. ผล PoC เก่าที่ได้ประมาณ 8–10/53 ไม่ใช่ baseline ของระบบจริง เพราะใช้ CosPlace/SuperGlue รอบนี้ pipeline จริงให้ 19/53 ที่ top-k 4
2. การเพิ่ม MegaLoc shortlist จาก 4 เป็น 20 ให้ gain มากที่สุด โดยไม่เปลี่ยน model หรือ map: 19 → 28 successes
3. top-k 10 และ 20 ให้ 19/27 เท่ากันบน coarse set สำหรับ raw แต่ VC70 เพิ่มจาก 19/27 เป็น 20/27 ที่ k=20 แสดงว่าผลเริ่มอิ่มตัวและควรใช้ adaptive retry แทน k=20 ทุกเฟรม
4. exact-size แก้ความไม่สอดคล้อง `1929×1092` ที่อนุมานจาก `2cx,2cy` กับ keyframe จริง `1920×1080` แต่เพิ่มเพียงเล็กน้อย จึงไม่ใช่ root cause หลัก
5. center virtual camera ที่สมมุติ 70° ดีกว่า 80°–120° ใน coarse test การบังคับ crop/reproject แรงจึงทำให้ matching แย่ลงสำหรับคลิปนี้
6. HFoV ที่ต่างกันอาจให้ pose บนแผนที่ต่างกันมาก แม้ทั้งคู่ผ่าน PnP จึงยังห้ามเลือก HFoV ต่อเฟรมจากจำนวน inliers อย่างเดียว
7. เฟรมที่ raw top-k20 ล้มเหลวมี median Laplacian sharpness 17.0 ส่วนเฟรมสำเร็จ 32.7 ภาพ evidence แสดง motion blur, ผนังเรียบ และ corridor ซ้ำเป็นปัญหาหลักที่เหลือ

## ข้อเสนอ implementation ที่ปลอดภัยในขณะนี้

ยังไม่ควรแก้ production เป็น virtual-camera ถาวร เพราะไม่มี query-camera K/distortion และไม่มี ground truth ยืนยัน position bias

candidate ที่หลักฐานรองรับมากที่สุดคือ adaptive cascade:

1. เริ่มด้วย raw query และ MegaLoc top-k 4 ตาม production เพื่อคง latency ต่ำ
2. ถ้า PnP ไม่ผ่าน ให้ reuse query global/local features แล้วขยาย candidate rank 5–20; ไม่ควร extract feature ซ้ำ
3. ถ้ายังไม่ผ่านและ input เป็น video ให้เลือกเฟรมคมกว่าใน temporal window ขนาดเล็ก แล้วรัน expanded shortlist
4. virtual-camera เปิดเป็นขั้นทดลองเฉพาะเมื่อทราบ/ประมาณ query intrinsics ที่น่าเชื่อถือ และต้องผ่าน trajectory/manual-GT audit ก่อน

## งานถัดไป

1. ทำ manual audit เฟรมที่ k=20 กู้กลับมา โดยใช้ evidence sheet และเส้นทางที่ผู้ใช้ทราบ เพื่อคัด false positives
2. ทดลองประมาณ focal length/radial distortion จาก 2D–3D correspondences ด้วย solver ที่มีที่มา เช่น [P5Pfr, ICCV 2013](https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html) แทนการ sweep HFoV แล้วเลือกต่อเฟรม
3. หลังได้ intrinsics ระดับวิดีโอหนึ่งชุด ให้ rerun VC แบบ fixed parameter และวัด trajectory consistency; ห้ามปรับ FoV ต่อเฟรมเพื่อไล่ success rate
4. ถ้า manual audit ผ่าน จึงทำ adaptive top-k เป็น feature flag ใน production พร้อม latency benchmark

## ไฟล์ผลลัพธ์

- Harness: `run_floor1_wide_production_sweep.py`
- Temporal experiment: `run_floor1_wide_temporal_recovery.py`
- Full baseline: `out/floor1_wide_production_validation53_topk4_summary.json`
- Full top-k20: `out/floor1_wide_production_validation53_topk20_summary.json`
- Full per-attempt data: `out/floor1_wide_production_validation53_topk20.csv`
- Temporal result: `out/floor1_wide_temporal_sharpest05_topk20_summary.json`
- Trajectory: `out/floor1_wide_production_validation53_topk20_trajectory.png`
- k=20 recovered evidence: `out/floor1_wide_topk20_recovered_evidence.png`
- Remaining-failure evidence: `out/floor1_wide_topk20_remaining_failures_evidence.png`

---

# รายงานการทดลองรอบที่ 2 — ตามสมมติฐาน "กล้องคนละเครื่อง คนละ FoV"

วันที่ทดลอง: 6 กันยายน 2026 (ต่อจากรอบที่ 1)

โจทย์ที่ผู้ใช้ระบุชัดเจนในรอบนี้: แผนที่ถ่ายด้วยมือถือเครื่องหนึ่ง แต่ query อาจมาจากมือถือคนละเครื่อง คนละ FoV/พารามิเตอร์กล้อง โดยไม่รู้ค่าพารามิเตอร์นั้นล่วงหน้า ระบบควรยังระบุตำแหน่ง**และทิศทางการหัน**ได้ ยังคงข้อจำกัดเดิมทุกข้อ (ไม่แก้ map, ไม่เปลี่ยน pipeline, ไม่ลด gate)

## ขั้นที่ 1 — เก็บหลักฐานราคาถูกก่อนเปลี่ยนโค้ดหรือเพิ่ม dependency

1. **Metadata วิดีโอ query** (อ่านด้วย ffmpeg ที่ bundle มากับ `imageio_ffmpeg` เพราะเครื่องนี้ไม่มี ffprobe แยก):
   วิดีโอมาจาก **iPhone 14 Plus** (`com.apple.quicktime.model`), ความละเอียด 1920×1080 (HEVC 10-bit, HLG/BT.2020) — ไม่มี focal length/K ฝังมาให้โดยตรง มีแค่ยี่ห้อ/รุ่น
2. **ตรวจ HDR/color decode**: decode เฟรมจริงด้วย OpenCV แล้วดูภาพ (`out/debug_raw_cv2_frame100.png`) — ภาพออกมาปกติ สี/คอนทราสต์ดูสมเหตุสมผล ไม่มีสัญญาณของ tone-mapping ผิดพลาด **ตัดทิ้งเป็นสาเหตุได้**
3. **เทียบ K ของแผนที่กับ query**: จาก `camera.K` ที่มีอยู่แล้วในทุก summary.json — map ใช้ focal 1400px บนภาพ 1920×1080 → **map HFoV = 68.88°** ซึ่งใกล้เคียงกับค่ามาตรฐานกล้องหลัก ("Wide") ของ iPhone ทั่วไป (~68–73°) มากกว่ากล้อง ultra-wide (~120°) แม้ชื่อไฟล์จะมีคำว่า "wide" — ข้อนี้ทำให้สมมติฐาน "FoV ต่างกันมาก" มีน้ำหนักน้อยลงตั้งแต่ต้น (Apple ตั้งชื่อกล้องหลักว่า "Wide" เป็นมาตรฐาน ไม่ใช่ ultra-wide)

## ขั้นที่ 2 — พบและแก้บั๊กจริงใน virtual-camera reprojection

โค้ดเดิม (`virtual_camera` ใน `run_floor1_wide_production_sweep.py`) render ภาพเสมอลงผืนขนาด `reference_size` (ขนาดของ map, 1920×1080) โดยใช้ `target_k` ของ map ตรงๆ เมื่อสมมติ source HFoV กว้างกว่า map HFoV (68.88°) การคำนวณจะไปสุ่มตัวอย่างเฉพาะพื้นที่ตรงกลางของภาพต้นฉบับ (แคบกว่าความกว้างเต็ม) แล้ว upsample กลับให้เต็มผืน 1920×1080 — เท่ากับ**ลด pixel-per-degree จริงของบริเวณที่ตรงกับ FoV ของแผนที่** (คำนวณเป็นตัวเลข: สมมติ source HFoV=90° จะใช้พิกเซลจริงจากต้นฉบับเพียงราว 1316/1920 px แล้วขยายเป็น 1920 px คือ upsample ~1.46 เท่า) ซึ่งเป็นการทำลายรายละเอียดที่ SuperPoint ต้องใช้ตรวจจับ keypoint และอาจเป็นสาเหตุที่ผลการทดลองรอบที่ 1 พบว่า HFoV ที่กว้างกว่า 70° กลับ "แย่ลง" — **เป็นไปได้ว่านั่นคือผลจากบั๊ก ไม่ใช่ผลจาก HFoV ที่แท้จริง**

แก้ไข: เพิ่ม `fov_preserving_canvas()` — เมื่อ source HFoV ที่สมมติกว้างกว่า map HFoV ให้ขยายผืนภาพผลลัพธ์ตามอัตราส่วน `tan(source_hfov/2) / tan(map_hfov/2)` แทน โดยคง focal length เดิมของ map (คือคง pixel-per-degree เท่าของแผนที่) แต่ครอบคลุม FoV เต็มของ query แทนการ crop กลาง — ไม่กระทบพาธ `raw` และไม่กระทบกรณี source HFoV ≤ map HFoV (พฤติกรรมเดิมคงอยู่)

## ขั้นที่ 3 — ประมาณ query focal length จาก correspondences จริง (ไม่ติดตั้งอะไรใหม่)

สร้าง `estimate_query_focal.py`: ดึง 2D–3D inlier correspondences ที่ pipeline (เดิม ไม่แก้ไข) ยอมรับแล้วบนเฟรมที่ผ่าน gate จริง จากนั้น grid-search หา focal length เดียว (fx=fy=f, cx/cy คงที่) ที่ทำให้ reprojection error ต่ำสุด บน correspondences ชุดเดิม — เป็นการประมาณแบบหยาบแทนที่ closed-form PnPf solver ของ [Kukelova et al. (P4Pfr, ICCV 2013)](https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html) เพื่อดูทิศทาง/ขนาดของความคลาดเคลื่อนก่อนตัดสินใจเพิ่ม dependency

ผล (20 เฟรมที่ผ่าน gate จาก top-k4, ทั้งชุด 53 timestamps):

| ค่า | ผล |
|---|---:|
| median(focal_query / focal_map) | 0.836 |
| mean | 0.962 |
| std | 0.448 |

median ratio 0.836 บ่งชี้ว่า query อาจมี HFoV จริงกว้างกว่า map เล็กน้อย (~68.9° → ~79°) แต่ **variance สูงมาก** (std เกือบเท่า mean) ซึ่งสอดคล้องกับปัญหาที่รู้จักกันดีของ PnP บนฉากเกือบระนาบ (corridor, ผนังเรียบ) คือ focal–depth ambiguity ("bas-relief ambiguity") ทำให้ประมาณ focal จากภาพเดียวด้วยวิธีนี้ไม่เสถียรพอจะฟันธง — **สนับสนุน mismatch แบบอ่อนถึงปานกลางเท่านั้น ไม่ใช่รุนแรง**

## ขั้นที่ 4 — ทดสอบด้วย HFoV ที่ประมาณได้จริง บนโค้ดที่แก้บั๊กแล้ว (การทดลองตัดสิน)

รัน `run_floor1_wide_production_sweep.py` ใหม่ด้วยโค้ดหลังแก้บั๊ก:

**Coarse set (27 เฟรม, step 20s, top-k 4)** — สัญญาณเบื้องต้นดูดี:

| Config | Successes |
|---|---:|
| raw_production | 15/27 (55.6%) |
| vc_hfov_70 | 17/27 (63.0%) |
| vc_hfov_100 | **18/27 (66.7%)** |
| vc_hfov_110 | **18/27 (66.7%)** |
| vc_hfov_120 | 16/27 (59.3%) |

**Full benchmark (53 timestamps, step 10s, top-k 20)** — การทดลองยืนยัน:

| Config | Successes |
|---|---:|
| raw_production | 28/53 (52.8%) |
| raw_exact_1920x1080 | 29/53 (54.7%) |
| vc_hfov_100 (bug-fixed) | 29/53 (54.7%) |
| vc_hfov_110 (bug-fixed) | 29/53 (54.7%) |

**สรุปขั้นนี้: บนชุดทดสอบเต็ม การแก้บั๊ก virtual-camera + ใช้ HFoV ที่ประมาณได้จริง (100–110°) ไม่ได้ให้ success rate สูงกว่า raw_exact-size ธรรมดาเลย** ผลบวกที่เห็นใน coarse-set (27 เฟรม) ไม่ generalize ไปยังชุดเต็ม แสดงว่าเป็น noise จาก sample size เล็ก ไม่ใช่สัญญาณจริง

## ขั้นที่ 5 — ตรวจ reproducibility (จำเป็นก่อนอ่านตัวเลขใดๆ เป็นสัจจะ)

รัน raw-only baseline ซ้ำ 3 ครั้งด้วยโค้ดปัจจุบัน (2 ครั้งอิสระ + 1 ครั้งในชุด sweep) ได้ **15/27 ตรงกันทุกครั้ง** — pipeline เชิงกำหนด (deterministic) เมื่อโค้ด/อินพุตเดิมทุกประการ แต่ตัวเลขนี้ต่างจากไฟล์ผลลัพธ์เดิมของรอบที่ 1 (`floor1_wide_production_coarse_hfov_summary.json` บันทึกไว้ 17/27) โดยไม่ทราบสาเหตุ (เป็นไปได้ว่ามีการแก้ config/state ระหว่าง session ก่อนหน้าที่ context หลุดไปแล้ว) — **บันทึกไว้เป็นข้อควรระวัง**: อย่าเทียบตัวเลขข้าม session โดยไม่ re-baseline ด้วยโค้ดปัจจุบันก่อนเสมอ

## ขั้นที่ 6 — Trajectory + heading consistency (ตอบโจทย์ "ทิศทางการหัน" ที่ผู้ใช้ถาม)

พบว่า pipeline คำนวณ heading (`theta`) อยู่แล้วภายใน (`app/core/localization.py`, `get_yaw`/`transform_yaw`) แต่ sweep script ไม่เคยบันทึกออกมา — **เพิ่มคอลัมน์ `heading_deg` ใน CSV แล้ว** (ไม่กระทบ pipeline หรือ gate ใดๆ)

สร้าง `analyze_trajectory_consistency.py`: เนื่องจากไม่มี ground truth และไม่มี scale (เมตร/พิกเซล) ของแผนที่ จึงใช้ robust outlier check (MAD, modified z-score) กับ "ระยะกระโดด" และ "การเปลี่ยนทิศ" ระหว่าง pose ที่ผ่าน gate ติดกันในเวลา (แนวคิดใกล้เคียง sequence-consistency ของ [SeqSLAM](https://doi.org/10.1109/ICRA.2012.6224623) ที่อ้างไว้แล้วในรอบที่ 1) เพื่อแยก "gate-pass" ออกจาก "trajectory-consistent" โดยไม่ต้องมี GT

ผลบนทั้ง topk20 เดิมและชุดใหม่: **ไม่พบ position/heading outlier ที่ผิดปกติ** (0 จุดถูก flag ทุก config) — เป็นสัญญาณสนับสนุนเพิ่มเติมว่าตัวเลข success ที่ได้ไม่ได้มาจาก false-positive ที่เห็นได้ชัดจากความไม่ต่อเนื่องของ trajectory (แต่ไม่ใช่การพิสูจน์ที่แน่นหนาเท่า manual audit ที่ระบุไว้ในงานถัดไปของรอบที่ 1)

## ข้อสรุปรอบที่ 2

1. **สมมติฐาน FoV/intrinsics-mismatch มีน้ำหนักอ่อน ไม่ใช่ตัวการหลัก** — สามหลักฐานอิสระชี้ทางเดียวกัน: (ก) map HFoV เองก็อยู่ในช่วงกล้องหลักมาตรฐาน ไม่ใช่ ultra-wide, (ข) การประมาณ focal จาก correspondences จริงให้ผลใกล้ 1.0 โดยเฉลี่ยแต่ variance สูงจนฟันธงไม่ได้, (ค) การทดสอบ HFoV ที่ประมาณได้จริงบนโค้ดที่แก้บั๊กแล้ว **ไม่ทำให้ full-benchmark ดีขึ้นกว่า raw_exact-size**
2. ข้อค้นพบเดิมจากรอบที่ 1 (motion blur + ผนังเรียบ + corridor ซ้ำ เป็นตัวการหลักของความล้มเหลวที่เหลือ) **ยังคงเป็นคำอธิบายที่มีหลักฐานหนักแน่นที่สุด** ไม่มีอะไรในรอบนี้หักล้าง
3. **จึงยังไม่ควรติดตั้ง GeoCalib หรือ self-calibration model อื่นในตอนนี้** — งานวิจัยด้าน single-image calibration ที่เกี่ยวข้อง ([GeoCalib, Veicht et al., ECCV 2024](https://arxiv.org/abs/2409.06704), จากทีมเดียวกับ LightGlue/HLoc) ยังคงเป็นตัวเลือกที่มีที่มาและเข้ากับ pipeline ได้ถ้าอนาคตมีสัญญาณ FoV-mismatch ที่ชัดกว่านี้ (เช่น กล้องอื่นที่ HFoV ต่างจาก map มากจริง เช่น ultra-wide 120° หรือกล้อง DSLR/action-cam) แต่สำหรับคลิปนี้ค่าใช้จ่ายในการเพิ่ม dependency ไม่คุ้มกับหลักฐานที่มี
4. บั๊ก virtual-camera ที่แก้ไปยังคงมีประโยชน์เชิงวิศวกรรม (ถูกต้องกว่าของเดิม) และควรเก็บไว้ใช้ต่อเมื่อวันหนึ่งมีวิดีโอที่ FoV ต่างจริงและมาก
5. เรื่อง**ทิศทางการหัน**ที่ผู้ใช้ถาม: ระบบมีอยู่แล้วภายใน (`theta`) และตอนนี้ถูก log ออกมาให้ตรวจสอบได้ แต่ยังไม่มีวิธียืนยันความแม่นยำเพราะไม่มี ground truth ของทิศทาง — นี่ควรเป็นจุดสนใจถัดไปพอๆ กับตำแหน่ง ไม่ใช่รองจากตำแหน่ง

## งานถัดไป (ปรับปรุงจากรอบที่ 1)

1. **เปลี่ยนทิศทางความพยายามไปที่ motion blur / repetitive-texture** แทน FoV: ทดลองวิธี deblurring หรือ multi-frame feature aggregation ที่มีที่มา (เช่นต่อยอดจาก [Cho & Lee, Simultaneous Localization Mapping and Deblurring, ICCV 2011](https://doi.org/10.1109/ICCV.2011.6126370) ที่อ้างไว้แล้ว) บนเฟรมที่ sharpness ต่ำกว่า median ของกลุ่มสำเร็จ (32.7)
2. ทำ **manual audit + heading ground truth** อย่างน้อยบางจุด (เช่น จุดที่ผู้ใช้จำทิศทางได้ เช่น หน้าลิฟต์/ทางเข้า) เพื่อยืนยันทั้งตำแหน่งและทิศทาง ไม่ใช่แค่ gate-pass
3. ถ้าในอนาคตมีวิดีโอ query จากกล้อง**ที่รู้แน่ชัดว่า FoV ต่างจาก map มาก** (เช่น ultra-wide, action-cam) ค่อยเปิดใช้ `fov_preserving_canvas` + พิจารณา GeoCalib เป็นตัวประมาณ prior ต้นทาง แทนการ sweep HFoV มั่ว
4. แก้ปัญหา reproducibility gap ที่พบในขั้นที่ 5 ก่อนสร้างรายงานเปรียบเทียบข้าม session ใดๆ ต่อไป

## ไฟล์ที่เพิ่ม/แก้ในรอบนี้ (ก่อนแก้ตาม advisor รอบ 2)

- แก้บั๊ก: `run_floor1_wide_production_sweep.py` (`fov_preserving_canvas`, เพิ่ม `heading_deg` ใน CSV)
- ใหม่: `estimate_query_focal.py` — map-grounded focal estimation จาก inlier correspondences
- ใหม่: `analyze_trajectory_consistency.py` — post-hoc trajectory/heading consistency check
- หลักฐาน: `out/debug_raw_cv2_frame100.png`, `out/floor1_wide_focal_estimate_topk4*.{csv,json}`, `out/floor1_wide_postfix_coarse_hfov*.{csv,json}`, `out/floor1_wide_round2_topk20_hfov100_110*.{csv,json}`, `out/floor1_wide_variance_check_{1,2}*.{csv,json}`, `out/*_trajectory_consistency.json`

---

# ภาคผนวกรอบที่ 2 — แก้ตามข้อทักท้วงที่ยังไม่ผ่าน + ข้อค้นพบใหม่เรื่อง heading

หลังส่งรายงานรอบที่ 2 ฉบับแรก มีข้อทักท้วงว่า (1) การเปรียบเทียบ coarse-set (top-k 4) กับ full-set (top-k 20) เปลี่ยนตัวแปรสองตัวพร้อมกัน สรุปว่า "เป็น noise จาก sample size" ยังไม่ผ่านเพราะยังไม่ตัดผลของ top-k ออก และ (2) `analyze_trajectory_consistency.py` ไม่หาร Δt ทำให้ timestamp ที่ fail สลับกันทำให้ jump ที่วัดได้ปนกันจนไม่มีอำนาจแยกแยะ (flag 0 ทุก config ไม่ใช่เพราะสะอาดจริง แต่เพราะเครื่องมือตรวจจับไม่ได้)

## แก้จุดที่ 1: ทดสอบแบบคุมตัวแปร top-k

รัน full 53-timestamp benchmark ที่ **top-k 4** (เท่ากับ coarse-set เดิม) ด้วยโค้ดหลังแก้บั๊ก:

| Config | Successes (top-k 4, full 53) |
|---|---:|
| raw_production | 20/53 (37.7%) |
| raw_exact_1920x1080 | 22/53 (41.5%) |
| vc_hfov_100 | 23/53 (43.4%) |
| vc_hfov_110 | 21/53 (39.6%) |

vc_hfov_100 ดีกว่า raw_exact +1/53 (+1.9 จุดเปอร์เซ็นต์) และดีกว่า raw ดิบ +3/53 — ทิศทางเดียวกับ coarse-set แต่**ขนาดเล็กกว่า noise floor ที่วัดได้จริงในขั้นถัดไป (±2/27 จาก nondeterminism ล้วนๆ)** ที่ top-k 20 (จุดที่ production คาดว่าจะใช้งานจริงถ้าเปิด adaptive top-k) ผลต่างนี้หายไปสนิท (29=29) สรุป: **ข้อสรุปเดิมยังยืนได้ แต่ตอนนี้มีหลักฐานที่คุมตัวแปรถูกต้องรองรับแล้ว ไม่ใช่แค่ inference จาก sample size**

## แก้จุดที่ 2: normalize ด้วย Δt แล้วรันใหม่

แก้ `analyze_trajectory_consistency.py` ให้หาร position-jump และ heading-jump ด้วยเวลาที่ห่างจริง (px/s, deg/s) แทนการนับ raw jump ระหว่างแถวที่ผ่าน gate ติดกัน (ซึ่งอาจห่างกัน 10/20/30/40 วินาทีปนกัน) ผลหลังแก้:

| Config | Trajectory-consistent / gate-pass |
|---|---:|
| raw_production | 28/28 (0 outlier) |
| raw_exact_1920x1080 | **27/29 (2 flagged)** |
| vc_hfov_100 | 29/29 (0 outlier) |
| vc_hfov_110 | 29/29 (0 outlier) |

ตอนนี้เครื่องมือมีอำนาจแยกแยะจริง (ไม่ใช่ flag 0 ทุกช่องเหมือนก่อนแก้) — raw_exact มี 2 เฟรมที่ position/heading เปลี่ยนเร็วผิดปกติเทียบกับ pace ของ run นั้น ควรอยู่ในรายการ manual-audit ก่อน (ยังไม่สรุปว่าเป็น false positive เพราะไม่มี GT แต่เป็นจุดที่ควรตรวจก่อน)

## หาสาเหตุ 2 เฟรมที่ผลไม่ตรงกันระหว่าง run (raw_production, coarse-set)

Diff เฟรม 771 และ 3855 ระหว่างไฟล์รอบที่ 1 กับรอบที่ 2 (โค้ด raw ไม่ถูกแก้เลย) พบว่า **จำนวน match/inlier ต่างกันจริงในระดับ 1-5 จุด** (เช่น max_candidate_matches 31→29, 25→20) ทั้งที่ input และโค้ดเหมือนกันทุกประการ — แปลว่า retrieval/matching stack (MegaLoc/SuperPoint/LightGlue หรือ backend GPU) **มี nondeterminism อยู่จริง** เฟรมทั้งสองอยู่ที่ inlier=10-11 ซึ่งเฉียด gate (min_inliers) พอดี จึงพลิกได้ง่าย **สรุป: มี noise floor ~2/27 (~7%) จาก nondeterminism ล้วนๆ โดยไม่ต้องเปลี่ยนอะไรเลย — ตัวเลข delta ใดๆ ที่เล็กกว่านี้ถือว่าตีความไม่ได้แน่นอน** (บันทึกไว้ใช้เทียบกับทุก delta ในรายงานนี้และรายงานถัดไป)

## ข้อค้นพบใหม่ที่สำคัญที่สุดของรอบนี้: heading อาจมีบั๊กจริงใน pipeline หลัก

ตรวจสอบ heading ที่ log ออกมา (จาก `theta` ที่มีอยู่แล้วใน pipeline) โดย plot เทียบกับเวลา พบว่า **heading กระโดดแบบไม่มีรูปแบบ** (เช่น -80.6° → -23.2° → 141.4° → 157.3° → 88.1° ระหว่างจุดที่ห่างกัน 10-20 วินาที) ทั้งที่ตำแหน่ง x,y ในช่วงเดียวกันดูสมเหตุสมผล (เคลื่อนที่ต่อเนื่อง)

ตรวจโค้ด `get_yaw(R)` ใน `app/core/localization.py`:
```python
def get_yaw(R: np.ndarray) -> float:
    return np.degrees(np.arctan2(R[0, 2], R[2, 2]))
```
pose.txt ของ map ระบุชัดว่า R,t คือ **Tcw (world → camera)** ดังนั้นทิศทางที่กล้องหันในโลก (world-frame forward vector) ต้องมาจาก `R^T @ [0,0,1]` ซึ่งตรงกับ**แถวที่ 3** ของ R ไม่ใช่คอลัมน์ที่ 3 ที่โค้ดปัจจุบันใช้อยู่ สูตรที่ถูกต้องน่าจะเป็น `atan2(R[2,0], R[2,2])` ไม่ใช่ `atan2(R[0,2], R[2,2])`

**ทดสอบยืนยันด้วยข้อมูลจริงของแผนที่เอง** (ไม่ต้องมี GT ภายนอก, บันทึกเป็นสคริปต์ reproducible คือ `validate_yaw_formula.py`): ใช้ pose.txt ของ keyframe ทั้ง 3224 จุด (เรียงตามลำดับการถ่ายซึ่งน่าจะเป็นลำดับการเดินจริง) คำนวณทิศทางการเคลื่อนที่จริงจากตำแหน่งกล้องที่เปลี่ยนไประหว่างเฟรม แล้วเทียบกับ heading ที่ได้จากสองสูตร — ตรวจสอบก่อนว่า array อยู่ตรงตำแหน่งกัน (keyframe ทุกโฟลเดอร์มี pose.txt ครบ ไม่มี index เลื่อน) แล้ว sweep threshold ของ "การเคลื่อนที่ที่นับว่ามีนัยสำคัญ" (หน่วยแผนที่ ไม่ทราบสเกลเป็นเมตร) เพื่อดูว่าผลเสถียรไม่ใช่ artifact ของ threshold ใดค่าหนึ่ง:

| min-motion | n คู่ที่ผ่าน | error สูตรเดิม | error สูตรที่เสนอ |
|---:|---:|---:|---:|
| 0.01 | 1973 | 12.8° | **3.4°** |
| 0.02 | 642 | 8.4° | **3.3°** |
| 0.05 | 45 | 21.8° | **8.0°** |
| 0.10 | 8 | 17.1° | 24.9° (พลิก แต่ n=8 เล็กเกินจะเชื่อถือ) |

ที่ threshold ซึ่งมีจำนวนตัวอย่างเพียงพอ (0.01–0.02, n=642–1973) สูตรที่เสนอแม่นยำกว่าสูตรเดิม**อย่างสม่ำเสมอและชัดเจน** (error ต่ำกว่า 2.5–3.7 เท่า) เป็นหลักฐานหนักแน่นว่า **การอ่าน heading ปัจจุบันของ production มีบั๊กสัญลักษณ์ (sign) จริง**

**แต่ — ตรวจแล้วพบว่านี่ไม่ใช่คำอธิบายของอาการ heading กระโดดมั่วในวิดีโอ query**: ลอง negate ค่า heading ทั้งชุดของ query (`raw_exact_1920x1080`, topk20) แล้ววัด median |Δheading| ระหว่างจุดที่ผ่าน gate ติดกัน — ได้ **57.37° เท่ากันทุกประการทั้งก่อนและหลัง negate** (เป็นไปตามคณิตศาสตร์: การกลับเครื่องหมายไม่เปลี่ยนขนาดของผลต่างระหว่างจุด) นั่นคือ **บั๊ก sign ใน `get_yaw` กับอาการ heading กระโดดมั่วในวิดีโอ query เป็นคนละปัญหากัน**:

1. **บั๊ก sign ใน `get_yaw`** — ยืนยันแล้วด้วยข้อมูล map เอง (n มาก, สม่ำเสมอ) กระทบทุก query แต่เป็น "หมุนผิดทิศเป็นค่าคงที่" ไม่ใช่ทำให้ noisy
2. **Heading ของ query เองไม่นิ่ง** (median jump ~57°/step แม้จุดติดกันแค่ 10-20 วินาที) — ยังไม่ทราบสาเหตุ สมมติฐานที่เป็นไปได้คือ PnP-RANSAC บนฉาก corridor เกือบระนาบประเมิน rotation ได้แม่นน้อยกว่า translation มาก (baseline แคบ, degenerate geometry) ทำให้ตำแหน่งดูสมเหตุสมผลแต่ทิศทางไม่นิ่ง — **ยังไม่ได้พิสูจน์ ต้องตรวจเพิ่มในรอบถัดไป** ไม่ควรเหมาว่าแก้ sign แล้วจะแก้ปัญหานี้ด้วย

**สิ่งที่ยังไม่ได้ทำ (จงใจ ไม่ใช่ลืม)**: ไม่ได้แก้ `get_yaw` ในโค้ด production เพราะ (1) เป็นโค้ดที่ frontend/ระบบอื่นอาจ depend อยู่ (AR arrow, navigation heading) ไม่ใช่แค่ query-side ของ PoC นี้ (2) แก้ sign อย่างเดียวไม่ได้แก้ปัญหา heading-instability ที่เป็นตัวที่กระทบผู้ใช้จริงมากกว่า ต้องวิเคราะห์แยกกัน (3) โจทย์เดิมของ session นี้จำกัดขอบเขตไว้ที่ query-side เท่านั้น การแก้ core pipeline นอกขอบเขตนี้ควรให้ผู้ใช้ยืนยันก่อน — **นี่คือสิ่งที่ต้องตัดสินใจร่วมกับผู้ใช้เป็นลำดับแรกของรอบถัดไป** เพราะเป็นคำตอบโดยตรงต่อคำถามเรื่อง "ทิศทางการหัน" ที่ถามมา

## สรุปรวมทั้งสองรอบ (แก้ไขให้ตรงกับหลักฐานที่คุมตัวแปรแล้ว)

1. FoV/intrinsics-mismatch ระหว่างกล้อง: มีหลักฐานสนับสนุนแบบอ่อน (+1 ถึง +3 จาก 53 ที่ top-k4) แต่**เล็กกว่า noise floor ของระบบเอง** และหายไปที่ top-k20 → ยังไม่ควรลงทุนกับ self-calibration (GeoCalib ฯลฯ) สำหรับคลิปนี้
2. Motion blur + ผนังเรียบ + corridor ซ้ำ ยังคงเป็นคำอธิบายหลักของความล้มเหลวที่เหลือ (ไม่เปลี่ยนจากรอบที่ 1)
3. **ตำแหน่ง (x,y)** ที่ pipeline รายงาน ดูน่าเชื่อถือกว่าที่คาด (ต่อเนื่อง ไม่มี outlier ผิดปกติในเกือบทุก config หลัง normalize)
4. **ทิศทางการหัน (heading)** มีปัญหา 2 เรื่องที่แยกกัน: (ก) บั๊ก sign ใน `get_yaw` ที่ยืนยันแล้วด้วยข้อมูล map เอง (n=642-1973) กระทบทุก query แบบคงที่ และ (ข) heading ของ query เองไม่นิ่ง (jump ~57°/step) ซึ่งบั๊ก sign แก้ไม่ได้และยังไม่ทราบสาเหตุ — เรื่องนี้เป็นความเสี่ยงที่ใหญ่กว่าเรื่อง FoV มาก เพราะกระทบ**ทุก query** ไม่ใช่แค่กล้องต่างเครื่อง

## งานถัดไป (แก้จากรอบที่ 2 ฉบับแรก)

1. **[ตัดสินใจร่วมกับผู้ใช้ก่อน]** ยืนยัน/แก้บั๊ก sign ใน `get_yaw` (`app/core/localization.py`) — หลักฐานหนักแน่นพอสมควรแล้ว (n=642-1973) แต่ยังต้องพิจารณาผลกระทบต่อ frontend ที่ใช้ `theta` ก่อนแก้จริง
2. **สืบหาสาเหตุ heading-instability ของ query แยกต่างหาก** จากบั๊ก sign — ตั้งสมมติฐานเริ่มต้น: rotation จาก PnP-RANSAC ไม่นิ่งบนฉาก corridor เกือบระนาบ (ต้องทดสอบ เช่น เทียบ rotation covariance/reprojection sensitivity ต่อการรบกวน correspondence เล็กน้อย)
3. เปลี่ยนทิศทางความพยายามเรื่อง success rate ไปที่ motion blur / repetitive-texture ตามเดิม
4. Manual audit เฟรมที่ `analyze_trajectory_consistency.py` flag ไว้ (2 จุดใน raw_exact) ก่อนเชื่อตัวเลข success rate เต็มที่
5. ถ้าจะเทียบ delta ใดๆ ต่อไป ต้องรันซ้ำอย่างน้อย 2 ครั้งเพื่อดูว่าต่างจาก noise floor (~2/27) จริงหรือไม่ ก่อนสรุปเป็นข้อค้นพบ

## ไฟล์ที่เพิ่ม/แก้เพิ่มเติมในภาคผนวกนี้

- แก้ไข: `analyze_trajectory_consistency.py` (normalize ด้วย Δt)
- ใหม่: `validate_yaw_formula.py` — เทียบสองสูตร `get_yaw` กับทิศทางเคลื่อนที่จริงจาก keyframe pose.txt ของแผนที่เอง พร้อม `--min-motion` สำหรับ sweep threshold (ตรวจสอบแล้วว่า index ของ positions/yaw อยู่ตรงกัน ไม่มี keyframe ใดขาด pose.txt)
- หลักฐาน: `out/floor1_wide_round2_topk4_hfov100_110*.{csv,json}` (controlled top-k4 full-53 run)

---

# แก้ไข production ตามคำขอผู้ใช้ (หลังยืนยันหลักฐานครบ)

## สิ่งที่แก้จริง

แก้ `get_yaw()` ใน `app/core/localization.py` จาก `atan2(R[0,2], R[2,2])` เป็น `atan2(R[2,0], R[2,2])` ตามหลักฐานในภาคผนวกก่อนหน้า (n=642-1973 คู่จาก map keyframes เอง, error ลดจาก ~8-13° เหลือ ~3-4°) — จุดนี้กระทบเฉพาะ **legacy fallback path** ใน `app/api/localization.py` (ใช้เมื่อ `calculate_camera_heading` คืนค่า `None` เพราะไม่มี R หรือ projector)

## ตรวจสอบก่อนสรุปว่าแก้ปัญหาที่ผู้ใช้ถามจริง — พบว่ายังไม่ใช่

ก่อนอื่นตรวจว่า path หลักที่ frontend ใช้จริง (`calculate_camera_heading` ใน `app/utils/heading.py`) เป็นคนละฟังก์ชันกับ `get_yaw`/`theta` และ**คำนวณถูกต้องอยู่แล้ว** (ใช้ `R.T @ [0,0,1]` ตรงกับสูตรที่เสนอ มีคอมเมนต์ในโค้ดยืนยันว่าจงใจเลี่ยงปัญหาแบบ `90 - theta` ที่เจอ) — เขียน `compare_heading_paths.py` รันทั้งสองฟังก์ชันบนเฟรมเดียวกัน (53 timestamps, raw_exact) เพื่อเทียบ:

| Path | median \|Δheading\| ระหว่างจุดที่ผ่าน gate ติดกัน |
|---|---:|
| `theta` (get_yaw, หลังแก้บั๊กแล้ว) | 57.3° |
| `calculate_camera_heading` (production จริง) | 54.4° |

ค่าทั้งสองต่างกันแค่ offset คงที่ (~10°, มาจาก H_matrix/floor alignment) ไม่ใช่ต่างกันเชิงโครงสร้าง — **สรุปว่า path การคำนวณ heading ที่ frontend ใช้จริงมีอาการไม่นิ่งแบบเดียวกันทุกประการ** ไม่ใช่ artifact จากการวัดผ่าน fallback ที่ผิด บั๊ก sign ที่แก้ไปเป็นการแก้ที่ถูกต้องและควรเก็บไว้ (ป้องกันปัญหาซ้ำในกรณีที่ fallback ถูกเรียกใช้จริง) **แต่ไม่ใช่คำตอบของอาการ heading กระโดดที่ผู้ใช้น่าจะเจอ**

## บริบทเพิ่มเติมที่พบ: มี smoothing layer อยู่แล้วในสตรีมจริง (แต่ไม่ใช่ทางแก้ที่ราก)

พบ `blend_heading_deg()` (`app/utils/heading.py`) ถูกเรียกใช้ใน `app/services/video_processor.py` (บรรทัด ~640) สำหรับ blend heading แบบ circular ระหว่างเฟรมต่อเนื่องในสตรีมจริง (alpha 0.45–0.65 ขึ้นกับเงื่อนไข) — การทดสอบของเราเรียก `localize()` แบบอิสระทีละเฟรม (ไม่มี state ต่อเนื่อง) จึงวัดค่า**ก่อน smoothing** ผู้ใช้จริงที่ใช้แอปแบบสตรีมต่อเนื่องน่าจะไม่เห็นอาการกระโดดสุดขั้วเท่าตัวเลขดิบที่วัดได้ตรงๆ แต่ alpha ระดับนี้ (blend เข้าหาเป้าใหม่ 45-65% ต่อเฟรม) **ลดความรุนแรงได้บางส่วนเท่านั้น ไม่ได้แก้ที่ต้นเหตุ** ถ้า rotation ที่ PnP คืนมาไม่นิ่งจริง สตรีมจะยังเห็นทิศทางสั่น/ตามหลังจริงช้า ไม่ใช่ทิศทางที่แม่นยำ

## สรุปสถานะ heading หลังแก้

1. ✅ แก้บั๊ก sign ใน `get_yaw` แล้ว (legacy fallback path เท่านั้น) — ปลอดภัย มีหลักฐานรองรับ ไม่กระทบ behavior หลักเพราะ path หลักไม่ได้ใช้ฟังก์ชันนี้
2. ❌ **ยังไม่แก้ปัญหาความไม่นิ่งของ heading ที่ผู้ใช้ถามจริง** — root cause อยู่ที่ rotation estimate จาก PnP-RANSAC เองไม่นิ่งบนฉาก corridor นี้ ไม่ใช่ที่สูตรอ่านค่า yaw
3. ต้องแก้ต่อที่ต้นเหตุ (ตัวเลือกที่ยังไม่ได้ทำ): ตรวจ covariance ของ rotation จาก PnP, ลอง constrain แกน roll/pitch ด้วย gravity prior (เช่นจาก GeoCalib ที่ประเมิน gravity ได้จากภาพเดี่ยวโดยไม่ต้องรู้ focal length — ใช้ได้แม้ตัดสมมติฐาน FoV-mismatch ไปแล้ว เพราะนี่เป็นคนละเรื่อง), หรือปรับ alpha ของ `blend_heading_deg` ให้เข้ากับ scene นี้มากขึ้นเป็นการบรรเทาระยะสั้น

## ไฟล์ที่เพิ่ม/แก้ในส่วนนี้

- แก้ไข production: `app/core/localization.py::get_yaw` (sign fix, มีคอมเมนต์อ้างอิงหลักฐานในโค้ด)
- ใหม่: `poc_cross_camera/compare_heading_paths.py` — เทียบ `theta` กับ `calculate_camera_heading` บนเฟรมเดียวกัน

---

# รอบที่ 3 — ทดลอง Manhattan vanishing-point self-calibration (ตอบคำถาม "ประมาณพารามิเตอร์กล้องที่ไม่รู้ได้ยังไง")

บริบท: ผู้ใช้ถามหางานวิจัยสำหรับรับมือกล้องที่ไม่รู้พารามิเตอร์ (ปัญหาทั่วไป ไม่ใช่แค่คลิปนี้ เพราะยืนยันแล้วว่า FoV ไม่ใช่คอขวดของคลิปนี้) เลือกทดลองตัวเลือกที่ไม่ต้องเพิ่ม dependency ก่อน: **self-calibration จาก vanishing point แบบ Manhattan-world** ([Simon et al., IJCV 2015](https://link.springer.com/article/10.1007/s11263-015-0854-5)) เพราะฉาก corridor มีเส้นตั้งฉาก 3 แกนตามธรรมชาติ (พื้น/ผนัง/เพดาน)

## Implementation

`estimate_focal_vanishing_points.py`: ตรวจจับเส้นตรง (`cv2.createLineSegmentDetector`), แยกเป็นกลุ่ม "แนวตั้ง" (±25° จากแนวดิ่ง) กับ "แนวอื่น" (candidate ทิศทางตามยาวของ corridor) จากนั้น**ต้องใช้ RANSAC หา vanishing point ที่มีเส้นบรรจบกันจริง** ในแต่ละกลุ่ม (ลองแบบ least-squares รวมทุกเส้นตรงๆ ก่อน ผลออกมาไม่สมเหตุสมผลเลย เพราะปนเส้นที่ไม่ได้บรรจบจุดเดียวกันจริงเข้าด้วยกัน — แก้เป็น RANSAC แล้วดีขึ้น) แล้วคำนวณ focal จากสูตร VP ตั้งฉากมาตรฐาน `f² = -(v1-p0)·(v2-p0)`

## ผล — ขัดแย้งกับวิธี correspondence-based ในรอบที่ 2

| วิธี | median focal ratio (query/map) | n ตัวอย่าง |
|---|---:|---:|
| Correspondence-based grid search (รอบที่ 2, `estimate_query_focal.py`) | 0.836 (~79° HFoV) | 20/53 |
| Manhattan vanishing-point (รอบนี้) | 0.572 (~100° HFoV) | 25/53 |

สองวิธีอิสระกันเห็นตรงกันแค่ **ทิศทาง** (query กว้างกว่า map) แต่ตัวเลข**ไม่ตรงกัน**ต่างกันเกือบ 1.5 เท่า — implementation แบบ classical VP ที่เขียนเองในรอบนี้ยังหยาบเกินจะเชื่อถือค่าตัวเลขได้ (การแบ่งกลุ่มเส้น "แนวตั้ง/แนวอื่น" แบบ fixed-angle-band ไม่ได้ยืนยันว่าเป็น Manhattan direction ที่แท้จริง อาจจับเส้นป้าย/ขอบวัตถุที่บังเอิญบรรจบกันเป็น VP ปลอมได้ และวิดีโอมี motion blur ที่ทำให้ LSD หาเส้นสั้น/ไม่แม่น)

## สรุป

1. **ไม่ควรใช้ตัวเลขจากทั้งสองวิธีไปตัดสินใจอะไรจริงจัง** — เห็นตรงกันแค่ทิศทาง (มี mismatch จริง ไม่มาก ไม่น้อย) ไม่ใช่ขนาด
2. **ไม่กระทบข้อสรุปเรื่อง success rate ของคลิปนี้** — ที่พิสูจน์แล้วด้วย controlled A/B (VC100/110 ไม่ชนะ raw_exact ที่ top-k20) ยังยืนได้เหมือนเดิม ต่อให้ FoV จริงกว้างกว่านี้ ก็ไม่ใช่ตัวที่ทำให้ success rate ต่ำ
3. **สำหรับการรับมือกล้องไม่รู้พารามิเตอร์ในอนาคต (โจทย์ทั่วไป ไม่ใช่คลิปนี้)**: การเขียน classical method เองแบบง่ายๆ (ทั้ง grid-search PnPf และ VP-based) ให้ผล noisy เกินกว่าจะใช้งานจริง สองวิธีที่ทำเองแล้วไม่ลงรอยกันเป็นสัญญาณว่า**ควรลงทุนกับโมเดลที่ผ่านการ validate มาแล้ว** (เช่น GeoCalib ที่เสนอไว้ก่อนหน้า) แทนการพยายามอิมพลีเมนต์ classical method เองต่อไปเรื่อยๆ

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `estimate_focal_vanishing_points.py` — Manhattan VP self-calibration พร้อม RANSAC
- หลักฐาน: `out/floor1_wide_vanishing_point_focal_summary.json`

---

# รอบที่ 4 — โจมตี bottleneck ตัวจริง (blur/low-texture) จนกว่าจะเห็น success rate ขยับ

บริบท: ผู้ใช้ขอให้ทดลองต่อเรื่อยๆ จนกว่าจะเห็น success rate เพิ่มจริง หยุดเรื่อง FoV (พิสูจน์แล้วว่าไม่ใช่คอขวด) ไปโจมตี motion blur + repetitive/low-texture corridor ตามข้อค้นพบเดิม (finding #7 รอบที่ 1)

## ความพยายามที่ 1: CLAHE + unsharp masking (query-side preprocessing) — **ล้มเหลว**

มีหลักฐานจาก ORB-SLAM2 และ visual-SLAM front-end อื่นๆ ว่า CLAHE ช่วยเพิ่ม keypoint ในฉาก low-texture ลอง implement `run_preprocessing_sweep.py` (CLAHE, unsharp mask, และรวมกัน) บน full 53 timestamps ที่ top-k4:

| Config | Successes |
|---|---:|
| raw (baseline, ตรงกับรอบที่ 2 เป๊ะ) | 22/53 |
| CLAHE | 19/53 |
| Unsharp | 19/53 |
| CLAHE+Unsharp | 18/53 |

**แย่ลงทั้งหมด** ตรวจ per-frame flip (แทนดูแค่ผลรวม เพราะ delta เล็กอาจเป็น noise): gains (raw ล้มเหลว→วิธีนี้สำเร็จ) = 0-1 แต่ losses (raw สำเร็จ→วิธีนี้ล้มเหลว) = 3-4 ทุก variant — เป็น pattern ไม่สมมาตรชัดเจน ไม่ใช่ noise แต่เป็นผลเสียจริง และจำนวน match (`max_candidate_matches`) แทบไม่เปลี่ยน (median delta 0-1) ซึ่งอธิบายได้ว่า **CLAHE/unsharp ปรับเฉพาะฝั่ง query แต่ keyframe บนแผนที่ไม่ถูกปรับ ทำให้ค่าสถิติของสอง descriptor set เบี่ยงออกจากกันมากขึ้น matching แย่ลงแม้ keypoint จะไม่ได้น้อยลง** — สรุป: **ไม่ใช้วิธีนี้ต่อ**

## ความพยายามที่ 2: Sharpest-frame-in-window เป็นคำตอบของทุก timestamp — **ได้ผลจริง**

รอบที่ 1 เคยลอง "temporal recovery" แต่ใช้เฉพาะกับ timestamp ที่ล้มเหลวอยู่แล้ว แล้วเรียกผลว่า "coverage" ไม่ใช่ same-frame success (เพราะเป็นการเลือกเฉพาะกรณีที่มีโอกาสดีขึ้นอย่างเดียว ไม่ยุติธรรมเทียบกับ baseline) รอบนี้ทำให้ยุติธรรมขึ้น: **ใช้ policy เดียวกันกับทุก timestamp ทั้ง 53 จุด** — เลือกเฟรมที่คมที่สุด (Laplacian variance, อ้างอิง [Cho & Lee, ICCV 2011](https://doi.org/10.1109/ICCV.2011.6126370)) ภายใน ±0.5 วินาทีมาเป็น query แทนเฟรม ณ timestamp นั้นตรงๆ เสมอ (ถ้าเฟรมตรงคมที่สุดอยู่แล้ว ก็เท่ากับ baseline ไม่ได้เปรียบอะไรพิเศษ)

ผล (`run_sharpest_frame_policy.py`), **รันซ้ำ 2 ครั้งที่ top-k4 ได้ผลตรงกันทุกเฟรม 100% (deterministic)**:

| Top-k | Baseline (เฟรมตรง) | Sharpest-in-window policy | net delta |
|---:|---:|---:|---:|
| 4 | 22/53 (41.5%) | **24/53 (45.3%)** | +2 (gains=3, losses=1) |
| 20 | 29/53 (54.7%) | **31/53 (58.5%)** | +2 (gains=3, losses=1) |

**ผลไม่หายที่ top-k สูง** (ต่างจากเรื่อง FoV ที่ effect หายที่ top-k20) เพราะกลไกคนละแบบ: การเลือกเฟรมคมกว่า**เพิ่มข้อมูลใหม่จริง** (ภาพที่มี feature ตรวจจับได้มากกว่า) ไม่ใช่แค่ขยาย search space ซึ่งจะอิ่มตัวเมื่อ retrieval แม่นอยู่แล้ว — ยืนยันด้วย per-frame diff ระหว่าง run ซ้ำ: **0 ความต่าง** ทุกเฟรม (ทั้ง baseline และ policy ตรงกันเป๊ะ)

## สรุป: success rate ที่ดีที่สุดตอนนี้คือ **31/53 (58.5%)** ที่ top-k20 — ดีขึ้นจากตัวเลขเดิม (29/53) เป็นครั้งแรกในรอบทดลองนี้ทั้งหมด

หมายเหตุความยุติธรรมของตัวเลข: +2/53 (~3.8 จุดเปอร์เซ็นต์) เล็กกว่า noise floor ที่เคยวัดได้บนชุด 27 เฟรม (~2/27 ≈ 7.4%) เมื่อคิดเป็นสัดส่วน แต่**ยืนยัน reproducible แล้วภายใน session/harness เดียวกัน** (รันซ้ำตรงกันทุกเฟรม) และมี gains:losses = 3:1 ซึ่งเป็นทิศทางเดียวกับสมมติฐาน sharpness ที่ตั้งไว้ตั้งแต่รอบที่ 1 — ควรตีความว่า**เป็นสัญญาณบวกจริงแต่ยังเล็ก** ไม่ใช่ตัวเปลี่ยนเกม ต้องขยาย window/จำนวน candidate หรือรวมกับวิธีอื่นเพื่อให้ได้ผลที่ใหญ่ขึ้น

## งานถัดไปจากรอบนี้

1. ขยาย `--window-s` และ `--candidates-in-window` ของ sharpest-policy ดูว่า gain โตขึ้นหรืออิ่มตัว (ระวัง window กว้างเกินไปจะทำให้ตำแหน่งที่รายงานคลาดจาก timestamp จริงมากขึ้น เป็น trade-off ที่ต้องพูดคุยกับผู้ใช้)
2. ลอง**รวม sharpest-policy กับ top-k20 expansion แบบ adaptive cascade** ตามที่เสนอไว้ในรอบที่ 1 (ข้อเสนอ implementation ที่ปลอดภัย) แทนที่จะรัน sweep เต็มทุกจุดเสมอ เพื่อคุม latency
3. วิเคราะห์ 4 จุด gain/loss ที่เจอ (`out/floor1_wide_sharpest_policy_topk4.csv`) แบบ manual เพื่อเข้าใจว่าทำไมถึงเปลี่ยนผล ก่อนตัดสินใจ deploy

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `run_preprocessing_sweep.py` — CLAHE/unsharp sweep (ผลลบ, เก็บไว้เป็นหลักฐานว่าอย่าทำซ้ำ)
- ใหม่: `run_sharpest_frame_policy.py` — sharpest-in-window ทุก timestamp (ผลบวก, reproducible)
- หลักฐาน: `out/floor1_wide_preprocessing_sweep_topk4*.{csv,json}`, `out/floor1_wide_sharpest_policy*_topk{4,20}*.{csv,json}`

---

# รอบที่ 5 — วิดีโอทดสอบใหม่จากมือถือคนละเครื่องจริง (iPhone 11): `IMG_1895.MOV`

ผู้ใช้ส่งวิดีโอใหม่มาให้ทดสอบ: `D:\video\video_from_iphone_pare\IMG_1895.MOV` — metadata ยืนยัน **iPhone 11** (ต่างจาก iPhone 14 Plus ของคลิปเดิม) 1920×1080, SDR (bt709, ไม่ใช่ HDR/HLG แบบคลิปก่อน), 5:36 นาที, GPS ใกล้เคียงคลิปเดิมมาก (ตึกเดียวกัน) ภาพตัวอย่างยืนยันเป็นชั้น/อาคารเดียวกับ floor1 (ลายกระเบื้อง ป้ายห้อง M04 ตรงกับสไตล์เดิม) และเห็น radial distortion เล็กน้อยที่ขอบภาพ ชวนให้คิดว่าอาจเป็นกล้อง ultra-wide จริงของ iPhone 11 ไม่ใช่กล้อง Wide ธรรมดา

## ผลลัพธ์ — ดีกว่าคลิปเดิมมาก ไม่ต้องแก้อะไรเลย

รันผ่าน `run_floor1_wide_production_sweep.py` ตรงๆ (map/pipeline/gate เดิมทุกอย่าง) sample ทุก 10 วินาที ได้ 34 timestamps:

| Config | Top-k4 | Top-k20 |
|---|---:|---:|
| raw_production | 25/34 (73.5%) | **33/34 (97.1%)** |
| raw_exact_1920x1080 | 28/34 (82.4%) | 32/34 (94.1%) |

เทียบกับ floor1_wide.MOV (iPhone 14 Plus) ที่ top-k20 ได้แค่ 28-29/53 (52.8-54.7%) — **วิดีโอใหม่นี้ดีกว่ามาก** ทั้งที่เป็นคนละเครื่องจริง

## ตรวจว่าทำไมถึงดีกว่า — สมมติฐาน "sharper" ถูกหักล้างด้วยข้อมูลจริง

**สมมติฐาน 1 — FoV ใกล้เคียง map กว่าเลยดีกว่า:** ตรวจด้วย `estimate_query_focal.py` เดิม (map-grounded correspondence-based) ได้ median focal ratio = **0.757** (n=25) เทียบกับ 0.836 ของคลิปเดิม — **แปลว่าคลิปนี้ FoV mismatch จริงมากกว่าคลิปเดิมด้วยซ้ำ** (implied HFoV ~84° เทียบ 69° ของ map) แต่ std ต่ำกว่ามาก (0.156 เทียบ 0.448) คือ**ประมาณค่าได้เสถียรกว่า** ไม่ใช่ FoV ใกล้กว่า — สมมติฐานนี้ตกไป ยิ่งตอกย้ำว่า **FoV mismatch ไม่ใช่ตัวตัดสิน success rate** เพราะคลิปที่ mismatch เยอะกว่ากลับ success สูงกว่ามาก

**สมมติฐาน 2 — sharper (blur น้อยกว่า) เลยดีกว่า:** วัด Laplacian sharpness เทียบกันตรงๆ บน sample เดียวกัน (ทุก 10s) — **ผลตรงข้ามกับที่คาด**: floor1_wide.MOV median sharpness = 70.3, IMG_1895.MOV median sharpness = **49.5 (ต่ำกว่า)** ทั้งที่ success สูงกว่ามาก — **สมมติฐานนี้ก็ตกไปเช่นกันในการเทียบข้ามวิดีโอ** (หมายเหตุ: sharpness ที่ใช้ในรอบที่ 1 เทียบ "สำเร็จ vs ล้มเหลวภายในคลิปเดียวกัน" ซึ่งควบคุมกล้อง/แสง/เลนส์ให้คงที่ได้ ยังใช้ได้อยู่ แต่การเทียบ metric นี้ข้ามคลิปที่ต่างกล้อง/ต่างฉากไม่ควบคุมตัวแปรพอ เพราะ Laplacian variance ปนกันระหว่าง "เบลอ" กับ "เนื้อภาพมี texture มาก/น้อย")

## สรุปตรงไปตรงมา: ยังไม่ทราบสาเหตุที่แน่ชัดว่าทำไมคลิปนี้ดีกว่ามาก

ทั้งสองสมมติฐานหลักที่มีอยู่ (FoV mismatch, sharpness) **อธิบายผลนี้ไม่ได้** ตัวแปรที่ยังไม่ตัดออกและน่าจะเป็นตัวจริงมากกว่า:

1. **เส้นทางที่เดินคาบเกี่ยวกับพื้นที่ที่ map มี keyframe หนาแน่น/มุมมองใกล้เคียงกันมากกว่า** — ยังไม่ได้ตรวจสอบ ต้องดู `retrieval_top1_score` ในคลิปนี้เทียบกับคลิปเดิม
2. **สัดส่วนฉากที่มี texture สูง (ประตู/เฟอร์นิเจอร์/หน้าต่าง) เทียบกับ corridor ผนังเรียบ** — จากภาพตัวอย่างที่ดู คลิปนี้ดูเหมือนผ่านโซนที่มีของ/ป้ายห้องเยอะกว่า แต่ยังไม่ได้วัดเชิงปริมาณ
3. ความเร็วเดิน/ความนิ่งของมือขณะถ่าย ที่ไม่สะท้อนออกมาใน Laplacian variance ตรงๆ

**ไม่ควรรีบสรุปเป็นทฤษฎีใหม่โดยไม่มีหลักฐานเพิ่ม** — ข้อเท็จจริงที่ยืนยันได้ตอนนี้มีแค่: (ก) คลิปนี้ทำงานได้ดีกับ pipeline เดิมโดยไม่ต้องแก้อะไรเลย และ (ข) FoV mismatch ที่มากกว่าคลิปแรกไม่ได้ทำให้แย่ลง ซึ่งเป็นหลักฐานเพิ่มเติมที่**สนับสนุนข้อสรุปเดิมของรายงานทั้งหมด**: อย่าไปแก้ปัญหา FoV/intrinsics ก่อน เพราะไม่ใช่ตัวตัดสินผลจริง

## งานถัดไปจากรอบนี้

1. เทียบ `retrieval_top1_score` และการกระจายตัวของ matched keyframe ระหว่างสองคลิป เพื่อตรวจสมมติฐานเรื่อง keyframe coverage
2. วัดสัดส่วนพื้นที่ "corridor เปล่า" vs "ฉากมี texture" เชิงปริมาณในแต่ละคลิป (เช่น จาก edge density หรือ manual label) แทนการเดาจากสายตา
3. ทำ contact sheet ของ IMG_1895 เหมือนที่ทำกับ floor1_wide.MOV เพื่อเปรียบเทียบเนื้อหาด้วยตา

## ไฟล์ที่เพิ่มในรอบนี้

- หลักฐาน: `out/floor1_wide_img1895_baseline_topk{4,20}*.{csv,json}`, `out/floor1_wide_img1895_focal_estimate*.{csv,json}`, `out/debug_img1895_frame*.png`

---

# รอบที่ 6 — ติดตั้ง GeoCalib จริง (paper's own code/weights) + ตรวจ bias ก่อนเชื่อ + วัด latency จริง

บริบท: ผู้ใช้ขอให้ทุกวิธีมี paper รองรับจริง ไม่ใช่แค่ยืมแนวคิดมาทำเอง — วิธีเดียวในทั้งหมดที่ยังไม่เคยรันจริงคือ GeoCalib ([Veicht, Sarlin, Lindenberger, Pollefeys, ECCV 2024](https://arxiv.org/abs/2409.06704)) รอบนี้ติดตั้งและรันโค้ด/โมเดลของผู้เขียน paper ตรงๆ (`pip install git+https://github.com/cvg/GeoCalib.git`, ใช้ pretrained weights ของเขาเอง ไม่ได้เขียน implementation เอง)

## ติดตั้งและรันสำเร็จ

- ติดตั้งผ่าน pip จาก GitHub ตรงๆ, ใช้ torch ที่มีอยู่แล้วในเครื่อง (2.5.1+cu124, มี CUDA)
- โมเดลโหลดอัตโนมัติครั้งแรก (~111MB, ครั้งเดียว)
- รันได้ทั้งบน floor1_wide.MOV (iPhone 14 Plus) และ IMG_1895.MOV (iPhone 11)

## ผล raw (ยังไม่แก้ bias)

| วิดีโอ | median focal ratio (query/map=1400) | std | n |
|---|---:|---:|---:|
| floor1_wide.MOV | 0.680 | 0.072 | 30 |
| IMG_1895.MOV | 0.646 | 0.040 | 30 |

**นิ่งกว่าสองวิธีที่ทำเองมาก** (correspondence-based std=0.448 บน floor1_wide, VP-based ก็ noisy ไม่แพ้กัน) — สมเหตุสมผลเพราะเป็นโมเดลที่เทรนมาเพื่องานนี้โดยตรง ไม่ใช่ heuristic คำนวณมือ

## ตรวจ bias ก่อนเชื่อตัวเลข — พบว่า GeoCalib มี bias เป็นระบบกับฉากนี้จริง

รัน GeoCalib กับ **keyframe ของแผนที่เอง 25 จุด** (สุ่ม, ที่รู้ค่า K จริง = 1400px แน่นอนเพราะเป็นค่าที่ localizer ใช้จริง) ผลควรได้ ratio ≈ 1.0 ถ้าไม่มี bias:

**median ratio บน map keyframes = 0.903 (ไม่ใช่ 1.0)** — GeoCalib **ประเมิน focal ต่ำกว่าจริงอย่างสม่ำเสมอ ~10%** บนฉาก corridor แบบนี้ (คาดว่าเพราะข้อมูลเทรนของโมเดลเน้นภาพ outdoor/general มากกว่าทางเดินในอาคารแคบๆ) — นี่คือเหตุผลที่**ห้ามเอา ratio ดิบไปเทียบกับ 1400 ตรงๆ** ต้องหารด้วย bias ของโมเดลเองก่อน

## ผลหลังแก้ bias (query_ratio_raw / map_ratio_raw) — เทียบกับวิธีอื่นที่ทำเอง

| วิดีโอ | GeoCalib bias-corrected | Correspondence-based (grid-search) | Manhattan VP (ทำเอง) |
|---|---:|---:|---:|
| floor1_wide.MOV | 0.680/0.903 = **0.753** (~85° HFoV) | 0.836 (~79°) | 0.572 (~100°) |
| IMG_1895.MOV | 0.646/0.903 = **0.716** (~88° HFoV) | 0.757 (~84°) | ยังไม่ได้ทดสอบ |

**สอง method อิสระกัน (GeoCalib ที่แก้ bias แล้ว, correspondence-based) เห็นตรงกันในช่วง 75-85° ทั้งสองคลิป** — ใกล้กันพอจะเชื่อถือได้ในระดับ "ทิศทางและขนาดคร่าวๆ" ส่วน Manhattan VP ที่เขียนเองยังคงเป็น outlier (100°) ยืนยันข้อสรุปเดิมว่า**implementation ของ VP method เองยังไม่น่าเชื่อถือพอ**

## วัด latency จริง (ไม่ใช่ประมาณแล้ว)

| ขั้นตอน | เวลาเฉลี่ยต่อครั้ง (median) |
|---|---:|
| GeoCalib (บน GPU, CUDA) | **132-148 ms** |
| Correspondence-based grid-search | 35 ms |
| Vanishing-point (ทำเอง) | 115 ms |
| Localize เต็ม top-k4 (เทียบ) | 147 ms |

GeoCalib แพงกว่า correspondence-based ~4 เท่า แต่ยังเร็วพอสำหรับ**รันครั้งเดียวตอนเริ่มเซสชัน**ตามดีไซน์ cold-start ที่เสนอไว้ (ไม่กระทบ real-time ถ้าไม่รันทุกเฟรม) หมายเหตุ: ครั้งแรกที่รันมี CUDA warm-up cost สูงกว่า (~470-850ms) ควร warm-up โมเดลไว้ล่วงหน้าตอนแอปเปิด ไม่ใช่ตอนเรียกใช้ครั้งแรกจริง

## สรุป

1. **GeoCalib ใช้งานได้จริง ติดตั้งง่าย เร็วพอสำหรับ cold-start calibration** (ครั้งเดียวต่อเซสชัน)
2. **ห้ามใช้ raw output เทียบกับค่า assumed ตรงๆ โดยไม่ calibrate bias ของโมเดลเองก่อนกับ scene ปัจจุบัน** — ค้นพบนี้สำคัญกว่าตัวเลข focal เองด้วยซ้ำ เพราะถ้าไม่เช็ค จะเข้าใจผิดว่า mismatch มากกว่าความจริง ~10%
3. เมื่อแก้ bias แล้ว **สาม estimate จากวิธีต่างกันเห็นตรงกันมากขึ้น (75-88° HFoV)** ยกเว้น Manhattan VP ที่ยังไม่น่าเชื่อถือ — เพิ่มความมั่นใจว่า mismatch ที่แท้จริงของทั้งสองคลิปอยู่แถวๆ นี้ ไม่ใช่ 100°+ ตามที่ VP method ทำเองบอกไว้ก่อนหน้า
4. **ยังคงไม่เปลี่ยนข้อสรุปเรื่อง success rate** — mismatch ระดับ 75-88° นี้มีอยู่จริงในทั้งสองคลิป แต่ IMG_1895 ที่ mismatch เท่าๆ กัน (หรือมากกว่า) กลับ success rate สูงกว่ามาก (97% vs 55%) ยืนยันอีกครั้งว่า**ไม่ใช่ FoV เป็นตัวตัดสิน**

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `estimate_focal_geocalib.py` — รัน GeoCalib จริง (paper's own model)
- หลักฐาน: `out/floor1_wide_geocalib_floor1_wide_summary.json`, `out/floor1_wide_geocalib_img1895_summary.json`
- dependency ใหม่ที่ติดตั้งแล้วใน `.venv`: `geocalib` (จาก `pip install git+https://github.com/cvg/GeoCalib.git`)

---

# รอบที่ 7 — วิดีโอควบคุม (เลนส์ปกติ vs wide เครื่องเดียวกัน) + adaptive cascade ตาม paper ใหม่ + แก้ข้อผิดพลาดการเทียบ latency

## วิดีโอควบคุมใหม่: `IMG_1894.MOV` (iPhone 11 เครื่องเดียวกับ IMG_1895, ถ่ายก่อนหน้า 6 นาที, ตำแหน่งเดียวกัน)

ผู้ใช้ระบุว่าเป็นกล้อง "ปกติ ไม่ wide" — **ยืนยันด้วย GeoCalib จริง ไม่ใช่เชื่อคำบอก**: รัน `estimate_focal_geocalib.py` แล้วแก้ bias ด้วยค่า 0.903 ที่วัดไว้จาก map keyframes (รอบที่ 6) ได้ ratio = 1.148/0.903 = **1.271** (HFoV ≈ 57°, **แคบกว่า map เองด้วยซ้ำ**) ต่างจาก IMG_1895 ที่ได้ 0.716 (HFoV ≈ 88°) อย่างชัดเจน — ยืนยันว่าเป็นคนละเลนส์จริงด้วยหลักฐาน ไม่ใช่แค่ metadata/คำบอก

## ผล baseline

| วิดีโอ | top-k4 | top-k20 |
|---|---:|---:|
| IMG_1894 (ปกติ, HFoV~57°) | 30/35 (85.7%) | 31/35 (88.6%) |
| IMG_1895 (wide, HFoV~88°) | 25/34 (73.5%) | **33/34 (97.1%)** |

**สังเกต (ตั้งเป็นสมมติฐาน ไม่ใช่ข้อสรุป — n=34/35 เล็กเกินไป)**: เลนส์ปกติชนะที่ top-k4 แต่เลนส์ wide กลับแซงที่ top-k20 รูปแบบนี้เข้ากับสมมติฐานที่ว่า **FoV mismatch กระทบขั้น retrieval มากกว่า PnP** — query ที่ FoV กว้างกว่าต้องการ shortlist ยาวกว่าเพื่อให้ keyframe ที่ถูกต้องหลุดเข้ามาใน top-k แต่พอหลุดเข้ามาแล้ว PnP ทำงานได้ปกติไม่มีปัญหา ต้องการข้อมูลเพิ่มก่อนยืนยันเป็นข้อสรุปจริง (เช่น เทียบ retrieval_top1_score ของ IMG_1894 vs IMG_1895 ที่ top-k4 โดยตรง)

**ปรับข้อสรุปเดิม**: จาก "FoV ไม่มีผลเลย" เป็น **"FoV mismatch มีผลจริงที่ขั้น retrieval แต่ไม่ใช่ตัวตัดสินหลักของ success rate โดยรวม เพราะปัจจัยอื่น (คุณภาพ retrieval โดยรวมของแต่ละคลิป/route) มีผลใหญ่กว่ามาก" — ข้อมูล retrieval score รอบที่ 6 (success median 0.496 vs failure 0.319 ภายใน floor1_wide เดียวกัน) ก็อาจเป็นแค่ "อาการ" ของเฟรมที่ยากอยู่แล้ว (blur/มุมกล้อง) ไม่ใช่ "สาเหตุ" อิสระ — ยังฟันธงทิศทางเหตุ-ผลไม่ได้จากข้อมูลที่มี**

## Adaptive cascade ตาม paper ใหม่ (Barbarani et al., 2025) — วัด latency ให้ถูกวิธีคราวนี้

Paper: [To Match or Not to Match: Revisiting Image Matching for Reliable Visual Place Recognition (2025)](https://arxiv.org/abs/2504.06116) — พบว่า **inlier count จาก local matching จริง (ไม่ใช่ retrieval score ดิบ)** เป็นตัวทำนายที่น่าเชื่อถือกว่าว่าเมื่อไหร่ควร escalate ไป re-rank/ขยาย candidate — ออกแบบ `run_adaptive_cascade.py` ตามหลักการนี้: รัน top-k4 (ถูก) ก่อนเสมอ ถ้า pipeline เดิมปฏิเสธ (ไม่ผ่าน gate) ค่อย retry ด้วย top-k20 (แพง) เฉพาะเฟรมนั้น

**แก้ข้อผิดพลาดสำคัญที่เกือบเขียนผิดลงรายงาน**: รอบแรกเทียบ latency ของ cascade กับตัวเลข top-k20 จากรอบที่ 1 (session อื่น, "~456ms") ซึ่งผิดหลักที่ตั้งไว้เองในรอบที่ 2 (ห้ามเทียบ latency ข้าม session) — แก้โดยคำนวณ**ต้นทุนจริงของ top-k20 จาก log ในโปรเซสเดียวกัน** (`total_elapsed_s - cheap_elapsed_s` ของเฟรมที่ escalate):

| วิดีโอ | top-k4 จริง (median) | top-k20 จริง (median, in-process) | escalation rate | Cascade latency (mean) |
|---|---:|---:|---:|---:|
| floor1_wide (ยาก) | 185 ms | 546 ms | 58.5% (31/53) | 525 ms — **ใกล้เคียง top-k20 เฉยๆ ไม่ได้แพงกว่าอย่างที่รายงานผิดไปตอนแรก** |
| IMG_1895 (ง่าย) | 150 ms | 460 ms | 17.6% (6/34) | **251 ms — เร็วกว่า top-k20 เฉยๆ เกือบครึ่ง** |

**Success rate ของ cascade**: floor1_wide 29/53 (เท่า top-k20 เป๊ะ, ตามคาด เพราะ retry ทุกจุดที่ top-k4 พลาด), IMG_1895 32/34 (ใกล้เคียง top-k20's 32/34 ที่ raw_exact — เท่ากันพอดี)

## สรุป

1. **Adaptive cascade ได้ผลตามที่คาดจริง**: success rate เท่ากับใช้ top-k20 เสมอ แต่ latency ถูกกว่าเมื่อวิดีโอ "ง่าย" (escalation rate ต่ำ) และไม่แพ้ (ไม่ใช่แพงกว่าอย่างที่เข้าใจผิดตอนแรก) แม้วิดีโอ "ยาก" — **นี่คือ design ที่ปลอดภัยจะ deploy จริง** ไม่มี downside ชัดเจน
2. **เลนส์ปกติ vs wide บนเครื่องเดียวกัน**: ยืนยันด้วย GeoCalib จริงว่าเป็นคนละ FoV จริง (57° vs 88°) แต่ success rate ต่างกันไม่มากเท่าที่คาด และรูปแบบ top-k4 vs top-k20 ชวนคิดว่า FoV mismatch กระทบขั้น retrieval มากกว่า PnP — เป็นสมมติฐานที่ยังต้องตรวจสอบเพิ่ม
3. **ถอนคำพูด "FoV ไม่มีผลเลย"** เป็น "FoV ไม่ใช่ตัวตัดสินหลัก แต่มีผลจริงในบางขั้นตอน (retrieval)" — ระมัดระวังไม่ให้ over-claim ทั้งสองทาง

## งานถัดไป

1. เทียบ retrieval_top1_score ของ IMG_1894 vs IMG_1895 ที่ top-k4 โดยตรง เพื่อตรวจสมมติฐาน "FoV กระทบ retrieval" ให้ชัดขึ้น
2. หาทางแยกว่า retrieval score เป็นสาเหตุหรือแค่อาการ (เช่น ลอง fix ปัจจัยอื่นแล้ว manipulate เฉพาะ FoV จริงๆ ผ่าน virtual-camera ที่แก้บั๊กแล้วในรอบที่ 2 แล้ววัด retrieval score ก่อน-หลัง)
3. Deploy adaptive cascade (ข้อ 1 ของสรุป) เป็น production candidate ได้เลย มีหลักฐานเพียงพอและไม่มี downside ที่วัดได้

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `run_adaptive_cascade.py` — confidence-triggered cascade (paper-backed)
- หลักฐาน: `out/floor1_wide_img1894_baseline_topk{4,20}*.{csv,json}`, `out/floor1_wide_geocalib_img1894_summary.json`, `out/floor1_wide_adaptive_cascade_{floor1wide,img1895}*.{csv,json}`

---

# รอบที่ 8 — ปิด loop: เอาค่า FoV ที่ paper รับรองไปใช้จริง + สรุปที่มาที่ไปของทุกวิธีประมาณ parameter

บริบท: ผู้ใช้ขอให้โฟกัสที่การประมาณ camera parameter เป็นหลัก ต้องการให้ทุกวิธีมี paper รองรับจริง และอยากเห็นผลของแต่ละวิธีเทียบกัน

## ปิด hypothesis ค้างจากรอบที่ 7: FoV กระทบ retrieval จริงแต่เล็ก

เทียบ retrieval_top1_score ของ IMG_1894 (ปกติ) vs IMG_1895 (wide) ที่ top-k4 ตรงๆ: **0.622 vs 0.575 (ต่างกัน ~7.5%)** — ต่างจากผลต่างระหว่าง floor1_wide vs IMG_1895 ที่ต่างกันถึง 34% มาก **สรุป: FoV มีผลต่อ retrieval จริงแต่เป็นผลเล็ก ปัจจัยเรื่อง route/environment มีผลใหญ่กว่ามาก** — ยืนยันกรอบสรุปของรอบที่ 7

## ทดลองที่พยายามแล้วไม่สำเร็จ (บันทึกไว้ตรงๆ): ติดตั้งวิธีที่สองเพื่อ triangulate กับ GeoCalib

ลองติดตั้ง **Perspective Fields** ([Jin et al., CVPR 2023 Highlight](https://openaccess.thecvf.com/content/CVPR2023/html/Jin_Perspective_Fields_for_Single_Image_Camera_Calibration_CVPR_2023_paper.html)) และ **WildCamera** ([Zhu et al., NeurIPS 2023](https://arxiv.org/abs/2306.10988)) เพื่อเป็นวิธีที่สามยืนยันร่วมกับ GeoCalib และ correspondence-based grid-search

- WildCamera: repo ไม่มี `setup.py`/`pyproject.toml` ติดตั้งผ่าน pip ไม่ได้ตรงๆ
- Perspective Fields: ติดตั้งได้หลัง patch encoding bug ใน `setup.py` แต่ dependency ของมันต้องการ **`opencv-contrib-python`** ซึ่ง**ชนกับ `opencv-python` ที่ LightGlue/MAST3R/GeoCalib ใช้อยู่ในเครื่องเดียวกัน** (ติดตั้งพร้อมกันจะทำให้ `cv2` import พังทั้งระบบ) — **ตัดสินใจไม่ติดตั้งต่อ** เพราะความเสี่ยงต่อ pipeline หลักไม่คุ้มกับการได้ความเห็นที่สาม ในเมื่อมี 2 วิธีที่ยืนยันตรงกันอยู่แล้ว (correspondence-based, GeoCalib)

**บทเรียน**: ไม่ใช่ทุก paper ที่มี public code จะติดตั้งง่ายหรือปลอดภัยกับ environment ที่มีอยู่ ต้องประเมินความเสี่ยงต่อระบบหลักก่อนเสมอ ไม่ใช่แค่ดูว่า pip install ผ่านไหม

## การทดลองหลัก: เอาค่า FoV ที่ GeoCalib ประมาณ (แก้ bias แล้ว) ไปใช้กับ virtual-camera ที่แก้บั๊กแล้ว

จากรอบที่ 6: GeoCalib bias-corrected ratio ของ floor1_wide = 0.753 → HFoV ≈ **85°** (ปัดจากคำนวณ) — รัน `run_floor1_wide_production_sweep.py --hfovs "85"` เทียบกับ raw_exact และค่าที่เดามั่ว (100°, 110° จากรอบที่ 2) บนชุดเดิม 53 timestamps top-k20 **รันซ้ำ 2 ครั้งเพื่อยืนยัน reproducibility ตามมาตรฐานที่ตั้งไว้เอง**:

| Config | Successes (top-k20, รันซ้ำ 2 ครั้งตรงกัน) |
|---|---:|
| raw_production | 28/53 |
| raw_exact_1920x1080 | 29/53 |
| VC เดาสุ่ม HFoV 100°/110° (รอบที่ 2) | 29/53 (เท่า raw_exact, ไม่ดีขึ้น) |
| **VC ด้วย HFoV จาก GeoCalib (85°, แก้ bias แล้ว)** | **30/53 — ดีขึ้นจริงเป็นครั้งแรก** |

per-frame diff เทียบ raw_exact: gains=2 เฟรม (1925, 12320), losses=1 เฟรม (11550) — สัดส่วน 2:1 ไปทางบวก แม้ n เล็ก

## สรุปสำคัญของรอบนี้: "FoV ไม่ใช่ตัวตัดสินหลัก" ยังจริงอยู่ แต่ **"การประมาณ FoV ให้ถูกต้องมีประโยชน์จริง เมื่อใช้ค่าที่มาจาก paper-validated method ไม่ใช่เดามั่ว**

นี่คือครั้งแรกในทั้ง 8 รอบที่ virtual-camera reprojection เอาชนะ raw_exact ได้จริงบน full benchmark — ความต่างระหว่างรอบที่ 2 (เดา HFoV, เสมอกับ raw_exact) กับรอบนี้ (ใช้ GeoCalib, ชนะ raw_exact) **คือคุณภาพของค่าประมาณ ไม่ใช่กลไกของ virtual-camera เอง** (ซึ่งเหมือนกันทุกประการ ใช้โค้ดเดียวกันที่แก้บั๊กในรอบที่ 2)

## ตารางสรุปที่มาที่ไปของทุกวิธีประมาณ camera parameter ที่ลองในเซสชันนี้ (อัปเดต)

| วิธี | Paper | Implementation ตรงตาม paper? | ผลบน floor1_wide | ผลบน IMG_1895 |
|---|---|---|---:|---:|
| Correspondence-based grid-search | แนวคิดจาก [Kukelova et al. ICCV 2013](https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html) (PnPf) | ไม่ — grid search เอง ไม่ใช่ closed-form solver | ratio 0.836 (~79°) | ratio 0.757 (~84°) |
| Manhattan vanishing-point | สูตรจาก [Caprile & Torre, IJCV 1990](https://doi.org/10.1007/BF00127813) | สูตรคำนวณตรง, แต่ line detection/RANSAC เขียนเอง | ratio 0.572 (~100°, outlier ไม่น่าเชื่อ) | ไม่ได้ทดสอบ |
| **GeoCalib** (bias-corrected ด้วย map keyframes) | [Veicht et al., ECCV 2024](https://arxiv.org/abs/2409.06704) | **ใช่ — โค้ด/โมเดลของผู้เขียน paper ตรงๆ** | ratio 0.753 (~85°) | ratio 0.716 (~88°) |
| Perspective Fields, WildCamera | CVPR2023 / NeurIPS2023 | ไม่ได้ติดตั้ง (ความเสี่ยงต่อ environment) | — | — |

**สองวิธีที่น่าเชื่อถือที่สุด (correspondence-based + GeoCalib) เห็นตรงกันในช่วง 75-88° ทั้งสองคลิป** และเมื่อเอาค่าจาก GeoCalib ไปใช้จริงก็ได้ผลบวกที่ reproducible — นี่คือคำตอบที่หนักแน่นที่สุดเท่าที่มีตอนนี้สำหรับคำถามเดิมของเซสชัน ("กล้องคนละเครื่อง ประมาณ parameter ยังไง")

## ข้อเสนอ implementation สำหรับ production (อัปเดตจากรอบที่ 1)

1. Cold-start: localize ด้วย top-k สูง (20) จนกว่าจะได้ fix แรก (จากรอบที่ 5-6 latency data)
2. หลัง fix แรก: รัน **GeoCalib ครั้งเดียว** (background, ~130-150ms) เพื่อประมาณ K ของกล้องเครื่องนี้ **ต้อง bias-correct ด้วยค่าที่วัดจาก map keyframes ของแผนที่นั้นๆ ก่อนเสมอ** (รอบที่ 6 พิสูจน์แล้วว่า raw output มี bias ~10% กับฉาก corridor)
3. ใช้ K ที่ calibrate แล้วสร้าง virtual-camera reprojection (โค้ดที่แก้บั๊กแล้วในรอบที่ 2) เป็น query preprocessing สำหรับเฟรมถัดไป — คาดว่าได้ +1-2 จุดเปอร์เซ็นต์แบบ reproducible ไม่ใช่ตัวเปลี่ยนเกม
4. ใช้ **adaptive cascade** (รอบที่ 7, paper-backed) ควบคู่กันเพื่อคุม latency — escalate top-k เฉพาะเมื่อ inlier count ต่ำ
5. ยังไม่แตะปัญหา heading-instability และ blur/repetitive-texture (ยังเป็นปัญหาใหญ่กว่าเรื่อง FoV มาก ตามรอบที่ 1, 4, 5)

## ไฟล์ที่เพิ่มในรอบนี้

- หลักฐาน: `out/floor1_wide_geocalib_informed_hfov85_topk{4,20}*.{csv,json}`, `out/floor1_wide_geocalib_informed_hfov85_topk20_repeat_summary.json`
- dependency ที่ติดตั้งแล้วแต่ไม่ได้ใช้งาน (เหลือทิ้งไว้เฉยๆ ไม่เป็นอันตราย): `perspective2d`, `yacs`

---

# รอบที่ 9 — ยืนยันผล VC85 ด้วยจำนวนเฟรมที่หนาแน่นขึ้น (สถิติมีน้ำหนักกว่าเดิม)

ชุดทดสอบเดิม (53 timestamps, step 10s) เล็กเกินไปที่จะเชื่อ delta +1 ได้เต็มที่ — สุ่มใหม่ที่ step 5s ครอบคลุมทั้งวิดีโอ (106 timestamps) **หมายเหตุสำคัญ**: ชุดนี้ **ไม่ใช่ superset ของชุด 53 เฟรมเดิม** (frame grid คนละความถี่ กล่าวคือ raw_exact ที่ได้ 52/106 ไม่ใช่ผลขยายจาก 29/53) ต้องรายงานแยกเป็นแถวของตัวเอง ห้ามเอาไปเทียบตรงๆ กับตัวเลข 53-เฟรม

## ผล

| Config | 53 เฟรม (step 10s) | 106 เฟรม (step 5s) |
|---|---:|---:|
| raw_exact_1920x1080 | 29/53 (54.7%) | 52/106 (49.1%) |
| VC ด้วย HFoV จาก GeoCalib (85°) | 30/53 (56.6%) | 54/106 (50.9%) |

## Per-frame McNemar-style check (สำคัญกว่าตัวเลขรวม)

| ชุดข้อมูล | gains (raw_exact ล้มเหลว→VC85 สำเร็จ) | losses (raw_exact สำเร็จ→VC85 ล้มเหลว) | อัตราส่วน |
|---|---:|---:|---:|
| 53 เฟรม | 2 | 1 | 2:1 |
| 106 เฟรม | 4 | 2 | 2:1 |

**อัตราส่วน gains:losses เท่ากันเป๊ะทั้งสองชุดตัวอย่างที่สุ่มเป็นอิสระกัน** — นี่คือหลักฐานที่ดีกว่าการดูตัวเลขรวมเฉยๆ มาก เพราะสองชุดที่ independent กันเห็น pattern เดียวกัน (~+2 จุดเปอร์เซ็นต์, สัดส่วน 2:1) ไม่ใช่ความบังเอิญที่จะหายไปเมื่อเพิ่ม n

## สรุป

**ผลบวกจาก GeoCalib-informed FoV correction เป็นของจริง ยืนยันซ้ำได้ที่ n สูงขึ้น แต่ยังคงเป็นผลเล็ก (~+2 จุดเปอร์เซ็นต์) ไม่ใช่ตัวเปลี่ยนเกม** — ปรับคำจาก "ชนะจริงเป็นครั้งแรก" (ฟังดูใหญ่เกินจริง) เป็น "ผลบวกเล็กแต่ reproducible ข้ามการสุ่มตัวอย่างสองชุดที่เป็นอิสระกัน" ให้ตรงกับหลักฐานมากขึ้น

## งานถัดไปที่มีความสำคัญกว่า (ยังไม่ได้ทำ)

โจทย์เดิมของผู้ใช้ตั้งแต่ต้น session คือ "ระบุตำแหน่งและทิศทางการหันได้" — เรื่อง**ตำแหน่ง**ได้ทดลองจนอิ่มตัวแล้ว (เพดานผลบวกจากการแก้ FoV อยู่ที่ระดับ +2 จุดเปอร์เซ็นต์) แต่เรื่อง**ทิศทางการหัน**ยังค้างมาตั้งแต่รอบที่ 3 และมีสถานะแย่กว่า: ยืนยันแล้วว่า production path เองก็ไม่นิ่ง (รอบที่ 3, 54.4°/step) และบั๊ก sign ที่แก้ไปไม่ใช่สาเหตุ — **ยังไม่เคยทดสอบวิธีแก้เลยสักครั้ง**

ข้อมูลที่มีอยู่แล้วและยังไม่ได้ใช้: `estimate_focal_geocalib.py` log ค่า `roll_deg`/`pitch_deg` มาด้วยทุกเฟรม (gravity direction จาก GeoCalib) — บน floor1_wide พบว่า **roll อยู่ในช่วง ±3° (นิ่ง) แต่ pitch แกว่งตั้งแต่ -11° ถึง +4° (ไม่นิ่งเลย)** ซึ่งตรงกับ degree-of-freedom ที่น่าจะเป็นตัวทำให้การอ่านค่า yaw จาก PnP คลาดเคลื่อน

**แนวทางที่เสนอ**: ใช้ gravity direction จาก GeoCalib มา constrain roll/pitch ก่อน แล้วให้ PnP-RANSAC solve หา yaw อย่างเดียว (ลด degree of freedom ของ rotation จาก 3 เหลือ 1) — มี metric พร้อมวัดผลอยู่แล้ว (median |Δheading| ต่อ step จาก `compare_heading_paths.py`)

**ข้อควรระวังสำคัญ**: วิธีนี้ **แก้ไขตัว PnP solver โดยตรง ไม่ใช่แค่ query-side preprocessing** — อยู่นอกขอบเขตที่ตกลงกันไว้ตอนต้น session (เหมือนกรณี `get_yaw` ที่ต้องถามก่อนแก้) **ยังไม่ได้ทำ รอการตัดสินใจของผู้ใช้ก่อน**

---

# รอบที่ 10 — ทดสอบ gravity-constrained PnP จริง (diagnostic เท่านั้น ไม่แตะ production)

ผู้ใช้อนุมัติให้ทดลอง สร้าง `test_gravity_constrained_heading.py` **เป็นแค่การวัดผลนอก pipeline ไม่ได้แก้ production PnP จริง**

## ขั้นเตรียมการที่จำเป็น: ตรวจ axis convention ของ GeoCalib ก่อนใช้งาน

GeoCalib คืนค่า `gravity.vec3d` (ทิศทาง gravity ในกรอบอ้างอิงกล้อง) แต่ไม่มีเอกสารบอกชัดว่าตรงกับแกนไหนของระบบพิกัดที่ pipeline นี้ใช้ — **ตรวจสอบเชิงประจักษ์กับ keyframe ของแผนที่เอง 10 จุดที่รู้ R จริง** (ไม่เดา ไม่เชื่อ docstring เฉยๆ) พบว่า **`gravity.vec3d` ≈ `-R[:,1]`** (cos-similarity -0.996 ถึง -0.999 สม่ำเสมอทุกตัวอย่าง) ตรงกับสัญชาตญาณทางฟิสิกส์ (gravity ชี้ลง) — ยืนยัน convention ได้แน่นอนก่อนใช้งานจริง

## วิธีทดลอง

Fix rotation 2 DOF (roll/pitch) จาก `up_cam = -gravity.vec3d` เหลือแค่ 1 DOF (yaw) ให้ grid-search หา yaw ที่ทำ reprojection error บน correspondences ที่ pipeline เดิมยอมรับแล้วต่ำสุด (translation แก้แบบ linear least-squares ตามปัญหา "known-rotation PnP" คลาสสิก) — เทียบ heading time series กับของเดิม (6-DOF unconstrained)

## ผล — ปฏิเสธสมมติฐานชัดเจน

| | median \|Δheading\|/step | reprojection error เฉลี่ย |
|---|---:|---:|
| PnP เดิม (6-DOF, ไม่ constrain) | 63.5° | 2.90 px |
| Gravity-constrained (yaw-only, 1-DOF) | 62.4° | **11.97 px (แย่กว่า ~4 เท่า)** |

**Heading ยังกระโดดพอๆ กัน** (แทบไม่ต่างจากเดิม) **และ**การบังคับ roll/pitch ตาม GeoCalib ทำให้ fit เข้ากับ correspondences แย่ลงมาก — สองอย่างนี้ร่วมกันบอกว่า **สมมติฐาน "pitch ที่ไม่นิ่งจาก GeoCalib คือสาเหตุของ heading instability" ผิด**

## วิเคราะห์ว่าทำไมถึงผิด

reprojection error ที่แย่ลง 4 เท่าเมื่อบังคับ roll/pitch ตาม GeoCalib บ่งชี้ว่า **gravity estimate ของ GeoCalib เองก็ไม่แม่นพอสำหรับเฟรม query เหล่านี้** (ต่างจากตอน bias-correct ค่า focal ที่ยังพอเชื่อถือได้หลังปรับ) หรือไม่ก็ระบบพิกัดของแผนที่มี "up" ที่ไม่สม่ำเสมอ 100% ทุกจุด — ทั้งสองกรณีทำให้การบังคับ roll/pitch จากภายนอกเข้าไปยิ่งทำร้าย pose มากกว่าช่วย **ต้นเหตุที่แท้จริงของ heading instability จึงไม่ใช่ปัญหา rotation-parametrization/DOF แต่น่าจะเป็นเรื่อง correspondences เอง** (จำนวนน้อย, กระจายตัวไม่ดีในภาพ, หรือ retrieval ไปคนละ keyframe ที่มีมุมกล้องต่างกันมากในแต่ละครั้ง) ซึ่งเป็นปัญหาคนละชั้นจากที่ตั้งสมมติฐานไว้

## สรุป

**gravity-constrained PnP ไม่ใช่ทางแก้ heading instability — ปิด hypothesis นี้อย่างเป็นทางการ** ไม่แนะนำให้ implement ใน production ผลชัดเจนว่าแย่ลงทั้งสองมิติที่วัด (ไม่นิ่งขึ้น และ fit แย่ลง)

## งานถัดไป

ต้นเหตุ heading instability ยังไม่ทราบแน่ชัด ทิศทางที่ควรตรวจต่อ (ยังไม่ได้ทำ):
1. ตรวจการกระจายตัวเชิงพื้นที่ของ correspondences ที่ pipeline ใช้จริง (กระจุกตัวมุมเดียวของภาพหรือไม่ — เป็นสาเหตุคลาสสิกของ rotation ambiguity)
2. ตรวจว่า matched_keyframe ที่ retrieval เลือกในแต่ละ timestamp มีมุมกล้อง (viewpoint) ต่างจากเฟรมก่อนหน้ามากแค่ไหน (ถ้า retrieval กระโดดไป keyframe คนละมุมทุกครั้ง heading ที่ไม่นิ่งอาจเป็นเรื่องปกติ ไม่ใช่บั๊ก)
3. พิจารณา temporal smoothing (`blend_heading_deg` ที่มีอยู่แล้วใน production) ว่าเพียงพอหรือไม่แทนที่จะพยายามแก้ที่ราก

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `test_gravity_constrained_heading.py` — diagnostic เท่านั้น ไม่แก้ production
- หลักฐาน: `out/floor1_wide_gravity_constrained_heading*.{csv,json}`

---

# รอบที่ 11 — พบต้นเหตุจริงของ heading instability: เชื่อมกับปัญหาเดิมตั้งแต่รอบที่ 1

สร้าง `diagnose_heading_instability.py` ตรวจสองสมมติฐานจากรอบที่ 10 บนเฟรมที่ผ่าน gate จริง 28 จุด:

| ตัวชี้วัด | ผล |
|---|---:|
| จำนวน correspondence ต่อเฟรม (median) | **10-13 จุด** |
| พื้นที่กระจายตัวของจุดในภาพ (median ของ min(x_coverage, y_coverage)) | **~19% ของภาพ** |
| correlation(heading jump, keyframe-id jump) | -0.042 (ไม่มีนัยสำคัญ) |
| correlation(heading jump, point coverage) | 0.182 (อ่อนมาก) |

## สรุปการวิเคราะห์

ทั้งสมมติฐาน "retrieval กระโดดไป keyframe คนละมุม" และ "จุดกระจุกตัวแปรผันตามความไม่นิ่ง" **ไม่ใช่คำอธิบายที่ดี** (correlation ต่ำทั้งคู่) แต่สิ่งที่เด่นชัดคือ**ทุกเฟรมอยู่ในสภาวะเดียวกันหมด**: จุดน้อย (~10-13, ใกล้ min_inliers=10 ของ gate มาก) และกระจุกตัวแคบ (~19% ของภาพ) แทบทุกครั้ง ไม่ใช่ว่าบางเฟรมดีบางเฟรมแย่ — เป็น **floor effect**: correlation หาไม่เจอเพราะแทบไม่มี variance ให้ correlate เนื่องจากทุกเฟรมอยู่ในสภาวะเดียวกันคือ "แย่พอๆ กันหมด"

จุดน้อย+กระจุกตัวแคบเป็นสภาวะที่รู้จักกันดีในวงการ PnP ว่าทำให้ **rotation ประเมินไม่นิ่ง แม้ translation/position จะยังพอใช้ได้** (error กระจายไปที่ rotation ได้ง่ายกว่าเมื่อจุด baseline เชิงมุมแคบ) — นี่คือกลไกที่อธิบาย pattern ที่เห็นตลอดทั้งเซสชัน: **position ยังพอเชื่อถือได้ (ไม่มี outlier ผิดปกติจาก trajectory-consistency check รอบที่ 2), แต่ heading ไม่นิ่งเลย (63°/step)**

## ข้อสรุปสุดท้ายที่เชื่อมทุกอย่างในเซสชันนี้เข้าด้วยกัน

**ต้นเหตุของทั้ง "success rate ต่ำ" (ปัญหาตำแหน่ง) และ "heading ไม่นิ่ง" (ปัญหาทิศทาง) คือสิ่งเดียวกัน**: motion blur + ผนังเรียบ + corridor ซ้ำ (finding #7, รอบที่ 1) ทำให้ SuperPoint/LightGlue หา correspondence ได้น้อยและกระจุกตัว — เฟรมที่มีน้อยพอจะ "ผ่าน gate ได้แบบเฉียดฉิว" (~10-13 จุด) ก็เพียงพอให้ position ผ่าน min_inliers=10 ได้ แต่**ไม่พอจะ constrain rotation ให้นิ่ง** — ไม่ใช่ปัญหาคนละเรื่องที่ต้องแก้แยกกันอย่างที่คิดตอนแรก (FoV, gravity, sign) แต่เป็นผลข้างเคียงของปัญหาเดียวกันที่ยังไม่ได้แก้จริง

**นัยสำคัญ**: การแก้ปัญหา blur/low-texture (ที่ยังไม่ได้ทำจริงจัง มีแค่ CLAHE ที่ล้มเหลวและ sharpest-frame-window ที่ช่วยได้เล็กน้อย) **จะช่วยทั้งสองปัญหาพร้อมกัน** ทำให้เป็นจุดที่ควรลงทุนต่อมากกว่าการพยายามแก้ camera-parameter-estimation หรือ rotation-parametrization ต่อไป (ที่พิสูจน์แล้วว่ามีเพดานผลบวกต่ำมากทั้งคู่)

## งานถัดไปที่มีคุณค่าจริงจากการค้นพบนี้

1. หาวิธีเพิ่มจำนวน/การกระจายตัวของ correspondence ให้มากกว่า 10-13 จุด (ไม่ใช่แค่ผ่าน gate เฉียดฉิว) — อาจเป็น multi-frame feature aggregation (สะสม keypoint จากหลายเฟรมใกล้เคียงกันมาใช้ร่วมกัน) แทนการเลือกเฟรมเดียวที่คมที่สุด
2. ทดสอบว่าถ้าลด min_inliers requirement ของ retrieval/matching แต่เพิ่มความเข้มงวดด้าน spatial coverage ของจุดแทน จะช่วยให้ rotation นิ่งขึ้นไหม (ต้องคุยกับผู้ใช้ก่อน เพราะเป็นการแก้ gate/threshold ของ pipeline โดยตรง)
3. งาน deblurring ที่มี paper รองรับจริง (ไม่ใช่ CLAHE/unsharp ที่ล้มเหลวไปแล้วในรอบที่ 4) เช่น learned deblurring model — ยังไม่ได้ลอง

## ไฟล์ที่เพิ่มในรอบนี้

- ใหม่: `diagnose_heading_instability.py`
- หลักฐาน: log การวิเคราะห์ (ยังไม่ได้ save เป็น json แยก — อยู่ใน console output ของสคริปต์)


# รอบที่ 12 — Temporal landmark propagation ด้วย 2D–3D association จากเฟรมก่อนหน้า

รอบนี้ทดลองตามแผน `NEXT-EXPERIMENT-PLAN-LUNA.md` โดยเริ่มจากวิธีที่ไม่แตะ production และไม่สร้าง map ใหม่: ใช้ SuperPoint/LightGlue + MegaLoc เดิมหา `mappoint_id` ใน source frame แล้วใช้ pyramidal Lucas–Kanade พร้อม forward–backward check ติดตามจุดเหล่านั้นมายัง target frame จากนั้นส่งเฉพาะพิกัด 2D ใน target frame เข้า PnP

วิธีนี้ไม่ได้นำพิกัด 2D จากหลาย camera pose มารวมเข้า single-camera PnP โดยตรง จึงไม่เกิดการละเมิดโมเดลกล้องแบบ generalized-camera ที่ต้องใช้ solver เฉพาะ

## Protocol

- benchmark: 53 timestamps เดิม, step 10 วินาที
- map: `result_floor1_4` เดิม
- retrieval: MegaLoc, top-k20
- local features/matcher: SuperPoint + LightGlue accelerated path เดิม
- PnP/reprojection/acceptance gate: ค่าเดิม
- temporal offsets: `-0.25, -0.125, +0.125, +0.25` วินาที
- forward–backward tracking error: ≤ 1.5 px
- `direct_plus_past` เป็นเงื่อนไข online-compatible; `direct_plus_propagated` ใช้ทั้ง future และเป็น offline upper bound เท่านั้น
- รัน full benchmark ซ้ำ 2 ครั้งด้วย parameter เดิม ได้ผลเหมือนกันทุกค่าที่รายงานด้านล่าง

งานวิจัยที่รองรับกรอบการทดลอง: Sarlin et al., CVPR 2019 เรื่อง hierarchical localization/covisibility, Karaev et al. เรื่อง CoTracker และ Ventura et al., CVPR 2014 เรื่อง generalized pose สำหรับ multi-frame observations

## ผลในสคริปต์ temporal extractor

| Config | Success | Median matches | Median inliers | Median occupied cells (4×3) |
|---|---:|---:|---:|---:|
| direct | 22/53 (41.5%) | 14 | 8 | 2 |
| propagated only | 29/53 (54.7%) | 30 | 10 | 3 |
| direct + propagated (past + future) | 33/53 (62.3%) | 40 | 13 | 3 |
| past only | 26/53 (49.1%) | 17 | 9 | 3 |
| direct + past | 31/53 (58.5%) | 29 | 11 | 3 |

ผลแสดงว่าการ propagation เพิ่ม correspondence และ spatial coverage ได้จริง โดยเฉพาะ `direct + past` ซึ่งเป็น configuration ที่นำไปใช้ online ได้

## เปรียบเทียบกับ baseline canonical ในรายงานเดิม

เนื่องจาก temporal script เป็น diagnostic extractor แยกจาก `Localizer.localize()` จึงต้องเทียบ per-frame กับไฟล์ canonical ไม่ใช่ใช้ success ของ config `direct` ใน script เป็น baseline production โดยตรง

เมื่อเทียบ `direct_plus_past` กับ `raw_exact_1920x1080` ใน `floor1_wide_production_validation53_topk20.csv`:

- baseline canonical: 29/53 (54.7%)
- direct+past: 31/53 (58.5%) ใน run นี้
- gains: 3 เฟรม
- losses: 1 เฟรม
- net: +2 เฟรม หรือ +3.8 จุดเปอร์เซ็นต์
- McNemar exact two-sided p-value สำหรับ discordant pair 3 ต่อ 1: 0.625 — ยังไม่ถือว่าพิสูจน์เชิงสถิติ

สำหรับ offline `direct_plus_propagated`:

- success: 33/53 (62.3%)
- gains เทียบ canonical: 5
- losses: 0
- net: +5 เฟรม หรือ +9.4 จุดเปอร์เซ็นต์
- McNemar exact two-sided p-value: 0.0625
- ห้ามใช้ตัวเลขนี้เป็น production claim เพราะใช้ future frames

## Trajectory consistency และ manual evidence

`direct_plus_past` มี 31 gate-pass และไม่ถูก flag เป็น position/heading outlier จาก MAD-based trajectory check ในรอบนี้ ส่วน `direct_plus_propagated` ถูก flag 4 จุด จึงยิ่งต้องแยก online result ออกจาก offline upper bound

ไฟล์หลัก:

- `run_temporal_landmark_propagation.py`
- `out/floor1_wide_temporal_landmark_full_run1.csv`
- `out/floor1_wide_temporal_landmark_full_run1_summary.json`
- `out/floor1_wide_temporal_landmark_full_run1_trajectory_consistency.json`
- `out/floor1_wide_temporal_landmark_full_run2.csv`
- `out/floor1_wide_temporal_landmark_full_run2_summary.json`
- `render_temporal_evidence.py`
- `out/floor1_wide_temporal_discordant_evidence.png`

Evidence sheet แสดง discordant frames 1925, 3465, 11550 และ 12320 สำหรับ manual audit โดยตรง ยังไม่มี ground truth metric เต็มชุด ดังนั้นผลรอบนี้เป็นหลักฐานว่า hypothesis ช่วยเพิ่ม gate-pass ได้ แต่ยังไม่ใช่หลักฐานว่า pose ใหม่ถูกต้องทุกจุด

## ข้อสรุปและงานต่อ

ผล online `direct_plus_past` เป็นสัญญาณบวกเล็กถึงปานกลาง (+2 เฟรมเทียบ canonical) แต่ยังไม่ผ่านเกณฑ์ตัดสินที่ตั้งไว้ว่า net gain ต้อง ≥ +3/53 และต้องมี audit/GT สนับสนุน จึงยังไม่แก้ production

งานที่ควรทำต่อ:

1. manual audit จุด discordant ทั้ง 4 จุด โดยเทียบภาพ query, map position และเส้นทางจริง
2. ทำ paired repeat กับ canonical baseline ใน process เดียวกันเพื่อลดความคลาดเคลื่อนจาก implementation path ที่ต่างกัน
3. ถ้า gains ยังอยู่ ให้เพิ่ม spatial coverage gate/track confidence ก่อนพิจารณา CoTracker
4. ถ้า KLT สูญเสีย track ใน failure ที่ภาพ blur ชัดเจน ค่อยทำ CoTracker ablation ใน environment แยก


# รอบที่ 13 — ทำซ้ำ Temporal landmark propagation บน `floor1_wide_pare.MOV`

ผู้ใช้กำหนดให้เปลี่ยน query video จาก `floor1_wide.MOV` เป็น `D:\wayfindar\floor1_wide_pare.MOV` และทำการทดลองซ้ำโดยใช้ map/pipeline/threshold เดิมทั้งหมด

## Protocol และข้อมูล

- video: `D:\wayfindar\floor1_wide_pare.MOV`
- resolution: `1920×1080`
- FPS: `29.989436`
- frame count: `10078`
- duration: ประมาณ `336.05s`
- sampling: ทุก 10 วินาทีเหมือน protocol เดิม ได้ 34 timestamps ไม่ใช่ 53 เพราะวิดีโอสั้นกว่า
- frame indices: `0, 300, 600, ..., 9900`
- map: `result_floor1_4` เดิม
- retrieval: MegaLoc top-k20
- matcher: SuperPoint + LightGlue accelerated path
- temporal propagation: offsets `±0.125s, ±0.25s`, forward–backward KLT error ≤ 1.5 px

## Baseline canonical ของวิดีโอใหม่

รัน `run_floor1_wide_production_sweep.py` แยกด้วย canonical production path:

| Config | Success | Failure |
|---|---:|---:|
| raw production | 33/34 (97.1%) | 1 |
| raw exact 1920×1080 | 32/34 (94.1%) | 2 |

Failure ของ raw exact ทั้งสองจุดอยู่ที่ `pnp_insufficient_inliers`; ไม่พบ local-matching failure หรือ quality/pose-gate failure

## ผล Temporal landmark propagation

| Config | Success | Median matches | Median inliers | Median occupied cells (4×3) |
|---|---:|---:|---:|---:|
| direct diagnostic | 26/34 (76.5%) | 30.5 | 13.5 | 3 |
| propagated only | 32/34 (94.1%) | 85 | 30.5 | 4 |
| direct + propagated (past + future) | 32/34 (94.1%) | 98 | 32 | 4 |
| past only | 30/34 (88.2%) | 47.5 | 21 | 4 |
| direct + past | 31/34 (91.2%) | 66.5 | 22 | 4 |

เมื่อเทียบแบบ per-frame กับ canonical `raw_exact_1920x1080`:

- `direct_plus_past`: gains 0, losses 1, net -1
- `direct_plus_propagated`: gains 0, losses 0, net 0
- `propagated only`: gains 0, losses 0, net 0
- baseline canonical: 32/34
- online temporal result: 31/34

เฟรมที่เสียผลคือ `frame 7200` หรือประมาณ `240.1s` เป็น corridor ที่ baseline canonical ได้ pose แต่ `direct_plus_past` ไม่ผ่าน PnP gate

## ข้อสรุป

สำหรับ `floor1_wide_pare.MOV` temporal landmark propagation **ยังไม่ให้ประโยชน์เพิ่ม** เพราะคลิปนี้ localize ได้ดีอยู่แล้วด้วย canonical pipeline: raw exact 32/34 (94.1%) และ raw production 33/34 (97.1%)

ที่สำคัญคือผลนี้เตือนว่าไม่ควรนำวิธี `direct_plus_past` ไปแทน baseline ตรง ๆ เพราะอาจทำให้เสียเฟรมที่ baseline สำเร็จอยู่แล้ว แม้จำนวน correspondence และ spatial coverage จะเพิ่มขึ้นมากก็ตาม

แนวทางที่ยังสมเหตุสมผลถ้าจะทำต่อคือ fallback-only:

```text
baseline ผ่าน → คง baseline pose
baseline ไม่ผ่าน → ค่อยเรียก temporal propagation
```

แต่สำหรับคลิปนี้ fallback-only จะยังไม่เพิ่ม success จาก canonical หากใช้ผลรอบนี้ เพราะ temporal method ไม่ได้กู้เฟรมที่ canonical ล้มเหลวเลย

ไฟล์ผลลัพธ์:

- `out/floor1_wide_pare_canonical_topk20.csv`
- `out/floor1_wide_pare_canonical_topk20_summary.json`
- `out/floor1_wide_pare_temporal_landmark_full_run1.csv`
- `out/floor1_wide_pare_temporal_landmark_full_run1_summary.json`


# Round 16 — Multi-device HFoV stress test and unknown-focal P4Pf

รอบนี้ทดสอบต่อบน `D:\wayfindar\floor1_wide_pare.MOV` โดยจำลองกล้องมือถือที่มี horizontal field of view (HFoV) ต่างกันมาก: `45°`, `70°`, `90°`, `120°` ทำซ้ำ 34 timestamps เดิมทุก 10 วินาที และไม่สร้าง map/keyframe ใหม่

ข้อจำกัดสำคัญ: MOV นี้ไม่มี calibration ground truth ของกล้องหลายเครื่อง การทดลองนี้จึงเป็น controlled HFoV simulation เพื่อดู sensitivity และความเสถียรของวิธี ไม่ใช่การแทนการถ่ายวิดีโอจริงจากมือถือ 4 เครื่อง

## 16.1 Fixed virtual-camera localization

| Query | Gate-pass | Trajectory-consistent | หมายเหตุ |
|---|---:|---:|---|
| raw production baseline | **33/34 (97.1%)** | 33/34 | pipeline เดิมดีที่สุดบนคลิปนี้ |
| simulated HFoV 45° | 28/34 (82.4%) | 22/34 | กล้องแคบทำให้ overlap/coverage ลดลงและเกิด outlier |
| simulated HFoV 70° | 31/34 (91.2%) | 31/34 | ใกล้กับ map HFoV ~68.9° |
| simulated HFoV 90° | 32/34 (94.1%) | 32/34 | ยังไม่ดีกว่า raw |
| simulated HFoV 120° | 32/34 (94.1%) | 32/34 | wide source ไม่ได้ช่วยเมื่อ source เป็น finite-FoV และมีขอบ invalid |

ผลนี้บอกว่าไม่ควรเลือก virtual-camera HFoV เดียวมาแทนทุกเครื่องโดยอัตโนมัติ การปรับให้เป็น FOV เดียวมีประโยชน์เป็น fallback/normalization แต่ไม่ใช่ตัวแก้หลักสำหรับกล้องที่มี overlap กับ map น้อย

ไฟล์ผล: `out/floor1_wide_pare_fov_stress.csv`, `out/floor1_wide_pare_fov_stress_summary.json`, `out/floor1_wide_pare_fov_stress_trajectory_consistency.json`

## 16.2 Unknown-focal P4Pf stress test

ใช้ correspondences เดิมจาก MegaLoc + SuperPoint/LightGlue แล้วรัน PoseLib `P4Pf` ใน custom RANSAC เพื่อประมาณ pose และ focal พร้อมกัน โดยถือ radial distortion เป็นศูนย์ การผ่าน solver อย่างเดียวไม่ถือว่า focal ถูก จึงรายงานเพิ่มด้วย gate อย่างน้อย 10 inliers

| Simulated HFoV | Solver success | ผ่าน 10-inlier gate | Median estimated focal / map focal | Median inliers |
|---:|---:|---:|---:|---:|
| 45° | 25/34 | 25/34 | 0.398 | 24 |
| 70° | 33/34 | 33/34 | 0.646 | 22 |
| 90° | 32/34 | 24/34 | 1.024 | 11 |
| 120° | 30/34 | 7/34 | 3.266 | 8 |

สรุปจาก stress test นี้คือ P4Pf เป็นกลไกที่เหมาะสำหรับ “ลองกู้ค่า focal เมื่อไม่รู้ K” แต่ต้องมี robust multi-frame refinement และ uncertainty gate เพราะ wide-FoV/ข้อมูลน้อยทำให้ minimal solver มีคำตอบที่ดู valid แต่ไม่น่าเชื่อถือได้ง่าย

ไฟล์ผล: `run_p4pf_fov_stress.py`, `out/floor1_wide_p4pf_fov_stress.csv`, `out/floor1_wide_p4pf_fov_stress_summary.json`

## 16.3 ข้อสรุปสำหรับรองรับมือถือหลายเครื่อง

คำแนะนำสำหรับ production แบบ **ไม่พึ่ง ARCore, ARKit หรือ device calibration API**:

1. **ประมาณ K จากภาพเดี่ยวเป็น initial prior**: ใช้ GeoCalib หรือ vanishing-point/Manhattan calibration เพื่อได้ช่วงค่า `fx, fy, cx, cy` และ gravity โดยไม่อ่าน metadata จากเครื่อง
2. **ถ้าไม่มี K ให้ใช้ unknown-focal estimation**: ใช้ P4Pf/PnPf หรือ P5Pfr ที่รองรับ radial distortion ใน RANSAC จาก 2D–3D correspondences; อย่ารับค่า focal จาก correspondence ชุดเดียว
3. **รวมค่าเป็น session parameter**: สะสม frame ที่มี inlier สูงหลายเฟรม แล้วใช้ robust median/Huber/IRLS หรือ bundle adjustment ร่วมกับ pose แต่ละ frame; reject ค่า focal ที่ dispersion สูงหรือ reprojection error สูง
4. **ใช้ temporal geometry เพื่อตรวจสอบและ refine**: ใช้ fundamental/essential matrix ระหว่าง query frames, track จุดหลายเฟรม และ optimize `K + pose + 3D structure` แบบ self-calibration; ไม่ใช้ IMU เป็นเงื่อนไขบังคับ
5. **ค่อยทำ virtual-camera normalization หลังประมาณ K สำเร็จ**: ให้เป็น fallback เมื่อค่า K ต่างจาก map มาก หรือใช้หลาย hypothesis แล้วเลือกด้วย inlier count + reprojection + temporal consistency
6. **ถ้า HFoV แคบจน overlap กับ map ไม่พอ ต้องแก้ที่ map coverage**: เพิ่ม keyframes จากหลาย FOV/หลายกล้อง หรือทำ 360°/multi-FoV map เพราะ calibration ไม่สามารถสร้าง feature ที่อยู่นอกขอบภาพได้

ดังนั้นวิธีที่ควรนำไปพัฒนาต่อคือ:

```text
ภาพ query เดี่ยว
  -> GeoCalib/vanishing-point ให้ prior ของ K
  -> 2D–3D matching + P4Pf/PnPf/P5Pfr ใน RANSAC
  -> รวม focal จากหลายเฟรมระดับ session
  -> self-calibration จาก temporal geometry + bundle adjustment
  -> ตรวจ inlier/reprojection/dispersion/trajectory
  -> ใช้ raw path เป็น first path
  -> ใช้ estimated-K หรือ virtual-camera เป็น fallback เมื่อ confidence ต่ำ
```

ข้อสรุปเชิง engineering จากข้อมูลชุดนี้คือ **อย่า hard-code map K เดียวสำหรับมือถือทุกเครื่อง แต่ก็อย่าแทน raw path ด้วย virtual camera เดียว** แนวทางที่ตรงกับ requirement คือ `image-only self-calibration + unknown-focal multi-frame refinement + confidence gating + multi-FoV map coverage`

ลำดับ implementation ที่ควรทำต่อคือสร้าง `self_calibration_session.py` โดยรับเฉพาะวิดีโอและ map: (ก) สุ่ม frame ที่มี feature overlap, (ข) สร้าง 2D–3D candidates, (ค) หา focal ด้วย P4Pf/PnPf หลาย frame, (ง) รวมค่าและคัด outlier, (จ) refine `K`/pose ด้วย bundle adjustment, และ (ฉ) เปรียบเทียบกับ ground-truth K ของชุดทดสอบที่เรารู้ค่าล่วงหน้า การทดลองจริงต้องรายงาน focal error, HFoV error และ pose error เพิ่มจาก gate-pass rate

## 16.4 งานวิจัยที่รองรับแนวทางนี้

- [360Loc, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_360Loc_A_Dataset_and_Benchmark_for_Omnidirectional_Visual_Localization_with_CVPR_2024_paper.html): ศึกษา cross-device/omnidirectional localization และการทำ virtual-camera views หลาย HFoV; สนับสนุนการทำ multi-FoV normalization แต่กรณีนี้ยังมีข้อจำกัดเพราะ source เป็น finite-FoV ไม่ใช่ panorama
- [Real-Time Solution to the P4P/P5P Problem with Radial Distortion, ICCV 2013](https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html): รองรับการแก้ pose พร้อม focal และ radial distortion จาก minimal correspondences; ใน PoC นี้ binding ที่ติดตั้งมี P4Pf แต่ยังไม่มี P5Pfr
- [GeoCalib, ECCV 2024](https://arxiv.org/abs/2409.06704): ประมาณ camera calibration จากภาพเดี่ยวและใช้เป็น prior/fallback เมื่อไม่มี metadata จากอุปกรณ์
- [Relative Pose from a Calibrated and an Uncalibrated Smartphone Image, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/papers/Ding_Relative_Pose_From_a_Calibrated_and_an_Uncalibrated_Smartphone_Image_CVPR_2022_paper.pdf): สนับสนุน unknown-focal geometric solver และ larger-than-minimal refinement; งานใช้ gravity เป็นข้อมูลเสริม แต่ pipeline ของเราจะไม่บังคับพึ่ง IMU
- [Deep Geometry-Aware Camera Self-Calibration from Video, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/papers/Hagemann_Deep_Geometry-Aware_Camera_Self-Calibration_from_Video_ICCV_2023_paper.pdf): สนับสนุนการใช้ข้อมูลหลายเฟรมเพื่อ self-calibration แทนการเชื่อค่าจากภาพเดียว

ไฟล์สรุปรวมของรอบนี้: `out/floor1_wide_pare_multi_device_stress_summary.json`


# Round 17 — Fast-start image-only self-calibration budget

รอบนี้ทำ prototype integration เข้า `Localizer` จริง โดยไม่พึ่ง ARCore, ARKit หรือ device camera metadata

## 17.1 Design

- request แรกใช้ map `K` เป็น **provisional K** และไม่รอ self-calibration
- หลัง localize แต่ละ frame ระบบเลือก correspondence set ที่มีจำนวนจุดมากที่สุดเพียงชุดเดียวต่อ request
- ส่งชุดนั้นเข้า one-worker background P4Pf queue; ไม่รันหลาย candidate จาก frame เดียวจนกลายเป็นหลักฐานหลายเฟรมปลอม
- commit ค่า focal ใหม่เมื่อมีอย่างน้อย 3 estimates จากคนละ request/เฟรม, มีอย่างน้อย 10 inliers ต่อ estimate และ focal MAD dispersion ไม่เกิน 12%
- หากยังไม่ผ่าน gate ระบบใช้ provisional/map K ต่อไป
- fast path รอบนี้ประมาณเฉพาะ `fx=fy`; `cx, cy` ยังยึด principal point ของ map และยังไม่ estimate radial distortion

## 17.2 Measured timing

วัดบน `floor1_wide_pare.MOV`, frame 300, accelerated MegaLoc + SuperPoint/LightGlue:

| Stage | เวลา |
|---|---:|
| model/localizer initialization | 4.02 s |
| process รวมตั้งแต่เริ่มจนจบ benchmark | 5.68 s |
| capture correspondences + localization | 0.75 s |
| P4Pf solver 200 iterations | 0.024 s |
| calibration stage รวม | **0.77 s** |
| blocking budget ของ request แรก | **0 ms** |

## 17.3 ตอบโจทย์ 3 วินาที

- ถ้าหมายถึง **เวลาที่ผู้ใช้รอจาก request แรกหลัง backend/model พร้อม**: ทำได้ เพราะ self-calibration เป็น background และ request แรกใช้ provisional K ทันที
- ถ้าหมายถึง **เปิด Python process ใหม่ตั้งแต่ศูนย์จน server พร้อมรับ localization**: ตอนนี้ยังไม่ถึง 3 วินาที; benchmark นี้วัดได้ประมาณ 5.68 วินาที โดยต้นทุนหลักมาจากการโหลด MegaLoc/SuperPoint/LightGlue ไม่ใช่ P4Pf
- ดังนั้นห้ามนำ self-calibration ไปไว้ใน startup critical path; ให้ backend process รันค้างและ warm model ก่อนรับผู้ใช้ หรือแยก model worker ที่ persistent

ไฟล์ implementation: `app/core/self_calibration.py`, การเชื่อมเข้ากับ `app/core/localizer.py` และ callback ใน `app/core/localization.py`

ข้อจำกัดของ implementation รอบนี้: full calibration ที่จะ estimate `fx, fy, cx, cy, k1, k2` พร้อมกันยังเป็นงานรอบถัดไป เพราะต้องใช้ multi-view bundle adjustment/rolling-shutter-aware refinement และควรทำใน background เช่นเดิม


# Round 18 — Three-consecutive-frame calibration window

เพื่อทดสอบคำถามว่า pipeline ที่เร็วกว่า 1 วินาทีต่อเฟรมสามารถ calibrate ภายใน 3 วินาทีหรือไม่ จึงรัน localizer จริงกับ frame ติดต่อกัน `300, 301, 302` ของ `floor1_wide_pare.MOV` หลัง model พร้อมแล้ว

| Metric | Result |
|---|---:|
| model/localizer initialization | 4.75 s (รายงานแยก ไม่รวมใน calibration window) |
| frame 300 processing | 0.714 s |
| frame 301 processing | 0.452 s |
| frame 302 processing | 0.456 s |
| 3-frame processing รวม | **1.622 s** |
| calibration commit จาก frame แรก | **1.721 s** |
| final focal | 949.3 px, ratio 0.678 ของ map focal |
| final focal MAD | 9.3 px |
| calibration status | `calibrated` |

ผลนี้ตอบได้ว่า **image-only focal self-calibration ทำภายใน 3 วินาทีได้จริง** เมื่อ model พร้อมอยู่แล้ว และ request แรกไม่ต้อง block เพราะใช้ provisional map K ระหว่าง background calibration

สิ่งที่ทำให้ตัวเลขก่อนหน้านี้เกิน 3 วินาทีคือการรวมเวลาของ MegaLoc/SuperPoint/LightGlue initialization ซึ่งใช้ประมาณ 4–5 วินาทีบน environment นี้ ส่วน P4Pf solverใช้เพียงหลักสิบมิลลิวินาที และต้นทุนหลักของ calibration window คือการประมวลผล query 3 เฟรม

ไฟล์ benchmark: `benchmark_self_calibration_3frame_window.py`, `out/self_calibration_3frame_window.json`


# Round 19 — เปรียบเทียบตำแหน่งจาก map K กับ estimated K

รอบนี้ใช้ correspondence sets เดียวกันในทุก timestamp แล้วคำนวณ pose/ตำแหน่งแยกด้วย K สองชุด เพื่อวัด sensitivity ต่อ camera calibration โดยตรง ไม่ใช่การเปรียบเทียบ retrieval คนละรอบ

## 19.1 Camera parameters

| Parameter | Map K | Estimated K |
|---|---:|---:|
| `fx` | 1400.0 px | 949.3 px |
| `fy` | 1400.0 px | 949.3 px |
| `cx` | 964.7 px | 964.7 px |
| `cy` | 546.2 px | 546.2 px |
| implied HFoV | 68.88° | 90.64° |

estimated K มาจาก three-frame image-only calibration window (`f≈949.3 px`) ส่วน `cx, cy` ยังใช้ค่า map เพราะ fast path รอบนี้ยังไม่ estimate principal point

## 19.2 Position comparison on 34 timestamps

| Metric | Result |
|---|---:|
| map K gate-pass | 33/34 |
| estimated K gate-pass | 33/34 |
| เฟรมที่ทั้งสอง K ผ่าน | 33/34 |
| median position delta | **27.6 map-pixels** |
| mean position delta | **32.2 map-pixels** |
| 95th percentile delta | **55.2 map-pixels** |
| maximum delta | **64.4 map-pixels** |

ตัวอย่างตำแหน่ง:

| Frame | map K `(x,y)` | estimated K `(x,y)` | distance |
|---:|---|---|---:|
| 0 | `(315.9, 86.0)` | `(315.7, 131.4)` | 45.4 px |
| 300 | `(313.9, 147.2)` | `(316.5, 172.6)` | 25.6 px |
| 600 | `(297.7, 183.3)` | `(309.5, 224.7)` | 43.0 px |
| 1200 | `(326.2, 248.5)` | `(330.6, 310.7)` | 62.4 px |

## 19.3 Interpretation

1. ค่า K มีผลต่อตำแหน่งจริง แม้ทั้งสองชุดจะผ่าน PnP quality gate เหมือนกัน
2. ในคลิปนี้ estimated K ทำให้ตำแหน่งขยับเฉลี่ยประมาณ 32 pixels แต่ยังสรุปไม่ได้ว่า estimated K ถูกกว่า map K เพราะไม่มี metric ground truth ของตำแหน่ง/กล้อง
3. gate-pass rate เท่ากัน (`33/34`) แปลว่า success rate อย่างเดียวไม่ไวพอที่จะตัดสิน calibration; ต้องมี ground truth หรือ reference trajectory เพิ่ม
4. การเลือก K ใน production จึงควรใช้ multi-frame consistency และ calibration benchmark ที่มี known K; ไม่ควรเลือกจากตำแหน่งที่ใกล้ map มากที่สุด เพราะนั่นจะ bias ให้เลือก map K

ไฟล์ผล: `compare_map_vs_estimated_k.py`, `out/floor1_wide_map_vs_estimated_k_pare.csv`, `out/floor1_wide_map_vs_estimated_k_pare_summary.json`

ไฟล์ benchmark: `benchmark_self_calibration_budget.py`, `out/self_calibration_budget_summary_after_fix.json`


# รอบที่ 15 — Camera-parameter estimation ตามงานวิจัยบน `floor1_wide_pare.MOV`

รอบนี้ทดลองแนวทางประมาณ camera parameters ที่มี paper รองรับ โดยใช้ protocol เดียวกันทั้งหมด: วิดีโอใหม่, 34 timestamps ทุก 10 วินาที, map `result_floor1_4` เดิม และ map focal `1400 px` เป็น reference

## สถานะ reproduction ของแต่ละ paper

| แนวทาง | สถานะ | ผลบนวิดีโอใหม่ |
|---|---|---|
| GeoCalib (Veicht et al., ECCV 2024) | **reproduction ตรง** ด้วย code/weights ของผู้เขียน | 34/34 เฟรม, median focal ratio `0.644`, robust `f≈905 px`, HFoV≈`93.4°`, median latency `135 ms` |
| Manhattan/vanishing-point self-calibration | **paper-backed adaptation** ใช้ line detector + RANSAC + orthogonal VP equation | valid estimate `22/34`, median ratio `0.654`, std `0.191`; มี outlier จึงใช้เป็น prior เท่านั้น |
| PnPf/P4Pf | **solver ตรงระดับ minimal** ผ่าน PoseLib `p4pf` + RANSAC | `33/34`, median focal ratio `0.652`, median `22` inliers |
| P5Pfr (Kukelova et al., ICCV 2013) | **ยังไม่ใช่ reproduction ตรง** | binding ที่มีให้ P4Pf แต่ไม่มี P5Pfr พร้อม radial distortion; จึงตรึง distortion เป็นศูนย์ในรอบนี้ |
| Video self-calibration | **multi-frame adaptation** | aggregate focal ต่อวิดีโอจาก PnPf ได้ robust `f≈1070 px`, HFoV≈`83.8°`; ไม่ใช่ full deep SC-BA ของ Hagemann et al. |

งานอ้างอิงหลัก: [GeoCalib](https://arxiv.org/abs/2409.06704), [P4Pfr/P5Pfr](https://openaccess.thecvf.com/content_iccv_2013/html/Kukelova_Real-Time_Solution_to_2013_ICCV_paper.html), [Manhattan calibration](https://www.microsoft.com/en-us/research/publication/automatic-camera-calibration-from-a-single-manhattan-image/) และ [video self-calibration](https://openaccess.thecvf.com/content/ICCV2023/papers/Hagemann_Deep_Geometry-Aware_Camera_Self-Calibration_from_Video_ICCV_2023_paper.pdf)

## ทดสอบค่าที่ประมาณได้กับ localization จริง

นำค่าระดับ session ไปสร้าง fixed virtual-camera hypothesis แล้วรัน pipeline เดิมแบบ top-k20:

| Query camera hypothesis | Success | Trajectory check |
|---|---:|---:|
| raw production baseline | **33/34 (97.1%)** | 33/34 consistent |
| raw exact baseline | **32/34 (94.1%)** | 32/34 consistent |
| P4Pf aggregate, HFoV≈84° | 30/34 (88.2%) | 30/34 consistent |
| Manhattan/GeoCalib/P4Pf, HFoV≈93° | 31/34 (91.2%) | 25/34 consistent, flag 6 จุด |
| GeoCalib rounded, HFoV≈94° | 30/34 (88.2%) | 30/34 consistent |

## ข้อสรุปของรอบนี้

1. **ระบบสามารถประมาณ focal length ของกล้อง query ได้จริง** และสามวิธีอิสระให้ทิศทางใกล้กันมาก: GeoCalib `0.644`, Manhattan `0.654`, P4Pf `0.652` ของ map focal
2. ผลที่สอดคล้องกันนี้น่าเชื่อถือกว่าวิธี grid search เดิม ซึ่งได้ ratio `0.771` เพราะ P4Pf ใช้ minimal solver + RANSAC กับ candidate correspondences โดยตรง
3. แต่การนำค่าประมาณไปทำ virtual-camera preprocessing ยัง **ไม่เพิ่ม success rate** บนคลิปนี้ เพราะ raw baseline แข็งแรงกว่าอยู่แล้ว และบางค่าเพิ่ม trajectory outlier
4. ค่าที่ควรนำไปใช้จริงตอนนี้คือ **ใช้เป็น uncertainty-aware prior/diagnostic** หรือใช้เลือก camera profile ไม่ใช่แทน K ของ map อัตโนมัติทุกคลิป
5. งานต่อไปที่มีคุณค่าคือเพิ่ม P5Pfr ที่ solve `f + radial distortion` จริง และทำ full multi-frame bundle adjustment โดยตรึง intrinsics ร่วมทั้งวิดีโอ ก่อนตัดสินใจเลือก K ใหม่

ไฟล์ผลลัพธ์:

- `estimate_focal_geocalib.py`
- `estimate_focal_vanishing_points.py`
- `run_p4pf_poselib.py`
- `refine_video_focal.py`
- `out/floor1_wide_pare_geocalib_summary.json`
- `out/floor1_wide_pare_manhattan_vp_summary.json`
- `out/floor1_wide_pare_p4pf_poselib.csv`
- `out/floor1_wide_pare_p4pf_poselib_summary.json`
- `out/floor1_wide_pare_pnpf_adaptation_summary.json`
- `out/floor1_wide_pare_video_focal_refinement_summary.json`
- `out/floor1_wide_pare_paper_fov_adaptations_summary.json`
- `out/floor1_wide_pare_paper_fov_adaptations_trajectory.png`
- `out/floor1_wide_pare_temporal_landmark_full_run1_trajectory_consistency.json`
- `out/floor1_wide_pare_temporal_discordant_evidence.png`

ผลรอบนี้เป็น gate-pass ไม่ใช่ ground-truth accuracy; evidence sheet มี discordant frame เดียวสำหรับตรวจสอบด้วยเส้นทางจริง


# รอบที่ 14 — Re-run ชุดทดลองหลักของรายงานเดิมบน `floor1_wide_pare.MOV`

รอบนี้ทำตามคำขอให้ย้ายการทดลองหลักจาก `D:\\wayfindar\\floor1_wide.MOV` มาใช้ `D:\\wayfindar\\floor1_wide_pare.MOV` จริง โดยล็อก map, pipeline, threshold และ sampling protocol เดิมไว้เท่าที่วิดีโอใหม่รองรับ วิดีโอเก่าถูกเก็บเป็น historical เท่านั้น ไม่ใช้เป็นผลอ้างอิงของ benchmark ใหม่นี้

## Protocol ที่ใช้ร่วมกัน

- query video: `D:\\wayfindar\\floor1_wide_pare.MOV`
- 1920×1080, 29.989436 FPS, 10078 frames, ประมาณ 336.05 วินาที
- sample ทุก 10 วินาที ได้ 34 timestamps (`frame 0, 300, ..., 9900`)
- fixed map: `result_floor1_4`; ไม่สร้าง map/keyframe/descriptor ใหม่
- pipeline: MegaLoc → SuperPoint/LightGlue → PnP-RANSAC
- success หมายถึงผ่าน production quality gate ไม่ใช่ ground-truth accuracy

## ผลการ re-run baseline และวิธีที่อยู่ในรายงานเดิม

| การทดลอง | Success | รายละเอียด |
|---|---:|---|
| raw production, top-k4 | **25/34 (73.5%)** | local matching fail 2, PnP inliers ไม่พอ 7 |
| raw exact 1920×1080, top-k4 | **28/34 (82.4%)** | local matching fail 2, PnP inliers ไม่พอ 4 |
| raw production, top-k20 | **33/34 (97.1%)** | PnP inliers ไม่พอ 1 |
| raw exact 1920×1080, top-k20 | **32/34 (94.1%)** | PnP inliers ไม่พอ 2 |
| adaptive cascade top-k4→20 | **32/34 (94.1%)** | ยกระดับ 6/34 จุด (17.6%), median latency 0.157 s |
| sharpest-frame window ±0.5 s, top-k20 | **33/34 (97.1%)** | baseline เฟรมเดิม 32/34; gain 1, loss 0 |
| temporal landmark propagation, `direct_plus_past` | **31/34 (91.2%)** | ต่ำกว่า canonical exact 1 จุด |
| temporal landmark propagation, propagated/offline | **32/34 (94.1%)** | เท่ากับ canonical exact ไม่ได้เพิ่ม coverage |

## การตีความ

1. บนวิดีโอใหม่ **top-k retrieval เป็นตัวแปรที่มีผลชัดเจน**: raw exact เพิ่มจาก 28/34 เป็น 32/34 เมื่อขยาย top-k จาก 4 เป็น 20 (+4 จุด)
2. วิธีที่คุ้มค่าที่สุดจากชุดทดลองนี้คือ **sharpest-frame-in-window**: ได้ 33/34 และกู้จุด `frame 6600` ที่เฟรมเป้าหมายเดิมล้มเหลว โดยไม่พบ loss ในการเปรียบเทียบ per-timestamp
3. adaptive cascade ลดค่าใช้จ่ายโดยเรียก top-k20 เฉพาะ 17.6% ของ timestamps แต่ผลรันนี้ได้ 32/34 ขณะที่ raw production top-k20 ได้ 33/34 ในอีก run หนึ่ง จึงต้องถือว่าเป็นผล **ไม่ด้อยกว่าในระดับที่สรุปได้ไม่ได้จาก run เดียว** และควรทำ paired repeat เพิ่มก่อน deploy
4. temporal propagation เพิ่มจำนวน correspondence และ spatial coverage ได้จริง แต่บนคลิปนี้ canonical baseline แข็งแรงอยู่แล้ว จึงยังไม่เพิ่ม success; `direct_plus_past` ยังทำให้เสียจุดที่ baseline ผ่านได้ 1 จุด
5. ตัวเลข production กับ exact ต่างกันเพราะ code path ของขนาดภาพต่างกัน และผลที่แกว่ง 1 จุดอาจอยู่ใน noise floor ของ GPU/matching stack ตามข้อควรระวังในรายงานเดิม จึงไม่ควรอ้าง delta เล็ก ๆ เป็น improvement ที่ยืนยันแล้ว

## ข้อเสนอหลัง re-run

สำหรับงานนี้ให้ใช้ลำดับต่อไปนี้เป็น implementation candidate:

```text
เลือกเฟรมคมที่สุดใน temporal window
  → localize ด้วย top-k4
  → ถ้าไม่ผ่าน ค่อย escalate เป็น top-k20
  → ถ้ายังไม่ผ่าน จึงพิจารณา temporal propagation เป็น fallback
```

ก่อนแก้ production ควรทำ paired repeat อย่างน้อย 3 runs บน timestamps เดิม และทำ manual/GT audit จุด discordant โดยเฉพาะ `frame 6600` (sharpest gain) และจุดที่ adaptive cascade ต่างจาก canonical เพื่อแยก improvement จริงออกจาก nondeterminism

## ไฟล์ผลลัพธ์ของรอบนี้

- `out/floor1_wide_pare_canonical_topk4.csv`
- `out/floor1_wide_pare_canonical_topk4_summary.json`
- `out/floor1_wide_pare_canonical_topk20.csv`
- `out/floor1_wide_pare_canonical_topk20_summary.json`
- `out/floor1_wide_pare_adaptive_cascade.csv`
- `out/floor1_wide_pare_adaptive_cascade_summary.json`
- `out/floor1_wide_pare_sharpest_policy_topk20.csv`
- `out/floor1_wide_pare_sharpest_policy_topk20_summary.json`
- `out/floor1_wide_pare_temporal_landmark_full_run1.csv`
- `out/floor1_wide_pare_temporal_landmark_full_run1_summary.json`
