# Full-rate AR overlay experiment: `IMG_6955.MOV`

วันที่ทดลอง: 2026-09-07  
วิดีโอ: `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV`  
ช่วงที่ render: 0–90 วินาที  
source: 29.96 FPS  
output: 2,700 เฟรม ที่ 1280×720  
global PnP anchor: ประมาณทุก 1.5 วินาที  
ไม่ใช้ IMU, ARCore หรือ ARKit

## จุดประสงค์

การทดลองก่อนหน้าใช้เฉพาะเฟรมห่างกัน 1.5 วินาที จึงทำให้ตัววิดีโอเป็น slideshow และดูเหมือนกระโดด แม้จะไม่ได้บอกความสมูทของ AR จริง รอบนี้ใช้ทุกเฟรมของวิดีโอสำหรับ playback แล้วให้แต่ละวิธีจัดการ pose/AR ระหว่าง PnP anchors เอง

## วิธีที่ซ้อนทับบนภาพจริง

- **RAW PnP**: ค้าง `ar_world` ล่าสุดระหว่างรอ anchor ใหม่ จึงเห็นการเปลี่ยนเป็นช่วง ๆ
- **EMA interpolated**: interpolate camera pose ระหว่าง anchor ด้วย smoothstep
- **JUMP-GATED HOLD**: ปฏิเสธ anchor ที่ตำแหน่ง map กระโดดมาก แล้วค้าง overlay ที่ยอมรับล่าสุด
- **KLT + soft PnP**: ใช้ KLT/optical-flow + homography warp ทุกเฟรม แล้วดึงกลับเข้าหา AR pose จาก PnP ด้วย correction gain 35%

## วิดีโอ

- [วิดีโอเปรียบเทียบ full-rate พร้อม AR overlay](./non_imu_fullrate_ar_90s_comparison.mp4)
- [RAW PnP](./non_imu_fullrate_ar_90s_raw_pnp.mp4)
- [EMA interpolated](./non_imu_fullrate_ar_90s_ema_interpolated.mp4)
- [Jump-gated hold](./non_imu_fullrate_ar_90s_jump_gated_hold.mp4)
- [KLT + soft PnP](./non_imu_fullrate_ar_90s_klt_soft_pnp.mp4)
- [contact sheet](./non_imu_fullrate_ar_90s_contact_sheet.png)
- [metrics](./non_imu_fullrate_ar_90s_summary.json)

## ผลที่เห็น

ตัววิดีโอพื้นหลังเล่นต่อเนื่องตามเฟรมจริงแล้ว ไม่กระโดดแบบ sparse preview เดิม ส่วน AR overlay ยังมีพฤติกรรมต่างกัน:

- RAW PnP อยู่กับที่ระหว่าง anchor และขยับเป็นช่วง ๆ เมื่อได้ pose ใหม่
- EMA ดูต่อเนื่องกว่า แต่มี lag และ geometry ของ route อาจเปลี่ยนเมื่อ payload ใหม่เข้ามา
- Jump-gated hold ปลอดภัยที่สุดเมื่อ PnP มี outlier แต่จะหยุดนิ่งชั่วคราวเมื่อ reject pose
- KLT + soft PnP เคลื่อนตามภาพทุกเฟรมได้จริง แต่รอบนี้ยังมีบางช่วงที่ ribbon/caret เบี่ยงหรือขยายผิด โดยเฉพาะตอนฉากมี parallax/หมุนกล้อง แม้ KLT quality gate ผ่าน

## ข้อสรุป

การซ้อน AR บน full-rate video ทำให้เห็นว่าปัญหาไม่ได้อยู่ที่การวาด Three.js เพียงอย่างเดียว แต่มีสองชั้น:

1. **temporal continuity**: ต้องใช้ visual propagation ระหว่าง PnP anchors เพื่อไม่ให้ pose กระโดด
2. **registration correctness**: optical flow ที่ถูกต้องในภาพ 2D ยังไม่รับรองว่า world-space AR pose ถูกต้องในฉาก 3D

ดังนั้นวิธีที่ควรพัฒนาต่อคือ KLT/visual tracking ที่ทำงานทุกเฟรมจริง แต่ต้องใช้ flow เฉพาะเป็น relative correction และมีการตรวจ homography/pose เพิ่ม เช่น scale, corner warp, 3D reprojection และ route/map consistency ก่อนนำไปวาด AR

ผลรอบนี้ยังไม่ควรนำ KLT + soft PnP ไป production โดยตรง ส่วน `Jump-gated hold` เหมาะเป็น fallback เมื่อ confidence ของ visual propagation ต่ำ

