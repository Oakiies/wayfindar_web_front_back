# แผนทดลองรอบถัดไปและข้อความส่งต่อให้ Luna

วันที่จัดทำ: 6 กันยายน 2026

## เป้าหมาย

เพิ่มความสำเร็จในการระบุตำแหน่งของ `floor1_wide.MOV` และลดความไม่นิ่งของ heading โดยแก้คอขวดที่รายงานรอบก่อนวัดพบจริง: PnP มี correspondence เพียงประมาณ 10–13 จุดและกระจายตัวเพียงประมาณ 19% ของภาพ เนื่องจาก motion blur, ผนังเรียบ และ corridor ที่มีลักษณะซ้ำ

งานนี้ต้องรักษา MegaLoc → SuperPoint/LightGlue → PnP, map `result_floor1_4`, keyframes และ acceptance gate เดิมไว้ การเปลี่ยนแปลงทั้งหมดต้องอยู่ใน experiment script แยกจาก production จนกว่าจะผ่านเกณฑ์ยืนยัน

## หลักฐานงานวิจัยที่ใช้กำหนดการทดลอง

1. Sarlin et al., *From Coarse to Fine: Robust Hierarchical Localization at Large Scale*, CVPR 2019: รองรับ hierarchical retrieval → local matching และการรวมข้อมูลในบริเวณที่มี covisibility เพื่อสร้าง 2D–3D matches ที่มีประโยชน์ต่อ pose estimation  
   Paper: https://openaccess.thecvf.com/content_CVPR_2019/html/Sarlin_From_Coarse_to_Fine_Robust_Hierarchical_Localization_at_Large_Scale_CVPR_2019_paper.html
2. Karaev et al., *CoTracker: It is Better to Track Together*, 2023: รองรับการ track จุดจำนวนมากร่วมกันในวิดีโอและใช้ temporal dependency เพิ่มความทนทานของ point tracks  
   Paper: https://arxiv.org/abs/2307.07635  
   Official code: https://github.com/facebookresearch/co-tracker
3. Ventura et al., *A Minimal Solution to the Generalized Pose-and-Scale Problem*, CVPR 2014: แสดงกรอบ generalized camera สำหรับรวม observations จากหลายเฟรมอย่างถูกเรขาคณิต และประยุกต์กับ multi-frame loop closure  
   Paper: https://openaccess.thecvf.com/content_cvpr_2014/html/Ventura_A_Minimal_Solution_2014_CVPR_paper.html
4. Su et al., *Deep Video Deblurring for Hand-Held Cameras*, CVPR 2017: รองรับการใช้ข้อมูลจากเฟรมข้างเคียงเพื่อแก้ motion blur ของวิดีโอ handheld  
   Paper: https://openaccess.thecvf.com/content_cvpr_2017/html/Su_Deep_Video_Deblurring_CVPR_2017_paper.html
5. Sarlin et al., *Back to the Feature: Learning Robust Camera Localization From Pixels To Pose*, CVPR 2021: สนับสนุนหลักการให้ learned features จัดการความทนทานของภาพ แต่คง geometric pose estimation เป็นขั้นตอนที่มีหลักเรขาคณิตตรวจสอบได้  
   Paper: https://openaccess.thecvf.com/content/CVPR2021/html/Sarlin_Back_to_the_Feature_Learning_Robust_Camera_Localization_From_Pixels_CVPR_2021_paper.html
6. Xue et al., *Learning Multi-View Camera Relocalization With Graph Neural Networks*, CVPR 2020: เป็นหลักฐานว่าข้อมูลหลายมุม/หลายเฟรมให้บริบทเพิ่มแก่ relocalization ได้ แต่ paper นี้เปลี่ยนโมเดลและต้อง train จึงใช้สนับสนุน hypothesis เท่านั้น ไม่ใช่ implementation รอบแรก  
   Paper: https://openaccess.thecvf.com/content_CVPR_2020/html/Xue_Learning_Multi-View_Camera_Relocalization_With_Graph_Neural_Networks_CVPR_2020_paper.html

## ข้อควรระวังด้านเรขาคณิต

