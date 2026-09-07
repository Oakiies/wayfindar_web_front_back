
print("DEBUG: triangulate_safe.py started")
import sys
import traceback

try:
    print("DEBUG: Importing standard libs...")
    import argparse
    from pathlib import Path

    # Attempt to mitigate DLL hell (OpenCV vs PyCOLMAP)
    # Importing OpenCV first often solves conflicts
    print("DEBUG: Pre-importing cv2...")
    try:
        import cv2
        print(f"DEBUG: cv2 version: {cv2.__version__}")
    except ImportError:
        print("DEBUG: cv2 not found via direct import")

    print("DEBUG: Adding path...")
    sys.path.append(str(Path(__file__).parent))

    print("DEBUG: Importing hloc.triangulation...")
    from hloc import triangulation
    
    print("DEBUG: Importing pycolmap (verification)...")
    import pycolmap
    print(f"DEBUG: pycolmap version: {pycolmap.__version__}")

except Exception:
    print("FATAL ERROR during imports:")
    traceback.print_exc()
    sys.exit(101)

def main():
    print("DEBUG: Entering main()...")
    parser = argparse.ArgumentParser()
    parser.add_argument('--sfm_dir', type=Path, required=True)
    parser.add_argument('--reference_model', type=Path, required=True)
    parser.add_argument('--images_dir', type=Path, required=True)
    parser.add_argument('--pairs_path', type=Path, required=True)
    parser.add_argument('--feature_path', type=Path, required=True)
    parser.add_argument('--match_path', type=Path, required=True)
    parser.add_argument('--skip_geometric_verification', action='store_true')
    args = parser.parse_args()

    print(f"Calling hloc.triangulation.main with:")
    print(f" - sfm_dir: {args.sfm_dir}")
    print(f" - skip_geo: {args.skip_geometric_verification}")
    
    try:
        triangulation.main(
            sfm_dir=args.sfm_dir,
            reference_model=args.reference_model,
            image_dir=args.images_dir,
            pairs=args.pairs_path,       
            features=args.feature_path,  
            matches=args.match_path,     
            skip_geometric_verification=args.skip_geometric_verification
        )
        print("Triangulation completed successfully in subprocess.")
    except Exception:
        print("FATAL ERROR during triangulation execution:")
        traceback.print_exc()
        sys.exit(102)

if __name__ == "__main__":
    main()
