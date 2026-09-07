"""
hloc Wrapper Module
Provides a clean interface to use hloc's SuperPoint and SuperGlue for the navigation system.
"""

import numpy as np
import torch
import cv2
from pathlib import Path
from typing import Tuple, Optional, Dict
import warnings
warnings.filterwarnings('ignore')

# Import hloc models directly
import sys
from hloc.utils.base_model import dynamic_load


class HlocExtractor:
    """
    Wrapper for hloc's SuperPoint feature extractor
    """
    def __init__(self, 
                 max_keypoints: int = 2048,
                 keypoint_threshold: float = 0.005,
                 nms_radius: int = 4,
                 device: str = 'auto'):
        """
        Initialize SuperPoint extractor
        
        Args:
            max_keypoints: Maximum number of keypoints to detect
            keypoint_threshold: Detector confidence threshold
            nms_radius: Non-maximum suppression radius
            device: 'cuda', 'cpu', or 'auto'
        """
        if device == 'auto':
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
            
        self.max_keypoints = max_keypoints
        self.keypoint_threshold = keypoint_threshold
        self.nms_radius = nms_radius
        
        # Load SuperPoint model using hloc's dynamic loader
        import hloc.extractors as extractors
        Model = dynamic_load(extractors, 'superpoint')
        self.model = Model({
            'nms_radius': nms_radius,
            'max_keypoints': max_keypoints,
            'keypoint_threshold': keypoint_threshold,
        }).eval().to(self.device)
        
        print(f"SuperPoint extractor initialized on {self.device}")
    
    def extract(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract SuperPoint features from an image
        
        Args:
            image: Input image (grayscale or BGR)
            
        Returns:
            keypoints: (N, 2) array of keypoint coordinates
            descriptors: (N, 256) array of feature descriptors (float32)
            scores: (N,) array of keypoint confidence scores
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Convert to tensor
        image_tensor = torch.from_numpy(image).float()[None, None] / 255.0
        image_tensor = image_tensor.to(self.device)
        
        # Extract features
        with torch.no_grad():
            pred = self.model({'image': image_tensor})
        
        # Convert to numpy
        keypoints = pred['keypoints'][0].cpu().numpy()  # (N, 2)
        descriptors = pred['descriptors'][0].T.cpu().numpy()  # (N, 256)
        # Handle different possible key names for scores
        if 'keypoint_scores' in pred:
            scores = pred['keypoint_scores'][0].cpu().numpy()  # (N,)
        elif 'scores' in pred:
            scores = pred['scores'][0].cpu().numpy()  # (N,)
        else:
            # If no scores, create dummy ones
            scores = np.ones(len(keypoints), dtype=np.float32)
        
        return keypoints, descriptors, scores


class HlocMatcher:
    """
    Wrapper for hloc's SuperGlue matcher
    """
    def __init__(self,
                 match_threshold: float = 0.2,
                 sinkhorn_iterations: int = 20,
                 device: str = 'auto'):
        """
        Initialize SuperGlue matcher
        
        Args:
            match_threshold: Matching confidence threshold
            sinkhorn_iterations: Number of Sinkhorn iterations
            device: 'cuda', 'cpu', or 'auto'
        """
        if device == 'auto':
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
            
        self.match_threshold = match_threshold
        self.sinkhorn_iterations = sinkhorn_iterations
        
        # Load SuperGlue model using hloc's dynamic loader
        import hloc.matchers as matchers
        Model = dynamic_load(matchers, 'superglue')
        self.model = Model({
            'weights': 'indoor',  # or 'outdoor'
            'sinkhorn_iterations': sinkhorn_iterations,
            'match_threshold': match_threshold,
        }).eval().to(self.device)
        
        print(f"SuperGlue matcher initialized on {self.device}")
    
    def match(self,
              kpts0: np.ndarray, desc0: np.ndarray, scores0: np.ndarray,
              kpts1: np.ndarray, desc1: np.ndarray, scores1: np.ndarray,
              image0_shape: Tuple[int, int] = None,
              image1_shape: Tuple[int, int] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Match features between two images using SuperGlue
        
        Args:
            kpts0, desc0, scores0: Keypoints, descriptors, scores from image 0
            kpts1, desc1, scores1: Keypoints, descriptors, scores from image 1
            image0_shape, image1_shape: Optional image shapes (H, W)
            
        Returns:
            matches: (M, 2) array of matched indices [idx0, idx1]
            match_confidence: (M,) array of matching confidence scores
        """
        # Prepare data for SuperGlue
        data = {
            'keypoints0': torch.from_numpy(kpts0).float()[None].to(self.device),
            'keypoints1': torch.from_numpy(kpts1).float()[None].to(self.device),
            'descriptors0': torch.from_numpy(desc0.T).float()[None].to(self.device),
            'descriptors1': torch.from_numpy(desc1.T).float()[None].to(self.device),
            'scores0': torch.from_numpy(scores0).float()[None].to(self.device),
            'scores1': torch.from_numpy(scores1).float()[None].to(self.device),
        }
        
        # SuperGlue normalises keypoints by the image size, so passing the wrong
        # size (the old 480x640 default) mis-normalises keypoints from larger
        # frames and yields ZERO matches. When the shape isn't given, infer it
        # from each image's keypoint bounding box.
        if image0_shape is not None:
            h0, w0 = image0_shape
        elif len(kpts0):
            w0 = int(np.max(kpts0[:, 0])) + 8
            h0 = int(np.max(kpts0[:, 1])) + 8
        else:
            h0, w0 = 480, 640

        if image1_shape is not None:
            h1, w1 = image1_shape
        elif len(kpts1):
            w1 = int(np.max(kpts1[:, 0])) + 8
            h1 = int(np.max(kpts1[:, 1])) + 8
        else:
            h1, w1 = 480, 640
        
        data['image0'] = torch.zeros(1, 1, h0, w0).to(self.device)
        data['image1'] = torch.zeros(1, 1, h1, w1).to(self.device)
        
        # Match
        with torch.no_grad():
            pred = self.model(data)
        
        # Extract matches
        matches = pred['matches0'][0].cpu().numpy()  # (N0,) with values in [-1, N1-1]
        match_confidence = pred['matching_scores0'][0].cpu().numpy()  # (N0,)
        
        # Convert to match pairs
        valid = matches > -1
        match_indices = np.stack([
            np.where(valid)[0],
            matches[valid]
        ], axis=1).astype(np.int32)
        
        match_scores = match_confidence[valid]
        
        return match_indices, match_scores


def match_2d_3d_superglue(query_kpts: np.ndarray, 
                          query_desc: np.ndarray,
                          query_scores: np.ndarray,
                          kf_kpts: np.ndarray,
                          kf_desc: np.ndarray,
                          kf_scores: np.ndarray,
                          kf_mp_ids: np.ndarray,
                          mappoint_dict: Dict,
                          matcher: HlocMatcher,
                          min_matches: int = 4) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Match 2D features to 3D points using SuperGlue
    
    Args:
        query_kpts, query_desc, query_scores: Query image features
        kf_kpts, kf_desc, kf_scores: Keyframe features
        kf_mp_ids: MapPoint IDs for keyframe keypoints
        mappoint_dict: Dictionary mapping MapPoint ID to 3D coordinates
        matcher: HlocMatcher instance
        min_matches: Minimum number of matches required
        
    Returns:
        points_2d: (N, 2) query image points
        points_3d: (N, 3) corresponding 3D world points
    """
    if query_desc is None or kf_desc is None:
        return None, None
    
    if len(query_desc) < min_matches or len(kf_desc) < min_matches:
        return None, None
    
    # Match using SuperGlue
    match_indices, match_scores = matcher.match(
        query_kpts, query_desc, query_scores,
        kf_kpts, kf_desc, kf_scores
    )
    
    if len(match_indices) < min_matches:
        return None, None
    
    # Build 2D-3D correspondences
    points_2d = []
    points_3d = []
    
    for query_idx, kf_idx in match_indices:
        # Get MapPoint ID from keyframe
        mp_id = int(kf_mp_ids[kf_idx])
        
        if mp_id > 0 and mp_id in mappoint_dict:
            # Add 2D point from query
            points_2d.append(query_kpts[query_idx])
            # Add 3D point from map
            points_3d.append(mappoint_dict[mp_id])
    
    if len(points_2d) < min_matches:
        return None, None
    
    return np.array(points_2d, dtype=np.float32), np.array(points_3d, dtype=np.float32)


# [NEW] Helper functions for direct usage
# These wrappers make it easier to use the classes above
# and match the interface expected by app.py

# Global instances (lazy loaded)
_extractor = None
_matcher = None

def extract_superpoint_features(image: np.ndarray):
    """
    Helper function to extract features using the global extractor instance
    """
    global _extractor
    if _extractor is None:
        _extractor = HlocExtractor(max_keypoints=2048)
        
    return _extractor.extract(image)

def match_superglue(kpts0, desc0, kpts1, desc1, image0=None, image1=None):
    """
    Helper function to match features using the global matcher instance
    """
    global _matcher
    if _matcher is None:
        _matcher = HlocMatcher()
        
    # Create dummy scores since they act as weights
    scores0 = np.ones(len(kpts0), dtype=np.float32)
    scores1 = np.ones(len(kpts1), dtype=np.float32)
    
    # Get image shapes if provided
    shape0 = image0.shape[:2] if image0 is not None else None
    shape1 = image1.shape[:2] if image1 is not None else None
    
    matches, match_scores = _matcher.match(
        kpts0, desc0, scores0,
        kpts1, desc1, scores1,
        shape0, shape1
    )
    
    return {
        'matches': matches,
        'match_confidence': match_scores
    }

if __name__ == "__main__":
    print("Testing hloc wrapper...")
    
    # Initialize extractor and matcher
    extractor = HlocExtractor(max_keypoints=1024)
    matcher = HlocMatcher()
    
    # Test with a dummy image
    test_image = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
    
    # Extract features
    kpts, desc, scores = extractor.extract(test_image)
    
    print(f"\nExtracted {len(kpts)} keypoints")
    print(f"Descriptor shape: {desc.shape}")
    print(f"Descriptor dtype: {desc.dtype}")
    print(f"Scores shape: {scores.shape}")
    
    # Test matching with itself
    matches, match_scores = matcher.match(kpts, desc, scores, kpts, desc, scores)
    
    print(f"\nMatched {len(matches)} features")
    print(f"Match confidence range: [{match_scores.min():.3f}, {match_scores.max():.3f}]")
    
    # Test helper functions
    print("\nTesting helper functions...")
    _, _, _ = extract_superpoint_features(test_image)
    res = match_superglue(kpts, desc, kpts, desc)
    print(f"Helper match result keys: {res.keys()}")
    
    print("\nhloc wrapper test completed successfully!")
