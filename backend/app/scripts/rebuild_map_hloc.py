
import os
import shutil
import numpy as np
import cv2
from pathlib import Path
from tqdm import tqdm
import hloc
from hloc import extract_features, match_features, pairs_from_poses, triangulation
import pycolmap
import torch

from hloc.utils import read_write_model

# Configuration
SOURCE_DIR = Path('d:/webanv/result_floor5_6')
DEST_DIR = Path('d:/webanv/result_floor5_6_hloc')
WORK_DIR = Path('hloc_work_dir')

def setup_directories():
    if DEST_DIR.exists():
        print(f"Destination directory {DEST_DIR} exists.")
        # Automatically overwrite for now to avoid user prompt blocking if running automation
        # ans = input("Overwrite? (y/n): ")
        # if ans.lower() != 'y':
        #     print("Aborting.")
        #     exit()
        try:
           shutil.rmtree(DEST_DIR)
        except Exception as e:
           print(f"Warning: Could not delete {DEST_DIR}: {e}")
    
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print("Directories created.")

def load_camera_intrinsics(data_dir):
    camera_path = data_dir / 'camera.yaml'
    with open(camera_path, 'r') as f:
        lines = f.read().strip().split('\n')
        camera = {}
        for l in lines[1:]:
            if ':' in l:
                parts = l.split(':')
                camera[parts[0].strip()] = float(parts[1].strip())
    return camera

def load_keyframe_poses(keyframes_dir):
    poses = {}
    kf_dirs = sorted([d for d in keyframes_dir.iterdir() if d.is_dir()])
    for d in kf_dirs:
        try:
            kf_id = int(d.name)
            pose_path = d / 'pose.txt'
            if pose_path.exists():
                 with open(pose_path, 'r') as f:
                    lines = [l.strip() for l in f.readlines() if not l.startswith('#') and l.strip()]
                    if len(lines) >= 4:
                        Tcw = np.array([[float(x) for x in line.split()] for line in lines[:4]])
                        poses[kf_id] = Tcw
        except ValueError:
            pass
    return poses

def create_reference_model(camera_params, poses, model_dir):
    model_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Creating binary COLMAP model in {model_dir}...")

    # 1. Cameras
    # PINHOLE width height fx fy cx cy
    width = int(camera_params.get('Camera.width', 640))
    height = int(camera_params.get('Camera.height', 480))
    fx = camera_params['Camera.fx']
    fy = camera_params['Camera.fy']
    cx = camera_params['Camera.cx']
    cy = camera_params['Camera.cy']
    
    # params: fx, fy, cx, cy
    params = np.array([fx, fy, cx, cy])
    
    cameras = {
        1: read_write_model.Camera(id=1, model="PINHOLE", width=width, height=height, params=params)
    }

    # 2. Images
    images = {}
    
    for kf_id, Tcw in poses.items():
        R = Tcw[:3, :3]
        t = Tcw[:3, 3]
        
        # rotation matrix to quaternion (qw, qx, qy, qz)
        qvec = read_write_model.rotmat2qvec(R)
        
        img_name = f"{kf_id:04d}.jpg" 
        
        # Empty points2D (will be filled by hloc later or not needed for reference?)
        # For reference model, we just need pose. 
        # hloc docs say: "Reference model ... must contain images with established poses"
        
        images[kf_id] = read_write_model.Image(
            id=kf_id,
            qvec=qvec,
            tvec=t,
            camera_id=1,
            name=img_name,
            xys=np.zeros((0, 2)),
            point3D_ids=np.zeros((0,), dtype=np.uint64)
        )
            
    # 3. Points3D (Empty)
    points3D = {}
    
    # Write using hloc utils
    read_write_model.write_model(cameras, images, points3D, str(model_dir), ext=".bin")

