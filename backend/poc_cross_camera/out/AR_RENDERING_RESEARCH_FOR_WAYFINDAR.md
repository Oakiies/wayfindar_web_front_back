# งานวิจัยและแนวทางวาด AR ให้ตามเส้นทางแบบต่อเนื่อง

วันที่: 2026-09-07

## ข้อสรุปสั้น ๆ

อาการที่เห็นในโหมด Test Localize มีแนวโน้มไม่ได้เกิดจากรูปทรงลูกศรอย่างเดียว แต่เกิดจากการอัปเดต pose ไม่ถี่พอและไม่มีการชดเชยการเคลื่อนที่ระหว่างผล localization แต่ละครั้ง

แนวทางที่งานวิจัยใช้ซ้ำ ๆ คือ:

```text
global visual localization / map correction  (ช้ากว่า แต่แก้ drift)
                    +
relative visual-inertial tracking              (เร็วระดับ frame)
                    ↓
camera pose T_map_camera ทุก render frame
                    ↓
route polyline ใน map ถูก project เป็น geometry 3D บนพื้น
```

ระบบของ WayfindAR มีส่วน global localization, route และ world-space ribbon อยู่แล้ว แต่ production camera path ยังส่งผล localization ประมาณทุก 1 วินาที และ `NavigationView` ยังไม่ได้ส่ง relative pose ความถี่สูงเข้า `ARFloorThreeOverlay`.

## วิธีที่งานวิจัยใช้

### 1. แปลงเส้นทางจากแผนที่เป็นวัตถุ 3D แล้ว project ผ่าน camera pose

Hsieh และ Tsai แยก coordinate system เป็น global coordinate system (GCS), camera coordinate system (CCS) และ image coordinate system (ICS) จากนั้นคำนวณเมทริกซ์ GCS → CCS แล้ว project จุดลงจอด้วย camera projection matrix งานเดียวกันวาด path เป็น thick 3D line segments และ arrow บนพื้น ไม่ใช่เส้น 2D ติดหน้าจอ และเลือกวาดเฉพาะช่วง path ด้านหน้าในแต่ละครั้ง

