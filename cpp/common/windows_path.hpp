#pragma once
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace iimt::windows_support {
inline std::wstring absolute_path(const std::string &path) {
  if (path.empty() || path.find('\0') != std::string::npos)
    throw std::invalid_argument(
        "file path must be nonempty and contain no NUL");
  const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                                        path.c_str(), -1, nullptr, 0);
  if (count == 0)
    throw std::runtime_error("Invalid UTF-8 file path; Win32 error=" +
                             std::to_string(GetLastError()));
  std::wstring wide(static_cast<size_t>(count), L'\0');
  if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path.c_str(), -1,
                           wide.data(), count))
    throw std::runtime_error("Cannot decode file path; Win32 error=" +
                             std::to_string(GetLastError()));
  // Resolve exactly once: relative-path resolution depends on process CWD.
  // Win32 preserves UNC paths, unlike the observed MinGW filesystem::absolute.
  std::wstring resolved(32768, L'\0');
  const DWORD size =
      GetFullPathNameW(wide.c_str(), static_cast<DWORD>(resolved.size()),
                       resolved.data(), nullptr);
  if (size == 0)
    throw std::runtime_error(
        "Cannot resolve file path '" + path +
        "'; Win32 error=" + std::to_string(GetLastError()));
  if (size >= resolved.size())
    throw std::invalid_argument(
        "Resolved file path exceeds Windows path limit");
  resolved.resize(size);
  return resolved;
}
inline std::string utf8_path(const std::wstring &path) {
  const int count =
      WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path.c_str(), -1,
                          nullptr, 0, nullptr, nullptr);
  if (count == 0)
    throw std::runtime_error("Cannot encode resolved file path; Win32 error=" +
                             std::to_string(GetLastError()));
  std::string result(static_cast<size_t>(count), '\0');
  if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path.c_str(), -1,
                           result.data(), count, nullptr, nullptr))
    throw std::runtime_error("Cannot encode resolved file path; Win32 error=" +
                             std::to_string(GetLastError()));
  result.resize(static_cast<size_t>(count - 1));
  return result;
}
} // namespace iimt::windows_support
#endif
