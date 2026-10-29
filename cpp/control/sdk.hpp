#pragma once
#include "windows_support.hpp"
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace iimt {
using Handle = std::int64_t;
#pragma pack(push, 1)
struct ServoParameters {
  double q[6]{};
  float a{}, v{}, t{}, lookahead_time{}, gain{};
};
#pragma pack(pop)
static_assert(sizeof(ServoParameters) == 68,
              "Vendor ABI requires packed 68-byte ServoJ");
static_assert(sizeof(Handle) == 8, "Only x64 SDKs are supported");

// No SDK functions are called at import. Each arm owns separate control and
// servo handles.
class Sdk {
public:
  explicit Sdk(const std::string &path) {
#ifdef _WIN32
    // Honor dependency directories registered by repaired Windows wheels while
    // avoiding legacy current-working-directory DLL lookup.
    const auto absolute = windows_support::absolute_path(path);
    const auto resolved = windows_support::utf8_path(absolute);
    library_ = LoadLibraryExW(absolute.c_str(), nullptr,
                              LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR |
                                  LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
#else
    library_ = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
#endif
    if (!library_) {
#ifdef _WIN32
      const auto error = GetLastError();
      throw std::runtime_error("Cannot load SDK: requested='" + path +
                               "' resolved='" + resolved +
                               "'; Win32 error=" + std::to_string(error));
#else
      const char *error = dlerror();
      throw std::runtime_error("Cannot load SDK: " + path + "; " +
                               (error ? error : "unknown loader error"));
#endif
    }
    try {
      login_ = symbol<Login>("API_Login");
      logout_ = symbol<Logout>("API_Logout");
      servo_ = symbol<Servo>("API_Servoj");
      stop_ = symbol<Unary>("API_Stop");
      clear_ = symbol<Unary>("API_ClearUnfinishedTrajectory");
    } catch (...) {
      unload();
      throw;
    }
  }
  ~Sdk() { unload(); }
  Sdk(const Sdk &) = delete;
  Sdk &operator=(const Sdk &) = delete;
  bool login(const std::string &ip, int port, Handle &handle) {
    return login_(ip.c_str(), port, handle) != 0;
  }
  bool logout(Handle &handle) { return logout_(handle) != 0; }
  bool servo(Handle handle, ServoParameters &p) {
    return servo_(handle, &p) != 0;
  }
  bool stop(Handle handle) { return stop_(handle) != 0; }
  bool clear(Handle handle) { return clear_(handle) != 0; }

private:
  using Login = int (*)(const char *, int, Handle &);
  using Logout = int (*)(Handle &);
  using Servo = int (*)(Handle, ServoParameters *);
  using Unary = int (*)(Handle);
  template <class T> T symbol(const char *name) {
#ifdef _WIN32
    auto value = GetProcAddress(library_, name);
#else
    auto value = dlsym(library_, name);
#endif
    if (!value)
      throw std::runtime_error(std::string("Missing SDK export: ") + name);
    return reinterpret_cast<T>(value);
  }
  void unload() {
    if (!library_)
      return;
#ifdef _WIN32
    FreeLibrary(library_);
#else
    dlclose(library_);
#endif
    library_ = nullptr;
  }
#ifdef _WIN32
  HMODULE library_{};
#else
  void *library_{};
#endif
  Login login_{};
  Logout logout_{};
  Servo servo_{};
  Unary stop_{}, clear_{};
};
} // namespace iimt
