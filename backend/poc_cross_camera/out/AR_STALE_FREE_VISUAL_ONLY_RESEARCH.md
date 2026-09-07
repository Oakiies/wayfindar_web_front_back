# Visual-only AR: แผนแก้ AR ค้างและให้สอดคล้องกับทางเดิน

วันที่: 2026-09-07

เอกสารนี้สรุปแนวทางจากงานวิจัยและผูกกับอาการที่พบในระบบปัจจุบัน โดยไม่ใช้ IMU, ARCore หรือ ARKit

## ข้อสรุป

สาเหตุหลักไม่ใช่แค่การ render กระตุก แต่เป็นการใช้ `ar_world` เก่าต่อเมื่อยังไม่มี localization ใหม่ และการรักษา caret เดิมไว้โดยไม่มีเงื่อนไขว่าเดินผ่านจุดเลี้ยวแล้วหรือยัง

วิธีที่ควรใช้คือ **visual tracking ความถี่สูง + global visual localization ความถี่ต่ำ + route-state gating**:

```text
ทุก frame: ติดตาม feature พื้นหลังด้วย optical flow/KLT
              ↓
      อัปเดต relative camera motion และ AR overlay
              ↓
เมื่อมี frame localization ใหม่: PnP + reprojection verification
              ↓
     ค่อย ๆ correct drift เฉพาะ pose ที่ผ่านเกณฑ์
              ↓
   เปลี่ยน segment/ผ่าน turn → ยกเลิก caret ของ turn เดิมทันที
```

## หลักฐานจากงานวิจัย

