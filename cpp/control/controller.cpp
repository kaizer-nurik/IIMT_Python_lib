#include "controller.hpp"
#include <algorithm>
#include <cstdio>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <utility>

namespace iimt {
void Config::validate() const {
  auto positive = [&](double value, const char *label, double upper = 1e6) {
    if (!std::isfinite(value) || value <= 0 || value > upper)
      throw std::invalid_argument(
          name + ": " + label +
          " must be finite, positive and <= " + std::to_string(upper));
  };
  if (name.empty() || sdk_library.empty() || !TcpReader::valid_address(ip) ||
      port < 1 || port > 65535)
    throw std::invalid_argument(
        "Each arm needs name, sdk_library, valid IPv4 ip and port 1..65535");
  if (joint_names.size() != 6 ||
      std::set<std::string>(joint_names.begin(), joint_names.end()).size() !=
          6 ||
      std::find(joint_names.begin(), joint_names.end(), "") !=
          joint_names.end())
    throw std::invalid_argument(
        name + ": six unique nonempty joint_names in SDK order required");
  if (windows_timer_resolution_ms < 0 || windows_timer_resolution_ms > 1000)
    throw std::invalid_argument(name +
                                ": windows_timer_resolution_ms must be an "
                                "integer in 0..1000 (0 disables the request)");
  // Bound reciprocals before converting periods to Clock durations or the
  // float ServoJ.t field. Even finite positive subnormal rates can overflow.
  for (const auto &rate : {std::make_pair(command_rate, "command_rate"),
                           std::make_pair(read_rate, "read_rate")}) {
    if (!std::isfinite(rate.first) || rate.first < .01 || rate.first > 125)
      throw std::invalid_argument(name + ": " + rate.second +
                                  " must be finite and within 0.01..125 Hz "
                                  "(period 0.008..100 seconds)");
  }
  positive(read_timeout, "read_timeout", 60);
  positive(state_timeout, "state_timeout", 60);
  positive(startup_timeout, "startup_timeout", 120);
  positive(servo_a, "servo_a");
  positive(servo_v, "servo_v");
  for (const auto &parameter : {std::make_pair(servo_a, "servo_a"),
                                std::make_pair(servo_v, "servo_v")}) {
    const float encoded = static_cast<float>(parameter.first);
    if (!std::isfinite(encoded) || encoded <= 0)
      throw std::invalid_argument(name + ": " + parameter.second +
                                  " must remain finite and positive when "
                                  "encoded as an SDK float");
  }
  positive(start_tolerance, "start_tolerance");
  positive(path_tolerance, "path_tolerance");
  positive(goal_tolerance, "goal_tolerance");
  positive(goal_time_tolerance, "goal_time_tolerance", 120);
  positive(jitter_warning, "jitter_warning", 10);
  positive(clock_jump_tolerance, "clock_jump_tolerance", 10);
  trajectory::advance_seconds(advance_ms);
  if (!std::isfinite(lookahead_time) || lookahead_time < 0 ||
      lookahead_time > 1 || !std::isfinite(gain) || gain < 0 || gain > 1e6)
    throw std::invalid_argument(
        name + ": invalid lookahead_time (0..1 s) or gain (0..1e6)");
  for (size_t i = 0; i < 6; ++i) {
    if (!std::isfinite(min_position[i]) || !std::isfinite(max_position[i]) ||
        min_position[i] >= max_position[i])
      throw std::invalid_argument(
          name + ": invalid position limits, axis=" + std::to_string(i + 1));
    positive(max_velocity[i], "max_velocity");
    positive(max_acceleration[i], "max_acceleration");
    positive(max_step[i], "max_step");
  }
}
Controller::Controller(std::vector<Config> configs) {
  if (configs.empty() || configs.size() > 2)
    throw std::invalid_argument("One or two CI-05 arms required");
  std::set<std::string> names, endpoints, joints;
  for (auto &config : configs) {
    config.validate();
    if (!names.insert(config.name).second ||
        !endpoints.insert(config.ip + ":" + std::to_string(config.port)).second)
      throw std::invalid_argument("Arm names and endpoints must be unique");
    for (const auto &name : config.joint_names)
      if (!joints.insert(name).second)
        throw std::invalid_argument("Joint names must be globally unique: " +
                                    name);
    arms_.push_back(std::make_unique<Arm>(std::move(config)));
  }
}
Controller::~Controller() { close(); }
void Controller::login(Arm &arm) {
  arm.sdk = std::make_unique<Sdk>(arm.config.sdk_library);
  arm.control_logged =
      arm.sdk->login(arm.config.ip, arm.config.port, arm.control);
  if (!arm.control_logged)
    throw std::runtime_error(arm.config.name + ": API_Login(control) failed");
  arm.servo_logged = arm.sdk->login(arm.config.ip, arm.config.port, arm.servo);
  if (!arm.servo_logged)
    throw std::runtime_error(arm.config.name + ": API_Login(servo) failed");
}
void Controller::logout(Arm &arm) {
  if (arm.servo_logged) {
    if (!arm.sdk->logout(arm.servo))
      std::fprintf(stderr, "IIMT ERROR arm=%s API_Logout(servo) failed\n",
                   arm.config.name.c_str());
    arm.servo_logged = false;
  }
  if (arm.control_logged) {
    if (!arm.sdk->logout(arm.control))
      std::fprintf(stderr, "IIMT ERROR arm=%s API_Logout(control) failed\n",
                   arm.config.name.c_str());
    arm.control_logged = false;
  }
  arm.sdk.reset();
}
void Controller::connect() {
  std::unique_lock<std::mutex> lifecycle(lifecycle_mutex_);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (connected_)
      return;
    if (!fault_.empty())
      throw std::runtime_error(
          "Controller fault latched; create new controller: " + fault_);
    shutdown_ = false;
    for (auto &arm : arms_)
      arm->state = State{};
  }
  try {
#ifdef _WIN32
    windows_waits_.reset_for_connect();
#endif
    unsigned timer_period = 0;
    for (const auto &arm : arms_) {
      const auto requested =
          static_cast<unsigned>(arm->config.windows_timer_resolution_ms);
      if (requested && (!timer_period || requested < timer_period))
        timer_period = requested;
    }
    const auto timer_status = windows_timer_.start(timer_period);
    {
      std::lock_guard<std::mutex> lock(mutex_);
      windows_timer_status_ = timer_status;
    }
    for (auto &arm : arms_)
      login(*arm);
    for (size_t i = 0; i < arms_.size(); ++i) {
      arms_[i]->reader_thread = std::thread(&Controller::read_loop, this, i);
      arms_[i]->sender_thread = std::thread(&Controller::send_loop, this, i);
    }
    auto timeout = arms_.front()->config.startup_timeout;
    for (const auto &arm : arms_)
      timeout = std::max(timeout, arm->config.startup_timeout);
    std::unique_lock<std::mutex> lock(mutex_);
    bool ready = wake_.wait_until(lock, shifted(Clock::now(), timeout), [&] {
      return shutdown_ || !fault_.empty() ||
             std::all_of(arms_.begin(), arms_.end(), [&](const auto &arm) {
               return arm->state.valid &&
                      seconds(Clock::now(), arm->state.received) <=
                          arm->config.state_timeout;
             });
    });
    if (shutdown_ || !fault_.empty())
      throw std::runtime_error("Controller startup interrupted: " + fault_);
    if (!ready) {
      std::string reason = "Timed out acquiring fresh initial state";
      for (const auto &arm : arms_)
        reason += "; arm=" + arm->config.name + " " + arm->stats.message;
      throw std::runtime_error(reason);
    }
    connected_ = true;
  } catch (...) {
    shutdown_ = true;
#ifdef _WIN32
    windows_waits_.shutdown();
#endif
    wake_.notify_all();
    for (auto &arm : arms_) {
      if (arm->sender_thread.joinable())
        arm->sender_thread.join();
      if (arm->reader_thread.joinable())
        arm->reader_thread.join();
      logout(*arm);
    }
    windows_timer_.stop();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      windows_timer_status_ = "released_after_startup_failure";
    }
    throw;
  }
}
void Controller::close() {
  std::lock_guard<std::mutex> lifecycle(lifecycle_mutex_);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    connected_ = false;
    shutdown_ = true;
    if (goal_ && goal_->status == "running" && !goal_->cancel) {
      goal_->cancel = true;
      goal_->requested_status = "cancelled";
      goal_->message = "Cancelled by controller shutdown";
    }
  }
