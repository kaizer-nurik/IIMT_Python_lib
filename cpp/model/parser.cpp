#include "../common/windows_path.hpp"
#include "model.hpp"

#include <fcl/geometry/shape/box.h>
#include <fcl/geometry/shape/cylinder.h>
#include <fcl/geometry/shape/sphere.h>
#include <tinyxml2.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <functional>
#include <iterator>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace iimt::model {
namespace {
using Element = tinyxml2::XMLElement;

std::string required(const Element *element, const char *key) {
  const char *value = element ? element->Attribute(key) : nullptr;
  if (!value || !*value)
    throw std::invalid_argument(std::string("URDF missing attribute '") + key +
                                "'");
  return value;
}

std::vector<double> numbers(const std::string &text, std::size_t count) {
  std::istringstream stream(text);
  stream.imbue(std::locale::classic());
  std::vector<double> values(count);
  for (double &value : values)
    if (!(stream >> value) || !std::isfinite(value))
      throw std::invalid_argument("Expected " + std::to_string(count) +
                                  " finite numbers: '" + text + "'");
  std::string extra;
  if (stream >> extra)
    throw std::invalid_argument("Unexpected extra numeric field: " + text);
  return values;
}

Eigen::Vector3d vector3(const Element *element, const char *attribute,
                        const Eigen::Vector3d &fallback) {
  if (!element || !element->Attribute(attribute))
    return fallback;
  const auto values = numbers(element->Attribute(attribute), 3);
  return {values[0], values[1], values[2]};
}

double scalar(const Element *element, const char *attribute) {
  return numbers(required(element, attribute), 1).front();
}

Transform origin(const Element *parent) {
  const auto *item = parent->FirstChildElement("origin");
  Transform result = Transform::Identity();
  result.translation() = vector3(item, "xyz", Eigen::Vector3d::Zero());
  const auto rpy = vector3(item, "rpy", Eigen::Vector3d::Zero());
  result.linear() = (Eigen::AngleAxisd(rpy.z(), Eigen::Vector3d::UnitZ()) *
                     Eigen::AngleAxisd(rpy.y(), Eigen::Vector3d::UnitY()) *
                     Eigen::AngleAxisd(rpy.x(), Eigen::Vector3d::UnitX()))
                        .toRotationMatrix();
  return result;
}

std::filesystem::path mesh_path(const std::string &uri,
                                const std::filesystem::path &directory,
                                const Packages &packages) {
  std::filesystem::path path;
  if (uri.rfind("package://", 0) == 0) {
    const auto slash = uri.find('/', 10);
    const auto package = uri.substr(10, slash - 10);
    if (slash == std::string::npos || !packages.count(package))
      throw std::invalid_argument("No package path mapping for mesh URI: " +
                                  uri);
    path = std::filesystem::u8path(packages.at(package)) /
           std::filesystem::u8path(uri.substr(slash + 1));
  } else if (uri.rfind("file://", 0) == 0) {
    path = std::filesystem::u8path(uri.substr(7));
  } else {
    if (uri.find("://") != std::string::npos)
      throw std::invalid_argument("Unsupported mesh URI: " + uri);
    path = std::filesystem::u8path(uri);
#ifdef _WIN32
    const auto separator = [](char c) { return c == '/' || c == '\\'; };
    const bool rooted =
        (uri.size() >= 2 && separator(uri[0]) && separator(uri[1])) ||
        (uri.size() >= 3 && uri[1] == ':' && separator(uri[2]));
    if (!rooted && path.is_relative())
#else
    if (path.is_relative())
#endif
      path = directory / path;
  }
  if (!std::filesystem::is_regular_file(path))
    throw std::invalid_argument("Mesh file does not exist: " + path.u8string());
#ifdef _WIN32
  // MinGW canonical()/absolute() corrupt network-share roots; Win32 does not.
  return std::filesystem::path(windows_support::absolute_path(path.u8string()));
#else
  return std::filesystem::canonical(path);
#endif
}

std::array<double, 4>
color(const Element *material,
      const std::map<std::string, std::array<double, 4>> &materials) {
  std::array<double, 4> result{0.65, 0.7, 0.75, 1.};
  if (!material)
    return result;
  if (const auto *item = material->FirstChildElement("color")) {
    const auto values = numbers(required(item, "rgba"), 4);
    std::copy(values.begin(), values.end(), result.begin());
    for (double value : result)
      if (value < 0 || value > 1)
        throw std::invalid_argument("URDF color must be within [0,1]");
  } else if (const char *name = material->Attribute("name")) {
    if (materials.count(name))
      result = materials.at(name);
  }
  return result;
}

Shape parse_shape(const Element *item, const std::filesystem::path &directory,
                  const Packages &packages,
                  const std::map<std::string, std::array<double, 4>> &materials,
                  bool collision) {
  Shape shape;
  shape.origin = origin(item);
  shape.color = color(item->FirstChildElement("material"), materials);
  const auto *geometry = item->FirstChildElement("geometry");
  const auto *primitive = geometry ? geometry->FirstChildElement() : nullptr;
  if (!primitive || primitive->NextSiblingElement())
    throw std::invalid_argument(
        "URDF geometry must contain exactly one supported shape");
  const std::string type = primitive->Name();
  if (type == "mesh") {
    const auto scale = vector3(primitive, "scale", Eigen::Vector3d::Ones());
    if ((scale.array() <= 0).any())
      throw std::invalid_argument("Mesh scale must be positive");
    shape.mesh = load_mesh(
        mesh_path(required(primitive, "filename"), directory, packages), scale);
    if (collision)
      shape.collision = mesh_collision(shape.mesh);
  } else if (type == "box") {
    const auto values = numbers(required(primitive, "size"), 3);
    const Eigen::Vector3d size(values[0], values[1], values[2]);
    if ((size.array() <= 0).any())
      throw std::invalid_argument("Box size must be positive");
    shape.mesh = box_mesh(size);
    if (collision)
      shape.collision = std::make_shared<fcl::Boxd>(size);
  } else if (type == "sphere") {
    const double radius = scalar(primitive, "radius");
    if (radius <= 0)
      throw std::invalid_argument("Sphere radius must be positive");
    shape.mesh = sphere_mesh(radius);
    if (collision)
      shape.collision = std::make_shared<fcl::Sphered>(radius);
  } else if (type == "cylinder") {
    const double radius = scalar(primitive, "radius"),
                 length = scalar(primitive, "length");
    if (radius <= 0 || length <= 0)
      throw std::invalid_argument("Cylinder dimensions must be positive");
    shape.mesh = cylinder_mesh(radius, length);
    if (collision)
      shape.collision = std::make_shared<fcl::Cylinderd>(radius, length);
  } else {
    throw std::invalid_argument("Unsupported URDF geometry: " + type);
  }
  return shape;
}
} // namespace

