pybind11_add_module(_control
  ${CMAKE_CURRENT_LIST_DIR}/control/bindings.cpp
  ${CMAKE_CURRENT_LIST_DIR}/control/controller.cpp
  ${CMAKE_CURRENT_LIST_DIR}/control/tcp_reader.cpp)
target_compile_features(_control PRIVATE cxx_std_17)
find_package(Threads REQUIRED)
target_link_libraries(_control PRIVATE Threads::Threads ${CMAKE_DL_LIBS})
if(WIN32)
  target_link_libraries(_control PRIVATE ws2_32 winmm)
  target_compile_definitions(_control PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN _WIN32_WINNT=0x0A00)
endif()
if(MSVC)
  target_compile_options(_control PRIVATE /W4)
else()
  target_compile_options(_control PRIVATE -Wall -Wextra -Wpedantic)
endif()
install(TARGETS _control LIBRARY DESTINATION iimt RUNTIME DESTINATION iimt)
