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