ห้ามนำพิกัด 2D จากหลายเฟรมมาต่อรวมกันแล้วเรียก single-camera `solvePnP` โดยตรง เพราะแต่ละเฟรมมี camera pose คนละค่า วิธีที่ถูกต้องสำหรับรอบแรกคือ:

- track association ของ 3D landmark จากเฟรมต้นทางมายังพิกัด 2D ของ **target frame** แล้ว solve PnP เฉพาะ observation ที่อยู่ใน target frame หรือ
- ใช้ generalized-camera solver ซึ่งจำลองหลาย camera centers อย่างถูกต้อง พร้อม relative poses ที่น่าเชื่อถือ

รอบแรกให้ทำวิธีแรก เพราะเปลี่ยนระบบน้อยกว่าและตรวจสอบง่ายกว่า

## Protocol กลางที่ทุก experiment ต้องใช้

### Dataset และ baseline

- Primary benchmark: 53 timestamps ชุดเดิมทุกประมาณ 10 วินาที ห้ามเปลี่ยน sample grid ระหว่าง A/B
- Baseline หลัก: `raw_exact_1920x1080`, top-k20, gate เดิม
- Baseline production-latency: adaptive top-k4 → top-k20
- รายงาน sharpest-frame policy แยกเป็น temporal coverage ห้ามเรียกว่า same-frame success
- รัน baseline และ config ใหม่อย่างน้อย 3 repeats เพื่อวัด nondeterminism
- ใช้ random seed/deterministic flags เท่าที่ backend รองรับ แต่ต้องรายงานสิ่งที่ยัง nondeterministic

### Metrics บังคับ

ต่อ timestamp ให้บันทึก:

- direct matches, propagated matches และจำนวนหลัง deduplicate
- PnP inliers, inlier ratio, median reprojection error
- spatial coverage อย่างน้อย `x_coverage`, `y_coverage`, convex-hull area/image area และจำนวน occupied cells ใน grid `4×3`
- success ตาม gate เดิม
- `x_px`, `y_px`, `heading_deg`
- latency แยก retrieval, matching/tracking, PnP และ total
- source frame/offset ของ propagated track และ forward-backward tracking error

สรุปผลด้วย:

- successes/53 พร้อม paired gains และ paired losses เทียบ baseline
- median correspondence count และ spatial coverage
- median absolute heading change ทั้ง deg/step และ deg/s
- bootstrap 95% CI ของ paired success-rate difference
- McNemar exact test บน paired success/failure
- ผลทั้งแต่ละ repeat และ aggregate ห้ามเลือกเฉพาะ run ที่ดีที่สุด

### Accuracy audit

คำว่า success ใน PoC ปัจจุบันหมายถึง gate-pass ไม่ใช่ ground-truth accuracy ดังนั้น:

- สร้าง contact sheet ของทุก `new-only success` และ `baseline-only success`
- บันทึก matched keyframe, query, จุด inlier และตำแหน่งบน map
- ห้ามเสนอ merge production หากยังไม่มี manual audit อย่างน้อยทุก discordant pair
- ถ้าทำได้ ให้สร้าง landmark GT 15–20 timestamps ที่ระบุตำแหน่งและทิศทางโดยประมาณเพื่อวัด position/heading error จริง

## Experiment 1 — Temporal landmark propagation

### Hypothesis

เฟรมเป้าหมายที่ blur/low-texture อาจหา SuperPoint matches โดยตรงได้น้อย แต่ 3D landmarks ที่จับคู่ได้ในเฟรมใกล้เคียงสามารถ track มายัง target frame และเพิ่มจำนวน/การกระจายของ 2D–3D correspondences ได้

### Implementation

สร้าง `run_temporal_landmark_propagation.py` โดย reuse วิธีดึง accepted/raw correspondences จาก `diagnose_heading_instability.py` หรือ `test_gravity_constrained_heading.py` และห้ามแก้ production

