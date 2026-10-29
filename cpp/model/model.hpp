#pragma once

#include <Eigen/Geometry>
#include <fcl/geometry/collision_geometry.h>

#include <array>
#include <filesystem>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace iimt::model {
using Transform = Eigen::Isometry3d;
using Pair = std::pair<std::string, std::string>;
using Packages = std::map<std::string, std::string>;
using Positions = std::vector<double>;

struct Mesh {
  std::vector<Eigen::Vector3d> vertices;
  std::vector<std::array<int, 3>> triangles;
};

struct Shape {
  Transform origin{Transform::Identity()};
  Mesh mesh;
  std::shared_ptr<fcl::CollisionGeometryd> collision;
  std::array<double, 4> color{0.65, 0.7, 0.75, 1.};
};

struct Link {
  std::string name;
  std::vector<Shape> collision;
  std::vector<Shape> visual;
  int parent{-1};
  int joint{-1};
  bool moving{false};
};

struct Joint {
  std::string name;
  int parent{};
  int child{};
  int axis_index{-1};
  Transform origin{Transform::Identity()};
  Eigen::Vector3d axis{1., 0., 0.};
};

struct Geometry {
  std::string name;
  std::string link;
  Mesh mesh;
  std::array<double, 4> color;
};

struct Check {
  bool valid{true};
  std::vector<Pair> collisions;
};

struct WorldShape {
  std::string name;
  std::shared_ptr<fcl::CollisionGeometryd> geometry;
};

class Model {
public:
  Model(const std::string &urdf_path,
        const std::vector<std::string> &joint_names, const Packages &packages,
        const std::vector<Pair> &disabled, std::optional<double> floor_z,
        std::optional<std::array<double, 4>> workspace);
  Check check(const Positions &q) const;
  std::vector<Positions> plan(const Positions &start, const Positions &goal,
                              double timeout, double resolution) const;
  std::vector<Transform> transforms(const Positions &q) const;
  std::vector<Geometry> geometry(const Positions &q) const;
  std::vector<Geometry> geometry_local() const;
  const Positions &lower() const { return lower_; }
  const Positions &upper() const { return upper_; }
  const Positions &velocity() const { return velocity_; }
  const std::vector<Link> &links() const { return links_; }

private:
  void parse(const std::filesystem::path &path,
             const std::vector<std::string> &names, const Packages &packages);
  void validate_tree();
  void validate_positions(const Positions &q) const;
  bool is_disabled(const std::string &a, const std::string &b) const;
  std::vector<Link> links_;
  std::vector<Joint> joints_;
  std::vector<int> traversal_;
  std::vector<std::string> names_;
  Positions lower_, upper_, velocity_;
  std::set<Pair> disabled_;
  std::vector<WorldShape> world_;
};

Mesh load_mesh(const std::filesystem::path &path, const Eigen::Vector3d &scale);
std::shared_ptr<fcl::CollisionGeometryd> mesh_collision(const Mesh &mesh);
Mesh box_mesh(const Eigen::Vector3d &size);
Mesh sphere_mesh(double radius);
Mesh cylinder_mesh(double radius, double length);
} // namespace iimt::model
