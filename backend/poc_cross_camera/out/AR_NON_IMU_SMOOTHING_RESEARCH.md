# แนวทางทำ AR ให้สมูทโดยไม่ใช้ IMU

วันที่: 2026-09-07  
ขอบเขต: WayfindAR / Test Localize / `IMG_6955.MOV` → `M21_A`  
ข้อจำกัด: ไม่ใช้ IMU, ไม่ใช้ ARCore, ไม่ใช้ ARKit

## ข้อสรุปสั้น ๆ

ทำให้สมูทขึ้นได้ แต่การใช้ EMA หรือการค่อย ๆ เลื่อน pose อย่างเดียวไม่พอ เพราะมันเพียงซ่อนการกระโดดของตำแหน่งและทำให้เกิด latency ได้ ระบบต้องมี **visual propagation ระหว่าง global localization fixes** ด้วย

แนวทางที่เหมาะกับ WayfindAR ที่สุดคือ:

```text
camera frames 15–30 Hz
        │
        ├─ visual tracking ระหว่างเฟรม
        │  KLT/optical flow + RANSAC affine/homography
        │  หรือ essential matrix เมื่อภาพไม่เป็นระนาบ
        │
        ├─ แปลง relative motion เป็นการขยับบน map route
        │  route cursor + 2.5D constraints
        │
        └─ PnP/VPR ทุกประมาณ 0.5–1.0 วินาที
           ใช้เป็น absolute correction และแก้ drift
```

ดังนั้น visual-only ช่วยให้ AR เคลื่อนต่อเนื่องและลดอาการ teleport ระหว่าง localization ได้ แต่ visual-only monocular ไม่ควรถูกใช้เป็นแหล่งพิกัดแผนที่แบบ absolute ตลอดทาง เพราะยังมี scale ambiguity และ drift

## สิ่งที่พบจาก pipeline ปัจจุบัน

- `frontend-v3/src/lib/camera.ts` กำหนด `LIVE_CAMERA_CAPTURE_INTERVAL_MS = 1000` จึงส่งภาพให้ backend ประมาณ 1 Hz
- `NavigationView` ส่ง `arWorld` เข้า `ARFloorThreeOverlay` แต่ไม่ได้ส่ง high-rate relative pose
- `ARFloorThreeOverlay` มี render loop และค่อย ๆ ตาม target pose ได้ แต่ target ใหม่ยังมาจาก localization ที่ช้า จึงเป็นการทำ easing ระหว่างจุด ไม่ใช่การติดตามการเดินจริง
- replay ใน `VideoTestPanel` เลือก update ล่าสุดที่ timestamp ไม่เกินเวลาวิดีโอ ยังไม่มีการคำนวณ pose ระหว่างสอง update
- backend มี PnP, pose smoothing, jump rejection และ hold-last-fix แล้ว สิ่งที่ขาดคือ visual motion ระหว่าง fix

ผลคือ ถ้า localization มาทุก 1 วินาที การ render ที่ 60 FPS จะดูนุ่มขึ้นเฉพาะตอนเลื่อนไปหาจุดใหม่ แต่ไม่รู้ว่าผู้ใช้เดินหรือหมุนอย่างไรในช่วง 1 วินาทีนั้น

## งานวิจัยที่เกี่ยวข้องและสิ่งที่นำมาใช้ได้

### 1. KLT / Lucas–Kanade optical flow

Lucas และ Kanade เสนอการหาการเคลื่อนที่จากความเปลี่ยนแปลงของ intensity ระหว่างภาพ โดยใช้การ optimize เฉพาะบริเวณรอบจุด ทำให้เร็วกว่าการลองจับคู่ทุกตำแหน่ง เหมาะเป็น front-end สำหรับติดตามจุดระหว่างเฟรมที่อยู่ใกล้กัน

นำมาใช้กับ WayfindAR ได้ดังนี้:

