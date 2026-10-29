#include "controller.hpp"
#include <limits>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <set>

namespace py = pybind11;
namespace iimt {
namespace {
template <class T> void read(const py::dict &source, const char *key, T &out) {
  if (source.contains(key))
    out = py::cast<T>(source[key]);
}
Config config_from_dict(const py::dict &source) {
  Config c;
  std::set<std::string> accepted;
#define READ(name)                                                             \
  read(source, #name, c.name);                                                 \
  accepted.insert(#name)
  READ(name);
  READ(ip);
  READ(sdk_library);
  READ(joint_names);
  READ(port);
  READ(windows_timer_resolution_ms);
  READ(enable_motion);
  READ(allow_protective_stop_release);
  READ(command_rate);
  READ(read_rate);
  READ(read_timeout);
  READ(state_timeout);
  READ(startup_timeout);
  READ(servo_a);
  READ(servo_v);
  READ(lookahead_time);
  READ(gain);
  READ(advance_ms);
  READ(start_tolerance);
  READ(path_tolerance);
  READ(goal_tolerance);
  READ(goal_time_tolerance);
  READ(jitter_warning);
  READ(clock_jump_tolerance);
  READ(min_position);
  READ(max_position);
  READ(max_velocity);
  READ(max_acceleration);
  READ(max_step);
#undef READ
  for (const auto &item : source) {
    auto key = py::cast<std::string>(item.first);
    if (!accepted.count(key))
      throw std::invalid_argument("Unknown arm parameter: " + key);
  }
  c.validate();
  return c;
}
py::dict state_dict(const Config &config, const State &state) {
  py::dict out;
  out["name"] = config.name;
  out["joint_names"] = config.joint_names;
  out["positions"] = state.position;
  out["velocities"] = state.velocity;
  out["stamp_unix_ns"] = state.stamp;
  out["received_monotonic_ns"] = state.valid ? monotonic_ns(state.received) : 0;
  out["age_s"] = state.valid ? seconds(Clock::now(), state.received)
                             : std::numeric_limits<double>::infinity();
  out["read_duration_s"] = state.read_duration;
  out["valid"] = state.valid;
  return out;
}
py::dict state(const Controller &controller) {
  auto snapshot = controller.snapshot();
  py::list arms;
  for (size_t i = 0; i < snapshot.states.size(); ++i) {
    auto arm = state_dict(controller.arms()[i]->config, snapshot.states[i]);
    if (snapshot.active) {
      arm["desired_positions"] = snapshot.desired_positions[i];
      arm["goal_id"] = snapshot.goal_id;
      arm["start_unix_ns"] = snapshot.start_unix_ns;
      arm["desired_stamp_unix_ns"] = snapshot.desired_stamp_unix_ns;
      arm["nominal_elapsed_s"] = snapshot.nominal_elapsed;
    } else {
      arm["desired_positions"] = py::none();
      arm["goal_id"] = py::none();
      arm["start_unix_ns"] = py::none();
      arm["desired_stamp_unix_ns"] = py::none();
      arm["nominal_elapsed_s"] = py::none();
    }
    arms.append(arm);
  }
  py::dict out;
  out["arms"] = arms;
  out["active"] = snapshot.active;
  out["connected"] = snapshot.connected;
  out["fault"] = snapshot.fault;
  return out;
}
py::dict diagnostics(const Controller &controller) {
  auto snapshot = controller.snapshot();
  py::list arms;
  for (size_t i = 0; i < snapshot.stats.size(); ++i) {
    const auto &s = snapshot.stats[i];
    const auto &c = controller.arms()[i]->config;
    py::dict out;
    out["name"] = c.name;
    out["ip"] = c.ip;
    out["port"] = c.port;
    out["command_rate"] = c.command_rate;
    out["read_rate"] = c.read_rate;
    out["windows_timer_resolution_ms"] = c.windows_timer_resolution_ms;
    out["allow_protective_stop_release"] = c.allow_protective_stop_release;
#define STAT(key) out[#key] = s.key
    STAT(read_calls);
    STAT(read_timeouts);
    STAT(read_errors);
    STAT(sends);
    STAT(missed_slots);
    STAT(warnings);
    STAT(last_read_duration);
    STAT(max_read_duration);
    STAT(last_send_duration);
    STAT(max_send_duration);
    STAT(last_send_interval);
    STAT(max_send_interval);
    STAT(max_lateness);
    STAT(first_send_stamp);
    STAT(message);
    STAT(clear_status);
#undef STAT
    out["state_age_s"] =
        snapshot.states[i].valid
            ? seconds(Clock::now(), snapshot.states[i].received)
            : std::numeric_limits<double>::infinity();
    arms.append(out);
  }
  py::dict out;
  out["arms"] = arms;
  out["active"] = snapshot.active;
  out["connected"] = snapshot.connected;
  out["fault"] = snapshot.fault;
  out["dropped_samples"] = snapshot.dropped_samples;
  out["windows_timer_status"] = snapshot.windows_timer_status;
#ifdef _WIN32
  out["timed_wait_backend"] = "windows_high_resolution_waitable_timer";
#else
  out["timed_wait_backend"] = "std_condition_variable";
#endif
  return out;
}
py::dict result(const Controller &controller) {
  auto goal = controller.result();
  py::dict out;
  out["goal_id"] = goal.id;
  out["status"] = goal.status;
  out["message"] = goal.message;
  out["start_unix_ns"] = goal.stamp;
  return out;
}
py::list samples(Controller &controller) {
  auto samples = controller.drain_samples();
  py::list out;
  for (const auto &sample : samples) {
    auto row = state_dict(controller.arms()[sample.arm]->config, sample.state);
    row["goal_id"] = sample.goal_id;
    if (sample.has_desired) {
      row["desired_positions"] = sample.desired;
      row["nominal_elapsed_s"] = sample.elapsed;
    }
    out.append(row);
  }
  return out;
}
} // namespace
} // namespace iimt
PYBIND11_MODULE(_control, module) {
  using namespace iimt;
  module.doc() =
      "Native best-effort CI-05 controller; no ROS or internal mock transport";
  py::class_<Controller>(module, "Controller")
      .def(py::init([](const std::vector<py::dict> &values) {
             std::vector<Config> configs;
             for (const auto &value : values)
               configs.push_back(config_from_dict(value));
             return std::make_unique<Controller>(std::move(configs));
           }),
           py::arg("arms"))
      .def("connect", &Controller::connect,
           py::call_guard<py::gil_scoped_release>())
      .def("close", &Controller::close,
           py::call_guard<py::gil_scoped_release>())
      .def("execute", &Controller::execute, py::arg("times"),
           py::arg("positions"), py::arg("start_unix_ns") = 0,
           py::arg("velocities") = Matrix{},
           py::arg("accelerations") = Matrix{},
           py::call_guard<py::gil_scoped_release>())
      .def("cancel", &Controller::cancel,
           py::call_guard<py::gil_scoped_release>())
      .def("get_state", &state)
      .def("result", &result)
      .def("diagnostics", &diagnostics)
      .def("drain_samples", &samples);
}
