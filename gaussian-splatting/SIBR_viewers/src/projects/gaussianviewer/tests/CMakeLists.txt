# RFVisualizer: Handheld WebSocket Consumer와 RFJF Frame Codec 검증.
# GL/CUDA/SIBR 라이브러리 없이 해당 소스만 컴파일해 돌린다.

project(SIBR_handheld_control_test)

find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)

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

# RFVisualizer: RGB332 변환·zlib round-trip·RFJF Header. FrameCodec.hpp만 있으면 된다.
add_executable(SIBR_frame_codec_test frame_codec_test.cpp)
target_include_directories(SIBR_frame_codec_test PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../../..)
target_link_libraries(SIBR_frame_codec_test ZLIB::ZLIB)
set_target_properties(SIBR_frame_codec_test PROPERTIES FOLDER "projects/gaussian/tests")

add_test(NAME frame_codec COMMAND SIBR_frame_codec_test)

# RFVisualizer: --grounded-fps 의 2D 충돌 solver·navigation geometry·좌표 계약.
# GroundedFPSController.cpp 하나만 컴파일한다(GL/CUDA/SIBR 링크 없음).
add_executable(SIBR_grounded_motion_test
	grounded_motion_test.cpp
	${CMAKE_CURRENT_LIST_DIR}/../renderer/GroundedFPSController.cpp
)
target_include_directories(SIBR_grounded_motion_test PRIVATE
	${CMAKE_CURRENT_LIST_DIR}/../renderer
	${CMAKE_CURRENT_LIST_DIR}/../../..
	${Boost_INCLUDE_DIRS}
)
target_compile_definitions(SIBR_grounded_motion_test PRIVATE SIBR_EXP_ULR_EXPORTS)
set_target_properties(SIBR_grounded_motion_test PROPERTIES FOLDER "projects/gaussian/tests")

add_test(NAME grounded_motion COMMAND SIBR_grounded_motion_test)

# RFVisualizer: FPSCamera의 grounded seam. 실제 FPSCamera를 돌리므로 sibr_view가 필요하다.
# Window/GL Context는 만들지 않고 ImGui Context만 써서 키 입력을 흉내낸다.
add_executable(SIBR_grounded_camera_test grounded_camera_test.cpp)
target_include_directories(SIBR_grounded_camera_test PRIVATE
	${CMAKE_CURRENT_LIST_DIR}/../../..
	${Boost_INCLUDE_DIRS}
)
target_link_libraries(SIBR_grounded_camera_test
	${Boost_LIBRARIES}
	sibr_view
	sibr_system
	imgui
)
set_target_properties(SIBR_grounded_camera_test PROPERTIES FOLDER "projects/gaussian/tests")

add_test(NAME grounded_camera COMMAND SIBR_grounded_camera_test)

# 이 Project는 rpath를 "$ORIGIN"으로 고정해(CMAKE_BUILD_WITH_INSTALL_RPATH) install 트리에서
# 실행하는 것을 전제한다. CTest는 build 트리에서 바로 돌리므로 라이브러리 경로를 직접 준다.
if(UNIX)
	set_tests_properties(grounded_camera PROPERTIES ENVIRONMENT
		"LD_LIBRARY_PATH=$<TARGET_FILE_DIR:sibr_view>:$<TARGET_FILE_DIR:sibr_system>:$<TARGET_FILE_DIR:sibr_graphics>:$<TARGET_FILE_DIR:sibr_assets>:$<TARGET_FILE_DIR:sibr_raycaster>:$<TARGET_FILE_DIR:sibr_scene>:$<TARGET_FILE_DIR:sibr_video>:$<TARGET_FILE_DIR:sibr_imgproc>:$<TARGET_FILE_DIR:xatlas>:${CMAKE_SOURCE_DIR}/embree-3.13.5.x86_64.linux/lib")
endif()

# RFVisualizer: 포물선 텔레포트의 궤적·판정·상태기계. proxy 충돌은 실제 Embree로 확인하므로
# sibr_raycaster가 필요하다. Window도 GL Context도 만들지 않는다.
add_executable(SIBR_arc_teleport_test
	arc_teleport_test.cpp
	${CMAKE_CURRENT_LIST_DIR}/../renderer/ArcTeleportController.cpp
	${CMAKE_CURRENT_LIST_DIR}/../renderer/GroundedFPSController.cpp
)
target_include_directories(SIBR_arc_teleport_test PRIVATE
	${CMAKE_CURRENT_LIST_DIR}/../renderer
	${CMAKE_CURRENT_LIST_DIR}/../../..
	${Boost_INCLUDE_DIRS}
)
target_compile_definitions(SIBR_arc_teleport_test PRIVATE SIBR_EXP_ULR_EXPORTS)
target_link_libraries(SIBR_arc_teleport_test
	${Boost_LIBRARIES}
	sibr_raycaster
	sibr_graphics
	sibr_system
)
set_target_properties(SIBR_arc_teleport_test PROPERTIES FOLDER "projects/gaussian/tests")

add_test(NAME arc_teleport COMMAND SIBR_arc_teleport_test)

if(UNIX)
	set_tests_properties(arc_teleport PROPERTIES ENVIRONMENT
		"LD_LIBRARY_PATH=$<TARGET_FILE_DIR:sibr_raycaster>:$<TARGET_FILE_DIR:sibr_graphics>:$<TARGET_FILE_DIR:sibr_system>:$<TARGET_FILE_DIR:sibr_assets>:$<TARGET_FILE_DIR:sibr_imgproc>:$<TARGET_FILE_DIR:sibr_video>:$<TARGET_FILE_DIR:xatlas>:${CMAKE_SOURCE_DIR}/embree-3.13.5.x86_64.linux/lib")
endif()
