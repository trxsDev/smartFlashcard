import cv2
import numpy as np
import os

class FeatureMatcher:
    def __init__(self, source_dir):
        """Initializes the SIFT matcher and pre-calculates features for the reference images."""
        # Standard/slightly sensitive SIFT to avoid capturing noise
        self.sift = cv2.SIFT_create(contrastThreshold=0.03, edgeThreshold=10)
        self.references = {}
        # MIN_MATCH_COUNT: Increased to 25 for stricter matching (requires more points to confirm)
        self.MIN_MATCH_COUNT = 25
        
        # Initialize FLANN matcher
        FLANN_INDEX_KDTREE = 1
        index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
        # Increased checks to 100 for more accurate (but slightly slower) matching
        search_params = dict(checks=100)
        self.flann = cv2.FlannBasedMatcher(index_params, search_params)

        print(f"FeatureMatcher: Loading references from {source_dir}...")
        self._load_reference_images(source_dir)
        print(f"FeatureMatcher: Loaded {len(self.references)} reference classes.")

    def _load_reference_images(self, source_dir):
        if not os.path.exists(source_dir):
            print(f"Error: Directory '{source_dir}' not found.")
            return

        for filename in os.listdir(source_dir):
            if not filename.lower().endswith(('png', 'jpg', 'jpeg')):
                continue
                
            filepath = os.path.join(source_dir, filename)
            img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
            
            if img is None:
                continue
            
            # If it has an alpha channel, composite it onto a white background
            if img.shape[2] == 4:
                alpha = img[:, :, 3] / 255.0
                bg = np.ones_like(img[:, :, :3]) * 255
                img_bgr = img[:, :, :3]
                img_composed = np.zeros_like(img_bgr)
                for c in range(3):
                    img_composed[:, :, c] = (alpha * img_bgr[:, :, c] + (1 - alpha) * bg[:, :, c])
                img_gray = cv2.cvtColor(img_composed.astype(np.uint8), cv2.COLOR_BGR2GRAY)
            else:
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                
            # Optional: Resize reference image if too large
            max_dim = 800
            h, w = img_gray.shape
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                img_gray = cv2.resize(img_gray, None, fx=scale, fy=scale)
                
            kp, des = self.sift.detectAndCompute(img_gray, None)
            
            if des is not None:
                class_name = os.path.splitext(filename)[0]
                self.references[class_name] = {
                    'keypoints': kp,
                    'descriptors': des,
                    'dims': img_gray.shape # (h, w)
                }

    def predict(self, frame_bgr, target_class=None):
        """
        Attempts to find a target class in the given frame using SIFT.
        Returns a detection dict if found, else None.
        If target_class is specified, it only searches for that class to speed it up.
        """
        frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        kp_frame, des_frame = self.sift.detectAndCompute(frame_gray, None)
        
        if des_frame is None or len(des_frame) == 0:
            return None
            
        best_match_class = None
        best_match_count = -1
        best_dst = None
        
        classes_to_check = [target_class] if target_class else self.references.keys()
        
        for cls_name in classes_to_check:
            if cls_name not in self.references:
                continue
                
            ref_data = self.references[cls_name]
            des_ref = ref_data['descriptors']
            
            if des_ref is None or len(des_ref) < 2:
                continue
                
            try:
                matches = self.flann.knnMatch(des_ref, des_frame, k=2)
            except Exception as e:
                continue
            
            # Lowe's ratio test - stricter ratio to filter weak matches (reduce from 0.65 down to 0.60 for high accuracy)
            good_matches = []
            for match_tuple in matches:
                if len(match_tuple) == 2:
                    m, n = match_tuple
                    if m.distance < 0.60 * n.distance:
                        good_matches.append(m)
            
            if len(good_matches) > self.MIN_MATCH_COUNT and len(good_matches) > best_match_count:
                # Try to find homography
                src_pts = np.float32([ref_data['keypoints'][m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                dst_pts = np.float32([kp_frame[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                
                M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
                
                if M is not None:
                    matchesMask = mask.ravel().tolist()
                    inliers = sum(matchesMask)
                    
                    if inliers > self.MIN_MATCH_COUNT and inliers > best_match_count:
                        # Verify if the transformed polygon is a valid convex shape
                        h, w = ref_data['dims']
                        pts = np.float32([[0, 0], [0, h - 1], [w - 1, h - 1], [w - 1, 0]]).reshape(-1, 1, 2)
                        dst = cv2.perspectiveTransform(pts, M)
                        
                        if cv2.isContourConvex(np.int32(dst)):
                            # Geometric Cross-Check
                            pts_int = np.int32(dst).reshape(-1, 2)
                            x, y, w_box, h_box = cv2.boundingRect(pts_int)
                            
                            if w_box > 0 and h_box > 0:
                                # 1. Aspect Ratio Check
                                ref_aspect = w / float(h)
                                box_aspect = w_box / float(h_box)
                                aspect_ratio_diff = abs(ref_aspect - box_aspect) / ref_aspect
                                
                                # 2. Area Check (preventing extremely tiny or massive matches from noise)
                                box_area = w_box * h_box
                                frame_area = frame_bgr.shape[0] * frame_bgr.shape[1]
                                area_ratio = box_area / float(frame_area)
                                
                                # Only accept if aspect ratio is within 50% error and area is at least 1% of frame
                                if aspect_ratio_diff < 0.50 and 0.01 < area_ratio < 0.80:
                                    best_match_count = inliers
                                    best_match_class = cls_name
                                    best_dst = dst
        
        if best_match_class and best_dst is not None:
            # Convert polygon back to bounding box for YOLO-like compatibility
            pts = np.int32(best_dst).reshape(-1, 2)
            x, y, w, h = cv2.boundingRect(pts)
            return {
                "class_name": best_match_class,
                "bbox": (x, y, x + w, y + h),
                "inliers": best_match_count,
                "polygon": pts
            }
            
        return None