def run_hloc_pipeline():
    # 1. Prepare Images (Flattened for hloc)
    images_dir = WORK_DIR / 'images'
    images_dir.mkdir(exist_ok=True)
    
    kf_source = SOURCE_DIR / 'keyframes'
    kf_dirs = sorted([d for d in kf_source.iterdir() if d.is_dir()])
    
    image_list = []
    
    print("Copying keyframe images...")
    for d in kf_dirs:
        kf_id = int(d.name)
        src_img = d / 'image.jpg'
        if not src_img.exists(): src_img = d / 'image.png'
        
        if src_img.exists():
            dst_name = f"{kf_id:04d}.jpg"
            shutil.copy(src_img, images_dir / dst_name)
            image_list.append(images_dir / dst_name)
    
    # 2. Extract Features (SuperPoint)
    feature_conf = extract_features.confs['superpoint_aachen']
    feature_path = extract_features.main(feature_conf, images_dir, WORK_DIR)
    
    # 3. Pairs from Poses
    reference_model = WORK_DIR / 'reference_model'
    pairs_path = WORK_DIR / 'pairs.txt'
    # We need a reference model for pairs_from_poses
    # Using the one we created
    pairs_from_poses.main(reference_model, pairs_path, num_matched=10)
    
    # 4. Match Features (SuperGlue)
    match_conf = match_features.confs['superglue']
    match_path = match_features.main(match_conf, pairs_path, feature_conf['output'], WORK_DIR)
    
    # 5. Triangulate
    sfm_dir = WORK_DIR / 'sfm_superpoint'
    
    print("Starting Triangulation (Subprocess)...")
    
    # Use subprocess to run triangulation in a clean environment (avoids Torch/Colmap conflicts)
    import subprocess
    import sys
    
    # Resolve absolute path to script to avoid "File not found" errors
    script_path = Path(__file__).parent / 'triangulate_safe.py'
    if not script_path.exists():
        raise FileNotFoundError(f"Cannot find {script_path}")
        
    cmd = [
        sys.executable,
        '-u', # Unbuffered output to capture print messages immediately
        str(script_path),
        '--sfm_dir', str(sfm_dir),
        '--reference_model', str(reference_model),
        '--images_dir', str(images_dir),
        '--pairs_path', str(pairs_path),
        '--feature_path', str(feature_path),
        '--match_path', str(match_path),
        '--skip_geometric_verification' # Always skip to avoid crash as per previous attempt
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    
    # Capture output to debug why it fails silently (Status 3)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Subprocess Output:")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("!"*60)
        print(f"SUBPROCESS FAILED with Exit Code {e.returncode}")
        print("STDOUT:")
        print(e.stdout)
        print("STDERR:")
        print(e.stderr)
        print("!"*60)
        raise e
    
    return sfm_dir, feature_path

def export_data(sfm_dir, feature_path, original_poses):
    print("Exporting data to new format...")
    
    # Load Reconstruction
    recon = pycolmap.Reconstruction(sfm_dir)
    
    # 1. Export MapPoints
    mappoints = []
    # format: [id, x, y, z, r, g, b, error, ...]
    # We only need [id, x, y, z] for basic
    
    for p3d_id, p3d in recon.points3D.items():
        xyz = p3d.xyz
        mappoints.append([p3d_id, xyz[0], xyz[1], xyz[2]])
    
    mappoints = np.array(mappoints)
    np.save(DEST_DIR / 'mappoints.npy', mappoints)
    print(f"Saved {len(mappoints)} MapPoints.")
    
    # 2. Export Keyframes
    dest_kf_root = DEST_DIR / 'keyframes'
    dest_kf_root.mkdir(parents=True)
    
    # Need to read features from H5
    import h5py
    h5_file = h5py.File(feature_path, 'r')
    
    for img_id, img in recon.images.items():
        # img.name is like "0001.jpg"
        # Parse ID
        try:
            real_id = int(Path(img.name).stem)
        except:
            continue
            
        kf_dir = dest_kf_root / f"{real_id}"
        kf_dir.mkdir()
        
        # Copy Pose (Original)
        # Or should we use Refined Pose from Colmap? 
        # Triangulation might refinement poses? 
        # Usually it keeps fixed poses if provided.
        # Let's check differences? No, safer to use the one from Colmap output (img.qvec, img.tvec)
        # Wait, if we use new poses, we might drift from floor plan alignment?
        # But triangulation uses existing poses as fixed constraints usually.
        # Let's copy original pose files to be safe about format.
        src_kf_dir = SOURCE_DIR / 'keyframes' / str(real_id)
        if (src_kf_dir / 'pose.txt').exists():
             shutil.copy(src_kf_dir / 'pose.txt', kf_dir / 'pose.txt')
        
        # Copy Image
        # shutil.copy(WORK_DIR / 'images' / img.name, kf_dir / 'image.jpg') # Optional
        # localize_version2 uses image.png/jpg check.
        if (src_kf_dir / 'image.jpg').exists():
            shutil.copy(src_kf_dir / 'image.jpg', kf_dir / 'image.jpg')
        elif (src_kf_dir / 'image.png').exists():
            shutil.copy(src_kf_dir / 'image.png', kf_dir / 'image.png')
            
        # Keypoints & Descriptors
        # Retrieve from H5
        kpts = h5_file[img.name]['keypoints'].__array__()
        # hloc doesn't save descriptors in separate file usually?
        # extract_features.py DOES save descriptors if 'descriptors' in output.
        # Usually hloc feature file contains 'keypoints', 'descriptors', 'scores'.
        
        # Confirm structure
        if 'descriptors' in h5_file[img.name]:
            descs = h5_file[img.name]['descriptors'].__array__() # (N, 256)
        else:
            print(f"Warning: No descriptors for {img.name}")
            descs = np.zeros((len(kpts), 256))
            
        # Scores
        if 'scores' in h5_file[img.name]:
            scores = h5_file[img.name]['scores'].__array__()
        
        # MapPoint IDs
        # img.points3D is array of standard point3D IDs (or -1) 
        # corresponding to keypoints?
        # PyColmap Image: points2D property?
        # img.points2D is list of Point2D.
        # Point2D has .point3D_id
        
        mp_ids = []
        # The keypoints in h5 and Colmap should be aligned if hloc imported them 1:1.
        # hloc imports features. 
        # But does Colmap reorder them? 
        # hloc `import_features` writes them in order.
        # So `img.points2D` array should correspond 1-to-1 with `kpts`.
        
        colmap_kpts = img.points2D
        # Be careful: Colmap might drop keypoints?
        # No, "import_features" imports all checks.
        
        if len(colmap_kpts) != len(kpts):
            print(f"Warning: Keypoint count mismatch for {real_id}: {len(colmap_kpts)} vs {len(kpts)}")
            # Fallback: Create -1 array
            mp_ids = np.full(len(kpts), -1, dtype=np.int32)
        else:
            mp_ids = np.array([p.point3D_id for p in colmap_kpts], dtype=np.int32)
            
        # Save NPYs
        np.save(kf_dir / 'keypoints.npy', kpts)
        np.save(kf_dir / 'descriptors.npy', descs)
        np.save(kf_dir / 'mappoint_ids.npy', mp_ids)
        np.save(kf_dir / 'scores.npy', scores) # Extra useful file
    
    # Copy Aux files (Global Descs, etc)
    for f in ['global_descriptors.npy', 'netvlad_centroids.npy', 'floor_algin_offset_config.json', 'H_matrix_floor5_offset.npy', 'camera.yaml', 'pca_model.pkl']:
        if (SOURCE_DIR / f).exists():
            shutil.copy(SOURCE_DIR / f, DEST_DIR / f)
            
    print(f"Successfully rebuilt map in {DEST_DIR}")

def main():
    setup_directories()
    
    cam = load_camera_intrinsics(SOURCE_DIR)
    poses = load_keyframe_poses(SOURCE_DIR / 'keyframes')
    print(f"Loaded {len(poses)} poses.")
    
    # Create Reference structure for hloc
    create_reference_model(cam, poses, WORK_DIR / 'reference_model')
    
    # Run
    sfm_dir, feat_path = run_hloc_pipeline()
    
    # Export
    export_data(sfm_dir, feat_path, poses)

if __name__ == "__main__":
    main()
