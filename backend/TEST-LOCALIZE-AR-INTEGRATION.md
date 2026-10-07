# Test Localize กับ AR floor-ribbon

เส้นทาง Test Localize ใช้ AR renderer เดียวกับ PoC ที่ผ่านการปรับปรุงแล้ว (`poc_ar_arrow/ar_arrow_v2.py`) ผ่าน adapter ใน `app/services/ar_service.py` และส่ง world-space payload ให้ `ARFloorThreeOverlay` วาดใน browser

การไหลของข้อมูล:

1. `VideoTestPanel` อัปโหลดไฟล์ไปที่ `/api/upload-video`
2. เริ่ม session ที่ `/api/start-navigation` โดยส่ง destination และ `auto_floor: true`
3. `video_processor` ตรวจ floor, localize แต่ละเฟรมตาม interval, คำนวณ route และสร้าง `ar_world`
4. `navigation-stream` ส่ง update ที่มี `ar_world` กลับมา
5. `VideoTestPanel` จับ update ตาม `video.currentTime` แล้วส่ง payload ให้ `ARFloorThreeOverlay` โดยเปิด `strictWorldAr`
6. Overlay ฉาย ribbon/carets จาก `K`, `R`, `t` ใน world coordinates; ถ้า pose หรือ geometry ไม่ผ่าน gate จะซ่อน AR ชั่วคราว

สิ่งที่ผูกเข้ามาแล้ว:

- continuous floor ribbon และ caret UI จาก PoC
- `PoseStabilizer` แบบ per-session ซึ่งเร่งการตามมุมเลี้ยวและกรอง jump
- `RouteProgressTracker` กัน caret ย้อนกลับไปแสดง turn เก่า
- world-space route แบบ pin กับแผนที่ ไม่เลื่อนตามทุก localization fix
- destination marker และ arrival state
- backend readiness guard: `/healthz` ต้องเป็น `ready: true` ก่อนเริ่ม session

วิธีทดลอง:

1. เปิด `frontend-v3` ด้วย `npm run dev`
2. เปิดหน้า Test Localize แล้วเลือกวิดีโอ
3. เลือกปลายทางจากรายการ เช่น `Fire Exit 1`
4. กด Start และเลือกโหมด AR

ตั้งค่า sampling เริ่มต้นไว้ที่ 0.5 วินาทีต่อ localization update หากเครื่องประมวลผลได้เร็วสามารถลดค่าได้ แต่ไม่ควรต่ำกว่าค่า latency จริงของ GPU เพราะจะทำให้ session สะสมคิว