#ifdef _WIN32
  windows_waits_.shutdown();
#endif
  wake_.notify_all();
  for (auto &arm : arms_) {
    if (arm->sender_thread.joinable())
      arm->sender_thread.join();
    if (arm->reader_thread.joinable())
      arm->reader_thread.join();
    logout(*arm);
  }
  windows_timer_.stop();
  std::lock_guard<std::mutex> lock(mutex_);
  connected_ = false;
  windows_timer_status_ = "released_on_close";
}
std::string Controller::context(const Arm &arm, size_t axis, double desired,
                                double tolerance) const {
  std::ostringstream out;
  out << std::setprecision(9) << "arm=" << arm.config.name
      << " joint=" << arm.config.joint_names[axis] << " SDK_axis=" << axis + 1
      << " desired_rad=" << desired
      << " actual_rad=" << arm.state.position[axis]
      << " error_rad=" << desired - arm.state.position[axis]
      << " tolerance_rad=" << tolerance
      << " state_age_s=" << seconds(Clock::now(), arm.state.received)
      << " measured_stamp_unix_ns=" << arm.state.stamp;
  return out.str();
}
std::string Controller::all_context(const Arm &arm,
                                    const Joints &desired) const {
  std::string out;
  for (size_t i = 0; i < 6; ++i)
    out += (i ? "; " : "") + context(arm, i, desired[i]);
  return out;
}
void Controller::check_fresh(const Arm &arm, Time now) const {
  if (!arm.state.valid ||
      seconds(now, arm.state.received) > arm.config.state_timeout ||
      arm.state.read_duration > arm.config.state_timeout)
    throw std::runtime_error(
        "No fresh state: arm=" + arm.config.name +
        " age_s=" + std::to_string(seconds(now, arm.state.received)) +
        " read_duration_s=" + std::to_string(arm.state.read_duration) +
        " state_timeout_s=" + std::to_string(arm.config.state_timeout) + "; " +
        arm.stats.message);
}
std::uint64_t Controller::execute(const std::vector<double> &times,
                                  const Matrix &positions, std::int64_t stamp,
                                  const Matrix &velocities,
                                  const Matrix &accelerations) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!connected_ || shutdown_)
    throw std::runtime_error("Controller is not connected");
  if (!fault_.empty())
    throw std::runtime_error("Controller fault latched: " + fault_);
  if (goal_ && goal_->status == "running")
    throw std::runtime_error("Another goal owns commands");
  if (times.empty() || times.size() > 1000000 ||
      positions.size() != times.size())
    throw std::invalid_argument(
        "Expected 1..1000000 timestamps and matching positions");
  const auto width = 6 * arms_.size();
  auto shape = [&](const Matrix &matrix, const char *name, bool optional) {
    if (optional && matrix.empty())
      return;
    if (matrix.size() != times.size())
      throw std::invalid_argument(std::string(name) + " row count mismatch");
    for (const auto &row : matrix)
      if (row.size() != width)
        throw std::invalid_argument(std::string(name) + " requires exactly " +
                                    std::to_string(width) + " columns");
  };
  shape(positions, "positions", false);
  shape(velocities, "velocities", true);
  shape(accelerations, "accelerations", true);
  if (!accelerations.empty() && velocities.empty())
    throw std::invalid_argument("Accelerations require velocities");
  double advance = 0;
  auto goal = std::make_shared<Goal>();
  for (const auto &arm : arms_) {
    if (!arm->config.enable_motion)
      throw std::runtime_error("Motion disabled: arm=" + arm->config.name);
    check_fresh(*arm, Clock::now());
    advance = std::max(advance, arm->config.advance_ms / 1000.);
    size_t offset = goal->paths.size() * 6;
    std::vector<Point> path;
    for (size_t row = 0; row < times.size(); ++row) {
      Point point;
      point.time = times[row];
      point.derivatives =
          !accelerations.empty() ? 2 : (!velocities.empty() ? 1 : 0);
      for (size_t axis = 0; axis < 6; ++axis) {
        point.position[axis] = positions[row][offset + axis];
        if (point.derivatives >= 1)
          point.velocity[axis] = velocities[row][offset + axis];
        if (point.derivatives == 2)
          point.acceleration[axis] = accelerations[row][offset + axis];
        if (!std::isfinite(point.position[axis]) ||
            point.position[axis] < arm->config.min_position[axis] ||
            point.position[axis] > arm->config.max_position[axis])
          throw std::invalid_argument(
              "Position limit at point=" + std::to_string(row) + "; " +
              context(*arm, axis, point.position[axis]));
      }
      path.push_back(point);
    }
    trajectory::validate(path);
    if (path.back().time > 86400)
      throw std::invalid_argument("Trajectory duration exceeds 24 hours");
    trajectory::validate_endpoint(path.back(), arm->config.max_acceleration);
    if (path.front().time == 0) {
      for (size_t axis = 0; axis < 6; ++axis)
        if (std::abs(path.front().position[axis] - arm->state.position[axis]) >
            arm->config.start_tolerance)
          throw std::invalid_argument("Start mismatch: " +
                                      context(*arm, axis,
                                              path.front().position[axis],
                                              arm->config.start_tolerance));
    } else {
      Point first;
      first.position = arm->state.position;
      first.derivatives = path.front().derivatives;
      path.insert(path.begin(), first);
    }
    goal->paths.push_back(std::move(path));
  }
  const auto now = Clock::now();
  const auto wall = unix_ns();
  if (!stamp)
    stamp = wall + static_cast<std::int64_t>((advance + .1) * 1e9);
  if (stamp < 0 || stamp > wall + 86400000000000LL)
    throw std::invalid_argument(
        "Start timestamp must be nonnegative and within 24 hours");
  double delay = static_cast<double>(stamp - wall) / 1e9;
  if (delay < advance || delay > 86400)
    throw std::invalid_argument("Start timestamp must allow full advance "
                                "pre-roll and be within 24 hours");
  goal->stamp = stamp;
  goal->start = shifted(now, delay);
  goal->id = next_goal_++;
  goal->finished.resize(arms_.size(), false);
  for (auto &arm : arms_)
    arm->stats.first_send_stamp = 0;
