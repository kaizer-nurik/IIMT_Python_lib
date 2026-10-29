#include "model.hpp"

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>
#include <fcl/geometry/bvh/BVH_model.h>
#include <fcl/math/bv/OBBRSS.h>

#include <cmath>
#include <stdexcept>

namespace iimt::model {
namespace {
constexpr double kPi = 3.14159265358979323846;
}

Mesh load_mesh(const std::filesystem::path &path,
               const Eigen::Vector3d &scale) {
  Assimp::Importer importer;
  const auto *scene = importer.ReadFile(
      path.u8string(), aiProcess_Triangulate | aiProcess_PreTransformVertices |
                           aiProcess_JoinIdenticalVertices |
                           aiProcess_ValidateDataStructure);
  if (!scene || !scene->HasMeshes())
    throw std::invalid_argument("Cannot load mesh '" + path.u8string() +
                                "': " + importer.GetErrorString());
  Mesh result;
  for (unsigned m = 0; m < scene->mNumMeshes; ++m) {
    const auto *mesh = scene->mMeshes[m];
    const int offset = static_cast<int>(result.vertices.size());
    for (unsigned i = 0; i < mesh->mNumVertices; ++i) {
      const auto &v = mesh->mVertices[i];
      Eigen::Vector3d vertex(v.x * scale.x(), v.y * scale.y(), v.z * scale.z());
      if (!vertex.allFinite())
        throw std::invalid_argument("Nonfinite mesh vertex: " +
                                    path.u8string());
      result.vertices.push_back(vertex);
    }
    for (unsigned i = 0; i < mesh->mNumFaces; ++i) {
      const auto &face = mesh->mFaces[i];
      if (face.mNumIndices != 3)
        throw std::invalid_argument("Mesh contains non-triangle primitives: " +
                                    path.u8string());
      std::array<int, 3> triangle{};
      for (unsigned k = 0; k < 3; ++k) {
        if (face.mIndices[k] >= mesh->mNumVertices)
          throw std::invalid_argument("Invalid mesh triangle index: " +
                                      path.u8string());
        triangle[k] = offset + static_cast<int>(face.mIndices[k]);
      }
      result.triangles.push_back(triangle);
    }
  }
  if (result.vertices.empty() || result.triangles.empty())
    throw std::invalid_argument("Empty triangle mesh: " + path.u8string());
  return result;
}

std::shared_ptr<fcl::CollisionGeometryd> mesh_collision(const Mesh &mesh) {
  auto model = std::make_shared<fcl::BVHModel<fcl::OBBRSSd>>();
  std::vector<fcl::Triangle> triangles;
  triangles.reserve(mesh.triangles.size());
  for (const auto &t : mesh.triangles)
    triangles.emplace_back(t[0], t[1], t[2]);
  if (model->beginModel() != fcl::BVH_OK ||
      model->addSubModel(mesh.vertices, triangles) != fcl::BVH_OK ||
      model->endModel() != fcl::BVH_OK)
    throw std::runtime_error("FCL failed to build triangle BVH");
  return model;
}

Mesh box_mesh(const Eigen::Vector3d &size) {
  Mesh mesh;
  for (int z = -1; z <= 1; z += 2)
    for (int y = -1; y <= 1; y += 2)
      for (int x = -1; x <= 1; x += 2)
        mesh.vertices.emplace_back(x * size.x() / 2, y * size.y() / 2,
                                   z * size.z() / 2);
  mesh.triangles = {{0, 2, 1}, {1, 2, 3}, {4, 5, 6}, {5, 7, 6},
                    {0, 1, 4}, {1, 5, 4}, {2, 6, 3}, {3, 6, 7},
                    {0, 4, 2}, {2, 4, 6}, {1, 3, 5}, {3, 7, 5}};
  return mesh;
}

Mesh sphere_mesh(double radius) {
  constexpr int rings = 16, slices = 24;
  Mesh mesh;
  for (int i = 0; i <= rings; ++i) {
    const double phi = kPi * i / rings;
    for (int j = 0; j < slices; ++j) {
      const double theta = 2 * kPi * j / slices;
      mesh.vertices.emplace_back(radius * std::sin(phi) * std::cos(theta),
                                 radius * std::sin(phi) * std::sin(theta),
                                 radius * std::cos(phi));
    }
  }
  for (int i = 0; i < rings; ++i)
    for (int j = 0; j < slices; ++j) {
      const int a = i * slices + j, b = i * slices + (j + 1) % slices;
      mesh.triangles.push_back({a, b, a + slices});
      mesh.triangles.push_back({b, b + slices, a + slices});
    }
  return mesh;
}

Mesh cylinder_mesh(double radius, double length) {
  constexpr int slices = 32;
  Mesh mesh;
  for (int i = 0; i < 2; ++i)
    for (int j = 0; j < slices; ++j) {
      const double angle = 2 * kPi * j / slices;
      mesh.vertices.emplace_back(radius * std::cos(angle),
                                 radius * std::sin(angle), (i - 0.5) * length);
    }
  mesh.vertices.emplace_back(0, 0, -length / 2);
  mesh.vertices.emplace_back(0, 0, length / 2);
  for (int j = 0; j < slices; ++j) {
    const int next = (j + 1) % slices;
    mesh.triangles.push_back({j, next, j + slices});
    mesh.triangles.push_back({next, next + slices, j + slices});
    mesh.triangles.push_back({2 * slices, next, j});
    mesh.triangles.push_back({2 * slices + 1, j + slices, next + slices});
  }
  return mesh;
}
} // namespace iimt::model
