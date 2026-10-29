#pragma once
#include <array>
#include <chrono>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace iimt {
class ReadTimeout : public std::runtime_error {
public:
  using std::runtime_error::runtime_error;
};

// Each failed transaction destroys its socket: a late reply cannot become a
// fresh sample.
class TcpReader {
public:
  TcpReader();
  ~TcpReader();
  TcpReader(const TcpReader &) = delete;
  TcpReader &operator=(const TcpReader &) = delete;
  std::array<double, 6> read(const std::string &ip, int port, double timeout);
  void close();
  static bool valid_address(const std::string &ip);

private:
  using Clock = std::chrono::steady_clock;
  using Deadline = Clock::time_point;
  void connect(const std::string &ip, int port, Deadline deadline);
  void wait(bool writing, Deadline deadline);
  void send(const std::string &data, Deadline deadline);
  std::string line(Deadline deadline);
  void check_idle(bool allow_closed = false);
  std::intptr_t socket_{-1};
  std::string buffer_;
};
} // namespace iimt