1. [Semi-dense Visual Odometry for a Monocular Camera (ICCV 2013)](https://openaccess.thecvf.com/content_iccv_2013/html/Engel_Semi-dense_Visual_Odometry_2013_ICCV_paper.html)

   ใช้การ align ภาพต่อเนื่องและติดตามการเคลื่อนที่ของกล้องจากภาพเพียงอย่างเดียว เหมาะกับการทำ local tracking ระหว่างที่ global localization ยังไม่มา

2. [Realtime Edge-Based Visual Odometry for a Monocular Camera (ICCV 2015)](https://openaccess.thecvf.com/content_iccv_2015/html/Tarrio_Realtime_Edge-Based_Visual_ICCV_paper.html)

   ใช้ edge/โครงสร้างภาพที่ติดตามได้ต่อเนื่องแทนการพึ่งผล pose จากภาพเดี่ยว ช่วยลดอาการ overlay หยุดค้างระหว่างเฟรม

3. [Real-time video stabilization via camera path correction and its applications to augmented reality on edge devices (2020)](https://doi.org/10.1016/j.comcom.2020.05.007)

   เสนอการประมาณ motion จาก sparse feature trajectories แล้ว smooth เส้นทางกล้องแบบ online ซึ่งเหมาะกับมือถือมากกว่าการใช้ dense optical flow ทุก pixel

4. [InLoc: Indoor Visual Localization With Dense Matching and View Synthesis (CVPR 2018)](https://openaccess.thecvf.com/content_cvpr_2018/html/Taira_InLoc_Indoor_Visual_CVPR_2018_paper.html)

   ใช้ coarse retrieval → pose estimation → dense matching/view synthesis verification แนวคิดนี้เหมาะกับการใช้ global localization เป็นตัวแก้ drift แต่ไม่ควรใช้เป็นตัวขยับ AR ทุก frame

5. [Is This the Right Place? Geometric-Semantic Pose Verification for Indoor Visual Localization (ICCV 2019)](https://openaccess.thecvf.com/content_ICCV_2019/html/Taira_Is_This_the_Right_Place_Geometric-Semantic_Pose_Verification_for_Indoor_ICCV_2019_paper.html)

   ชี้ว่าการเลือก pose ที่ดูดีจากภาพเดียวไม่พอ ต้องตรวจความสอดคล้องทาง geometry/appearance ก่อนยอมรับ pose ใหม่ เพื่อป้องกัน AR กระโดดไปตำแหน่งผิด

6. [Benchmarking Visual Localization for Autonomous Navigation (WACV 2023)](https://openaccess.thecvf.com/content/WACV2023/papers/Suomela_Benchmarking_Visual_Localization_for_Autonomous_Navigation_WACV_2023_paper.pdf)

   นำ temporal stability เข้ามาพิจารณาในระดับ pose และทิ้ง visual pose ที่เบี่ยงจากสถานะปัจจุบันมากเกินไป แนวคิดนี้ควรนำมาใช้กับ PnP update ของระบบนี้

## การแก้ที่ควรทำกับระบบปัจจุบัน

### 1. แยก local tracking กับ global localization

โค้ดปัจจุบันใช้ `build_ar_world_v2()` เมื่อได้ localization และมี `_ar_world_or_hold()` ที่ถือ payload เดิมได้ถึง 3 วินาที ทำให้ turn caret เก่าสามารถค้างหลังผู้ใช้เลี้ยวแล้ว

ควรเปลี่ยนเป็น:

- local tracker ทำงานทุก frame หรืออย่างน้อย 10–15 Hz ด้วย KLT/optical flow
- global PnP/localizer ทำงานตามรอบเดิม แล้วใช้เพื่อ correct drift
- ห้าม copy `ar_world` เก่าทั้งก้อนเพื่อทดแทน pose ใหม่
- ถ้า global pose หาย ให้ใช้ relative visual pose ต่อได้ชั่วคราว แต่ต้องลด confidence ตามเวลา

### 2. ทำ stale policy แยกตามชนิดของ AR

ไม่ควรใช้ timeout เดียวกับทุก geometry:

| payload | เมื่อ localization หาย | timeout ที่แนะนำ |
|---|---|---:|
| กล้อง/relative pose จาก optical flow | propagate ต่อถ้า confidence ผ่าน | 200–500 ms |
| ribbon เส้นทาง | ลด opacity แล้วค่อยซ่อน | 500–800 ms |
| turn caret/ลูกศรเลี้ยว | ซ่อนเมื่อ segment/turn ไม่ตรงทันที | 0–250 ms |
| global correction | รอ PnP ที่ verify แล้วเท่านั้น | ไม่ hold แบบไม่จำกัด |

ข้อสำคัญคือ **ห้าม hold turn caret 3 วินาที** เพราะผู้ใช้สามารถเดินผ่านจุดเลี้ยวไปแล้วในช่วงเวลานั้น

### 3. ผูก caret กับ route state

เพิ่ม metadata ใน `ar_world`:

```json
{
  "route_segment_id": 12,
  "turn_id": 4,
  "turn_status": "approaching",
  "source_timestamp": 123.45,
  "tracking_confidence": 0.91
}
```

เมื่อผู้ใช้ผ่าน corner หรือ segment เปลี่ยน:

- ลบ caret ของ `turn_id` เดิมทันที
- สร้าง caret จาก segment ปัจจุบัน/turn ถัดไปเท่านั้น
- ห้ามนำ `last_carets` จาก segment เดิมกลับมาเติมใน segment ใหม่
- `last_carets` ควรใช้ลด jitterภายใน segment เดียวกันเท่านั้น

### 4. ใช้ optical-flow confidence แทนการ hold แบบ blind

ทุก frame ควรเก็บอย่างน้อย:

- จำนวน feature ที่ติดตามได้
- RANSAC inlier ratio
- median reprojection/flow residual
- การกระจาย feature ทั่วภาพ ไม่ใช่กระจุกอยู่บริเวณเดียว
- ความต่างของ motion ที่คาดการณ์กับ PnP ล่าสุด

ถ้า confidence ต่ำ:

- ไม่อัปเดต turn caret จาก payload เก่า
- freeze ได้สั้น ๆ ประมาณ 100–250 ms เพื่อลด flicker
- ถ้ายังต่ำต่อ ให้ซ่อน caret และเหลือเพียงข้อความ/เส้นทางจาง ๆ

### 5. แก้ global pose แบบ gradual correction

เมื่อ PnP ใหม่ผ่าน geometric verification แล้ว ไม่ควรแทนที่ pose เดิมทันที ควรคำนวณ innovation แล้ว correct เฉพาะส่วนที่เชื่อถือได้:

- translation บนพื้น: smooth ด้วย bounded correction
- yaw: smooth แยกจาก translation
- roll/pitch: จำกัดการเปลี่ยนแปลงให้เล็ก เพราะระบบนำทางอยู่บนพื้น
- ถ้า innovation ใหญ่ผิดปกติ ให้ reject และทำ relocalization ใหม่แทนการลาก AR ไปตำแหน่งผิด

การ smooth ต้องไม่ข้าม state transition ของ turn: เปลี่ยน `turn_id` ทันที แล้ว smooth เฉพาะตำแหน่งการวาดภายใน state ใหม่

## ลำดับการทดลองที่แนะนำ

ใช้วิดีโอ `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV` และ destination `M21_A` เดิม โดยสร้าง output แบบ full-rate ทุก frame:

1. **Baseline**: PnP + hold เดิม 3 วินาที
2. **Short hold**: hold 0.5 วินาที แต่ยังไม่ใช้ optical flow
3. **KLT propagation**: optical flow ทุก frame + global PnP correction
4. **KLT + turn gating**: เพิ่ม `segment_id/turn_id` และล้าง caret เมื่อผ่าน corner
5. **Confidence policy**: ซ่อน caret เมื่อ flow confidence ต่ำ แต่ยังคง ribbon จาง ๆ
6. **Full system**: KLT + verified PnP + gradual correction + route-state gating

วัดผลอย่างน้อย:

- เวลาที่ turn caret ค้างหลังผ่าน corner (เป้าหมาย `< 0.25 s`)
- จำนวนเฟรมที่ AR อยู่ผิดด้านของทางเดิน
- lateral error ของ ribbon จาก centerline
- จำนวน pose jump ต่อวินาที
- jitter ของตำแหน่ง caret ระหว่างการเดินตรง
- tracking loss/relocalization rate

## แนวทางที่แนะนำสำหรับ production

ลำดับที่คุ้มค่าที่สุดคือ:

1. แก้ `turn_id/segment_id` และล้าง caret เก่าก่อน เพราะแก้อาการค้างได้ตรงที่สุด
2. ลด/แยก timeout ของ `_ar_world_or_hold()` โดยไม่ hold turn caret 3 วินาที
3. เพิ่ม KLT/optical-flow propagation ระหว่าง global localization
4. เพิ่ม PnP verification และ gradual correction
5. ค่อยพิจารณา dense/semi-dense VO หาก KLT ยังหลุดในบริเวณ texture ต่ำ

ไม่แนะนำให้แก้ด้วยการเพิ่มค่า smoothing เพียงอย่างเดียว เพราะจะทำให้ลูกศรดูนุ่มขึ้นแต่ยิ่งตอบสนองช้า และไม่แก้ปัญหา AR ของ turn เดิมที่ยังถูกนำกลับมาแสดง

