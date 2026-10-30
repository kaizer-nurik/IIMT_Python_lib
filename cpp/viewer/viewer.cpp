#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <GLFW/glfw3.h>
#if __has_include(<backends/imgui_impl_glfw.h>)
#include <backends/imgui_impl_glfw.h>
#include <backends/imgui_impl_opengl2.h>
#else
// vcpkg installs backend headers directly into its include directory.
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl2.h>
#endif
#include <imgui.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace py = pybind11;
namespace {
using Vec3 = std::array<float, 3>;
using Color = std::array<float, 4>;
using Triangle = std::array<unsigned int, 3>;
constexpr double pi = 3.14159265358979323846;
constexpr int panel_width = 320;

Vec3 subtract(const Vec3 &a, const Vec3 &b) {
  return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}
Vec3 cross(const Vec3 &a, const Vec3 &b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
          a[0] * b[1] - a[1] * b[0]};
}
Vec3 normalized(Vec3 value) {
  const float norm = std::sqrt(value[0] * value[0] + value[1] * value[1] +
                               value[2] * value[2]);
  if (norm > 1e-12f)
    for (auto &component : value)
      component /= norm;
  return value;
}

struct Mesh {
  std::vector<Vec3> vertices;
  std::vector<Vec3> normals;
  std::vector<Triangle> triangles;
  Color color{0.7f, 0.75f, 0.8f, 1.f};
  std::string link;
  std::array<float, 16> transform{1, 0, 0, 0, 0, 1, 0, 0,
                                  0, 0, 1, 0, 0, 0, 0, 1};
};

Mesh parse_mesh(const py::dict &source) {
  Mesh mesh;
  if (source.contains("link"))
    mesh.link = source["link"].cast<std::string>();
  else if (source.contains("name"))
    mesh.link = source["name"].cast<std::string>();
  mesh.vertices = source["vertices"].cast<std::vector<Vec3>>();
  mesh.triangles = source["triangles"].cast<std::vector<Triangle>>();
  if (source.contains("color"))
    mesh.color = source["color"].cast<Color>();
  for (const auto value : mesh.color)
    if (!std::isfinite(value) || value < 0.f || value > 1.f)
      throw std::invalid_argument(
          "Mesh color must contain four finite values in [0, 1]");
  for (const auto &vertex : mesh.vertices)
    for (const auto value : vertex)
      if (!std::isfinite(value))
        throw std::invalid_argument("Mesh vertices must be finite");
  mesh.normals.resize(mesh.vertices.size(), Vec3{0.f, 0.f, 0.f});
  for (const auto &triangle : mesh.triangles) {
    for (const auto index : triangle)
      if (index >= mesh.vertices.size())
        throw std::invalid_argument(
            "Mesh triangle index is outside vertex array");
    const auto normal =
        cross(subtract(mesh.vertices[triangle[1]], mesh.vertices[triangle[0]]),
              subtract(mesh.vertices[triangle[2]], mesh.vertices[triangle[0]]));
    for (const auto index : triangle)
      for (std::size_t axis = 0; axis < 3; ++axis)
        mesh.normals[index][axis] += normal[axis];
  }
  for (auto &normal : mesh.normals)
    normal = normalized(normal);
  if (mesh.triangles.size() >
      static_cast<std::size_t>(std::numeric_limits<GLsizei>::max()) / 3)
    throw std::invalid_argument("Mesh exceeds OpenGL draw count range");
  return mesh;
}