1. สำหรับ timestamp เป้าหมาย ใช้ window `±0.25s` ก่อน มี offsets ที่ตรึงไว้ เช่น `[-0.25, -0.125, 0, +0.125, +0.25]`
2. รัน pipeline เดิมในแต่ละ source frame เพื่อหา association ระหว่าง query keypoint กับ map 3D point/landmark ID
3. Track เฉพาะ keypoint ที่มี 3D association จาก source frame ไป target frame
4. รอบ cheap PoC ใช้ pyramidal Lucas–Kanade พร้อม forward-backward check; เก็บ track เมื่อ FB error ≤ 1.5 px และอยู่ในภาพ
5. รวม propagated target-frame 2D–3D matches กับ direct target-frame matches
6. Deduplicate ด้วย 3D landmark ID; ถ้าไม่มี ID ที่ expose ได้ ต้องเพิ่ม diagnostic API ที่คืน ID ห้าม deduplicate ด้วยระยะ 2D อย่างเดียว
7. ถ้า landmark เดียวมีหลาย observation ให้เลือก track ที่ FB error ต่ำสุด
8. รัน `solvePnPRansac` ด้วย K/gate/reprojection threshold เดิม แล้วประเมินผ่าน quality gate เดิม
9. ทำ ablation:
   - direct only
   - propagated only
   - direct + propagated
   - source จากเฟรมก่อนเท่านั้น
   - source จากก่อนและหลัง
10. อย่าใช้ผลจาก future frame เป็น production-online claim; ผล `before+after` เป็น offline upper bound ส่วน online candidate ใช้ past-only

### เกณฑ์ผ่านไป Experiment 2

ต้องผ่านทุกข้อ:

- median correspondence เพิ่มอย่างน้อย 30% หรือ median occupied grid cells เพิ่มอย่างน้อย 2 cells
- paired net gain อย่างน้อย `+3/53` และมากกว่า run-to-run flip ที่วัดได้
- paired losses ไม่เกิน gains
- heading median jump ลดอย่างน้อย 20% ในเฟรมที่มี temporal continuity
- manual audit ไม่พบ false localization ใหม่ที่ชัดเจน

ถ้าไม่ผ่าน ให้หยุด hypothesis นี้และรายงานสาเหตุ ห้ามปรับ window/threshold แบบไม่จำกัดเพื่อไล่ตัวเลข

## Experiment 2 — CoTracker propagation ablation

ทำเฉพาะเมื่อ Experiment 1 แสดงว่า propagation concept ช่วย แต่ KLT สูญเสีย track เพราะ blur หรือ displacement

1. ใช้ CoTracker official checkpoint ใน environment แยก ห้ามติดตั้ง dependency ทับ backend หลัก
2. Seed tracker ด้วยตำแหน่ง 2D ที่มี 3D landmark association เท่านั้น ไม่ใช้ grid points ที่ไม่รู้ 3D ID ใน PnP
3. ใช้ visibility/confidence จาก tracker และ forward/backward temporal consistency กรอง track
4. ใช้ benchmark, target frame และ PnP gateเดียวกับ Experiment 1
5. เปรียบเทียบ `direct`, `KLT propagation`, `CoTracker propagation` แบบ paired
6. รายงาน VRAM, initialization time และ per-window latency

เกณฑ์เลือก CoTracker: ต้องเพิ่ม net success จาก KLT อย่างน้อย `+2/53` หรือเพิ่ม heading stability อย่างชัดเจน โดย latency/ทรัพยากรยังยอมรับได้ มิฉะนั้นเลือก KLT ที่ง่ายกว่า

## Experiment 3 — Covisibility-consistent candidate fusion

ทำหลัง Experiment 1 หรือทำขนานได้ถ้าใช้ผล retrieval cache เดียวกัน

### Hypothesis

top-k20 เพิ่ม success มากที่สุดในรายงานเดิม แปลว่า information กระจายอยู่ใน shortlist แต่การประเมิน candidate แยกกันอาจใช้ 3D matches ไม่เต็มที่ การจัดกลุ่ม candidate ที่สอดคล้องกันก่อนรวม matches สอดคล้องกับ hierarchical localization/covisibility reasoning ของ Sarlin et al.

### Implementation