#ifdef _WIN32
  windows_waits_.reset_cancel();
#endif
  goal_ = goal;
  wake_.notify_all();
  return goal->id;
}
void Controller::cancel() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (goal_ && goal_->status == "running" && !goal_->cancel) {
    goal_->cancel = true;
    goal_->requested_status = "cancelled";
    goal_->message = "Cancelled by client";
#ifdef _WIN32
    windows_waits_.cancel();
#endif
  }
  wake_.notify_all();
}
bool Controller::wait_until(Time deadline, const std::shared_ptr<Goal> &goal) {
#ifdef _WIN32
  // MinGW condition-variable timed waits remained near 16 ms even after
  // timeBeginPeriod(1). Use kernel high-resolution one-shot timers instead.
  thread_local WindowsHighResolutionTimer timer;
  for (;;) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (shutdown_ || (goal && goal->cancel))
        return false;
    }
    const auto now = Clock::now();
    if (now >= deadline)
      return true;
    // Long future goals retain a bounded safety heartbeat if SetEvent fails.
    const auto next_check = std::min(deadline, shifted(now, .1));
    const auto remaining = std::chrono::duration_cast<std::chrono::nanoseconds>(
        next_check - Clock::now());
    if (!timer.wait(remaining, windows_waits_.shutdown_handle(),
                    goal ? windows_waits_.cancel_handle() : nullptr)) {
      std::lock_guard<std::mutex> lock(mutex_);
      if (shutdown_ || (goal && goal->cancel))
        return false;
      throw std::runtime_error(
          "Windows wake event signaled without shutdown/cancel state");
    }
  }
