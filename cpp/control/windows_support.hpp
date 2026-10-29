#pragma once

#include "../common/windows_path.hpp"
#include <cstdio>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <timeapi.h>

#endif

namespace iimt {
// Pair every successful timeBeginPeriod with the identical timeEndPeriod.
// This improves Windows wait granularity, not scheduling/real-time guarantees.
class WindowsTimerResolution {
public:
  WindowsTimerResolution() = default;
  ~WindowsTimerResolution() { stop(); }
  WindowsTimerResolution(const WindowsTimerResolution &) = delete;
  WindowsTimerResolution &operator=(const WindowsTimerResolution &) = delete;
  std::string start(unsigned milliseconds) {
    stop();
#ifdef _WIN32
    if (milliseconds == 0)
      return "disabled_by_configuration";
    const auto result = timeBeginPeriod(milliseconds);
    if (result != TIMERR_NOERROR) {
      const std::string message =
          "timeBeginPeriod(" + std::to_string(milliseconds) +
          ") failed, MMRESULT=" + std::to_string(result) +
          "; default timer resolution retained";
      std::fprintf(stderr, "IIMT WARN %s\n", message.c_str());
      return message;
    }
    period_ = milliseconds;
    return "requested_" + std::to_string(period_) + "_ms_best_effort";
#else
    (void)milliseconds;
    return "not_applicable_on_this_platform";
#endif
  }
  void stop() noexcept {
#ifdef _WIN32
    if (period_) {
      const auto result = timeEndPeriod(period_);
      if (result != TIMERR_NOERROR)
        std::fprintf(stderr,
                     "IIMT WARN timeEndPeriod(%u) failed, MMRESULT=%u\n",
                     period_, static_cast<unsigned>(result));
      period_ = 0;
    }
#endif
  }

private:
#ifdef _WIN32
  unsigned period_{};
#endif
};
} // namespace iimt

#ifdef _WIN32
#include <chrono>

namespace iimt {
inline std::runtime_error windows_wait_error(const char *operation) {
  const auto error = GetLastError();
  return std::runtime_error(std::string(operation) +
                            " failed; Win32 error=" + std::to_string(error));
}

// Event handles outlive all waiting threads and are reset only after ownership
// transitions (joined threads on reconnect; terminal previous goal on execute).
class WindowsWaitSignals {
public:
  WindowsWaitSignals() {
    shutdown_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!shutdown_)
      throw windows_wait_error("CreateEventW(shutdown)");
    cancel_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!cancel_) {
      const auto error = windows_wait_error("CreateEventW(cancel)");
      CloseHandle(shutdown_);
      throw error;
    }
  }
  ~WindowsWaitSignals() {
    CloseHandle(cancel_);
    CloseHandle(shutdown_);
  }
  WindowsWaitSignals(const WindowsWaitSignals &) = delete;
  WindowsWaitSignals &operator=(const WindowsWaitSignals &) = delete;
  void reset_for_connect() {
    if (!ResetEvent(shutdown_))
      throw windows_wait_error("ResetEvent(shutdown)");
    reset_cancel();
  }
  void reset_cancel() {
    if (!ResetEvent(cancel_))
      throw windows_wait_error("ResetEvent(cancel)");
  }
  void shutdown() noexcept { signal(shutdown_, "shutdown"); }
  void cancel() noexcept { signal(cancel_, "cancel"); }
  HANDLE shutdown_handle() const { return shutdown_; }
  HANDLE cancel_handle() const { return cancel_; }

private:
  static void signal(HANDLE handle, const char *name) noexcept {
    if (!SetEvent(handle))
      std::fprintf(stderr,
                   "IIMT ERROR SetEvent(%s) failed; Win32 error=%lu; bounded "
                   "timed-wait heartbeat remains active\n",
                   name, static_cast<unsigned long>(GetLastError()));
  }
  HANDLE shutdown_{}, cancel_{};
};

// One timer per native thread, with no APC callback, periodic tick, or busy
// wait.
class WindowsHighResolutionTimer {
public:
  WindowsHighResolutionTimer() {
    timer_ = CreateWaitableTimerExW(nullptr, nullptr,
                                    CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                    TIMER_MODIFY_STATE | SYNCHRONIZE);
    if (!timer_)
      throw windows_wait_error("CreateWaitableTimerExW(high resolution)");
  }
  ~WindowsHighResolutionTimer() { CloseHandle(timer_); }
  WindowsHighResolutionTimer(const WindowsHighResolutionTimer &) = delete;
  WindowsHighResolutionTimer &
  operator=(const WindowsHighResolutionTimer &) = delete;
  bool wait(std::chrono::nanoseconds remaining, HANDLE shutdown,
            HANDLE cancel) {
    if (remaining.count() <= 0)
      return true;
    LARGE_INTEGER due{};
    due.QuadPart =
        -((remaining.count() + 99) / 100); // Relative, ceil to 100ns.
    if (!SetWaitableTimerEx(timer_, &due, 0, nullptr, nullptr, nullptr, 0))
      throw windows_wait_error("SetWaitableTimerEx(high resolution)");
    HANDLE handles[3]{shutdown, cancel ? cancel : timer_, timer_};
    const DWORD count = cancel ? 3 : 2;
    const DWORD result =
        WaitForMultipleObjects(count, handles, FALSE, INFINITE);
    if (result == WAIT_FAILED)
      throw windows_wait_error("WaitForMultipleObjects(timer)");
    if (result == WAIT_OBJECT_0 + count - 1)
      return true;
    if (result == WAIT_OBJECT_0 || (cancel && result == WAIT_OBJECT_0 + 1))
      return false;
    throw std::runtime_error("Unexpected Windows timed-wait result=" +
                             std::to_string(result));
  }

private:
  HANDLE timer_{};
};
} // namespace iimt
#endif
