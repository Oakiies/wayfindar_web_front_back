import unittest
import numpy as np
from world_ar import fixed_arrows, clip_near, fit_floor, plane_intersection

class GeometryTests(unittest.TestCase):
    def test_anchors_on_floor_and_orthogonal_width(self):
        n=np.array([0.,1.,0.])
        route=np.array([[0.,1.,0.],[1.,1.,3.],[4.,1.,3.]])
        arrows=fixed_arrows(route,n,.1)
        self.assertGreater(len(arrows),5)
        for arrow in arrows:
            np.testing.assert_allclose(arrow['polygon']@n,1.)
            # The two arm tips are 0.60m apart, including on diagonal paths.
            self.assertAlmostEqual(np.linalg.norm(arrow['polygon'][2]-arrow['polygon'][0]),.06)

    def test_near_plane_clips_crossing_polygon(self):
        poly=np.array([[-1,-1,-1],[1,-1,2],[1,1,2],[-1,1,-1]],float)
        result=clip_near(poly,.25)
        self.assertEqual(len(result),4)
        self.assertTrue(np.isfinite(result).all())
        self.assertTrue((result[:,2]>=.25-1e-10).all())

    def test_plane_fit_rejects_outliers(self):
        rng=np.random.default_rng(4)
        points=rng.normal(size=(80,3))
        points[:60,1]=.2+rng.normal(0,.001,60)
        n,d,inliers=fit_floor(points,[0,1,0])
        self.assertGreater(inliers.sum(),55)
        self.assertLess(abs(d-.2),.003)
        self.assertGreater(n[1],.999)

    def test_intersection_preserves_map_plane_coordinates(self):
        p=np.array([1.,4.,2.])
        q=plane_intersection(p,np.array([0.,1.,0.]),np.array([0.,1.,0.]),.5)
        np.testing.assert_allclose(q,[1,.5,2])

if __name__=='__main__': unittest.main()
