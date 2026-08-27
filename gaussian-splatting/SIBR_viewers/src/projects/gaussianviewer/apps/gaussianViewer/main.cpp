/*
 * Copyright (C) 2023, Inria
 * GRAPHDECO research group, https://team.inria.fr/graphdeco
 * All rights reserved.
 *
 * This software is free for non-commercial, research and evaluation use
 * under the terms of the LICENSE.md file.
 *
 * For inquiries contact sibr@inria.fr and/or George.Drettakis@inria.fr
 */

#include <chrono>
#include <fstream>

#include <core/graphics/Window.hpp>
#include <core/view/MultiViewManager.hpp>
#include <core/system/String.hpp>
#include "projects/gaussianviewer/renderer/GaussianView.hpp"
#include "projects/gaussianviewer/renderer/ArcTeleportController.hpp"
#include "projects/gaussianviewer/renderer/GroundedFPSController.hpp"
#include "projects/gaussianviewer/renderer/HandheldControlClient.hpp"

#include <core/renderer/DepthRenderer.hpp>
#include <core/raycaster/Raycaster.hpp>
#include <core/view/SceneDebugView.hpp>
#include <algorithm>
#include <boost/filesystem.hpp>
#include <regex>
#include <imgui/imgui_internal.h>

namespace fs = boost::filesystem;

std::string findLargestNumberedSubdirectory(const std::string& directoryPath) {
	fs::path dirPath(directoryPath);
	if (!fs::exists(dirPath) || !fs::is_directory(dirPath)) {
		std::cerr << "Invalid directory: " << directoryPath << std::endl;
		return "";
	}

	std::regex regexPattern(R"_(iteration_(\d+))_");
	std::string largestSubdirectory;
	int largestNumber = -1;

	for (const auto& entry : fs::directory_iterator(dirPath)) {
		if (fs::is_directory(entry)) {
			std::string subdirectory = entry.path().filename().string();
			std::smatch match;

			if (std::regex_match(subdirectory, match, regexPattern)) {
				int number = std::stoi(match[1]);

				if (number > largestNumber) {
					largestNumber = number;
					largestSubdirectory = subdirectory;
				}
			}
		}
	}

	return largestSubdirectory;
}


#define PROGRAM_NAME "sibr_3Dgaussian"
using namespace sibr;

std::pair<int, int> findArg(const std::string& line, const std::string& name)
{
	int start = line.find(name, 0);
	start = line.find("=", start);
	start += 1;
	int end = line.find_first_of(",)", start);
	return std::make_pair(start, end);
}

static void* User_ReadOpen(ImGuiContext*, ImGuiSettingsHandler*, const char* name)
{
	return (void*)0x1;
}

static void User_ReadLine(ImGuiContext*, ImGuiSettingsHandler* handler, void*, const char* line)
{
	int i;
	if (sscanf(line, "DontShow=%d", &i) == 1)
		if (i)
		{
			*((bool*)handler->UserData) = true;
			return;
		}
	*((bool*)handler->UserData) = false;
}

static void User_WriteAll(ImGuiContext* imgui_ctx, ImGuiSettingsHandler* handler, ImGuiTextBuffer* buf)
{
	// Write a buffer
	// If a window wasn't opened in this session we preserve its settings
	buf->reserve(buf->size() + 96); // ballpark reserve
	buf->appendf("[UserData][UserData]\nDontShow=%d\n", *((bool*)handler->UserData) ? 1 : 0);
	buf->appendf("\n");
}

