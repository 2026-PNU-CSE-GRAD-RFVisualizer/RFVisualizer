/*
 * RFVisualizer: SIBR Gaussian 화면 위에 RF dBm Volume을 합성한다.
 *
 * Bundle(manifest.json + volume_rgba_f32.bin + occlusion_meshes/)은
 * tools/rf_experiment 의 export-viewer-volume 이 만든다.
 */
#pragma once

# include "Config.hpp"
# include <core/graphics/Mesh.hpp>
# include <core/graphics/RenderTarget.hpp>
# include <core/graphics/Shader.hpp>
# include <core/graphics/Camera.hpp>
# include <core/renderer/DepthRenderer.hpp>
# include <memory>
# include <string>
# include <vector>

namespace sibr {

	/** Bundle manifest에서 Renderer가 쓰는 값만 뽑아 둔 것. */
	struct RFVolumeManifest
	{
		std::string schemaVersion;
		std::string frameId;
		std::string verticalResidualPolicy;
		bool paperEvidenceEligible = false;
		int nx = 0, ny = 0, nz = 0;             ///< x가 가장 빠른 축이다.
		sibr::Vector3f originM;                  ///< 첫 voxel 중심 (metric)
		sibr::Vector3f spacingM;
		sibr::Vector3f boxMinM, boxMaxM;         ///< voxel 중심 ± 반칸
		sibr::Vector2f dbmRange;
		sibr::Matrix4f sceneFromMetric;
		std::vector<std::string> meshPaths;
	};

	/**
	 * \class RFVolumeRenderer
	 * \brief RGBA32F 3D Texture를 Full-screen Ray Marching으로 합성하는 Renderer.
	 *
	 * Gaussian 결과를 그대로 두고 그 위에 premultiplied alpha로 덧그린다.
	 * 표시를 끄면 아무것도 그리지 않으므로 기존 출력과 완전히 같다.
	 */
	class SIBR_EXP_ULR_EXPORT RFVolumeRenderer
	{
	public:
		using Ptr = std::shared_ptr<RFVolumeRenderer>;

		/** Bundle을 읽고 GPU 자원을 만든다. 실패하면 SIBR_ERR로 즉시 멈춘다.
		\param manifestPath viewer_volume/manifest.json 경로
		\param w 렌더 폭
		\param h 렌더 높이 */
		RFVolumeRenderer(const std::string& manifestPath, uint w, uint h);
		~RFVolumeRenderer();

		/** 이미 Gaussian이 그려진 rendertarget 위에 Volume을 합성한다. */
		void process(IRenderTarget& dst, const Camera& eye);

		/** 로컬 ImGui 조작부(방식·표시·투명도·dBm 범위·Z 절단). */
		void onGUI();

		bool enabled() const { return _enabled; }
		/** 시작 방식을 고른다. 0=Raw Sionna, 1=Plain IDW, 2=Residual IDW. */
		void method(int index);
		void enabled(bool value) { _enabled = value; }
		const char* methodName() const;
		const RFVolumeManifest& manifest() const { return _manifest; }
		const sibr::Vector2f& dbmRange() const { return _dbmRange; }

	private:
		void uploadVolume(const std::string& binaryPath, size_t expectedBytes);
		void loadMeshes();
		void resize(uint w, uint h);

		RFVolumeManifest _manifest;
		std::string _bundleDirectory;

		GLuint _volumeTexture = 0;
		sibr::Mesh::Ptr _occlusion;
		std::unique_ptr<sibr::DepthRenderer> _depth;
		uint _width = 0, _height = 0;

		sibr::GLShader _shader;
		sibr::GLParameter _invSceneClip, _metricFromScene, _clipFromMetric;
		sibr::GLParameter _boxMin, _boxMax, _zCutParam, _dbmRangeParam;
		sibr::GLParameter _cameraPos, _step, _alpha, _method;
		sibr::GLParameter _volumeSampler, _proxyDepthSampler;

		bool _enabled = true;
		int _methodIndex = 2;              ///< 기본값은 Residual IDW.
		float _extinctionPerM = 0.06f;   ///< 1 m당 흡수 계수
		float _stepM = 0.25f;
		sibr::Vector2f _dbmRange;
		sibr::Vector2f _zCut;
	};

} /*namespace sibr*/
