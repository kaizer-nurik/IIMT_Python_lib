find_package(Eigen3 CONFIG REQUIRED)
find_package(fcl CONFIG REQUIRED)
find_package(assimp CONFIG REQUIRED)
find_package(tinyxml2 CONFIG REQUIRED)
find_package(ompl CONFIG REQUIRED)

pybind11_add_module(_model NO_EXTRAS
  ${CMAKE_CURRENT_LIST_DIR}/model/bindings.cpp
  ${CMAKE_CURRENT_LIST_DIR}/model/model.cpp
  ${CMAKE_CURRENT_LIST_DIR}/model/parser.cpp
  ${CMAKE_CURRENT_LIST_DIR}/model/mesh.cpp
  ${CMAKE_CURRENT_LIST_DIR}/model/planning.cpp)
target_compile_features(_model PRIVATE cxx_std_17)
target_link_libraries(_model PRIVATE Eigen3::Eigen fcl assimp::assimp tinyxml2::tinyxml2)
if(TARGET ompl::ompl)
  target_link_libraries(_model PRIVATE ompl::ompl)
elseif(TARGET ompl)
  target_link_libraries(_model PRIVATE ompl)
else()
  target_include_directories(_model SYSTEM PRIVATE ${OMPL_INCLUDE_DIRS})
  target_link_libraries(_model PRIVATE ${OMPL_LIBRARIES})
endif()
if(MSVC)
  target_compile_options(_model PRIVATE /W4 /permissive-)
  target_compile_definitions(_model PRIVATE NOMINMAX)
else()
  target_compile_options(_model PRIVATE -Wall -Wextra -Wpedantic)
endif()
install(TARGETS _model LIBRARY DESTINATION iimt RUNTIME DESTINATION iimt)
