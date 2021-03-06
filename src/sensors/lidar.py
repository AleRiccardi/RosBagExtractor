import os
import yaml
import open3d as o3d
import numpy as np

from tqdm import tqdm
from sensor_msgs.msg import LaserScan
from laser_geometry import LaserProjection
import sensor_msgs.point_cloud2 as pc2

from utils.tools import msg_to_timestamp
from sensors.base import BaseExtraction


class Lidar:
    HOKUYO = "hokuyo"
    OUSTER = "ouster"
    VELODYNE = "velodyne"

    @staticmethod
    def list():
        sensors_list = [
            Lidar.HOKUYO,
            Lidar.OUSTER,
            Lidar.VELODYNE
        ]
        return sensors_list


class LidarExtraction(BaseExtraction):
    CLOUD_HEADER = "timestamp [ns]"
    CLOUD_FORMAT = "%s"

    def __init__(self, topic, bags, path_root, lidar=Lidar.VELODYNE, ) -> None:
        super().__init__(topic, bags, path_root, lidar)

        if not lidar in Lidar.list():
            raise ValueError(
                "\"{}\" lidar sensor type not supported".format(lidar))
        self.sensor: Lidar = lidar
        self.name = lidar
        self.available_point_time = False

    def initialize(self):
        print(">> Extracting clouds:")
        self.path_save = self.getPathSave()

    def extract(self):
        if not self.isAvailable():
            return
        self.initialize()

        data = []

        for idx, bag in enumerate(self.bags):
            print("{}/{}: {}".format(idx+1, len(self.bags), bag.filename))
            bag_msgs = bag.read_messages(topics=[self.topic])
            msg_count = bag.get_message_count(self.topic)

            for _, msg, _ in tqdm(bag_msgs, total=msg_count):
                if self.sensor == Lidar.HOKUYO:
                    self.singleHokuyo(msg, data)
                elif self.sensor == Lidar.OUSTER:
                    self.singleOuster(msg, data)
                elif self.sensor == Lidar.VELODYNE:
                    self.singleVelodyne(msg, data)

        data = np.sort(np.array(data))
        self.saveCSV(data)

    def loadHokuyo(self, msg):
        data_yaml = yaml.safe_load(msg)
        scan = LaserScan(
            header=data_yaml["header"],
            angle_min=data_yaml["angle_min"],
            angle_max=data_yaml["angle_max"],
            angle_increment=data_yaml["angle_increment"],
            time_increment=data_yaml["time_increment"],
            scan_time=data_yaml["scan_time"],
            range_min=data_yaml["range_min"],
            range_max=data_yaml["range_max"],
            ranges=data_yaml["ranges"],
            intensities=data_yaml["intensities"])

        projector = LaserProjection()
        cloud = projector.projectLaser(scan)
        return cloud

    def singleHokuyo(self, msg, data):
        msg = str(msg)

        try:
            cloud = self.loadHokuyo(msg)
        except Exception as _:
            msg = msg.replace("nan", "60")
            cloud = self.loadHokuyo(msg)

        # Timestamp and file name
        timestamp = msg_to_timestamp(msg)
        filename = str(timestamp) + ".ply"
        data.append(filename)

        xyz_s = []
        for pt in pc2.read_points(cloud, field_names=("x", "y", "z"), skip_nans=True):
            x, y, z = pt
            xyz = [x, y, z]
            xyz_s.append(xyz)

        xyz_s = np.array(xyz_s)
        irt_s = np.array([])
        self.savePLY(filename, xyz_s, irt_s)

    def singleOuster(self, msg, data):
        # Ouster fields
        field_names = ["x", "y", "z", "intensity", "t", "ring"]

        # Timestamp and file name
        timestamp = msg_to_timestamp(msg)
        filename = str(timestamp) + ".ply"
        data.append(filename)

        points = pc2.read_points_list(cloud=msg,
                                      field_names=field_names,
                                      skip_nans=True)
        xyz_s = []
        irt_s = []

        for pt in points:
            x, y, z, i, t, r = pt
            t_ms = t
            xyz = [x, y, z]
            irt = [i, r, t_ms]

            xyz_s.append(xyz)
            irt_s.append(irt)

        xyz_s = np.array(xyz_s)
        irt_s = np.array(irt_s)

        self.savePLY(filename, xyz_s, irt_s)

    def singleVelodyne(self, msg, data):
        ## Velodyne (standard)
        #  field_names = ["x", "y", "z", "intensity", "ring", "time"]
        # Velodyne (no point's time)
        field_names = ["x", "y", "z", "intensity", "ring"]

        # Timestamp and file name
        timestamp = msg_to_timestamp(msg)
        filename = str(timestamp) + ".ply"
        data.append(filename)

        points = pc2.read_points_list(cloud=msg,
                                      field_names=field_names,
                                      skip_nans=True)

        xyz_s = []
        irt_s = []
        for pt in points:
            if self.available_point_time:
                x, y, z, i, r = pt
                xyz = [x, y, z]
                irt = [i, r, 0]
            else:
                x, y, z, i, r, t_s = pt
                xyz = [x, y, z]
                t_ms = int(t_s * 1e9)
                irt = [i, r, t_ms]

            xyz_s.append(xyz)
            irt_s.append(irt)

        xyz_s = np.array(xyz_s)
        irt_s = np.array(irt_s)

        self.savePLY(filename, xyz_s, irt_s)

    def savePLY(self, name, points, normals):
        filename = os.path.join(self.path_save, name)
        o3d_cloud = o3d.geometry.PointCloud()
        o3d_cloud.points = o3d.utility.Vector3dVector(points)

        if normals.any():
            o3d_cloud.normals = o3d.utility.Vector3dVector(normals)

        o3d.io.write_point_cloud(filename, o3d_cloud)

    def saveCSV(self, data: np.ndarray):
        filename = os.path.join(self.path_save, "data.csv")
        np.savetxt(filename,
                   data,
                   fmt=self.CLOUD_FORMAT,
                   delimiter=',',
                   newline='\n',
                   header=self.CLOUD_HEADER,
                   footer='',
                   comments='# ',
                   encoding=None)
