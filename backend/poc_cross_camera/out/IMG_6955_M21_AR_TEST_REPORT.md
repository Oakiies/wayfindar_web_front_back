# AR walk test: iPhone wide `IMG_6955.MOV` → `M21`

วันที่ทดสอบ: 2026-09-07  
วิดีโอ: `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV`  
ปลายทางที่ร้องขอ: `m21`  
ปลายทางที่อยู่ในกราฟ: `M21_A` / `M21_B` บน `floor1`

## การตั้งค่าทดสอบ

- ใช้ navigation pipeline และ AR world payload ของ backend จริง
- `auto_floor=true`
- sampling interval: `1.5 s`
- debug mode: เปิด
- วิดีโอ: 1920×1080, ประมาณ 29.96 FPS, ยาวประมาณ 307.8 s
- ทดสอบเดิมประมวลผล 206 sampled frames และมี 185 trajectory updates

## ผลที่สังเกตได้

1. การส่ง `m21` รอบแรกไม่เริ่ม navigation เพราะ graph เดิมเก็บชื่อเป็น `M21_A` และ `M21_B` แบบ case-sensitive
2. เมื่อใช้ `M21_A` ระบบไปถึงบริเวณปลายทางประมาณช่วง frame 40 หรือประมาณนาทีแรกของวิดีโอ โดยตำแหน่งเข้าใกล้ `(338, 408)`
3. วิดีโอยังเดินต่อหลังผ่านจุดหมายและย้อนกลับ/เปลี่ยนทิศ จึงเห็นสถานะ `arrived` แล้วกลับเป็น `navigating` ได้ตาม hysteresis เดิม ไม่ได้หมายความว่าผู้ใช้ยังเดินไปทางปลายทางในช่วงท้ายคลิป
4. พบตำแหน่งกระโดดที่มีผลต่อเส้นทาง/AR หลายช่วง จุดใหญ่สุดประมาณ `86.6 px` ในหนึ่ง sampled update และมีจุดประมาณ `60.4`, `63.7`, `51.2` และ `47.5 px`
5. ใน run เดิมมี `HOLD_LAST_FIX` 42 ครั้ง, `arrived` 18 updates และ `overshoot` 58 updates

## การแก้ที่ทำ

- `backend/app/services/nav_service.py`: ทำชื่อปลายทางเป็น case-insensitive และยังคงรวม suffix `_A`/`_B` เป็น alias เดียวกัน ดังนั้น `m21` จะ resolve ไปยัง candidate ของ `M21`
- `backend/app/services/video_processor.py`: เพิ่ม visual jump gate ก่อนส่งตำแหน่งเข้า smoother/route/AR ถ้าจุดใหม่เคลื่อนเกิน `max(28 px, 18 px/s × elapsed video time)` จะถูกถือเป็น localization dropout และใช้ตำแหน่งล่าสุดชั่วคราวแทน

## ข้อสรุป

ปัญหา AR ที่เห็นไม่ได้มาจาก route อย่างเดียว แต่เกิดจากทั้งช่วงวิดีโอหลังถึงจุดหมายและ PnP outlier เมื่อใช้วิดีโอนี้ประเมินเส้นทาง ควรตัดผลช่วงหลัง arrival ออกจาก metric หลัก หรือแยกเป็น post-arrival/return segment และใช้ jump gate นี้เพื่อไม่ให้ outlier เปลี่ยน route cue แบบฉับพลัน

## ผลหลังแก้ไขและรันทดสอบซ้ำ

รันซ้ำด้วยวิดีโอเดิมและส่งปลายทางเป็น `m21` โดยตรง:

- session: `1788788912654`
- ประมวลผลครบ 206 sampled frames
- trajectory updates: 181 รายการ
- `PnP`: 152 รายการ
- `HOLD_LAST_FIX`: 29 รายการ
- jump gate reject: 10 ครั้ง
- จุดเดิมที่กระโดดประมาณ `86 px` ถูก reject และเปลี่ยนเป็น hold ที่ frame 150–151 แทน
- ปลายทางที่ resolve ได้คือ `M21_A`, `(338,408)`

การกระโดดที่ยังเห็นใน trajectory หลัง hold เป็นการเคลื่อนที่ที่สะสมในช่วงเวลาหลายวินาที (`97.4 px` ในประมาณ `9.0 s`, หรือราว `10.8 px/s`) จึงผ่าน speed gate ได้และไม่ใช่ jump แบบเดิมที่เกิดใน `1.5 s` การทดสอบนี้ลดการเปลี่ยน route cue จาก PnP outlier ได้ แต่ไม่ได้แก้ความหมายของวิดีโอช่วงหลังผู้ใช้เดินเลยปลายทางแล้ว