แหล่งอ้างอิง: [A Study on Indoor Navigation by Augmented Reality and Down-Looking Omni-Vision Techniques Using Mobile Devices](https://people.cs.nycu.edu.tw/~whtsai/Conference_Papers_PDF/Hsieh_Tsai_CVGIP_2012.pdf), sections 3.4 และ 6.1–6.3.

สิ่งที่นำมาใช้กับ WayfindAR:

- เก็บเส้นทางใน map/world coordinates เดิม
- สร้าง ribbon/chevrons เป็น geometry บนพื้น z=0
- ใช้ `K`, `R`, `t` ของ frame ปัจจุบัน project geometry
- แสดงเฉพาะ local look-ahead window จากตำแหน่งที่ project ลง route
- วาดทางโค้งตาม polyline จริง ไม่ใช้ bearing เดียวทั้งเส้น

ระบบปัจจุบันทำข้อแรกถึงข้อสุดท้ายไว้ใน `ar_arrow_v2.py` แล้ว จึงไม่ควรเปลี่ยนกลับไปวาดลูกศรแบบ screen-fixed เป็นวิธีหลัก

### 2. อัปเดต path ตาม last reachable point เมื่อผู้ใช้เดินออกจากแนวเดิม

Hsieh และ Tsai ไม่ได้คำนวณ path ใหม่แบบไร้เงื่อนไขทุก frame แต่เมื่อผู้ใช้ออกจาก planned path จะหา “last reachable point” บน path เดิม แล้วต่อ current point กับส่วนที่เหลือของ route ก่อน simplify ใหม่

แหล่งอ้างอิง: paper เดียวกัน, section 5, path update process.

สิ่งที่นำมาใช้:

- รักษา route identity และ segment ที่กำลังเดิน
- project pose ลง polyline เพื่อได้ `route_cursor`
- route จะเปลี่ยนเมื่อ lateral error เกิน threshold หรือเกิด off-route จริง
- ไม่ให้ nearest-node heuristic สลับไป node หลังทางเลี้ยวเพียงเพราะจุด localization แกว่ง

`_sticky_route()` ใน `video_processor.py` แก้ปัญหา nearest-node flip ไปแล้ว แต่ควรเพิ่ม route cursor ที่ใช้ร่วมกับ live AR ด้วย

### 3. ใช้ visual odometry/optical flow + IMU ระหว่าง absolute fixes

Gupta และคณะเสนอ client-server AR localization ที่ผสาน visual odometry กับ IMU ผ่าน EKF พวกเขาใช้ Shi–Tomasi keypoints และ Lucas–Kanade optical flow เพื่อติดตามการเคลื่อนที่ และรายงานว่า map overlay อัปเดตทุกประมาณ 200 ms ไม่ใช่รอ absolute localization แบบช้าเพียงอย่างเดียว พวกเขายังระบุว่า accelerometer หรือ visual odometry เพียงอย่างเดียวสะสม drift จึงต้องมี periodic correction และ bundle adjustment/loop closure

แหล่งอ้างอิง: [Indoor Localisation and Navigation on Augmented Reality Devices](https://gaurav16gupta.github.io/papers/IndoorLocalisation.pdf), abstract, sections 2–4 และผลการทดลอง.

Fusco และ Coughlan ใช้หลักการเดียวกันในรูปแบบ sign recognition เป็น absolute fix และ VIO เป็น continuous tracking เมื่อไม่มี sign ให้เห็น

แหล่งอ้างอิง: [Indoor Localization using Computer Vision and Visual-Inertial Odometry](https://pmc.ncbi.nlm.nih.gov/articles/PMC6497170/) และ [author preprint](https://www.ski.org/sites/default/files/publications/indoor_localization-fusco-coughlan_-_preprint.pdf).

สิ่งที่นำมาใช้กับ WayfindAR โดยไม่ใช้ ARCore/ARKit:

- backend PnP/VPR = absolute correction
- browser/device IMU gyro + custom optical flow/KLT = relative delta ระหว่าง correction
- EKF/SE(3) หรืออย่างน้อย 2.5D map-plane filter = fused pose
- Three.js render loop ใช้ fused pose ทุก `requestAnimationFrame`
- เมื่อ confidence ต่ำ ให้ propagate pose ชั่วคราว แต่ลด alpha และขอ absolute re-localization ใหม่

### 4. ชดเชย registration error และ latency

Bajura และ Neumann เสนอ dynamic registration correction: วัด 2D registration error ในภาพที่รวม real/virtual แล้วใช้ error นั้นปรับ 3D registration เพื่อชดเชย drift และ jitter โดยยอมรับ video delay เล็กน้อยได้

แหล่งอ้างอิง: [Dynamic Registration Correction in Augmented-Reality Systems](https://ieeexplore.ieee.org/document/512495/).

สิ่งที่นำมาใช้:

- ทุก pose ต้องมี `capture_timestamp` ไม่ใช่ใช้เวลาที่ response กลับถึง browser
- ชดเชย pose จากเวลาถ่ายภาพไปยังเวลาที่ render ด้วย relative motion
- วัด screen reprojection error ของจุดอ้างอิง/จุด route ที่เห็นจริง
- แยก `pose_age`, `reprojection_error`, `tracking_confidence` ให้ UI รู้ว่า AR สดหรือกำลัง hold

งานด้าน world-locked AR ก็ชี้ว่าความคลาดแบบ jitter เป็น artifact ที่ผู้ใช้รับรู้ได้ และควรวัดเป็น temporal stability แยกจาก localization accuracy: [User Self-Motion Modulates the Perceptibility of Jitter for World-locked Objects in Augmented Reality](https://ieeexplore.ieee.org/document/10316484/).

## เทียบกับโค้ดปัจจุบัน

### จุดที่ตรงกับ paper แล้ว

- backend สร้าง world-space ribbon/carets จาก route polyline ใน `backend/poc_ar_arrow/ar_arrow_v2.py`
- frontend ใช้ `K/R/t` สร้าง projection camera ใน `frontend-v3/src/components/ARFloorThreeOverlay.tsx`
- มี `PoseStabilizer`, jump hold และ near/far clipping
- มี `_sticky_route()` และ local path ahead

### จุดที่ทำให้ผู้ใช้รู้สึกว่า AR ไม่อัปเดต

1. Live camera loop ตั้งไว้ที่ `1000 ms` ใน `frontend-v3/src/lib/camera.ts` จึงมีเพียงประมาณ 1 pose update ต่อวินาที ขณะที่งาน Gupta รายงานการอัปเดตประมาณ 200 ms และใช้ optical flow/IMU คั่นกลาง
2. `NavigationView` เรียก `ARFloorThreeOverlay` โดยส่ง `liveArWorld` แต่ไม่ได้ส่ง `pdrPoseRef`; render loop จึงทำได้เพียง smooth ผล pose ล่าสุด ไม่ได้ขยับ camera ตาม motion ระหว่าง localization requests
3. Test Localize ใช้ `displayUpdate` จาก timeline ที่ timestamp ล่าสุดไม่เกิน `video.currentTime` ใน `VideoTestPanel.tsx`; ระหว่างสอง timestamp AR payload เดิมถูกค้างไว้ ไม่มี pose interpolation/propagation
4. backend สร้าง geometry และ pose payload ใหม่เมื่อมี localization result; ถ้าไม่มี result จะ hold payload เดิม ซึ่งช่วยลดการกระพริบ แต่ไม่ใช่ continuous tracking
5. วิดีโอ/กล้องกับ calibration อาจมี `imgWH`, crop และ `object-fit` ไม่ตรงกัน หาก K ถูกต้องแต่ canvas ใช้ crop คนละแบบ จุดที่วาดจะเลื่อนอย่างเป็นระบบทั้งภาพ

## แนวทางที่ควรทำต่อ

### P0 — แยก absolute localization กับ continuous AR tracking

สร้าง `PoseTrackState` ฝั่ง client:

```text
T_map_cam_abs  : จาก backend PnP/VPR ทุก 200–500 ms หรือเมื่อพร้อม
ΔT_cam         : จาก IMU gyro + optical flow ระหว่างเฟรม
T_map_cam_pred : T_map_cam_abs ⊕ ΔT_cam
```

ให้ `ARFloorThreeOverlay` ใช้ `T_map_cam_pred` ทุก render frame ส่วน absolute fix ใช้แก้ driftด้วย soft correction ไม่ teleport กล้องทันที

### P1 — ทำ replay ให้เทียบวิธีได้ถูกต้อง

- เก็บ `frame_timestamp` และ `capture_timestamp` ในทุก update
- interpolate pose ระหว่าง update สองจุดเมื่อ video เล่นอยู่ระหว่าง timestamp
- สร้าง replay mode `absolute-only` กับ `absolute+motion-propagation`
- วัด route cursor error, screen reprojection error, pose age และ jitter แยกกัน

### P1 — ปรับ route cursor

- project ตำแหน่งล่าสุดลง route polyline
- วาด ribbon จาก projection ไปข้างหน้า 8–20 m ตาม field of view
- เปลี่ยน route เฉพาะเมื่อ lateral error เกินประมาณ 0.5–1.0 m ต่อเนื่องหลาย update
- ค้าง current segment จนผ่าน corner จริง ไม่ใช้ตำแหน่งที่แกว่งเปลี่ยน start node

### P2 — calibration/registration test

ทดสอบจุด route ที่รู้ตำแหน่ง 5–10 จุดในภาพ แล้วคำนวณ:

- mean/95th percentile screen reprojection error
- horizontal/vertical drift ต่อ 1 วินาที
- jitter ของจุดคงที่เมื่อกล้องหยุด
- latency ตั้งแต่ capture ถึง overlay
- coverage ของ ribbon ระหว่างเดินผ่านทางเลี้ยว

## ข้อเสนอเชิงตัดสินใจ

วิธีที่เหมาะกับ WayfindAR คือ **server visual localization + custom client-side visual-inertial propagation + map-constrained route cursor + world-space floor ribbon** ไม่ใช่การลดความซับซ้อนเหลือเพียงการเพิ่มความถี่เรียก PnP อย่างเดียว และไม่จำเป็นต้องใช้ ARCore หรือ ARKit

การลด interval จาก 1000 ms เป็น 200–300 ms จะช่วยให้เห็นการอัปเดตเร็วขึ้น แต่ยังไม่พอสำหรับ AR ที่ติดพื้นจริง หากไม่มี relative pose ระหว่าง requests เพราะ network/backend latency จะยังทำให้ overlay ค้างและกระโดดเป็นช่วง ๆ

