#include "tcp_reader.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <locale>
#include <mutex>
#include <sstream>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace iimt {
namespace {
#ifdef _WIN32
using Socket = SOCKET;
int error_code() { return WSAGetLastError(); }
bool pending(int e) {
  return e == WSAEWOULDBLOCK || e == WSAEINPROGRESS || e == WSAEINTR;
}
void socket_close(Socket s) { closesocket(s); }
#else
using Socket = int;
int error_code() { return errno; }
bool pending(int e) {
  return e == EAGAIN || e == EWOULDBLOCK || e == EINPROGRESS || e == EINTR;
}
void socket_close(Socket s) { ::close(s); }
#endif
void ensure_network() {
#ifdef _WIN32
  static std::once_flag once;
  std::call_once(once, [] {
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data))
      throw std::runtime_error("WSAStartup failed");
  });
#endif
}
std::runtime_error socket_error(const char *operation) {
  return std::runtime_error(std::string(operation) +
                            " socket error=" + std::to_string(error_code()));
}
} // namespace
TcpReader::TcpReader() { ensure_network(); }
TcpReader::~TcpReader() { close(); }
bool TcpReader::valid_address(const std::string &ip) {
  ensure_network();
  in_addr address{};
  return inet_pton(AF_INET, ip.c_str(), &address) == 1;
}
void TcpReader::close() {
  if (socket_ != -1)
    socket_close(static_cast<Socket>(socket_));
  socket_ = -1;
  buffer_.clear();
}
void TcpReader::wait(bool writing, Deadline deadline) {
  for (;;) {
    auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(
        deadline - Clock::now());
    if (remaining.count() <= 0)
      throw ReadTimeout("TCP transaction deadline exceeded");
    timeval timeout{};
    timeout.tv_sec = static_cast<long>(remaining.count() / 1000000);
    timeout.tv_usec = static_cast<long>(remaining.count() % 1000000);
    fd_set fds;
    FD_ZERO(&fds);
    const auto socket = static_cast<Socket>(socket_);
    FD_SET(socket, &fds);
    int n = ::select(static_cast<int>(socket + 1), writing ? nullptr : &fds,
                     writing ? &fds : nullptr, nullptr, &timeout);
    if (Clock::now() >= deadline)
      throw ReadTimeout("TCP transaction deadline exceeded");
    if (n > 0)
      return;
    if (n < 0 && !pending(error_code()))
      throw socket_error("select");
  }
}
void TcpReader::connect(const std::string &ip, int port, Deadline deadline) {
  Socket s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
#ifdef _WIN32
  if (s == INVALID_SOCKET)
    throw socket_error("socket");
#else
  if (s < 0)
    throw socket_error("socket");
  if (s >= FD_SETSIZE) {
    socket_close(s);
    throw std::runtime_error("Socket exceeds select FD_SETSIZE");
  }
#endif
  socket_ = static_cast<std::intptr_t>(s);
#ifdef _WIN32
  u_long enabled = 1;
  if (ioctlsocket(s, FIONBIO, &enabled))
    throw socket_error("nonblocking");
#else
  if (fcntl(s, F_SETFL, O_NONBLOCK) < 0 || fcntl(s, F_SETFD, FD_CLOEXEC) < 0)
    throw socket_error("nonblocking");
#endif
  int yes = 1;
  setsockopt(s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char *>(&yes),
             sizeof(yes));
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_port = htons(static_cast<unsigned short>(port));
  if (inet_pton(AF_INET, ip.c_str(), &address.sin_addr) != 1)
    throw std::invalid_argument("Invalid IPv4 address: " + ip);
  if (::connect(s, reinterpret_cast<sockaddr *>(&address), sizeof(address)) !=
      0) {
    if (!pending(error_code()))
      throw socket_error("connect");
    wait(true, deadline);
    int error = 0;
#ifdef _WIN32
    int length = sizeof(error);
#else
    socklen_t length = sizeof(error);
#endif
    if (getsockopt(s, SOL_SOCKET, SO_ERROR, reinterpret_cast<char *>(&error),
                   &length) != 0 ||
        error)
      throw std::runtime_error("TCP connect failed, SO_ERROR=" +
                               std::to_string(error));
  }
  if (line(deadline).empty())
    throw std::runtime_error("Empty dashboard greeting");
}
void TcpReader::send(const std::string &data, Deadline deadline) {
  size_t offset = 0;
  while (offset < data.size()) {
    wait(true, deadline);
#ifdef _WIN32
    constexpr int flags = 0;
#else
    constexpr int flags = MSG_NOSIGNAL;
#endif
    int n = static_cast<int>(
        ::send(static_cast<Socket>(socket_), data.data() + offset,
               static_cast<int>(data.size() - offset), flags));
    if (n > 0)
      offset += static_cast<size_t>(n);
    else if (n == 0 || !pending(error_code()))
      throw socket_error("send");
  }
}
std::string TcpReader::line(Deadline deadline) {
  for (;;) {
    auto ending = buffer_.find('\n');
    if (ending != std::string::npos) {
      std::string result = buffer_.substr(0, ending);
      buffer_.erase(0, ending + 1);
      if (!result.empty() && result.back() == '\r')
        result.pop_back();
      return result;
    }
    if (buffer_.size() > 4096)
      throw std::runtime_error("Dashboard response exceeds 4096 bytes");
    wait(false, deadline);
    char bytes[1024];
    int n = static_cast<int>(
        ::recv(static_cast<Socket>(socket_), bytes, sizeof(bytes), 0));
    if (n > 0)
      buffer_.append(bytes, static_cast<size_t>(n));
    else if (n == 0)
      throw std::runtime_error("Dashboard EOF before complete line");
    else if (!pending(error_code()))
      throw socket_error("recv");
  }
}
void TcpReader::check_idle(bool allow_closed) {
  if (!buffer_.empty())
    throw std::runtime_error("Unexpected extra dashboard response data");
  char byte;
  int n = static_cast<int>(
      ::recv(static_cast<Socket>(socket_), &byte, 1, MSG_PEEK));
  if (n > 0)
    throw std::runtime_error("Unexpected queued dashboard response");
  if (n == 0) {
    if (allow_closed) {
      close();
      return;
    }
    throw std::runtime_error("Dashboard connection closed");
  }
  if (!pending(error_code()))
    throw socket_error("idle check");
}
std::array<double, 6> TcpReader::read(const std::string &ip, int port,
                                      double timeout) {
  auto deadline = Clock::now() + std::chrono::duration_cast<Clock::duration>(
                                     std::chrono::duration<double>(timeout));
  try {
    if (socket_ == -1)
      connect(ip, port, deadline);
    check_idle();
    send("get joint rad\n", deadline);
    const auto reply = line(deadline);
    const std::string prefix = "Joint radian ";
    if (reply.compare(0, prefix.size(), prefix) != 0)
      throw std::runtime_error("Expected 'Joint radian ', received " +
                               reply.substr(0, 160));
    std::istringstream stream(reply.substr(prefix.size()));
    stream.imbue(std::locale::classic());
    std::array<double, 6> joints{};
    for (size_t i = 0; i < joints.size(); ++i) {
      if (!(stream >> joints[i]) || !std::isfinite(joints[i]))
        throw std::runtime_error("Invalid joint value in dashboard response");
      if (i != 5) {
        char comma{};
        if (!(stream >> comma) || comma != ',')
          throw std::runtime_error("Expected six comma-separated joint angles");
      }
    }
    stream >> std::ws;
    if (!stream.eof())
      throw std::runtime_error("Extra values in dashboard response");
    check_idle(true);
    if (Clock::now() >= deadline)
      throw ReadTimeout("TCP transaction deadline exceeded");
    return joints;
  } catch (...) {
    close();
    throw;
  }
}
} // namespace iimt
