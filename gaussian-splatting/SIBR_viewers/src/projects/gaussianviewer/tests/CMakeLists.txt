# RFVisualizer: Handheld WebSocket Consumer 검증.
# GL/CUDA/SIBR 라이브러리 없이 HandheldControlClient.cpp 하나만 컴파일해 돌린다.

project(SIBR_handheld_control_test)

find_package(Threads REQUIRED)

add_executable(${PROJECT_NAME}
	handheld_control_test.cpp
	${CMAKE_CURRENT_LIST_DIR}/../renderer/HandheldControlClient.cpp
)

target_include_directories(${PROJECT_NAME} PRIVATE
	${CMAKE_CURRENT_LIST_DIR}/../renderer
	${Boost_INCLUDE_DIRS}
)
target_compile_definitions(${PROJECT_NAME} PRIVATE SIBR_EXP_ULR_EXPORTS BOOST_ALL_DYN_LINK)
target_link_libraries(${PROJECT_NAME}
	${Boost_LIBRARIES}
	Threads::Threads
)
set_target_properties(${PROJECT_NAME} PROPERTIES FOLDER "projects/gaussian/tests")

add_test(NAME handheld_control COMMAND ${PROJECT_NAME})
