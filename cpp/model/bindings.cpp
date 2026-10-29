#include "model.hpp"

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
using namespace iimt::model;

namespace {
py::list geometry_list(const std::vector<Geometry> &geometry) {
  py::list result;
  for (const auto &shape : geometry) {
    py::array_t<double> vertices(
        {static_cast<py::ssize_t>(shape.mesh.vertices.size()), py::ssize_t(3)});
    auto v = vertices.mutable_unchecked<2>();
    for (py::ssize_t i = 0; i < v.shape(0); ++i)
      for (py::ssize_t j = 0; j < 3; ++j)
        v(i, j) = shape.mesh.vertices[i][j];
    py::array_t<int> triangles(
        {static_cast<py::ssize_t>(shape.mesh.triangles.size()),
         py::ssize_t(3)});
    auto t = triangles.mutable_unchecked<2>();
    for (py::ssize_t i = 0; i < t.shape(0); ++i)
      for (py::ssize_t j = 0; j < 3; ++j)
        t(i, j) = shape.mesh.triangles[i][j];
    py::dict item;
    item["name"] = shape.name;
    item["link"] = shape.link;
    item["vertices"] = std::move(vertices);
    item["triangles"] = std::move(triangles);
    item["color"] = shape.color;
    result.append(std::move(item));
  }
  return result;
}
} // namespace

PYBIND11_MODULE(_model, module) {
  module.doc() = "Native URDF/FK, FCL mesh collision and OMPL RRTConnect; no "
                 "ROS dependency";
  py::class_<Model>(module, "Model")
      .def(py::init<const std::string &, const std::vector<std::string> &,
                    const Packages &, const std::vector<Pair> &,
                    std::optional<double>,
                    std::optional<std::array<double, 4>>>(),
           py::arg("urdf_path"), py::arg("joint_names"),
           py::arg("package_paths") = Packages{},
           py::arg("disabled_collisions") = std::vector<Pair>{},
           py::arg("floor_z") = py::none(), py::arg("workspace") = py::none())
      .def("limits",
           [](const Model &self) {
             py::dict result;
             result["lower"] = self.lower();
             result["upper"] = self.upper();
             result["velocity"] = self.velocity();
             return result;
           })
      .def(
          "check",
          [](const Model &self, const Positions &q) {
            Check checked;
            {
              py::gil_scoped_release unlock;
              checked = self.check(q);
            }
            py::dict result;
            result["valid"] = checked.valid;
            result["collisions"] = checked.collisions;
            return result;
          },
          py::arg("q"))
      .def("plan", &Model::plan, py::arg("start"), py::arg("goal"),
           py::arg("timeout") = 5., py::arg("resolution") = .02,
           py::call_guard<py::gil_scoped_release>())
      .def(
          "geometry",
          [](const Model &self, const Positions &q) {
            std::vector<Geometry> geometry;
            {
              py::gil_scoped_release unlock;
              geometry = self.geometry(q);
            }
            return geometry_list(geometry);
          },
          py::arg("q"))
      .def("geometry_local",
           [](const Model &self) {
             std::vector<Geometry> geometry;
             {
               py::gil_scoped_release unlock;
               geometry = self.geometry_local();
             }
             return geometry_list(geometry);
           })
      .def(
          "transforms",
          [](const Model &self, const Positions &q) {
            std::vector<Transform> poses;
            {
              py::gil_scoped_release unlock;
              poses = self.transforms(q);
            }
            py::dict result;
            for (std::size_t i = 0; i < poses.size(); ++i) {
              std::array<std::array<double, 4>, 4> matrix{};
              for (int row = 0; row < 4; ++row)
                for (int col = 0; col < 4; ++col)
                  matrix[row][col] = poses[i].matrix()(row, col);
              result[py::str(self.links()[i].name)] = matrix;
            }
            return result;
          },
          py::arg("q"));
}
