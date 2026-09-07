# Stale-free AR experiment: IMG_6955.MOV

วิดีโอทดสอบ: `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV`

ช่วงที่เรนเดอร์: วินาที 80–180 ซึ่งมีจุดเปลี่ยนเส้นทางหลายจุด

## วิธีที่เพิ่มในรอบนี้

- ใช้ทุก frame ของวิดีโอที่ประมาณ 30 FPS
- ใช้ KLT/homography ติดตาม overlay ระหว่าง localization anchor
- ใช้ fresh localization anchor เป็นจุด re-anchor ทุกประมาณ 1.5 วินาที
- เมื่อ `route_state` เปลี่ยน จะไม่ carry overlay จาก turn เดิมต่อ
- ซ่อน turn caret ชั่วคราว 0.75 วินาทีระหว่าง hand-off แต่ยังคง ribbon ไว้
- มี bounded warp ป้องกัน optical flow drift จน overlay ขยายหรือหลุดภาพ

## ผลการเรนเดอร์

- 3,000 frames
- 10 route-state changes
- optical-flow accepted 2,999/2,999 frames
- caret hand-off suppression 230 frames
- วิดีโอเปรียบเทียบยาว 100 วินาที

## ไฟล์

- `non_imu_stale_free_ar_turns_80_180.mp4`: เฉพาะผลปรับปรุง
- `non_imu_stale_free_ar_turns_80_180_comparison.mp4`: ซ้าย baseline เดิม / ขวา stale-free
- `non_imu_stale_free_ar_turns_80_180_contact_sheet.png`: ภาพตัวอย่างหลายช่วง
- `non_imu_stale_free_ar_turns_turn_transition_sheet.png`: ภาพเน้นช่วงก่อน/หลังจุดเลี้ยว
- `non_imu_stale_free_ar_turns_80_180_summary.json`: metrics การเรนเดอร์

## หมายเหตุ

นี่เป็น PoC renderer สำหรับตรวจแนวทาง ยังไม่ได้เปลี่ยน production pipeline ใน backend/frontend โดยตรง การทดลองนี้แสดงผลของการ reset ตาม route state และการไม่สะสม visual warp ข้ามหลาย localization anchor ก่อนนำ logic ไปใส่ production ควรทำ turn/segment metadata ให้มาจาก backend โดยตรงแทนการ derive state จาก cached update แบบในการทดลองนี้