1. Cache top-k20 retrieval และ local matches เพื่อไม่ extract feature ซ้ำ
2. สร้าง graph ของ retrieved keyframes โดยใช้ shared 3D landmark IDs; edge เมื่อ shared landmarks ≥ threshold ที่กำหนดล่วงหน้า
3. สร้าง connected components/covisibility clusters
4. รวม matches ภายใน cluster, deduplicate ด้วย query keypoint ID และ 3D landmark ID
5. solve PnP แยกต่อ cluster ห้ามรวม candidate ต่าง cluster
6. เลือก pose ด้วย gate เดิมก่อน แล้วใช้ inliers/reprojection เฉพาะ tie-break ระหว่าง pose ที่ผ่าน gate
7. Ablation threshold shared landmarks `{3, 5, 10}` เท่านั้น และประกาศก่อนรัน full benchmark

เกณฑ์ผ่าน: net gain ≥ `+3/53`, coverage เพิ่ม, losses ≤ gains และ discordant-frame audit ผ่าน

## Experiment 4 — Conditional video deblurring

ทำเมื่อ propagation/covisibility ยังเหลือ failure ที่ sharpness ต่ำอย่างชัดเจน

1. ใช้ implementation/checkpoint ที่เชื่อมโยงกับงาน video deblurring ที่ตีพิมพ์และติดตั้งใน environment แยก
2. ห้ามใช้ single-image generative enhancement ที่ไม่มี matching evaluation
3. ตรึง trigger จาก baseline ก่อนดูผล เช่น Laplacian sharpness ต่ำกว่า 25 หรือ quantile ที่กำหนดจาก training-free baseline statistics
4. ใช้ clip เดียวกันและจำนวน neighboring frames คงที่
5. รัน raw และ deblurred hypotheses; ห้ามแทน raw ถาวรในรอบแรก
6. วัด retrieval score, direct matches, inliers, spatial coverage, reprojection, success และ latency
7. manual audit ทุก deblurred-only success เพราะ hallucinated texture อาจสร้าง false match

เกณฑ์ผ่าน: paired gain มากกว่า noise floor, ไม่มี false localization ใน audit และเพิ่ม matches/coverage ไม่ใช่เพียงภาพดูคมขึ้น

## ลำดับการทำงานที่แนะนำ

1. เพิ่ม evaluator กลางและ rerun baseline 3 ครั้ง
2. Experiment 1: KLT temporal landmark propagation
3. ถ้า propagation มีสัญญาณบวกแต่ KLT เป็นคอขวด ให้ทำ Experiment 2
4. Experiment 3: covisibility-consistent candidate fusion
5. Experiment 4 เฉพาะ residual blur failures
6. เลือกวิธีที่ผ่านเกณฑ์ แล้วทดสอบร่วมกับ adaptive top-k cascade เป็น integration experiment สุดท้าย
7. ยังไม่แก้ production จนกว่า manual/GT audit ผ่าน

## สิ่งที่ไม่ควรทดลองซ้ำ

- sweep FoV ต่อเฟรมหรือเลือก FoV จาก inlier count
- gravity-constrained PnP แบบเดิม
- CLAHE/unsharp sweep
- top-k มากกว่า 20 โดยไม่มี retrieval evidence ใหม่
- ลด gate เพื่อเพิ่มตัวเลขโดยไม่มี spatial/accuracy validation
- temporal smoothing เพียงอย่างเดียวแล้วอ้างว่าแก้ heading root cause

---

# ข้อความพร้อมส่งให้โมเดล Luna

คุณรับช่วงงาน visual localization ใน repo `D:\wayfindar` ต่อจากรายงาน:

`D:\wayfindar\WebNav_front_back\backend\poc_cross_camera\EXPERIMENT-REPORT.md`

ให้อ่านรายงานทั้งหมดและไฟล์แผนนี้ก่อนลงมือ:

`D:\wayfindar\WebNav_front_back\backend\poc_cross_camera\NEXT-EXPERIMENT-PLAN-LUNA.md`

เป้าหมายคือเพิ่ม success rate ของ `D:\wayfindar\floor1_wide.MOV` และลด heading instability โดยยึดหลักฐานจาก paper ห้ามสุ่มลองวิธีที่ไม่มีที่มา

Constraints ที่ห้ามเปลี่ยน:

