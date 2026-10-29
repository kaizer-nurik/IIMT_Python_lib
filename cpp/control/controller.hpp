#pragma once
#include "sdk.hpp"
#include "tcp_reader.hpp"
#include "trajectory.hpp"
#include <atomic>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

namespace iimt {
using Clock = std::chrono::steady_clock;
using Time = Clock::time_point;
using Joints = trajectory::Joints;
using Point = trajectory::Point;
using Matrix = std::vector<std::vector<double>>;
inline double seconds(Time a, Time b) {
  return std::chrono::duration<double>(a - b).count();
}
inline Time shifted(Time t, double seconds) {
  return t + std::chrono::duration_cast<Clock::duration>(
                 std::chrono::duration<double>(seconds));
}
inline std::int64_t unix_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}
inline std::int64_t monotonic_ns(Time t) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             t.time_since_epoch())
      .count();
}
struct Config {
  std::string name, ip, sdk_library;
  std::vector<std::string> joint_names;
  int port{29999};
  int windows_timer_resolution_ms{1};
  bool enable_motion{false};
  bool allow_protective_stop_release{false};
  double command_rate{125}, read_rate{125}, read_timeout{.1}, state_timeout{.2};
  double servo_a{5}, servo_v{3}, lookahead_time{.012}, gain{0}, advance_ms{0};
  double start_tolerance{.02}, path_tolerance{3}, goal_tolerance{.003};
  double goal_time_tolerance{2}, jitter_warning{.004}, clock_jump_tolerance{.1};
  double startup_timeout{5};
  Joints min_position{-6.2832, -2.6167, -2.8783, -3.0528, -3.0528, -6.2832};
  Joints max_position{6.2832, 2.6167, 2.8783, 3.0528, 3.0528, 6.2832};
  Joints max_velocity{3.1415, 3.1415, 3.1415, 3.1415, 3.1415, 3.1415};
  Joints max_acceleration{1.875, 2.5, 3.75, 3.125, 3.75, 3.75};
  Joints max_step{.02, .02, .02, .02, .02, .02};
  void validate() const;
};
struct State {
  Joints position{}, velocity{};
  Time received{};
  std::int64_t stamp{};
  double read_duration{};
  bool valid{false};
};
struct Statistics {
  std::uint64_t read_calls{}, read_timeouts{}, read_errors{}, sends{},
      missed_slots{}, warnings{};
  double last_read_duration{}, max_read_duration{}, last_send_duration{},
      max_send_duration{};
  double last_send_interval{}, max_send_interval{}, max_lateness{};
  std::int64_t first_send_stamp{};
  std::string message, clear_status{"not_attempted"};
};
struct Sample {
  size_t arm{};
  State state;
  std::uint64_t goal_id{};
  Joints desired{};
  double elapsed{};
  bool has_desired{false};
};
struct Goal {
  std::uint64_t id{};
  std::int64_t stamp{};
  Time start{};
  std::vector<std::vector<Point>> paths;
  std::vector<bool> finished;
  bool cancel{false};
  std::string requested_status{"succeeded"}, message{"Trajectory completed"};
  std::string status{"running"};
};
struct Arm {
  explicit Arm(Config value) : config(std::move(value)) {}
  Config config;
  State state;
  Statistics stats;
  std::unique_ptr<Sdk> sdk;
  Handle control{}, servo{};
  bool control_logged{false}, servo_logged{false};
  std::thread reader_thread, sender_thread;
};

class Controller {
public:
  explicit Controller(std::vector<Config> configs);
  ~Controller();
  Controller(const Controller &) = delete;
  Controller &operator=(const Controller &) = delete;
  void connect();
  void close();
  std::uint64_t execute(const std::vector<double> &times,
                        const Matrix &positions, std::int64_t stamp,
                        const Matrix &velocities, const Matrix &accelerations);
  void cancel();
  struct Snapshot {
    std::vector<State> states;
    std::vector<Statistics> stats;
    std::vector<Joints> desired_positions;
    std::uint64_t goal_id{};
    std::int64_t start_unix_ns{}, desired_stamp_unix_ns{};
    double nominal_elapsed{};
    bool active{}, connected{};
    std::string fault, windows_timer_status;
    std::uint64_t dropped_samples{};
  };
  Snapshot snapshot() const;
  Goal result() const;
  std::vector<Sample> drain_samples();
  const std::vector<std::unique_ptr<Arm>> &arms() const { return arms_; }

private:
  void login(Arm &arm);
  void logout(Arm &arm);
  void read_loop(size_t index);
  void reader_wait_failed(size_t index, const std::string &reason);
  void send_loop(size_t index);
  struct Dispatch {
    Time next{}, last_send{};
    Joints previous{};
    bool motion_sent{false}, have_send{false}, endpoint_sent{false};
  };
  void run_goal(size_t index, const std::shared_ptr<Goal> &goal);
  bool prepare_command(size_t index, const std::shared_ptr<Goal> &goal,
                       Dispatch &dispatch, Point &command);
  void send_point(size_t index, const Point &point, Dispatch &dispatch);
  void warn_timing(Arm &arm, const std::string &message);
  void finish_arm(size_t index, const std::shared_ptr<Goal> &goal,
                  bool motion_sent);
  void fail_goal(const std::shared_ptr<Goal> &goal, const std::string &reason);
  void check_fresh(const Arm &arm, Time now) const;
  void check_command(const Arm &arm, const Point &point, const Joints &previous,
                     double dt) const;
  std::string context(const Arm &arm, size_t axis, double desired,
                      double tolerance = 0) const;
  std::string all_context(const Arm &arm, const Joints &desired) const;
  void record_sample(size_t index);
  bool wait_until(Time deadline, const std::shared_ptr<Goal> &goal = {});
  std::vector<std::unique_ptr<Arm>> arms_;
  mutable std::mutex mutex_;
  std::mutex lifecycle_mutex_;
  WindowsTimerResolution windows_timer_;
#ifdef _WIN32
  WindowsWaitSignals windows_waits_;
#endif
  std::string windows_timer_status_{"not_connected"};
  std::condition_variable wake_;
  bool connected_{false};
  std::atomic<bool> shutdown_{false};
  std::shared_ptr<Goal> goal_;
  std::uint64_t next_goal_{1}, dropped_samples_{};
  std::deque<Sample> samples_;
  std::string fault_;
};
} // namespace iimt
