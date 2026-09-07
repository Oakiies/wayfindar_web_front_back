"""
Localization pipeline configuration.

This is the single place to tune retrieval, matching, and smoothing.
Change RETRIEVAL_MODE to switch backends; adjust params below as needed.
"""

# ── Retrieval backend ──────────────────────────────────────────────────────────
# Available modes: 'cosplace' | 'megaloc' | 'netvlad'
# Must also have the corresponding descriptor .npy file built for your map.
# Run the matching extract script first: extract/extract_<mode>_features.py
RETRIEVAL_MODE = 'megaloc'

BACKEND_CONFIGS = {
    'cosplace': {
        'descriptor_file': 'global_descriptors_cosplace.npy',
        'pca_file':        'pca_model_cosplace.pkl',
        'input_size':      (320, 320),
        'weights_path':    '',       # empty → torch.hub auto-download
        'backbone':        'ResNet50',
        'output_dim':      2048,
    },
    'megaloc': {
        # MegaLoc: DINOv2 + SALAD aggregation
        # Paper: https://arxiv.org/abs/2502.17237
        # Weights: auto-downloaded from HuggingFace (gmberton/MegaLoc)
        'descriptor_file': 'global_descriptors_megaloc.npy',
        'pca_file':        '',       # MegaLoc descriptors are already L2-normalized, no PCA needed
        'input_size':      (518, 518),   # DINOv2 native size (must be multiple of 14)
        'output_dim':      8448,
    },
    'netvlad': {
        'descriptor_file': 'global_descriptors.npy',
        'pca_file':        'pca_model.pkl',
        'input_size':      (480, 640),
        'centroids_file':  'netvlad_centroids.npy',
    },
    # Built by extract/extract_vpr_features.py. input_size must stay in step with
    # MODEL_INPUT_SIZES there — query and database descriptors are only
    # comparable when both sides use the same preprocessing.
    'salad8192': {
        # DINOv2 + SALAD via torch.hub (serizba/salad); 8448-dim in practice.
        'descriptor_file': 'global_descriptors_salad8192.npy',
        'pca_file':        '',
        'input_size':      (322, 322),
        'output_dim':      8448,
    },
    'mixvpr4096': {
        'descriptor_file': 'global_descriptors_mixvpr4096.npy',
        'pca_file':        '',
        'input_size':      (320, 320),
        'output_dim':      4096,
        'repo_path':       'external/MixVPR',
        'weights_path':    'weights/resnet50_MixVPR_4096_channels_1024_rows_4.ckpt',
    },
    'mixvpr512': {
        'descriptor_file': 'global_descriptors_mixvpr512.npy',
        'pca_file':        '',
        'input_size':      (320, 320),
        'output_dim':      512,
        'repo_path':       'external/MixVPR',
        'weights_path':    'weights/resnet50_MixVPR_512_channels_256_rows_2.ckpt',
    },
}

# ── Localization thresholds ────────────────────────────────────────────────────
LOCALIZATION_PARAMS = {
    'top_k':                  10,    # candidate keyframes for global retrieval
    'reproj_threshold':        8.0,  # RANSAC max reprojection error (px)
    'min_inliers':             10,   # minimum PnP inliers to accept a pose
    'min_inlier_ratio':        0.15,
    'max_median_reproj_error': 9.0,  # final quality gate (px)
}

# ── Smoothing ──────────────────────────────────────────────────────────────────
# position.type:
#   'kalman' — current production smoother (Linear KF on x/y, separate angle smoother)
#   'ekf'    — Extended Kalman Filter; unicycle model, filters x/y/θ jointly
#              more physically consistent for walking; requires measured_heading each frame
SMOOTHER_CONFIG = {
    'position': {
        'type':              'ekf',  # 'kalman' | 'ekf'
        'process_noise':      2.0,
        'measurement_noise': 100.0,
        'min_init_frames':    3,        # frames before first output (3 = fast start)
    },
    'heading': {
        'window_size': 7,  # MedianWindowSmoother (used by both kalman and ekf for heading output)
    },
}