#else
  std::unique_lock<std::mutex> lock(mutex_);
  return !wake_.wait_until(lock, deadline,
                           [&] { return shutdown_ || (goal && goal->cancel); });
#endif
}
void Controller::record_sample(size_t index) {
  Sample sample;
  sample.arm = index;
  sample.state = arms_[index]->state;
  if (goal_ && goal_->status == "running") {
    sample.goal_id = goal_->id;
    sample.elapsed = seconds(sample.state.received, goal_->start);
    sample.desired =
        trajectory::sample(goal_->paths[index], sample.elapsed).position;
    sample.has_desired = true;
  }
  constexpr size_t capacity = 100000;
  if (samples_.size() == capacity) {
    samples_.pop_front();
    ++dropped_samples_;
  }
  samples_.push_back(sample);
}
void Controller::read_loop(size_t index) {
  Arm &arm = *arms_[index];
  TcpReader reader;
  while (!shutdown_) {
    const auto begin = Clock::now();
    try {
      const auto position =
          reader.read(arm.config.ip, arm.config.port, arm.config.read_timeout);
      const auto received = Clock::now();
      const auto stamp = unix_ns();
      std::lock_guard<std::mutex> lock(mutex_);
      const double dt = seconds(received, arm.state.received);
      Joints velocity{};
      if (arm.state.valid && dt > 0)
        for (size_t i = 0; i < 6; ++i)
          velocity[i] = (position[i] - arm.state.position[i]) / dt;
      arm.state = {
          position, velocity, received, stamp, seconds(received, begin), true};
      arm.stats.message.clear();
      record_sample(index);
    } catch (const ReadTimeout &error) {
      std::lock_guard<std::mutex> lock(mutex_);
      ++arm.stats.read_timeouts;
      arm.stats.message = error.what();
    } catch (const std::exception &error) {
      std::lock_guard<std::mutex> lock(mutex_);
      ++arm.stats.read_errors;
      arm.stats.message = error.what();
    }
    {
      std::lock_guard<std::mutex> lock(mutex_);
      ++arm.stats.read_calls;
      arm.stats.last_read_duration = seconds(Clock::now(), begin);
      arm.stats.max_read_duration =
          std::max(arm.stats.max_read_duration, arm.stats.last_read_duration);
    }
    wake_.notify_all();
    // Limit start-to-start rate, not completion-to-next-start rate. A slow
    // transaction already consumed its period; do not add another idle period.
    try {
      wait_until(
          std::max(shifted(begin, 1 / arm.config.read_rate), Clock::now()));
    } catch (const std::exception &error) {
      reader_wait_failed(index, error.what());
      return;
    }
  }
}
void Controller::reader_wait_failed(size_t index, const std::string &reason) {
  std::lock_guard<std::mutex> lock(mutex_);
  fault_ =
      "Reader timing failure: arm=" + arms_[index]->config.name + "; " + reason;
  arms_[index]->stats.message = fault_;
  connected_ = false;
  shutdown_ = true;
  if (goal_ && goal_->status == "running") {
    goal_->cancel = true;
    goal_->requested_status = "aborted";
    goal_->message += "; " + fault_;
  }
#ifdef _WIN32
  windows_waits_.shutdown();
#endif
  std::fprintf(stderr, "IIMT ERROR %s\n", fault_.c_str());
  wake_.notify_all();
}
void Controller::fail_goal(const std::shared_ptr<Goal> &goal,
                           const std::string &reason) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!goal->cancel) {
    goal->message = reason;
    goal->requested_status = "aborted";
    goal->cancel = true;
  } else if (goal->requested_status != "aborted") {
    goal->message += "; failure=" + reason;
    goal->requested_status = "aborted";
  }
