#include "model.hpp"
#include "../common/windows_path.hpp"

#include <fcl/geometry/shape/halfspace.h>
#include <fcl/geometry/shape/plane.h>
#include <fcl/narrowphase/collision.h>
#include <fcl/narrowphase/collision_object.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace iimt::model {
namespace {
Pair ordered(const std::string &a, const std::string &b) {
  return a < b ? Pair(a, b) : Pair(b, a);
}

bool collide(const fcl::CollisionObjectd &a, const fcl::CollisionObjectd &b) {
  if (!a.getAABB().overlap(b.getAABB()))
    return false;
  fcl::CollisionRequestd request(1, false);
  fcl::CollisionResultd result;
  fcl::collide(&a, &b, request, result);
  return result.isCollision();
}
} // namespace

Model::Model(const std::string &urdf_path,
             const std::vector<std::string> &joint_names,
             const Packages &packages, const std::vector<Pair> &disabled,
             std::optional<double> floor_z,
             std::optional<std::array<double, 4>> workspace) {
#ifdef _WIN32
  parse(std::filesystem::path(windows_support::absolute_path(urdf_path)),
        joint_names, packages);
#else
  parse(std::filesystem::absolute(urdf_path), joint_names, packages);
#endif
  std::set<std::string> names;
  for (const auto &link : links_)
    names.insert(link.name);
  if (floor_z) {
    if (!std::isfinite(*floor_z))
      throw std::invalid_argument("floor_z must be finite");
    world_.push_back(
        {"__floor__", std::make_shared<fcl::Planed>(0, 0, 1, *floor_z)});
    names.insert("__floor__");
  }
  if (workspace) {
    const auto &w = *workspace;
    for (double value : w)
      if (!std::isfinite(value))
        throw std::invalid_argument("Workspace bounds must be finite");
    if (w[0] >= w[1] || w[2] >= w[3])
      throw std::invalid_argument(
          "Workspace requires xmin < xmax and ymin < ymax");
    world_.push_back(
        {"__x_min__", std::make_shared<fcl::Halfspaced>(1, 0, 0, w[0])});
    world_.push_back(
        {"__x_max__", std::make_shared<fcl::Halfspaced>(-1, 0, 0, -w[1])});
    world_.push_back(
        {"__y_min__", std::make_shared<fcl::Halfspaced>(0, 1, 0, w[2])});
    world_.push_back(
        {"__y_max__", std::make_shared<fcl::Halfspaced>(0, -1, 0, -w[3])});
    for (const auto &shape : world_)
      names.insert(shape.name);
  }
  for (const auto &pair : disabled) {
    if (pair.first == pair.second || !names.count(pair.first) ||
        !names.count(pair.second))
      throw std::invalid_argument("Unknown/self disabled collision pair: " +
                                  pair.first + " / " + pair.second);
    const bool first_world = pair.first.rfind("__", 0) == 0;
    const bool second_world = pair.second.rfind("__", 0) == 0;
    if (first_world || second_world) {
      const auto &world = first_world ? pair.first : pair.second;
      const auto &robot = first_world ? pair.second : pair.first;
      const auto link =
          std::find_if(links_.begin(), links_.end(),
                       [&](const Link &l) { return l.name == robot; });
      if (world != "__floor__" || link == links_.end() || link->moving)
        throw std::invalid_argument(
            "Only fixed base links may be excluded from floor collision: " +
            robot);
    }
    disabled_.insert(ordered(pair.first, pair.second));
  }
}

void Model::validate_positions(const Positions &q) const {
  if (q.size() != names_.size())
    throw std::invalid_argument("Joint vector dimension mismatch");
  for (std::size_t i = 0; i < q.size(); ++i)
    if (!std::isfinite(q[i]))
      throw std::invalid_argument("Nonfinite position for joint " + names_[i]);
}

std::vector<Transform> Model::transforms(const Positions &q) const {
  validate_positions(q);
  std::vector<Transform> result(links_.size(), Transform::Identity());
  for (int index : traversal_) {
    const auto &link = links_[index];
    if (link.parent < 0)
      continue;
    const auto &joint = joints_[link.joint];
    result[index] = result[link.parent] * joint.origin;
    if (joint.axis_index >= 0)
      result[index].rotate(Eigen::AngleAxisd(q[joint.axis_index], joint.axis));
  }
  return result;
}

bool Model::is_disabled(const std::string &a, const std::string &b) const {
  return disabled_.count(ordered(a, b)) != 0;
}

Check Model::check(const Positions &q) const {
  validate_positions(q);
  Check result;
  for (std::size_t i = 0; i < q.size(); ++i) {
    if (q[i] < lower_[i] || q[i] > upper_[i])
      result.collisions.emplace_back(names_[i], "__joint_limit__");
  }
  if (!result.collisions.empty()) {
    result.valid = false;
    return result;
  }
  const auto poses = transforms(q);
  struct Body {
    std::string name;
    std::unique_ptr<fcl::CollisionObjectd> object;
  };
  std::vector<Body> bodies;
  for (std::size_t i = 0; i < links_.size(); ++i)
    for (const auto &shape : links_[i].collision)
      bodies.push_back(
          {links_[i].name, std::make_unique<fcl::CollisionObjectd>(
                               shape.collision, poses[i] * shape.origin)});
  std::set<Pair> contacts;
  for (std::size_t i = 0; i < bodies.size(); ++i) {
    const auto &a = bodies[i];
    for (std::size_t j = i + 1; j < bodies.size(); ++j) {
      const auto &b = bodies[j];
      if (a.name == b.name || is_disabled(a.name, b.name))
        continue;
      if (collide(*a.object, *b.object))
        contacts.insert(ordered(a.name, b.name));
    }
    for (const auto &obstacle : world_) {
      if (is_disabled(a.name, obstacle.name))
        continue;
      const fcl::CollisionObjectd object(obstacle.geometry);
      if (collide(*a.object, object))
        contacts.insert(ordered(a.name, obstacle.name));
    }
  }
  result.collisions.assign(contacts.begin(), contacts.end());
  result.valid = result.collisions.empty();
  return result;
}

std::vector<Geometry> Model::geometry_local() const {
  std::vector<Geometry> result;
  for (const auto &link : links_) {
    const auto &shapes = link.visual.empty() ? link.collision : link.visual;
    for (std::size_t i = 0; i < shapes.size(); ++i) {
      const auto &shape = shapes[i];
      Geometry item{link.name + "/" + std::to_string(i), link.name, shape.mesh,
                    shape.color};
      for (auto &vertex : item.mesh.vertices)
        vertex = shape.origin * vertex;
      result.push_back(std::move(item));
    }
  }
  return result;
}

std::vector<Geometry> Model::geometry(const Positions &q) const {
  const auto poses = transforms(q);
  auto result = geometry_local();
  std::map<std::string, Transform> by_name;
  for (std::size_t i = 0; i < links_.size(); ++i)
    by_name.emplace(links_[i].name, poses[i]);
  for (auto &item : result)
    for (auto &vertex : item.mesh.vertices)
      vertex = by_name.at(item.link) * vertex;
  return result;
}
} // namespace iimt::model