class Viewer {
public:
  Viewer(const std::string &title, int width, int height)
      : owner_(std::this_thread::get_id()) {
    if (width < 480 || height < 320)
      throw std::invalid_argument(
          "Viewer width must be >= 480 and height >= 320");
    if (instance_active_)
      throw std::runtime_error("Only one Viewer is supported per process; use "
                               "a separate viewer process");
    if (!glfwInit())
      throw std::runtime_error("GLFW initialization failed: provide a "
                               "graphical display or disable viewer");
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 2);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 1);
    window_ = glfwCreateWindow(width, height, title.c_str(), nullptr, nullptr);
    if (!window_) {
      glfwTerminate();
      throw std::runtime_error(
          "Cannot create OpenGL 2.1 viewer window; check display/GPU driver");
    }
    glfwMakeContextCurrent(window_);
    if (!glGetString(GL_VERSION)) {
      glfwDestroyWindow(window_);
      window_ = nullptr;
      glfwTerminate();
      throw std::runtime_error(
          "OpenGL context is not visible to the renderer; check for mixed "
          "graphics libraries (Linux wheels must use the host libGL)");
    }
    glfwSwapInterval(1);
    IMGUI_CHECKVERSION();
    context_ = ImGui::CreateContext();
    ImGui::GetIO().IniFilename =
        nullptr; // Do not create imgui.ini in the user's working directory.
    ImGui::GetIO().ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui::StyleColorsDark();
    if (!ImGui_ImplGlfw_InitForOpenGL(window_, true)) {
      release();
      throw std::runtime_error("Cannot initialize ImGui GLFW backend");
    }
    glfw_backend_ = true;
    if (!ImGui_ImplOpenGL2_Init()) {
      release();
      throw std::runtime_error("Cannot initialize ImGui OpenGL backend");
    }
    opengl_backend_ = true;
    instance_active_ = true;
  }

  Viewer(const Viewer &) = delete;
  Viewer &operator=(const Viewer &) = delete;
  ~Viewer() { release(); }

  py::dict update(const py::object &meshes, const std::vector<double> &target,
                  const std::vector<double> &lower,
                  const std::vector<double> &upper, const std::string &status,
                  const py::object &workspace, const py::object &floor_z,
                  const py::object &transforms) {
    assert_thread();
    validate_joints(target, lower, upper);
    auto next_target = target;
    if (!window_)
      return response(false, next_target, std::nullopt);
    set_scene(meshes, workspace, floor_z);
    set_transforms(transforms);
    if (!framed_ && !meshes_.empty()) {
      frame_scene();
      framed_ = true;
    }
    glfwMakeContextCurrent(window_);
    ImGui::SetCurrentContext(context_);
    glfwPollEvents();
    if (glfwWindowShouldClose(window_)) {
      close();
      return response(false, next_target, std::nullopt);
    }
    ImGui_ImplOpenGL2_NewFrame();
    ImGui_ImplGlfw_NewFrame();
    ImGui::NewFrame();
    const auto action = draw_controls(next_target, lower, upper, status);
    update_camera();
    ImGui::Render();
    {
      // Rendering/vsync cannot hold up Python callers in another thread.
      py::gil_scoped_release unlock;
      draw_scene();
      ImGui_ImplOpenGL2_RenderDrawData(ImGui::GetDrawData());
      glfwSwapBuffers(window_);
    }
    return response(true, next_target, action);
  }

  void set_geometry(const py::list &meshes) {
    assert_thread();
    std::vector<Mesh> next;
    for (const auto &source : meshes) {
      next.push_back(parse_mesh(py::cast<py::dict>(source)));
      if (next.back().link.empty())
        throw std::invalid_argument(
            "Local geometry requires a link key for each mesh");
    }
    meshes_ = std::move(next);
    local_geometry_ = true;
    have_transforms_ = false;
    framed_ = false;
  }

  void close() {
    assert_thread();
    release();
  }