#ifdef _WIN32
  windows_waits_.cancel();
#endif
  wake_.notify_all();
}
void Controller::check_command(const Arm &arm, const Point &point,
                               const Joints &previous, double dt) const {
  for (size_t axis = 0; axis < 6; ++axis) {
    const auto &c = arm.config;
    const double step = std::abs(point.position[axis] - previous[axis]);
    if (!std::isfinite(point.position[axis]) ||
        point.position[axis] < c.min_position[axis] ||
        point.position[axis] > c.max_position[axis] || dt <= 0 ||
        step > c.max_step[axis] || step / dt > c.max_velocity[axis] ||
        !std::isfinite(point.velocity[axis]) ||
        std::abs(point.velocity[axis]) > c.max_velocity[axis] ||
        !std::isfinite(point.acceleration[axis]) ||
        std::abs(point.acceleration[axis]) > c.max_acceleration[axis])
      throw std::runtime_error(
          "Command limit: " + context(arm, axis, point.position[axis]) +
          " previous_command_rad=" + std::to_string(previous[axis]) +
          " step_rad=" + std::to_string(step) + " max_step_rad=" +
          std::to_string(c.max_step[axis]) + " dt_s=" + std::to_string(dt) +
          " velocity_rad_s=" + std::to_string(point.velocity[axis]) +
          " max_velocity=" + std::to_string(c.max_velocity[axis]) +
          " acceleration_rad_s2=" + std::to_string(point.acceleration[axis]) +
          " max_acceleration=" + std::to_string(c.max_acceleration[axis]));
  }
}
void Controller::send_loop(size_t index) {
  std::uint64_t consumed = 0;
  for (;;) {
    std::shared_ptr<Goal> goal;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      wake_.wait(lock, [&] {
        return shutdown_ ||
               (goal_ && goal_->status == "running" && goal_->id != consumed);
      });
      if (!goal_ || goal_->status != "running" || goal_->id == consumed)
        return;
      goal = goal_;
      consumed = goal->id;
    }
    run_goal(index, goal);
    if (shutdown_)
      return;
  }
}
void Controller::warn_timing(Arm &arm, const std::string &message) {
  ++arm.stats.warnings;
  arm.stats.message = message;
  if (arm.stats.warnings == 1 || arm.stats.warnings % 125 == 0)
    std::fprintf(stderr, "IIMT WARN arm=%s %s\n", arm.config.name.c_str(),
                 message.c_str());
}
bool Controller::prepare_command(size_t index,
                                 const std::shared_ptr<Goal> &goal,
                                 Dispatch &dispatch, Point &command) {
  Arm &arm = *arms_[index];
  const auto &config = arm.config;
  const auto &path = goal->paths[index];
  const Time tick = Clock::now();
  const double elapsed = seconds(tick, goal->start);
  command = trajectory::sample(path, elapsed + config.advance_ms / 1000.);
  std::lock_guard<std::mutex> lock(mutex_);
  if (goal->cancel || shutdown_)
    return false;
  check_fresh(arm, tick);
  if (std::abs(static_cast<double>(unix_ns() - goal->stamp) / 1e9 - elapsed) >
      config.clock_jump_tolerance)
    throw std::runtime_error("Wall/steady clock divergence: arm=" +
                             config.name);
  const auto nominal = trajectory::sample(path, elapsed);
  for (size_t axis = 0; axis < 6; ++axis)
    if (std::abs(nominal.position[axis] - arm.state.position[axis]) >
        config.path_tolerance)
      throw std::runtime_error(
          "Path tolerance: " +
          context(arm, axis, nominal.position[axis], config.path_tolerance));
  bool endpoint = elapsed >= path.back().time &&
                  arm.state.received >= shifted(goal->start, path.back().time);
  for (size_t axis = 0; axis < 6; ++axis)
    endpoint =
        endpoint && std::abs(path.back().position[axis] -
                             arm.state.position[axis]) <= config.goal_tolerance;
  if (endpoint && dispatch.endpoint_sent)
    return false;
  if (elapsed > path.back().time + config.goal_time_tolerance)
    throw std::runtime_error("Missed endpoint deadline: " +
                             all_context(arm, path.back().position));
  if (!dispatch.have_send)
    dispatch.previous = arm.state.position;
  check_command(arm, command, dispatch.previous,
                dispatch.have_send ? seconds(tick, dispatch.last_send)
                                   : 1 / config.command_rate);
  const double lateness = std::max(0., seconds(tick, dispatch.next));
  arm.stats.max_lateness = std::max(arm.stats.max_lateness, lateness);
  if (lateness > config.jitter_warning)
    warn_timing(arm, "Timing warning: late dispatch " +
                         std::to_string(lateness) + " s; no replay");
  return true;
}
void Controller::send_point(size_t index, const Point &point,
                            Dispatch &dispatch) {
  Arm &arm = *arms_[index];
  const auto &config = arm.config;
  const double period = 1 / config.command_rate;
  ServoParameters parameter;
  std::copy(point.position.begin(), point.position.end(), parameter.q);
  parameter.a = static_cast<float>(config.servo_a);
  parameter.v = static_cast<float>(config.servo_v);
  parameter.t = static_cast<float>(period);
  parameter.lookahead_time = static_cast<float>(config.lookahead_time);
  parameter.gain = static_cast<float>(config.gain);
  const auto begin = Clock::now();
  const auto stamp = unix_ns();
  // Even a false SDK result may have partially transmitted a command.
  dispatch.motion_sent = true;
  const bool ok = arm.sdk->servo(arm.servo, parameter);
  const auto finished = Clock::now();
  std::lock_guard<std::mutex> lock(mutex_);
  arm.stats.last_send_duration = seconds(finished, begin);
  arm.stats.max_send_duration =
      std::max(arm.stats.max_send_duration, arm.stats.last_send_duration);
  if (arm.stats.last_send_duration > period + config.jitter_warning)
    warn_timing(arm, "Timing warning: ServoJ call duration=" +
                         std::to_string(arm.stats.last_send_duration) + " s");
  if (dispatch.have_send) {
    arm.stats.last_send_interval = seconds(begin, dispatch.last_send);
    arm.stats.max_send_interval =
        std::max(arm.stats.max_send_interval, arm.stats.last_send_interval);
  } else
    arm.stats.first_send_stamp = stamp;
  if (!ok)
    throw std::runtime_error(
        "API_Servoj returned false; partial transmission possible; " +
        all_context(arm, point.position));
  ++arm.stats.sends;
  dispatch.have_send = true;
  dispatch.last_send = begin;
  dispatch.previous = point.position;
  dispatch.next = shifted(dispatch.next, period);
  if (dispatch.next <= finished) {
    const auto skipped = static_cast<std::uint64_t>(std::floor(
                             seconds(finished, dispatch.next) / period)) +
                         1;
    dispatch.next = shifted(dispatch.next, skipped * period);
    arm.stats.missed_slots += skipped;
  }
}
void Controller::run_goal(size_t index, const std::shared_ptr<Goal> &goal) {
  Dispatch dispatch;
  dispatch.next =
      shifted(goal->start, -arms_[index]->config.advance_ms / 1000.);
  try {
    while (wait_until(dispatch.next, goal)) {
      Point command;
      if (!prepare_command(index, goal, dispatch, command))
        break;
      send_point(index, command, dispatch);
      dispatch.endpoint_sent = command.time >= goal->paths[index].back().time;
    }
  } catch (const std::exception &error) {
    fail_goal(goal, error.what());
  }
  finish_arm(index, goal, dispatch.motion_sent);
}
void Controller::finish_arm(size_t index, const std::shared_ptr<Goal> &goal,
                            bool motion_sent) {
  Arm &arm = *arms_[index];
  std::string evidence;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    const double elapsed = seconds(Clock::now(), goal->start);
    evidence =
        "desired_reference=nominal_at_cleanup; nominal_elapsed_s=" +
        std::to_string(elapsed) + "; " +
        all_context(arm,
                    trajectory::sample(goal->paths[index], elapsed).position);
  }
  bool stopped = true, cleared = true;
  std::string clear_status = "not_needed_no_command";
  if (motion_sent) {
    stopped = arm.sdk->stop(arm.control);
    // In the supplied SDK, Clear sends "unlock protective stop", not an
    // independently verified queue-purge operation. Never release implicitly.
    if (!stopped) {
      clear_status = "skipped_stop_failed";
    } else if (arm.config.allow_protective_stop_release) {
      cleared = arm.sdk->clear(arm.control);
      clear_status =
          cleared ? "succeeded_explicit_opt_in" : "failed_explicit_opt_in";
    } else {
      clear_status = "skipped_not_authorized";
    }
  }
  std::lock_guard<std::mutex> lock(mutex_);
  arm.stats.clear_status = clear_status;
  if (motion_sent && clear_status == "skipped_not_authorized")
    goal->message += "; arm=" + arm.config.name +
                     " API_Clear skipped: protective-stop release not "
                     "authorized; queue purge is NOT confirmed";
  if (!stopped || !cleared) {
    const std::string failure =
        "SDK Stop/Clear failed; arm=" + arm.config.name +
        " Stop=" + std::to_string(stopped) + " Clear=" + clear_status +
        "; physical stop is NOT confirmed; joint_cause=not_reported_by_sdk; " +
        evidence;
    goal->message += "; stop_failure=" + failure;
    goal->requested_status = "aborted";
    goal->cancel = true;
    fault_ = goal->message;
#ifdef _WIN32
    windows_waits_.cancel();
#endif
  }
  goal->finished[index] = true;
  if (std::all_of(goal->finished.begin(), goal->finished.end(),
                  [](bool done) { return done; })) {
    goal->status = goal->requested_status;
    if (goal->status == "aborted")
      std::fprintf(stderr, "IIMT ERROR %s\n", goal->message.c_str());
  }
  wake_.notify_all();
}
Controller::Snapshot Controller::snapshot() const {
  std::lock_guard<std::mutex> lock(mutex_);
  Snapshot out;
  for (const auto &arm : arms_) {
    out.states.push_back(arm->state);
    out.stats.push_back(arm->stats);
  }
  out.active = goal_ && goal_->status == "running";
  if (out.active) {
    // Reference time is now on the NOMINAL clock, independent of dispatch
    // advance.
    out.goal_id = goal_->id;
    out.start_unix_ns = goal_->stamp;
    out.nominal_elapsed = seconds(Clock::now(), goal_->start);
    out.desired_stamp_unix_ns = unix_ns();
    for (const auto &path : goal_->paths)
      out.desired_positions.push_back(
          trajectory::sample(path, out.nominal_elapsed).position);
  }
  out.connected = connected_;
  out.fault = fault_;
  out.windows_timer_status = windows_timer_status_;
  out.dropped_samples = dropped_samples_;
  return out;
}
Goal Controller::result() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (goal_) {
    Goal out;
    out.id = goal_->id;
    out.stamp = goal_->stamp;
    out.start = goal_->start;
    out.status = goal_->status;
    out.message = goal_->message;
    return out;
  }
  Goal idle;
  idle.status = "idle";
  idle.message.clear();
  return idle;
}
std::vector<Sample> Controller::drain_samples() {
  std::lock_guard<std::mutex> lock(mutex_);
  std::vector<Sample> out(samples_.begin(), samples_.end());
  samples_.clear();
  return out;
}
} // namespace iimt
