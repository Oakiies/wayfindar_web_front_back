from pathlib import Path
import subprocess
import imageio_ffmpeg

root=Path(__file__).resolve().parent
warm=root/'warmup_0_20.mp4'
ar=root/'IMG_1895_AR_20_60.mp4'
out=root/'IMG_1895_AR_0_60.mp4'
ff=imageio_ffmpeg.get_ffmpeg_exe()
subprocess.run([ff,'-y','-loglevel','error','-i',str(warm),'-i',str(ar),
    '-filter_complex','[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]',
    '-map','[v]','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(out)],check=True)
print(out)