private:
  void assert_thread() const {
    if (std::this_thread::get_id() != owner_)
      throw std::runtime_error(
          "Viewer must be updated/closed on its creating thread");
  }

  static void validate_joints(const std::vector<double> &target,
                              const std::vector<double> &lower,
                              const std::vector<double> &upper) {
    if ((target.size() != 6 && target.size() != 12) ||
        lower.size() != target.size() || upper.size() != target.size())
      throw std::invalid_argument(
          "Viewer target/lower/upper must contain matching 6 or 12 joints");
    for (std::size_t i = 0; i < target.size(); ++i)
      if (!std::isfinite(target[i]) || !std::isfinite(lower[i]) ||
          !std::isfinite(upper[i]) || lower[i] >= upper[i])
        throw std::invalid_argument(
            "Viewer joint values must be finite with lower < upper");
  }

  static py::dict response(bool open, const std::vector<double> &target,
                           const std::optional<std::string> &action) {
    py::dict result;
    result["open"] = open;
    result["target"] = target;
    result["action"] = action ? py::cast(*action) : py::none();
    return result;
  }

  void set_scene(const py::object &meshes, const py::object &workspace,
                 const py::object &floor_z) {
    std::optional<std::array<double, 4>> next_workspace;
    std::optional<double> next_floor;
    if (!workspace.is_none()) {
      next_workspace = workspace.cast<std::array<double, 4>>();
      for (const auto value : *next_workspace)
        if (!std::isfinite(value))
          throw std::invalid_argument("Viewer workspace bounds must be finite");
      if ((*next_workspace)[0] >= (*next_workspace)[1] ||
          (*next_workspace)[2] >= (*next_workspace)[3])
        throw std::invalid_argument(
            "Viewer workspace requires xmin < xmax and ymin < ymax");
    }
    if (!floor_z.is_none()) {
      next_floor = floor_z.cast<double>();
      if (!std::isfinite(*next_floor))
        throw std::invalid_argument("Viewer floor_z must be finite");
    }
    if (!meshes.is_none()) {
      std::vector<Mesh> next_meshes;
      for (const auto &mesh : meshes.cast<py::list>())
        next_meshes.push_back(parse_mesh(py::cast<py::dict>(mesh)));
      meshes_ = std::move(next_meshes);
      local_geometry_ = false;
      have_transforms_ = false;
    }
    workspace_ = next_workspace;
    floor_z_ = next_floor;
  }

  void set_transforms(const py::object &transforms) {
    if (transforms.is_none()) {
      if (local_geometry_ && !have_transforms_)
        throw std::invalid_argument("First update after set_geometry requires "
                                    "transforms for every mesh link");
      return;
    }
    const auto matrices = transforms.cast<py::dict>();
    std::vector<std::array<float, 16>> next;
    for (const auto &mesh : meshes_) {
      if (!matrices.contains(py::str(mesh.link)))
        throw std::invalid_argument("Missing transform for mesh link: " +
                                    mesh.link);
      const auto rows = matrices[py::str(mesh.link)]
                            .cast<std::array<std::array<double, 4>, 4>>();
      std::array<float, 16> column_major{};
      for (std::size_t row = 0; row < 4; ++row)
        for (std::size_t col = 0; col < 4; ++col) {
          if (!std::isfinite(rows[row][col]))
            throw std::invalid_argument("Nonfinite transform for mesh link: " +
                                        mesh.link);
          column_major[col * 4 + row] = static_cast<float>(rows[row][col]);
        }
      if (std::abs(rows[3][0]) > 1e-9 || std::abs(rows[3][1]) > 1e-9 ||
          std::abs(rows[3][2]) > 1e-9 || std::abs(rows[3][3] - 1.) > 1e-9)
        throw std::invalid_argument(
            "Expected affine transform for mesh link: " + mesh.link);
      next.push_back(column_major);
    }
    for (std::size_t i = 0; i < meshes_.size(); ++i)
      meshes_[i].transform = next[i];
    have_transforms_ = true;
  }

  void frame_scene() {
    Vec3 minimum{1e20f, 1e20f, 1e20f}, maximum{-1e20f, -1e20f, -1e20f};
    bool found = false;
    for (const auto &mesh : meshes_)
      for (const auto &vertex : mesh.vertices) {
        found = true;
        for (std::size_t i = 0; i < 3; ++i) {
          const float value = mesh.transform[i] * vertex[0] +
                              mesh.transform[4 + i] * vertex[1] +
                              mesh.transform[8 + i] * vertex[2] +
                              mesh.transform[12 + i];
          minimum[i] = std::min(minimum[i], value);
          maximum[i] = std::max(maximum[i], value);
        }
      }
    if (!found)
      return;
    double extent = 0;
    for (std::size_t i = 0; i < 3; ++i) {
      center_[i] = .5f * (minimum[i] + maximum[i]);
      extent = std::max(extent, static_cast<double>(maximum[i] - minimum[i]));
    }
    distance_ = std::clamp(extent * 2.2, .2, 1000.);
  }

  std::optional<std::string> draw_controls(std::vector<double> &target,
                                           const std::vector<double> &lower,
                                           const std::vector<double> &upper,
                                           const std::string &status) {
    const auto &io = ImGui::GetIO();
    ImGui::SetNextWindowPos(ImVec2(0, 0));
    ImGui::SetNextWindowSize(
        ImVec2(static_cast<float>(panel_width), io.DisplaySize.y));
    ImGui::Begin("IIMT joint targets", nullptr,
                 ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize |
                     ImGuiWindowFlags_NoCollapse);
    ImGui::TextWrapped("Targets only. Sliders do NOT move the robot.");
    ImGui::Separator();
    for (std::size_t i = 0; i < target.size(); ++i) {
      if (i % 6 == 0)
        ImGui::Text("Arm %zu | radians", i / 6 + 1);
      ImGui::PushID(static_cast<int>(i));
      const std::string label = "J" + std::to_string(i % 6 + 1);
      ImGui::SliderScalar(label.c_str(), ImGuiDataType_Double, &target[i],
                          &lower[i], &upper[i], "%.4f");
      ImGui::PopID();
    }
    ImGui::Separator();
    std::optional<std::string> action;
    if (ImGui::Button("Plan", ImVec2(84, 0)))
      action = "plan";
    ImGui::SameLine();
    if (ImGui::Button("Execute", ImVec2(84, 0)))
      action = "execute";
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(84, 0)))
      action = "cancel";
    ImGui::TextWrapped("%s", status.c_str());
    ImGui::Separator();
    if (ImGui::Button("Frame robot"))
      frame_scene();
    ImGui::Checkbox("Wireframe", &wireframe_);
    ImGui::TextWrapped(
        "Scene: left drag orbit, right drag pan, wheel zoom. Z is up.");
    ImGui::Text("%.0f fps", io.Framerate);
    ImGui::End();
    return action;
  }

  void update_camera() {
    const auto &io = ImGui::GetIO();
    if (io.WantCaptureMouse)
      return;
    if (ImGui::IsMouseDragging(ImGuiMouseButton_Left)) {
      yaw_ -= io.MouseDelta.x * .008;
      pitch_ = std::clamp(pitch_ + io.MouseDelta.y * .008, -.1, pi / 2 - .02);
    }
    if (ImGui::IsMouseDragging(ImGuiMouseButton_Right)) {
      const double scale = distance_ * .0015;
      center_[0] += static_cast<float>(
          (std::sin(yaw_) * io.MouseDelta.x +
           std::cos(yaw_) * std::sin(pitch_) * io.MouseDelta.y) *
          scale);
      center_[1] += static_cast<float>(
          (-std::cos(yaw_) * io.MouseDelta.x +
           std::sin(yaw_) * std::sin(pitch_) * io.MouseDelta.y) *
          scale);
      center_[2] +=
          static_cast<float>(-std::cos(pitch_) * io.MouseDelta.y * scale);
    }
    distance_ =
        std::clamp(distance_ * std::exp(-io.MouseWheel * .12), .05, 1000.);
  }

  void set_camera(int width, int height) const {
    const double near_clip = std::max(.001, distance_ * .001);
    const double top = near_clip * std::tan(45. * pi / 360.);
    const double right = top * width / std::max(height, 1);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glFrustum(-right, right, -top, top, near_clip, distance_ + 1000.);
    const Vec3 direction{static_cast<float>(std::cos(pitch_) * std::cos(yaw_)),
                         static_cast<float>(std::cos(pitch_) * std::sin(yaw_)),
                         static_cast<float>(std::sin(pitch_))};
    const Vec3 side = normalized(cross(direction, Vec3{0, 0, 1}));
    const Vec3 up = cross(side, direction);
    const float view[] = {-side[0],
                          up[0],
                          direction[0],
                          0,
                          -side[1],
                          up[1],
                          direction[1],
                          0,
                          -side[2],
                          up[2],
                          direction[2],
                          0,
                          0,
                          0,
                          0,
                          1};
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glMultMatrixf(view);
    glTranslated(-center_[0] - direction[0] * distance_,
                 -center_[1] - direction[1] * distance_,
                 -center_[2] - direction[2] * distance_);
  }

  void draw_grid() const {
    const double z = floor_z_.value_or(0.);
    const double span = std::max(2., distance_ * .8);
    const double step = std::pow(10., std::floor(std::log10(span))) * .1;
    glDisable(GL_LIGHTING);
    glLineWidth(1.f);
    glColor4f(.28f, .31f, .36f, 1.f);
    glBegin(GL_LINES);
    const auto low = static_cast<int>(std::floor(-span / step));
    const auto high = static_cast<int>(std::ceil(span / step));
    for (int i = low; i <= high; ++i) {
      glVertex3d(i * step, -span, z);
      glVertex3d(i * step, span, z);
      glVertex3d(-span, i * step, z);
      glVertex3d(span, i * step, z);
    }
    glEnd();
    glLineWidth(2.f);
    glBegin(GL_LINES);
    glColor3f(.9f, .25f, .25f);
    glVertex3d(0, 0, z);
    glVertex3d(.25, 0, z);
    glColor3f(.25f, .9f, .3f);
    glVertex3d(0, 0, z);
    glVertex3d(0, .25, z);
    glColor3f(.25f, .5f, 1.f);
    glVertex3d(0, 0, z);
    glVertex3d(0, 0, z + .25);
    glEnd();
    if (!workspace_)
      return;
    const auto &b = *workspace_;
    glColor3f(1.f, .65f, .15f);
    glBegin(GL_LINE_LOOP);
    glVertex3d(b[0], b[2], z + .001);
    glVertex3d(b[1], b[2], z + .001);
    glVertex3d(b[1], b[3], z + .001);
    glVertex3d(b[0], b[3], z + .001);
    glEnd();
    // Uprights show unbounded vertical side boundaries, never a ceiling.
    glBegin(GL_LINES);
    for (const auto x : {b[0], b[1]})
      for (const auto y : {b[2], b[3]}) {
        glVertex3d(x, y, z);
        glVertex3d(x, y, z + std::max(1., distance_));
      }
    glEnd();
  }

  void draw_meshes() const {
    glEnable(GL_LIGHTING);
    glEnable(GL_LIGHT0);
    glEnable(GL_COLOR_MATERIAL);
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE);
    glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE);
    const float light[]{-.3f, -.5f, 1.f, 0.f};
    const float ambient[]{.45f, .45f, .45f, 1.f};
    glLightfv(GL_LIGHT0, GL_POSITION, light);
    glLightModelfv(GL_LIGHT_MODEL_AMBIENT, ambient);
    glEnableClientState(GL_VERTEX_ARRAY);
    glEnableClientState(GL_NORMAL_ARRAY);
    glPolygonMode(GL_FRONT_AND_BACK, wireframe_ ? GL_LINE : GL_FILL);
    for (int pass = 0; pass < 2; ++pass) {
      glDepthMask(pass == 0 ? GL_TRUE : GL_FALSE);
      for (const auto &mesh : meshes_) {
        if (mesh.vertices.empty() || mesh.triangles.empty() ||
            (mesh.color[3] < .999f) != (pass == 1))
          continue;
        glPushMatrix();
        glMultMatrixf(mesh.transform.data());
        glColor4fv(mesh.color.data());
        glVertexPointer(3, GL_FLOAT, sizeof(Vec3), mesh.vertices.data());
        glNormalPointer(GL_FLOAT, sizeof(Vec3), mesh.normals.data());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(mesh.triangles.size() * 3),
                       GL_UNSIGNED_INT, mesh.triangles.data());
        glPopMatrix();
      }
    }
    glDepthMask(GL_TRUE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glDisableClientState(GL_NORMAL_ARRAY);
    glDisableClientState(GL_VERTEX_ARRAY);
    glDisable(GL_LIGHTING);
  }

  void draw_scene() const {
    int width, height;
    glfwGetFramebufferSize(window_, &width, &height);
    if (width <= 0 || height <= 0)
      return;
    glViewport(0, 0, width, height);
    glClearColor(.075f, .09f, .12f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    const auto &io = ImGui::GetIO();
    const int panel_pixels =
        static_cast<int>(panel_width * io.DisplayFramebufferScale.x);
    glViewport(panel_pixels, 0, std::max(1, width - panel_pixels), height);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_CULL_FACE);
    set_camera(std::max(1, width - panel_pixels), height);
    draw_grid();
    draw_meshes();
    glDisable(GL_DEPTH_TEST);
  }

  void release() noexcept {
    if (!window_)
      return;
    glfwMakeContextCurrent(window_);
    ImGui::SetCurrentContext(context_);
    if (opengl_backend_)
      ImGui_ImplOpenGL2_Shutdown();
    if (glfw_backend_)
      ImGui_ImplGlfw_Shutdown();
    if (context_)
      ImGui::DestroyContext(context_);
    glfwDestroyWindow(window_);
    glfwTerminate();
    window_ = nullptr;
    context_ = nullptr;
    glfw_backend_ = false;
    opengl_backend_ = false;
    instance_active_ = false;
  }

  inline static bool instance_active_ = false;
  std::thread::id owner_;
  GLFWwindow *window_ = nullptr;
  ImGuiContext *context_ = nullptr;
  bool glfw_backend_ = false, opengl_backend_ = false;
  std::vector<Mesh> meshes_;
  std::optional<std::array<double, 4>> workspace_;
  std::optional<double> floor_z_;
  Vec3 center_{0, 0, .4f};
  double yaw_ = -.8, pitch_ = .45, distance_ = 2.;
  bool framed_ = false, wireframe_ = false;
  bool local_geometry_ = false, have_transforms_ = false;
};
} // namespace

PYBIND11_MODULE(_viewer, module) {
  module.doc() =
      "Independent native IIMT viewer; UI events only, no robot transport";
  py::class_<Viewer>(module, "Viewer")
      .def(py::init<const std::string &, int, int>(), py::arg("title"),
           py::arg("width") = 1100, py::arg("height") = 800)
      .def("update", &Viewer::update, py::arg("meshes"), py::arg("target"),
           py::arg("lower"), py::arg("upper"), py::arg("status"),
           py::arg("workspace") = py::none(), py::arg("floor_z") = py::none(),
           py::arg("transforms") = py::none())
      .def("set_geometry", &Viewer::set_geometry, py::arg("meshes"))
      .def("close", &Viewer::close);
}
