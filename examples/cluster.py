import numpy as np
import open3d as o3d
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics import r2_score
import matplotlib.cm as cm

class PointCloudProcessor:
    def __init__(self, cylinder_radius=0.01, cylinder_height=1.0):
        self.cylinder_radius = cylinder_radius
        self.cylinder_height = cylinder_height

    def cluster(self, points, camera_pose, eps=0.1, min_samples=15):
        """
        Clusters the point cloud, fits cylinders, and returns them in the global frame.
        
        Args:
            points (np.ndarray): Nx3 array of point cloud data in the **camera frame**.
            camera_pose (np.ndarray): 4x4 homogeneous transformation matrix (camera → global).
            eps (float): DBSCAN clustering radius.
            min_samples (int): Minimum number of points for a cluster.

        Returns:
            List of (cylinder_mesh, transformation_matrix) in the **global frame**.
        """
        # Transform points to the global frame
        points_homog = np.hstack((points, np.ones((points.shape[0], 1))))  # Convert to homogeneous
        points_global = (camera_pose @ points_homog.T).T[:, :3]  # Transform and drop homogeneous coordinate

        # Apply DBSCAN clustering
        dbscan = DBSCAN(eps=eps, min_samples=min_samples).fit(points_global[:, :2])
        labels = dbscan.labels_
        unique_labels = set(labels)

        cylinders_with_transforms = []

        for cluster_label in unique_labels:
            if cluster_label == -1:
                continue

            cluster_mask = labels == cluster_label
            cluster_points = points_global[cluster_mask]

            # Compute PCA to find dominant direction
            pca = PCA(n_components=3)
            pca.fit(cluster_points)
            primary_direction = pca.components_[0]
            mean_pos = np.mean(cluster_points, axis=0)

            # Create a cylinder mesh
            cylinder = o3d.geometry.TriangleMesh.create_cylinder(radius=self.cylinder_radius, height=self.cylinder_height)
            cylinder.paint_uniform_color([0, 0, 1])

            # Compute rotation matrix
            z_axis = np.array([0, 0, 1])
            axis = np.cross(z_axis, primary_direction)
            angle = np.arccos(np.dot(z_axis, primary_direction) / np.linalg.norm(primary_direction))

            if np.linalg.norm(axis) > 1e-6:
                axis /= np.linalg.norm(axis)
                R = o3d.geometry.get_rotation_matrix_from_axis_angle(axis * angle)
            else:
                R = np.eye(3)

            # Store transformation matrix (in global frame)
            transformation = np.eye(4)
            transformation[:3, :3] = R
            transformation[:3, 3] = mean_pos
            cylinder.transform(transformation)

            cylinders_with_transforms.append((cylinder, cluster_points, transformation))

        return cylinders_with_transforms

    def compute_cylinder_metrics(self, transformation, cluster_points):
        cylinder_center = transformation[:3, 3]
        cylinder_axis = transformation[:3, 2]

        proj_lengths = np.dot(cluster_points - cylinder_center, cylinder_axis)
        proj_points = cylinder_center + np.outer(proj_lengths, cylinder_axis)

        distances = np.linalg.norm(cluster_points - proj_points, axis=1)
        mean_distance = np.mean(distances)
        median_distance = np.median(distances)
        num_points_within_radius = np.sum(np.abs(distances - self.cylinder_radius) < 0.002)

        y_true = distances
        y_pred = np.full_like(distances, self.cylinder_radius)

        ss_total = np.sum((y_true - np.mean(y_true)) ** 2)
        ss_residual = np.sum((y_true - y_pred) ** 2)

        r2 = 1 - (ss_residual / ss_total) if ss_total > 0 else 1

        return {
            "mean_distance": mean_distance,
            "median_distance": median_distance,
            "num_points_within_radius": num_points_within_radius,
            "r2_score": r2
        }

    def color_cylinders_by_r2(self, cylinders_with_transforms, cluster_points):
        cylinder_scores = []
        for i, (cylinder, transformation) in enumerate(cylinders_with_transforms):
            scores = self.compute_cylinder_metrics(transformation, cluster_points[i].points)
            cylinder_scores.append(scores)

        r2_scores = np.array([score["r2_score"] for score in cylinder_scores])
        if len(r2_scores) > 1:
            r2_norm = (r2_scores - np.min(r2_scores)) / (np.max(r2_scores) - np.min(r2_scores))
        else:
            r2_norm = np.ones_like(r2_scores)

        colormap = cm.get_cmap("jet")
        for i, (cylinder, _) in enumerate(cylinders_with_transforms):
            color = colormap(r2_norm[i])[:3]
            cylinder.paint_uniform_color(color)

        return cylinder_scores

    def visualize(self, cluster_pcds, cylinders_with_transforms):
        vis = o3d.visualization.Visualizer()
        vis.create_window()

        for cluster_pcd in cluster_pcds:
            vis.add_geometry(cluster_pcd)

        for cylinder, _, _ in cylinders_with_transforms:
            vis.add_geometry(cylinder)

        vis.run()
        vis.destroy_window()


# Example Usage
if __name__ == "__main__":
    import os, sys
    sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
    from utils.load_tutorial_data import load_tutorial_data

    data_dir = os.path.join(os.path.dirname(__file__), os.pardir, 'data', 'cam_on_bot1')

    pcd_colored = load_tutorial_data(data_dir, 1338)
    points = np.array(pcd_colored.points)
    camera_pose = np.eye(4)

    processor = PointCloudProcessor()
    cylinders_with_transforms = processor.cluster(points, camera_pose)
    
    cluster_pcds = []
    for _, pts, _ in cylinders_with_transforms:
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        cluster_pcds.append(pcd)
        
    for cyl, pts, trans in cylinders_with_transforms:
        print(processor.compute_cylinder_metrics(trans, pts))
    
    processor.visualize(cluster_pcds, cylinders_with_transforms)