int main(int ac, char** av)
{
	// Parse Command-line Args
	CommandLineArgs::parseMainArgs(ac, av);
	GaussianAppArgs myArgs;
	myArgs.displayHelpIfRequired();

	if(!myArgs.modelPath.isInit() && myArgs.modelPathShort.isInit())
		myArgs.modelPath = myArgs.modelPathShort.get();
	if(!myArgs.dataset_path.isInit() && myArgs.pathShort.isInit())
		myArgs.dataset_path = myArgs.pathShort.get();

	int device = myArgs.device;

	// rendering size
	uint rendering_width = myArgs.rendering_size.get()[0];
	uint rendering_height = myArgs.rendering_size.get()[1];

	// window size
	uint win_width = rendering_width; // myArgs.win_width;
	uint win_height = rendering_height; // myArgs.win_height;

	const char* toload = myArgs.modelPath.get().c_str();

	// Window setup
	// RFVisualizer: --grounded-fps의 계약 위반은 Window/GL을 만들기 **전에** 끝낸다.
	// Mesh 적재에 GL이 필요 없으므로 화면 없이도 여기서 바로 실패한다.
	sibr::GroundedFPSController::Ptr groundedFps;
	if (myArgs.groundedFps)
	{
		if (myArgs.rfVolume.get() == "")
		{
			SIBR_ERR << "--grounded-fps를 쓰려면 --rf-volume도 함께 줘야 합니다. "
				"바닥·벽을 담은 room_envelope_metric.obj와 좌표 변환이 그 manifest에 있습니다.";
		}
		try
		{
			groundedFps = std::make_shared<sibr::GroundedFPSController>(myArgs.rfVolume.get());
		}
		catch (const std::runtime_error& error)
		{
			SIBR_ERR << error.what();
		}
	}

	sibr::Window		window(PROGRAM_NAME, sibr::Vector2i(50, 50), myArgs, getResourcesDirectory() + "/gaussians/" + PROGRAM_NAME + ".ini");

	bool messageRead = false;
	ImGuiSettingsHandler ini_handler;
	ini_handler.TypeName = "UserData";
	ini_handler.UserData = &messageRead;
	ini_handler.TypeHash = ImHash("UserData", 0, 0);
	ini_handler.ReadOpenFn = User_ReadOpen;
	ini_handler.ReadLineFn = User_ReadLine;
	ini_handler.WriteAllFn = User_WriteAll;
	ImGui::GetCurrentContext()->SettingsHandlers.push_back(ini_handler);
	window.loadSettings();

	std::string cfgLine;
	std::ifstream cfgFile(myArgs.modelPath.get() + "/cfg_args");
	if (!cfgFile.good())
	{
		SIBR_ERR << "Could not find config file 'cfg_args' at " << myArgs.modelPath.get();
	}
	std::getline(cfgFile, cfgLine);

	if (!myArgs.dataset_path.isInit())
	{
		auto rng = findArg(cfgLine, "source_path");
		myArgs.dataset_path = cfgLine.substr(rng.first + 1, rng.second - rng.first - 2);
	}

	auto rng = findArg(cfgLine, "sh_degree");
	int sh_degree = std::stoi(cfgLine.substr(rng.first, rng.second - rng.first));

	rng = findArg(cfgLine, "white_background");
	bool white_background = cfgLine.substr(rng.first, rng.second - rng.first).find("True") != -1;

	BasicIBRScene::SceneOptions myOpts;
	myOpts.renderTargets = myArgs.loadImages;
	myOpts.mesh = true;
	myOpts.images = myArgs.loadImages;
	myOpts.cameras = true;
	myOpts.texture = false;

	BasicIBRScene::Ptr scene;
	try
	{
		scene.reset(new BasicIBRScene(myArgs, myOpts));
	}
	catch (...)
	{
		SIBR_LOG << "Did not find specified input folder, loading from model path" << std::endl;
		myArgs.dataset_path = myArgs.modelPath.get();
		scene.reset(new BasicIBRScene(myArgs, myOpts));
	}

	std::string plyfile = myArgs.modelPath.get();
	if (plyfile.back() != '/')
		plyfile += "/";
	plyfile += "point_cloud";
	if (!myArgs.iteration.isInit())
	{
		plyfile += "/" + findLargestNumberedSubdirectory(plyfile) + "/point_cloud.ply";
	}
	else
	{
		plyfile += "/iteration_" + myArgs.iteration.get() + "/point_cloud.ply";
	}

	// Setup the scene: load the proxy, create the texture arrays.
	const uint flags = SIBR_GPU_LINEAR_SAMPLING | SIBR_FLIP_TEXTURE;

	// Fix rendering aspect ratio if user provided rendering size
	uint scene_width = scene->cameras()->inputCameras()[0]->w();
	uint scene_height = scene->cameras()->inputCameras()[0]->h();
	float scene_aspect_ratio = scene_width * 1.0f / scene_height;
	float rendering_aspect_ratio = rendering_width * 1.0f / rendering_height;

	rendering_width = (rendering_width <= 0) ? std::min(1200U, scene_width) : rendering_width;
	rendering_height = (rendering_height <= 0) ? std::min(1200U, scene_width) / scene_aspect_ratio : rendering_height;
	if ((rendering_width > 0) && !myArgs.force_aspect_ratio ) {
		if (abs(scene_aspect_ratio - rendering_aspect_ratio) > 0.001f) {
			if (scene_width > scene_height) {
				rendering_height = rendering_width / scene_aspect_ratio;
			}
			else {
				rendering_width = rendering_height * scene_aspect_ratio;
			}
		}
	}
	Vector2u usedResolution(rendering_width, rendering_height);

	const unsigned int sceneResWidth = usedResolution.x();
	const unsigned int sceneResHeight = usedResolution.y();

	// Create the ULR view.
	GaussianView::Ptr	gaussianView(new GaussianView(scene, sceneResWidth, sceneResHeight, plyfile.c_str(), &messageRead, sh_degree, white_background, !myArgs.noInterop, device));

	// RFVisualizer: RF Volume 합성과 JPEG 송신은 인자를 준 경우에만 켜진다.
	sibr::RFVolumeRenderer::Ptr rfVolume;
	if (myArgs.rfVolume.get() != "")
	{
		rfVolume = std::make_shared<sibr::RFVolumeRenderer>(
			myArgs.rfVolume.get(), sceneResWidth, sceneResHeight);
		rfVolume->method(myArgs.rfMethod);
		rfVolume->enabled(!myArgs.rfHeatmapOff);
		gaussianView->setRFVolume(rfVolume);
	}
	sibr::FrameStreamer::Ptr streamer;
	if (myArgs.streamHost.get() != "")
	{
		sibr::FrameStreamer::Options streamOptions;
		streamOptions.host = myArgs.streamHost.get();
		streamOptions.port = myArgs.streamPort;
		streamOptions.fps = myArgs.streamFps;
		streamOptions.quality = myArgs.jpegQuality;
		streamOptions.dither = myArgs.streamDither;
		streamOptions.paletteFrames = myArgs.streamPaletteFrames;
		if (streamOptions.paletteFrames < 1)
		{
			SIBR_ERR << "--stream-palette-frames는 1 이상이어야 합니다. 받은 값: "
				<< streamOptions.paletteFrames;
		}
		if (!(streamOptions.dither >= 0.0f && streamOptions.dither <= 1.0f))
		{
			SIBR_ERR << "--stream-dither는 0.0에서 1.0 사이여야 합니다. 받은 값: "
				<< streamOptions.dither;
		}
		// 형식과 해상도는 렌더를 시작하기 전에 확정한다. 잘못된 조합은 여기서 끝낸다.
		if (!sibr::parseStreamFormat(myArgs.streamFormat.get(), streamOptions.format))
		{
			SIBR_ERR << "--stream-format은 rgb332-zlib 또는 jpeg여야 합니다. 받은 값: '"
				<< myArgs.streamFormat.get() << "'";
		}
		const std::string streamError =
			sibr::streamOptionError(streamOptions.format, sceneResWidth, sceneResHeight);
		if (!streamError.empty())
		{
			SIBR_ERR << streamError;
		}
		streamer = std::make_shared<sibr::FrameStreamer>(streamOptions, sceneResWidth, sceneResHeight);
		gaussianView->setStreamer(streamer);
	}

	// Raycaster.
	std::shared_ptr<sibr::Raycaster> raycaster = std::make_shared<sibr::Raycaster>();
	const bool raycasterReady = raycaster->init()
		&& raycaster->addMesh(scene->proxies()->proxy()) != sibr::Raycaster::InvalidGeomId;
	if (myArgs.groundedFps && !raycasterReady)
	{
		// 텔레포트 포물선이 가구·AP 같은 Proxy에 막히는지 판정하려면 Raycaster가 있어야 한다.
		SIBR_ERR << "--grounded-fps: Raycaster를 준비하지 못해 텔레포트 충돌 판정을 할 수 없습니다.";
	}

	// Camera handler for main view.
	sibr::InteractiveCameraHandler::Ptr generalCamera(new InteractiveCameraHandler());
	generalCamera->setup(scene->cameras()->inputCameras(), Viewport(0, 0, (float)usedResolution.x(), (float)usedResolution.y()), nullptr);
	// RFVisualizer: 확인용으로는 자유 비행(FPS)이 기본이어야 한다(생성자 기본값이 이미 FPS라
	// 보통은 no-op이다. 시작 로그의 "Switched to trackball mode"는 Top view 카메라다).
	// Smoothing은 꺼 둔다. 켜져 있으면 입력이 한 박자 늦게 따라와 조작감이 뭉개진다.
	generalCamera->switchMode(sibr::InteractiveCameraHandler::InteractionMode::FPS);
	generalCamera->switchSmoothing();

	// RFVisualizer: --grounded-fps는 기존 FPS 위에 위치 제약만 얹는다. Flag가 없으면 mesh를
	// 읽지도, callback을 걸지도 않으므로 기존 자유비행이 그대로다.
	sibr::ArcTeleportController::Ptr arcTeleport;
	if (groundedFps)
	{
		// 시작 pose를 검증하고 눈높이로 한 번만 스냅한다. 바닥 밖이면 추측하지 않고 멈춘다.
		const sibr::Vector3f startScene = generalCamera->getCamera().position();
		const double start[3] = { startScene.x(), startScene.y(), startScene.z() };
		double snapped[3] = { start[0], start[1], start[2] };
		bool relocated = false;
		try
		{
			relocated = groundedFps->snapStart(start, snapped);
		}
		catch (const std::runtime_error& error)
		{
			SIBR_ERR << error.what();
		}
		if (relocated)
		{
			// 조용히 순간이동시키지 않는다. 어디서 어디로 옮겼는지 남긴다.
			double before[3], after[3];
			groundedFps->toMetric(start, before);
			groundedFps->toMetric(snapped, after);
			SIBR_LOG << "[Grounded] 시작 Camera가 바닥 밖이거나 벽에 박혀 있어 가장 가까운 유효 "
				"위치로 옮겼습니다: metric XY (" << before[0] << ", " << before[1] << ") -> ("
				<< after[0] << ", " << after[1] << ")." << std::endl;
		}
		sibr::Transform3f startTransform = generalCamera->getCamera().transform();
		startTransform.position(sibr::Vector3f(float(snapped[0]), float(snapped[1]), float(snapped[2])));
		generalCamera->fromTransform(startTransform, false, false);

		// 텔레포트는 --grounded-fps에서 자동으로 켜진다. 별도 CLI를 만들지 않는다.
		arcTeleport = std::make_shared<sibr::ArcTeleportController>(groundedFps, raycaster);

		generalCamera->setFPSPositionConstraint(
			[groundedFps, arcTeleport](const sibr::Vector3f& current, const sibr::Vector3f& candidate)
			{
				// 조준 중에는 위치를 얼린다. 시점 회전은 Camera가 따로 하므로 계속 된다.
				if (arcTeleport->aiming())
				{
					return current;
				}
				const double from[3] = { current.x(), current.y(), current.z() };
				const double to[3] = { candidate.x(), candidate.y(), candidate.z() };
				double settled[3];
				groundedFps->constrain(from, to, settled);
				return sibr::Vector3f(float(settled[0]), float(settled[1]), float(settled[2]));
			});
		gaussianView->setTeleportOverlay(std::make_shared<sibr::TeleportOverlayRenderer>());
		SIBR_LOG << "[Grounded] 눈높이 " << sibr::grounded::EYE_HEIGHT_M << " m, 몸체 반경 "
			<< sibr::grounded::BODY_RADIUS_M << " m, 벽 " << groundedFps->walls().size()
			<< "개로 걷습니다. Q/E와 좌/가운데 버튼 Pan은 꺼집니다." << std::endl;
		SIBR_LOG << "[Teleport] R을 누른 채 조준하고 떼면 이동합니다. 초록은 유효, 빨강은 무효입니다."
			<< std::endl;
	}

	// RFVisualizer: Handheld는 Position을 Scene 좌표로 옮길 manifest가 있어야 켤 수 있다.
	sibr::HandheldControlClient::Ptr handheld;
	if (myArgs.handheldHost.get() != "")
	{
		if (!rfVolume)
		{
			SIBR_ERR << "--handheld-host를 쓰려면 --rf-volume도 함께 줘야 합니다. "
				"Position Update를 검증·변환할 manifest가 없습니다.";
		}
		sibr::HandheldControlClient::Options handheldOptions;
		handheldOptions.host = myArgs.handheldHost.get();
		handheldOptions.port = myArgs.handheldPort;
		handheldOptions.frameId = rfVolume->manifest().frameId;
		const sibr::Matrix4f& sceneFromMetric = rfVolume->manifest().sceneFromMetric;
		for (int row = 0; row < 4; ++row) {
			for (int column = 0; column < 4; ++column) {
				handheldOptions.sceneFromMetric[row * 4 + column] = double(sceneFromMetric(row, column));
			}
		}
		handheld = std::make_shared<sibr::HandheldControlClient>(handheldOptions);
		SIBR_LOG << "[Handheld] ws://" << handheldOptions.host << ":" << handheldOptions.port
			<< "/handheld/control 을 구독합니다 (frame_id " << handheldOptions.frameId << ")." << std::endl;
	}

	// Add views to mvm.
	MultiViewManager        multiViewManager(window, false);

	if (myArgs.rendering_mode == 1)
		multiViewManager.renderingMode(IRenderingMode::Ptr(new StereoAnaglyphRdrMode()));

	multiViewManager.addIBRSubView("Point view", gaussianView, usedResolution, ImGuiWindowFlags_ResizeFromAnySide | ImGuiWindowFlags_NoBringToFrontOnFocus);
	multiViewManager.addCameraForView("Point view", generalCamera);

	// Top view
	const std::shared_ptr<sibr::SceneDebugView> topView(new sibr::SceneDebugView(scene, generalCamera, myArgs, myArgs.imagesPath.get()));
	multiViewManager.addSubView("Top view", topView, usedResolution);
	CHECK_GL_ERROR;
	topView->active(false);

	// save images
	generalCamera->getCameraRecorder().setViewPath(gaussianView, myArgs.dataset_path.get());
	if (myArgs.pathFile.get() !=  "" )
	{
		generalCamera->getCameraRecorder().loadPath(myArgs.pathFile.get(), usedResolution.x(), usedResolution.y());
		generalCamera->getCameraRecorder().recordOfflinePath(myArgs.outPath, multiViewManager.getIBRSubView("Point view"), "");
		if( !myArgs.noExit )
			exit(0);
	}

	// Main looooooop.
	bool teleportHeld = false;      ///< 지난 Frame에 R이 눌려 있었는지(edge 판정용).
	bool handheldActive = false;    ///< Handheld가 Camera를 몰고 있는지.
	const auto startTime = std::chrono::steady_clock::now();
	const int runSeconds = myArgs.runSeconds;
	while (window.isOpened())
	{
		sibr::Input::poll();
		window.makeContextCurrent();
		if (sibr::Input::global().key().isPressed(sibr::Key::Escape)) {
			window.close();
		}

		// RFVisualizer: Camera는 Render Thread만 만진다. Worker는 mailbox만 채운다.
		handheldActive = false;
		if (handheld)
		{
			const sibr::Quaternionf& cameraQuat = generalCamera->getCamera().rotation();
			sibr::HandheldQuat cameraRotation;
			cameraRotation.x = cameraQuat.x();
			cameraRotation.y = cameraQuat.y();
			cameraRotation.z = cameraQuat.z();
			cameraRotation.w = cameraQuat.w();

			const sibr::HandheldControlClient::Frame handheldFrame =
				handheld->poll(sibr::HandheldControlClient::nowMs(), cameraRotation);

			handheldActive = handheldFrame.active;
			// 활성 중에 FPS handler를 두면 외부 자세를 매 Frame 덮어쓴다.
			const sibr::InteractiveCameraHandler::InteractionMode wanted = handheldFrame.active
				? sibr::InteractiveCameraHandler::InteractionMode::NONE
				: sibr::InteractiveCameraHandler::InteractionMode::FPS;
			if (generalCamera->getMode() != wanted)
			{
				// 마지막 transform을 그대로 둔 채 handler만 바꾸므로 화면이 튀지 않는다.
				generalCamera->switchMode(wanted);
			}

			if (handheldFrame.hasRotation || handheldFrame.hasPosition)
			{
				sibr::Transform3f transform = generalCamera->getCamera().transform();
				if (handheldFrame.hasRotation)
				{
					transform.rotation(sibr::Quaternionf(
						float(handheldFrame.rotation.w), float(handheldFrame.rotation.x),
						float(handheldFrame.rotation.y), float(handheldFrame.rotation.z)));
				}
				if (handheldFrame.hasPosition)
				{
					transform.position(sibr::Vector3f(
						handheldFrame.position[0], handheldFrame.position[1], handheldFrame.position[2]));
				}
				generalCamera->fromTransform(transform, false, false);
			}
		}

		// RFVisualizer: 텔레포트. 순서를 고정한다 —
		// 입력 -> handheld 소유권 -> 조준 시작/취소 -> Camera 갱신 -> 포물선 재계산 ->
		// commit -> overlay 전달 -> 렌더/캡처.
		sibr::TeleportAction teleportAction;
		bool teleportEligible = false;
		if (arcTeleport)
		{
			const bool textInput = ImGui::GetIO().WantTextInput;
			// Camera를 남이 몰고 있으면 조준하지 않는다.
			teleportEligible =
				generalCamera->getMode() == sibr::InteractiveCameraHandler::InteractionMode::FPS
				&& !(handheld && handheldActive)
				&& !generalCamera->getCameraRecorder().isPlaying()
				&& !textInput;

			const sibr::Input& globalInput = sibr::Input::global();
			const bool viaSibr = globalInput.key().isActivated(sibr::Key::R);
			const ImGuiIO& io = ImGui::GetIO();
			const bool viaImGui = !textInput && io.KeysDown[int(sibr::Key::R)];
			// 키보드 R을 입력원과 무관한 동작 값으로 바꾼다. 후속 작업에서 임베디드 버튼이
			// 같은 값을 채우면 아래 상태기계를 그대로 쓴다.
			teleportAction.active = viaSibr || viaImGui;
			teleportAction.pressed = teleportAction.active && !teleportHeld;
			teleportAction.released = !teleportAction.active && teleportHeld;
			teleportHeld = teleportAction.active;

			arcTeleport->beginFrame(teleportAction, teleportEligible);
		}

		multiViewManager.onUpdate(sibr::Input::global());

		if (arcTeleport)
		{
			// 갱신된 Camera로 다시 그린다. 조준 중에도 시점 회전은 그대로 먹는다.
			const sibr::InputCamera& camera = generalCamera->getCamera();
			sibr::Vector3f target;
			if (arcTeleport->endFrame(teleportAction, camera.position(), camera.dir(), target))
			{
				// 위치만 옮기고 시선과 FOV는 그대로 둔다.
				sibr::Transform3f moved = camera.transform();
				moved.position(target);
				generalCamera->fromTransform(moved, false, false);
			}
			gaussianView->setTeleportPreview(arcTeleport->preview());
		}

		multiViewManager.onRender(window);

		window.swapBuffer();
		CHECK_GL_ERROR;

		if (runSeconds > 0) {
			const auto elapsed = std::chrono::steady_clock::now() - startTime;
			if (std::chrono::duration_cast<std::chrono::seconds>(elapsed).count() >= runSeconds) {
				window.close();
			}
		}
	}

	if (streamer && myArgs.metricsJson.get() != "")
	{
		streamer->writeMetrics(myArgs.metricsJson.get());
	}

	return EXIT_SUCCESS;
}