- เลือก Shi–Tomasi corners ในภาพก่อนหน้า
- track ด้วย pyramidal `calcOpticalFlowPyrLK`
- ใช้ forward–backward check และ RANSAC ตัดจุดที่หลุด
- ประเมิน affine/homography หรือ essential matrix จาก inlier ที่เหลือ
- ใช้ relative motion อัปเดต pose ที่ render ทุกเฟรม

ข้อจำกัดคือ optical flow ให้ relative motion ไม่ใช่ตำแหน่ง absolute และจะล้มเหลวเมื่อภาพเบลอมาก, texture น้อย, มีคนบัง, หรือมีการหมุน/เคลื่อนที่เร็วเกินระยะที่ tracker รองรับ

แหล่งอ้างอิง: [Lucas–Kanade original paper](https://idl.uw.edu/living-papers-paper/lucas-kanade/)

### 2. Homography / affine tracking สำหรับการเคลื่อนที่ระยะสั้น

งาน camera tracking สำหรับ AR ใช้ natural features และ homography เพื่อเชื่อมภาพปัจจุบันกับภาพก่อนหน้า/ภาพอ้างอิง และใช้ temporal regularization แบบ recursive เพื่อลด jitter งานอีกกลุ่มแสดงว่าการคำนวณ homography เหมาะเมื่อกล้องหมุนเป็นหลักหรือเห็นพื้นผิวระนาบ

สิ่งที่ควรนำมาใช้คือ **ใช้ homography เป็น short-term image-motion model** ไม่ใช่สรุปว่ากล้องทั้งระบบอยู่บนระนาบเดียวกัน เพราะภาพ wide ของทางเดินมีผนัง เสา คน และวัตถุ 3D ที่ทำให้เกิด parallax

กติกาที่ควรใช้:

- ถ้า inlier กระจายทั่วภาพและ reprojection error ต่ำ: ใช้ affine/homography propagation ได้
- ถ้า homography มี residual สูงหรือ inlier รวมอยู่บริเวณเดียว: ห้ามอัปเดต world pose จาก homography
- ในฉาก non-planar ให้ใช้ essential matrix + `recoverPose` หรือ 2D–3D PnP จาก keyframe แทน

แหล่งอ้างอิง: [Real-time camera tracking for marker-less and unprepared AR environments](https://www.sciencedirect.com/science/article/abs/pii/S0262885607001266), [Augmented reality camera tracking with homographies](https://doi.org/10.1109/MCG.2002.1046627)

### 3. Direct / semi-dense visual odometry บน smartphone

Schöps, Engel และ Cremers แสดงระบบ monocular direct visual odometry ที่ทำงานบน smartphone โดย align intensity โดยตรงแทนการพึ่ง keypoint descriptor และรายงาน tracking ที่มากกว่า 30 Hz ในการตั้งค่าทดลอง ระบบทำแผนที่ inverse depth แบบ semi-dense ควบคู่กับการ tracking

ข้อดีสำหรับ WayfindAR:

- ใช้ขอบและ intensity gradient ได้ แม้จุด ORB จะไม่เด่น
- ให้ pose ต่อเนื่องระดับ frame rate
- แนวคิด tracking/mapping แยก thread เหมาะกับการรักษา latency

ข้อเสีย:

- ซับซ้อนและหนักกว่า KLT front-end
- ต้องจัดการ photometric calibration, motion blur และ rolling shutter
- monocular VO ยังมี scale/drift problem จึงต้องมี absolute correction จากแผนที่หรือ keyframe

แหล่งอ้างอิง: [Semi-Dense Visual Odometry for AR on a Smartphone](https://jakobengel.github.io/pdf/schoeps14ismar.pdf)

### 4. Feature-based visual SLAM / relocalization

PTAM แยก tracking กับ mapping เป็นงานคู่ขนาน เพื่อให้ tracking กล้อง handheld ทำงานที่ frame rate ในขณะที่ mapping และ optimization ทำงานหนักเบื้องหลัง ส่วน ORB-SLAM2 เพิ่ม map reuse, loop closing และ relocalization และมี localization mode ที่ใช้ visual tracks ในช่วงที่ยังจับ map point ไม่ได้

วิธีนี้มีศักยภาพแก้ drift ระยะยาวได้ดีกว่า optical flow อย่างเดียว แต่ไม่ควรเป็นการทดลองแรกของโปรเจกต์ เพราะต้องมี map/keyframe 3D, ระบบ relocalization และ resource บนมือถือมากกว่า pipeline ปัจจุบัน

แหล่งอ้างอิง: [PTAM](https://www.robots.ox.ac.uk/~lav/Papers/klein_murray_ismar2007/), [ORB-SLAM2](https://arxiv.org/abs/1610.06475)

### 5. Direct Sparse Odometry (DSO)

DSO optimize photometric error ใน window ของเฟรมและใช้ inverse depth แทนการพึ่ง keypoint descriptor จึงใช้บริเวณที่มี intensity gradient ได้กว้างกว่า feature-only tracking แต่ยังเป็น monocular odometry ที่สะสม drift ได้ และการนำมา deploy บนเว็บ/มือถือจะใหญ่กว่าการเพิ่ม KLT เข้า pipeline ปัจจุบัน

แหล่งอ้างอิง: [Direct Sparse Odometry](https://arxiv.org/abs/1607.02565)

### 6. การแก้ scale และ drift โดยใช้ข้อจำกัดของฉาก

งาน monocular VO ที่ใช้ planar road model แสดงว่าการใส่ constraint จากพื้น/ความสูงกล้องและการทำ bundle adjustment แบบ sliding window ช่วยลด scale drift ได้ ข้อสังเกตนี้สอดคล้องกับ WayfindAR ซึ่งมี floor map, route polyline และความสูงของกล้องโดยประมาณอยู่แล้ว

สำหรับงานนี้ควรใช้ constraint แบบ 2.5D แทนการพยายามสร้างโลก 3D เต็มรูปแบบ:

- ให้ตำแหน่งผู้ใช้เคลื่อนบน floor plane
- จำกัดความเร็วและระยะก้าวในช่วงสั้น ๆ
- ผูกการเคลื่อนที่เข้ากับ tangent ของ route เมื่อยังอยู่บนเส้นทาง
- ใช้ PnP/VPR เป็นจุดแก้ absolute pose
- ถ้า confidence ของ flow ต่ำ ให้หยุด propagation และรอ fix ใหม่

แหล่งอ้างอิง: [Monocular Visual Odometry using a Planar Road Model to Solve Scale Ambiguity](https://www.ri.cmu.edu/pub_files/2011/9/ECMR2011.pdf), [Ground Plane based Absolute Scale Estimation for Monocular Visual Odometry](https://arxiv.org/abs/1903.00912)

## วิธีที่ควรทดลองก่อน

### Visual Route Propagation (ข้อเสนอสำหรับ WayfindAR)

นี่เป็นการประกอบวิธีที่มีงานวิจัยรองรับเข้ากับโครงสร้างแผนที่ของโปรเจกต์ ไม่ใช่การอ้างว่าเป็น algorithm เดียวจาก paper ใด paper หนึ่ง

1. **Global anchor**: รัน PnP/VPR ตามปกติทุก 0.5–1.0 วินาที หรือเมื่อ confidence ต่ำ
2. **Frame tracker**: ใน browser หรือ worker ติดตามภาพ camera ที่ 15–30 Hz ด้วย KLT
3. **Robust motion**: ใช้ forward–backward flow check, RANSAC affine/homography และคัดทิ้งเมื่อ inlier น้อยหรือ residual สูง
4. **Pose propagation**: เปลี่ยน relative image motion เป็น relative map motion โดยใช้ anchor pose, camera K และ local floor/route model
5. **Route cursor**: project ตำแหน่งลง polyline และรักษา segment เดิมด้วย hysteresis ไม่ให้ nearest-node flip จาก noise
6. **Correction**: เมื่อ PnP ใหม่มา ให้แก้ offset แบบ weighted correction แทน teleport ทันที
7. **Rendering**: render จาก fused visual pose ทุก `requestAnimationFrame`; ไม่วาด world AR จากค่า localization ล่าสุดเพียงอย่างเดียว
8. **Fail-safe**: ถ้า flow quality ต่ำ ให้คงตำแหน่งล่าสุด/ลด opacity ของ AR ชั่วคราวและขอ global fix ใหม่ ไม่เดาตำแหน่งไกล ๆ

### ทำไมควรเริ่มจากวิธีนี้

- เปลี่ยนเฉพาะ front-end และ pose bridge ไม่ต้องรื้อ localizer/แผนที่ทั้งหมด
- ใช้ compute ต่ำกว่า full SLAM
- ทำงานได้โดยไม่ต้องใช้ IMU และไม่ผูกกับ ARCore/ARKit
- แก้ปัญหาหลักของระบบปัจจุบันโดยตรง คือช่องว่างระหว่าง update ที่ห่างประมาณ 1 วินาที
- ยอมรับข้อจำกัดของ monocular scale ด้วยการให้แผนที่และ PnP เป็นตัวคุมระยะยาว

## แผนการทดลองที่ควรทำ

ใช้วิดีโอเดียวกันทุกวิธีเพื่อเทียบกันได้:

- input: `D:\video\video_from_iphone_oak_wide\IMG_6955.MOV`
- floor: `floor1`
- destination: `M21_A` หรือ alias `m21`
- ใช้ช่วงก่อนถึงปลายทางแยกจากช่วงหลังถึงปลายทาง/เดินย้อนกลับ เพราะคลิปนี้เดินต่อหลังถึงจุดหมาย

### Ablation

| ชุดทดลอง | วิธี | เป้าหมาย |
|---|---|---|
| A | PnP ปัจจุบัน + hold/EMA | baseline ความถูกต้องและ jitter |
| B | PnP + KLT propagation ไม่มี route constraint | วัดประโยชน์ของ visual motion ล้วน |
| C | PnP + KLT + affine/homography quality gate | ดูว่าการ reject flow ที่ไม่เสถียรลด jump ได้หรือไม่ |
| D | PnP + KLT + route cursor + 2.5D constraints | candidate ที่เหมาะกับ WayfindAR ที่สุด |
| E | ORB-SLAM2/visual keyframe localization | baseline ของ full visual SLAM; ทำเมื่อ A–D มีผลแล้ว |

### Metrics

- visual update rate ของ pose และ render rate
- capture-to-overlay latency p50/p95
- จำนวนเฟรมที่มี pose ต่อเนื่อง
- จำนวน track loss, PnP reject และ visual jump
- frame-to-frame displacement standard deviation และ jerk ของ AR pose
- lateral error จาก route และ error ของ map position เทียบกับ global PnP ที่ผ่าน gate
- endpoint/arrival error ก่อนถึง M21_A
- false arrival และการสลับ segment หลังถึงปลายทาง
- CPU, memory และเวลาจากเปิดกล้องจนได้ visual tracking ครั้งแรก

เกณฑ์เบื้องต้นสำหรับ prototype ไม่ควรดูแค่ความนุ่มของภาพ: ต้องผ่านทั้ง `pose update ≥ 15 Hz`, ลด jump ที่เห็นได้ชัด, และไม่เพิ่ม route error/false arrival เมื่อเทียบกับ baseline

## จุดที่ต้องระวัง

1. **Flow ไม่ได้ทำให้ตำแหน่ง absolute ถูกต้องเอง**: ถ้าเริ่มจาก anchor ผิดหรือสะสม drift นานเกินไป ภาพจะลื่นแต่ AR อาจลื่นไปผิดที่
2. **Homography ไม่ใช่คำตอบทั่วไป**: ใช้ได้ดีกับพื้นผิวระนาบหรือ pure rotation; ทางเดินจริงมี parallax จึงต้องมี quality gate
3. **การ filter หนักเกินไปทำให้ lag**: ควร filter correction แยกจาก relative motion และเพิ่ม adaptive gain ตอนผู้ใช้เลี้ยว
4. **motion blur และ rolling shutter**: เป็น failure mode สำคัญของ monocular visual odometry ต้องบันทึก confidence และหยุด propagation เมื่อคุณภาพตก
5. **การส่งภาพขึ้น backend ไม่ทัน**: visual propagation สำหรับ live ต้องทำใน browser/worker หรือเพิ่ม frame rate ของ endpoint; backend ที่เห็นเพียงภาพทุก 1 วินาทีไม่สามารถสร้างรายละเอียดการเคลื่อนที่ที่ไม่ได้ส่งมาได้

## คำตอบต่อคำถาม “ไม่ใช้ IMU แล้วสมูทได้ไหม”

ได้ในแง่ความต่อเนื่องของการวาดและการเคลื่อนที่ระหว่างเฟรม โดยเฉพาะถ้าใช้ KLT/optical flow ที่ 15–30 Hz แล้ว render ที่ 60 FPS แต่จะไม่เทียบเท่า IMU หรือ full SLAM ในแง่การคาดการณ์ระหว่างภาพเบลอ/ไม่มี texture และการรักษา scale ระยะยาว

สำหรับ WayfindAR จึงแนะนำให้ทำ **PnP/VPR เป็น global correction + visual KLT propagation + route-constrained 2.5D filter** เป็นลำดับแรก แล้วค่อยพิจารณา direct VO หรือ ORB-SLAM2 หากผลทดสอบยังไม่พอ การเริ่มจาก full SLAM ทันทีมีต้นทุนและความเสี่ยงสูงกว่าปัญหาที่กำลังแก้อยู่

## แหล่งอ้างอิงหลัก

- Lucas, Kanade. *An Iterative Image Registration Technique with an Application to Stereo Vision*. 1981.  [ลิงก์](https://idl.uw.edu/living-papers-paper/lucas-kanade/)
- Prince, Xu, Cheok. *Augmented Reality Camera Tracking with Homographies*. IEEE Computer Graphics and Applications, 2002.  [ลิงก์ DOI](https://doi.org/10.1109/MCG.2002.1046627)
- Bleser et al. *Real-time camera tracking for marker-less and unprepared augmented reality environments*. Image and Vision Computing, 2008.  [ลิงก์](https://www.sciencedirect.com/science/article/abs/pii/S0262885607001266)
- Klein, Murray. *Parallel Tracking and Mapping for Small AR Workspaces*. ISMAR, 2007.  [ลิงก์](https://www.robots.ox.ac.uk/~lav/Papers/klein_murray_ismar2007/)
- Schöps, Engel, Cremers. *Semi-Dense Visual Odometry for AR on a Smartphone*. ISMAR, 2014.  [PDF](https://jakobengel.github.io/pdf/schoeps14ismar.pdf)
- Mur-Artal, Tardós. *ORB-SLAM2*. IEEE T-RO, 2017.  [arXiv](https://arxiv.org/abs/1610.06475)
- Engel, Koltun, Cremers. *Direct Sparse Odometry*. 2016.  [arXiv](https://arxiv.org/abs/1607.02565)
- Kitt et al. *Monocular Visual Odometry using a Planar Road Model to Solve Scale Ambiguity*. ECMR, 2011.  [PDF](https://www.ri.cmu.edu/pub_files/2011/9/ECMR2011.pdf)
- Zhou, Dai, Li. *Ground Plane based Absolute Scale Estimation for Monocular Visual Odometry*. 2019.  [arXiv](https://arxiv.org/abs/1903.00912)
- Lutwak, Murdison, Rio. *User Self-Motion Modulates the Perceptibility of Jitter for World-locked Objects in AR*. ISMAR, 2023.  [IEEE](https://ieeexplore.ieee.org/document/10316484/)

