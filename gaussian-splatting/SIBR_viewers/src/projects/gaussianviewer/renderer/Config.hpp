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


#pragma once

# include <core/system/Config.hpp>
# include <core/system/CommandLineArgs.hpp>

# ifdef SIBR_OS_WINDOWS
#  ifdef SIBR_STATIC_DEFINE
#    define SIBR_EXPORT
#    define SIBR_NO_EXPORT
#  else
#    ifndef SIBR_EXP_ULR_EXPORT
#      ifdef SIBR_EXP_ULR_EXPORTS
/* We are building this library */
#        define SIBR_EXP_ULR_EXPORT __declspec(dllexport)
#      else
/* We are using this library */
#        define SIBR_EXP_ULR_EXPORT __declspec(dllimport)
#      endif
#    endif
#    ifndef SIBR_NO_EXPORT
#      define SIBR_NO_EXPORT
#    endif
#  endif
# else
#  define SIBR_EXP_ULR_EXPORT
# endif

namespace sibr {

	/// Arguments for all ULR applications.
	struct GaussianAppArgs :
		virtual BasicIBRAppArgs {
		RequiredArg<std::string> modelPath = { "model-path", "Model directory" };
		RequiredArg<std::string> modelPathShort = { "m", "Model directory" };
		RequiredArg<std::string> iteration = { "iteration", "Iteration to load from model" };
		RequiredArg<std::string> pathShort = {"s", "path to the dataset root"};
		Arg<int> device = {"device", 0, "CUDA device index"};
		Arg<bool> loadImages = { "load_images", "Whether or not to load images for scene overview."};
		Arg<bool> noInterop = { "no_interop", "Don't try to use interop (may be required for unconventional OpenGL setups, like WSL)" };
		Arg<std::string> imagesPath = { "images-path", "path to the dataset images" };

		// RFVisualizer 확장: RF Volume 합성과 Frame 송신.
		Arg<std::string> rfVolume = { "rf-volume", "", "viewer_volume/manifest.json (없으면 heatmap 비활성)" };
		Arg<int> rfMethod = { "rf-method", 2, "0=Raw Sionna, 1=Plain IDW, 2=Residual IDW" };
		Arg<bool> rfHeatmapOff = { "rf-heatmap-off", "heatmap을 끈 상태로 시작한다" };
		Arg<std::string> streamHost = { "stream-host", "", "image_relay host (없으면 송신 비활성)" };
		Arg<int> streamPort = { "stream-port", 9101, "image_relay ingest port" };
		Arg<float> streamFps = { "stream-fps", 10.0f, "송신 목표 FPS" };
		Arg<std::string> streamFormat = { "stream-format", "rgb332-zlib", "송신 형식: rgb332-zlib(기본) 또는 jpeg" };
		Arg<int> jpegQuality = { "jpeg-quality", 80, "JPEG 품질 (1-100). --stream-format jpeg일 때만 쓴다" };
		Arg<int> runSeconds = { "run-seconds", 0, "이 시간이 지나면 종료한다. 0은 종료 전까지 실행" };
		Arg<std::string> metricsJson = { "metrics-json", "", "송신 측정값을 쓸 JSON 경로" };
		Arg<std::string> handheldHost = { "handheld-host", "", "Backend WebSocket host (없으면 Handheld 비활성, --rf-volume 필요)" };
		Arg<int> handheldPort = { "handheld-port", 8000, "Backend WebSocket port" };
	};

}
