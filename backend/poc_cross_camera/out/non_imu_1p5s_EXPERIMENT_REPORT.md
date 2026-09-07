# Non-IMU AR smoothing experiment: `IMG_6955.MOV` → `M21_A`

วันที่ทดลอง: 2026-09-07  
วิดีโอ: `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV`  
ปลายทาง: `M21_A`  
sampling: ทุก 1.5 วินาที  
preview video: 4 FPS หรือประมาณ 0.25 วินาทีต่อ sample (เร่งจากเวลาจริงประมาณ 6 เท่า)

## สิ่งที่ทดลอง

ทุกวิธีใช้ภาพ query ชุดเดียวกัน 206 เฟรม และใช้ backend navigation จริงเพื่อสร้าง `ar_world` ที่จุด sample:

1. **RAW PnP** — ใช้ AR pose ล่าสุดจาก backend ตรง ๆ
2. **EMA POSE** — smooth กล้องด้วย exponential moving average
3. **JUMP-GATED HOLD** — reject การเปลี่ยนตำแหน่งบน map ที่กระโดดมาก แล้วคง pose ล่าสุด
4. **VISUAL KLT FLOW** — ใช้ Shi–Tomasi + Lucas–Kanade + RANSAC homography warp overlay จาก sample ก่อนหน้า โดยไม่ใช้ IMU
5. **KLT + SOFT PnP CORRECTION** — ใช้ visual warp แล้วดึงกลับเข้าหา PnP ล่าสุดด้วย correction gain 35%

## ไฟล์วิดีโอ

- [วิดีโอเปรียบเทียบ 5 วิธี](./non_imu_1p5s_comparison.mp4)
- [RAW PnP](./non_imu_1p5s_raw_pnp.mp4)
- [EMA pose](./non_imu_1p5s_ema_pose.mp4)
- [Jump-gated hold](./non_imu_1p5s_jump_hold.mp4)
- [KLT visual flow](./non_imu_1p5s_klt_flow.mp4)
- [KLT + soft PnP correction](./non_imu_1p5s_klt_corrected.mp4)
- [ภาพ contact sheet สำหรับดูจุดต่างเร็ว ๆ](./non_imu_1p5s_contact_sheet.png)
- [ผลตัวเลขแบบ JSON](./non_imu_1p5s_summary.json)

## ผลที่เห็น

- **RAW PnP** มีช่วงที่ overlay หายและมีการกระโดดของ projection มาก เพราะบาง sample ไม่มี fresh AR payload หรือ pose เปลี่ยนผิดจากการ localize
- **EMA** ทำให้การเคลื่อนที่ดูนุ่มขึ้น แต่ยังลากความผิดพลาด/lag ตาม pose ที่ผิด และไม่ได้แก้ช่วงที่ไม่มี payload ได้อย่างถูกต้อง
- **JUMP-GATED HOLD** เสถียรที่สุดในชุดนี้ในแง่ไม่ปล่อยให้ outlier กระโดดไปไกล โดยมี overlay ต่อเนื่อง 201/206 samples เทียบกับ RAW 136/206
- **KLT FLOW** ติดตามภาพได้ดีในหลายช่วง แต่การใช้เฟรมห่างกัน 1.5 วินาทีทำให้บางช่วง homography ผิดหรือขยาย overlay ออกนอกภาพ แม้ค่า residual ของจุดที่ผ่านจะดูต่ำ
- **KLT + SOFT PnP CORRECTION** ดีกว่า KLT เดี่ยวในหลักการ เพราะมี absolute correction แต่ยังไม่ปลอดภัยพอเมื่อ homography จาก sparse samples ผิดตั้งแต่ต้น

KLT มีช่วงที่ผ่านเกณฑ์เบื้องต้น `inliers >= 20` จำนวน 139/206 samples (67.5%) ค่ามัธยฐานของ inlier อยู่ที่ 68 จุด และ median reprojection residual ประมาณ 1.47 px ในกลุ่มที่ผ่านเกณฑ์ แต่ตัวเลขนี้ไม่เพียงพอจะรับรองว่า AR world pose ถูกต้อง เพราะ homography อาจอธิบายภาพเฉพาะบริเวณได้ทั้งที่ไม่ใช่ global camera motion

## ข้อสรุปจากวิดีโอชุดนี้

1. การทำให้สมูทด้วย filter ช่วยลดอาการสะบัด แต่ไม่สามารถสร้าง motion ที่หายไประหว่างภาพทุก 1.5 วินาทีได้
2. KLT/optical flow มีประโยชน์จริง แต่ต้องใช้กับภาพที่ถี่กว่านี้มาก หรือทำงานจากเฟรมกล้องทุกประมาณ 15–30 Hz
3. การใช้ KLT จาก sparse samples ทุก 1.5 วินาทีโดยตรงยังไม่ปลอดภัย โดยเฉพาะตอนหมุนกล้อง, motion blur, หรือเห็นฉากที่เกิด parallax
4. วิธีที่ควรพัฒนาต่อคือ **KLT ระหว่างเฟรมถี่ + PnP/VPR correction + route/map constraint + quality gate**
5. `JUMP-GATED HOLD` ควรคงไว้เป็น safety fallback แม้เพิ่ม visual propagation แล้ว

## การทดลองถัดไปที่ควรทำ

การทดลองนี้ยืนยันแนวโน้มได้ แต่ยังไม่ใช่การจำลอง live visual propagation ที่สมบูรณ์ เพราะ input ถูกลดเหลือทุก 1.5 วินาทีตามคำขอ ขั้นต่อไปควร:

- อ่านเฟรมจริงที่ 15 หรือ 30 Hz จาก `IMG_6955.MOV`
- รัน KLT ระหว่างเฟรมถี่ในแต่ละช่วง 1.5 วินาที
- ใช้ PnP จาก sample ทุก 1.5 วินาทีเป็น anchor/correction เท่านั้น
- reject homography เมื่อ inlier ต่ำ, residual สูง, scale หรือ image-corner warp ผิดปกติ
- คำนวณ route cursor บน floor map แยกจาก screen-space warp
- เปรียบเทียบ endpoint error, route lateral error, visual jump, track loss และ latency

ดังนั้นผลรอบนี้ยังไม่ควรนำ KLT เดี่ยวไปใส่ production แต่สนับสนุนให้ทำ **high-rate visual propagation + global PnP correction** ต่อ โดยใช้ jump-gated hold เป็น fallback