void Model::parse(const std::filesystem::path &path,
                  const std::vector<std::string> &names,
                  const Packages &packages) {
  if (names.size() != 6 && names.size() != 12)
    throw std::invalid_argument(
        "Model requires six or twelve controlled joint names");
  std::map<std::string, int> axes;
  for (std::size_t i = 0; i < names.size(); ++i)
    if (names[i].empty() || !axes.emplace(names[i], static_cast<int>(i)).second)
      throw std::invalid_argument(
          "Controlled joint names must be nonempty and unique");
  names_ = names;
  lower_.resize(names.size());
  upper_.resize(names.size());
  velocity_.resize(names.size());

  tinyxml2::XMLDocument document;
  // TinyXML2's narrow fopen loses Unicode on non-UTF-8 Windows code pages.
  // filesystem::path keeps the native wide path; the document bytes are UTF-8.
  std::ifstream input(path, std::ios::binary);
  if (!input)
    throw std::invalid_argument("Cannot open URDF '" + path.u8string() + "'");
  const std::string contents{std::istreambuf_iterator<char>(input), {}};
  if (input.bad())
    throw std::invalid_argument("Cannot read URDF '" + path.u8string() + "'");
  if (document.Parse(contents.data(), contents.size()) != tinyxml2::XML_SUCCESS)
    throw std::invalid_argument("Cannot parse URDF '" + path.u8string() +
                                "': " + document.ErrorStr());
  const auto *robot = document.FirstChildElement("robot");
  if (!robot)
    throw std::invalid_argument("URDF requires a robot root element");
  for (auto *child = robot->FirstChildElement(); child;
       child = child->NextSiblingElement()) {
    const std::string tag = child->Name();
    if (tag.find(':') != std::string::npos)
      throw std::invalid_argument(
          "Unexpanded xacro/namespace element in URDF: " + tag);
  }
  std::map<std::string, std::array<double, 4>> materials;
  for (auto *item = robot->FirstChildElement("material"); item;
       item = item->NextSiblingElement("material"))
    materials[required(item, "name")] = color(item, materials);
  std::map<std::string, int> link_ids;
  for (auto *item = robot->FirstChildElement("link"); item;
       item = item->NextSiblingElement("link")) {
    Link link;
    link.name = required(item, "name");
    if (link.name.rfind("__", 0) == 0 ||
        !link_ids.emplace(link.name, static_cast<int>(links_.size())).second)
      throw std::invalid_argument("Duplicate or reserved link name: " +
                                  link.name);
    for (auto *shape = item->FirstChildElement("collision"); shape;
         shape = shape->NextSiblingElement("collision"))
      link.collision.push_back(
          parse_shape(shape, path.parent_path(), packages, materials, true));
    for (auto *shape = item->FirstChildElement("visual"); shape;
         shape = shape->NextSiblingElement("visual"))
      link.visual.push_back(
          parse_shape(shape, path.parent_path(), packages, materials, false));
    if (!link.visual.empty() && link.collision.empty())
      throw std::invalid_argument("Visible link has no collision geometry: " +
                                  link.name);
    links_.push_back(std::move(link));
  }
  if (links_.empty())
    throw std::invalid_argument("URDF contains no links");
  std::set<std::string> joint_names, controlled;
  for (auto *item = robot->FirstChildElement("joint"); item;
       item = item->NextSiblingElement("joint")) {
    Joint joint;
    joint.name = required(item, "name");
    if (!joint_names.insert(joint.name).second)
      throw std::invalid_argument("Duplicate joint name: " + joint.name);
    const auto type = required(item, "type");
    if (type != "fixed" && type != "revolute")
      throw std::invalid_argument("Unsupported joint type '" + type + "' for " +
                                  joint.name + "; require fixed/revolute");
    if (item->FirstChildElement("mimic"))
      throw std::invalid_argument("Mimic joints are unsupported: " +
                                  joint.name);
    const auto parent = required(item->FirstChildElement("parent"), "link");
    const auto child = required(item->FirstChildElement("child"), "link");
    if (!link_ids.count(parent) || !link_ids.count(child) || parent == child)
      throw std::invalid_argument("Invalid parent/child links at joint: " +
                                  joint.name);
    joint.parent = link_ids.at(parent);
    joint.child = link_ids.at(child);
    joint.origin = origin(item);
    auto &link = links_.at(joint.child);
    if (link.parent != -1)
      throw std::invalid_argument("Link has multiple parents: " + child);
    link.parent = joint.parent;
    link.joint = static_cast<int>(joints_.size());
    if (type == "revolute") {
      if (!axes.count(joint.name))
        throw std::invalid_argument("Unmapped movable joint: " + joint.name);
      joint.axis_index = axes.at(joint.name);
      controlled.insert(joint.name);
      joint.axis = vector3(item->FirstChildElement("axis"), "xyz",
                           Eigen::Vector3d::UnitX());
      if (joint.axis.norm() < 1e-12)
        throw std::invalid_argument("Zero joint axis: " + joint.name);
      joint.axis.normalize();
      const auto *limit = item->FirstChildElement("limit");
      const double lower = scalar(limit, "lower"),
                   upper = scalar(limit, "upper"),
                   velocity = scalar(limit, "velocity");
      if (lower >= upper || velocity <= 0)
        throw std::invalid_argument("Invalid joint bounds/velocity: " +
                                    joint.name);
      lower_[joint.axis_index] = lower;
      upper_[joint.axis_index] = upper;
      velocity_[joint.axis_index] = velocity;
    } else if (axes.count(joint.name)) {
      throw std::invalid_argument("Controlled joint cannot be fixed: " +
                                  joint.name);
    }
    joints_.push_back(std::move(joint));
  }
  if (controlled.size() != names.size())
    throw std::invalid_argument(
        "Not all controlled joints exist as revolute URDF joints");
  validate_tree();
}

void Model::validate_tree() {
  std::vector<std::vector<int>> children(links_.size());
  std::vector<int> roots;
  for (std::size_t i = 0; i < links_.size(); ++i) {
    if (links_[i].parent < 0)
      roots.push_back(static_cast<int>(i));
    else
      children[links_[i].parent].push_back(static_cast<int>(i));
  }
  if (roots.size() != 1)
    throw std::invalid_argument(
        "URDF must have exactly one connected root link");
  traversal_ = roots;
  for (std::size_t cursor = 0; cursor < traversal_.size(); ++cursor) {
    const int parent = traversal_[cursor];
    for (int child : children[parent]) {
      if (traversal_.size() >= links_.size())
        throw std::invalid_argument("URDF link cycle");
      links_[child].moving =
          links_[parent].moving || joints_[links_[child].joint].axis_index >= 0;
      traversal_.push_back(child);
    }
  }
  if (traversal_.size() != links_.size())
    throw std::invalid_argument("URDF has disconnected links or a cycle");
}
} // namespace iimt::model