- fixed map: `WebNav_front_back/backend/app/data/map_data/result_floor1_4`
- pipeline หลัก: MegaLoc → SuperPoint/LightGlue → PnP
- ห้าม rebuild map/keyframe/descriptor ฝั่ง map
- ห้ามเปลี่ยนเป็น HLoc/CosPlace/NetVLAD หรือโมเดล localization อื่น
- ห้ามลด production acceptance gates เพื่อทำให้ success rate ดูสูงขึ้น
- ทุกงานต้องเป็น script/CSV/JSON/PNG/Markdown ใน `poc_cross_camera`; ห้ามส่ง Artifact
- ห้ามแก้ production ในช่วง experiment

เริ่มจาก Experiment 1: Temporal landmark propagation เท่านั้น ก่อนเขียนโค้ดให้ตรวจ API ของ `Localizer` และสคริปต์ `diagnose_heading_instability.py`, `test_gravity_constrained_heading.py`, `run_floor1_wide_production_sweep.py` เพื่อระบุให้ได้ว่า query keypoint ใดสัมพันธ์กับ 3D landmark ID ใด

หลักเรขาคณิตที่ห้ามผิด: ห้าม pool พิกัด 2D จากหลายเฟรมแล้วส่งเข้า single-camera PnP เดียว ให้ track 3D landmark association มายังพิกัด 2D ใน target frame แล้ว solve PnP ของ target frameเท่านั้น

งานที่ต้องส่งในรอบแรก:

1. `run_temporal_landmark_propagation.py`
2. CSV ราย timestamp ที่มี direct/propagated/deduplicated matches, inliers, coverage, reprojection, pose, heading และ latency
3. summary JSON ที่มี paired gains/losses, McNemar exact result, bootstrap CI และผลแยกอย่างน้อย 3 repeats
4. contact sheet ของทุก discordant frame พร้อม query, matched keyframe, inlier overlay และตำแหน่งบน map
5. ต่อท้ายผลและข้อจำกัดใน `EXPERIMENT-REPORT.md`

Protocol:

- ใช้ 53 timestamps เดิมและ baseline `raw_exact_1920x1080 top-k20`
- window เริ่มต้น `±0.25s`, offsets ตรึงก่อนรัน full set
- cheap PoC ใช้ pyramidal Lucas–Kanade + forward-backward check ≤ 1.5 px
- deduplicate ด้วย 3D landmark ID
- ablation: direct-only, propagated-only, direct+propagated, past-only, past+future
- future-frame result ต้องติดป้าย offline upper bound; production candidate ต้อง past-only
- ห้ามปรับ parameter เพิ่มหลังเห็น full-test result หากยังไม่ได้ประกาศเป็นรอบใหม่

ก่อนรัน full 53 timestamps ให้ทำ smoke test 1–3 timestamps และตรวจด้วยภาพว่า landmark IDs ถูก propagate มายัง target frameจริง หากไม่สามารถ expose 3D IDs ได้ ให้หยุดและรายงานจุดใน API ที่ขาด ห้ามใช้ nearest 2D point เป็นตัวแทนแบบเงียบ ๆ

เกณฑ์ตัดสิน:

- correspondence หรือ spatial grid coverage ดีขึ้นอย่างมีนัยใช้งาน
- paired net gain ≥ +3/53 และมากกว่า run-to-run noise
- paired losses ≤ gains
- median heading jump ลดอย่างน้อย 20%
- discordant-frame manual audit ไม่พบ false localization ชัดเจน

ถ้า Experiment 1 ไม่ผ่าน ให้สรุปเชิงลบอย่างตรงไปตรงมาและหยุด ไม่ไล่ threshold จนได้ตัวเลข ถ้าผ่านแต่ KLT เป็นคอขวด ค่อยเสนอ Experiment 2 CoTracker โดยติดตั้งใน environment แยกและอ้าง paper/official repository ที่ระบุในแผน

ทุกข้อสรุปต้องแยกให้ชัดระหว่าง `PnP gate-pass`, `temporal coverage` และ `ground-truth accuracy` เพราะตอนนี้ยังไม่มี GT เต็มชุด
