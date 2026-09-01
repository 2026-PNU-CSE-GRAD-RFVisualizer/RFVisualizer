#include "RFVolumeRenderer.hpp"

#include <core/graphics/RenderUtility.hpp>
#include <core/graphics/Shader.hpp>
#include <core/system/String.hpp>
#include <core/assets/InputCamera.hpp>
#include <imgui/imgui.h>

#include <boost/filesystem.hpp>
#include <picojson/picojson.hpp>

#include <fstream>

namespace fs = boost::filesystem;

namespace sibr {

	namespace {

		const picojson::value& field(const picojson::value& node, const std::string& name)
		{
			if (!node.is<picojson::object>() || node.get(name).is<picojson::null>()) {
				SIBR_ERR << "RF Volume manifest에 '" << name << "' 항목이 없습니다.";
			}
			return node.get(name);
		}

		double number(const picojson::value& node, const std::string& name)
		{
			const picojson::value& value = field(node, name);
			if (!value.is<double>()) {
				SIBR_ERR << "RF Volume manifest의 '" << name << "'가 숫자가 아닙니다.";
			}
			return value.get<double>();
		}

		std::vector<double> numbers(const picojson::value& node, const std::string& name, size_t expected)
		{
			const picojson::value& value = field(node, name);
			if (!value.is<picojson::array>()) {
				SIBR_ERR << "RF Volume manifest의 '" << name << "'가 배열이 아닙니다.";
			}
			const picojson::array& array = value.get<picojson::array>();
			if (array.size() != expected) {
				SIBR_ERR << "RF Volume manifest의 '" << name << "'는 " << expected
					<< "개여야 하는데 " << array.size() << "개입니다.";
			}
			std::vector<double> result;
			result.reserve(expected);
			for (const picojson::value& item : array) {
				if (!item.is<double>()) {
					SIBR_ERR << "RF Volume manifest의 '" << name << "'에 숫자가 아닌 값이 있습니다.";
				}
				result.push_back(item.get<double>());
			}
			return result;
		}

	} // namespace

	RFVolumeRenderer::RFVolumeRenderer(const std::string& manifestPath, uint w, uint h)
	{
		const fs::path manifestFile(manifestPath);
		if (!fs::exists(manifestFile)) {
			SIBR_ERR << "RF Volume manifest를 찾을 수 없습니다: " << manifestPath;
		}
		_bundleDirectory = manifestFile.parent_path().string();

		std::ifstream stream(manifestPath);
		picojson::value root;
		const std::string error = picojson::parse(root, stream);
		if (!error.empty()) {
			SIBR_ERR << "RF Volume manifest를 읽을 수 없습니다: " << error;
		}

		_manifest.schemaVersion = field(root, "schema_version").to_str();
		if (_manifest.schemaVersion != "1.0") {
			SIBR_ERR << "지원하지 않는 RF Volume schema_version입니다: " << _manifest.schemaVersion;
		}
		_manifest.frameId = field(root, "frame_id").to_str();
		_manifest.verticalResidualPolicy = field(root, "vertical_residual_policy").to_str();
		_manifest.paperEvidenceEligible = field(root, "paper_evidence_eligible").evaluate_as_boolean();

		const picojson::value& grid = field(root, "grid");
		if (field(grid, "storage_order").to_str() != "zyx") {
			SIBR_ERR << "RF Volume 저장 순서는 zyx 만 지원합니다.";
		}
		const std::vector<double> shape = numbers(grid, "shape_zyx", 3);
		_manifest.nz = int(shape[0]);
		_manifest.ny = int(shape[1]);
		_manifest.nx = int(shape[2]);
		if (_manifest.nx <= 0 || _manifest.ny <= 0 || _manifest.nz <= 0) {
			SIBR_ERR << "RF Volume 격자 크기가 올바르지 않습니다.";
		}
		const std::vector<double> origin = numbers(grid, "origin_m", 3);
		const std::vector<double> spacing = numbers(grid, "spacing_m", 3);
		_manifest.originM = sibr::Vector3f(float(origin[0]), float(origin[1]), float(origin[2]));
		_manifest.spacingM = sibr::Vector3f(float(spacing[0]), float(spacing[1]), float(spacing[2]));
		// Texture 좌표 0..1은 voxel 중심이 아니라 바깥 반 칸까지를 덮는다.
		const sibr::Vector3f half = 0.5f * _manifest.spacingM;
		const sibr::Vector3f counts(float(_manifest.nx - 1), float(_manifest.ny - 1), float(_manifest.nz - 1));
		_manifest.boxMinM = _manifest.originM - half;
		_manifest.boxMaxM = _manifest.originM + counts.cwiseProduct(_manifest.spacingM) + half;

		const std::vector<double> range = numbers(root, "dbm_range", 2);
		_manifest.dbmRange = sibr::Vector2f(float(range[0]), float(range[1]));
		_dbmRange = _manifest.dbmRange;
		_zCut = sibr::Vector2f(_manifest.boxMinM.z(), _manifest.boxMaxM.z());

		const picojson::value& transform = field(root, "T_scene_from_metric");
		if (!transform.is<picojson::array>() || transform.get<picojson::array>().size() != 4) {
			SIBR_ERR << "T_scene_from_metric은 4x4 행렬이어야 합니다.";
		}
		const picojson::array& rows = transform.get<picojson::array>();
		for (int row = 0; row < 4; ++row) {
			if (!rows[row].is<picojson::array>() || rows[row].get<picojson::array>().size() != 4) {
				SIBR_ERR << "T_scene_from_metric은 4x4 행렬이어야 합니다.";
			}
			const picojson::array& values = rows[row].get<picojson::array>();
			for (int column = 0; column < 4; ++column) {
				_manifest.sceneFromMetric(row, column) = float(values[column].get<double>());
			}
		}

		const picojson::value& data = field(root, "data");
		const size_t expectedBytes = size_t(number(data, "byte_count"));
		if (field(data, "dtype").to_str() != "float32"
			|| field(data, "byte_order").to_str() != "little_endian") {
			SIBR_ERR << "RF Volume 데이터는 float32 little-endian 만 지원합니다.";
		}
		const size_t voxelBytes = size_t(_manifest.nx) * _manifest.ny * _manifest.nz * 4 * sizeof(float);
		if (expectedBytes != voxelBytes) {
			SIBR_ERR << "RF Volume byte 수가 격자 크기와 맞지 않습니다: manifest " << expectedBytes
				<< ", 격자 " << voxelBytes;
		}

		for (const picojson::value& mesh : field(root, "occlusion_meshes").get<picojson::array>()) {
			_manifest.meshPaths.push_back((fs::path(_bundleDirectory) / field(mesh, "file").to_str()).string());
		}
		if (_manifest.meshPaths.empty()) {
			SIBR_ERR << "RF Volume Bundle에 가림용 Proxy Mesh가 없습니다.";
		}

		uploadVolume((fs::path(_bundleDirectory) / field(data, "file").to_str()).string(), expectedBytes);
		loadMeshes();

		_shader.init("RFVolume",
			sibr::loadFile(sibr::getShadersDirectory("gaussian") + "/rf_volume.vert"),
			sibr::loadFile(sibr::getShadersDirectory("gaussian") + "/rf_volume.frag"));
		_invSceneClip.init(_shader, "invSceneClip");
		_metricFromScene.init(_shader, "metricFromScene");
		_clipFromMetric.init(_shader, "clipFromMetric");
		_boxMin.init(_shader, "boxMinM");
		_boxMax.init(_shader, "boxMaxM");
		_zCutParam.init(_shader, "zCutM");
		_dbmRangeParam.init(_shader, "dbmRange");
		_cameraPos.init(_shader, "cameraPosScene");
		_step.init(_shader, "stepM");
		_alpha.init(_shader, "extinctionPerM");
		_method.init(_shader, "method");
		_volumeSampler.init(_shader, "volume");
		_proxyDepthSampler.init(_shader, "proxyDepth");

		resize(w, h);
		SIBR_LOG << "[RFVolume] " << _manifest.nx << "x" << _manifest.ny << "x" << _manifest.nz
			<< " voxels, frame '" << _manifest.frameId << "', dBm ["
			<< _manifest.dbmRange.x() << ", " << _manifest.dbmRange.y() << "]" << std::endl;
	}

	RFVolumeRenderer::~RFVolumeRenderer()
	{
		if (_volumeTexture != 0) {
			glDeleteTextures(1, &_volumeTexture);
		}
	}

	void RFVolumeRenderer::uploadVolume(const std::string& binaryPath, size_t expectedBytes)
	{
		std::ifstream stream(binaryPath, std::ios::binary | std::ios::ate);
		if (!stream.good()) {
			SIBR_ERR << "RF Volume 데이터를 열 수 없습니다: " << binaryPath;
		}
		const size_t actualBytes = size_t(stream.tellg());
		if (actualBytes != expectedBytes) {
			SIBR_ERR << "RF Volume 데이터 크기가 manifest와 다릅니다: 파일 " << actualBytes
				<< ", manifest " << expectedBytes;
		}
		stream.seekg(0);
		std::vector<float> voxels(expectedBytes / sizeof(float));
		stream.read(reinterpret_cast<char*>(voxels.data()), std::streamsize(expectedBytes));

		glGenTextures(1, &_volumeTexture);
		glBindTexture(GL_TEXTURE_3D, _volumeTexture);
		glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
		glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
		// 격자 바깥은 valid mask 0으로 읽혀 자연스럽게 사라진다.
		const float border[4] = { 0.f, 0.f, 0.f, 0.f };
		glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
		glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
		glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_BORDER);
		glTexParameterfv(GL_TEXTURE_3D, GL_TEXTURE_BORDER_COLOR, border);
		glTexImage3D(GL_TEXTURE_3D, 0, GL_RGBA32F, _manifest.nx, _manifest.ny, _manifest.nz,
			0, GL_RGBA, GL_FLOAT, voxels.data());
		glBindTexture(GL_TEXTURE_3D, 0);
		CHECK_GL_ERROR;
	}

	void RFVolumeRenderer::loadMeshes()
	{
		_occlusion.reset(new sibr::Mesh());
		sibr::Mesh::Vertices vertices;
		sibr::Mesh::Triangles triangles;
		for (const std::string& path : _manifest.meshPaths) {
			sibr::Mesh part;
			if (!part.load(path)) {
				SIBR_ERR << "가림용 Proxy Mesh를 읽을 수 없습니다: " << path;
			}
			const int offset = int(vertices.size());
			for (const sibr::Vector3f& vertex : part.vertices()) {
				// Bundle의 Mesh는 metric 좌표라 scene 좌표로 옮겨야 Depth가 맞는다.
				const sibr::Vector4f scene = _manifest.sceneFromMetric * sibr::Vector4f(vertex.x(), vertex.y(), vertex.z(), 1.f);
				vertices.push_back(sibr::Vector3f(scene.x(), scene.y(), scene.z()));
			}
			for (const sibr::Vector3u& triangle : part.triangles()) {
				triangles.push_back(sibr::Vector3u(triangle.x() + offset, triangle.y() + offset, triangle.z() + offset));
			}
		}
		if (triangles.empty()) {
			SIBR_ERR << "가림용 Proxy Mesh에 삼각형이 없습니다.";
		}
		_occlusion->vertices(vertices);
		_occlusion->triangles(triangles);
	}

	void RFVolumeRenderer::resize(uint w, uint h)
	{
		if (w == _width && h == _height && _depth) {
			return;
		}
		_width = w;
		_height = h;
		_depth.reset(new sibr::DepthRenderer(int(w), int(h)));
	}

	void RFVolumeRenderer::process(IRenderTarget& dst, const Camera& eye)
	{
		if (!_enabled) {
			return;
		}
		resize(dst.w(), dst.h());

		// 1) Proxy Mesh Depth-only Pass. 벽 반대편 Volume을 버리는 데만 쓴다.
		const sibr::InputCamera depthCamera(eye, int(dst.w()), int(dst.h()));
		_depth->render(depthCamera, *_occlusion);

		// 2) Full-screen Ray Marching 합성.
		dst.bind();
		glViewport(0, 0, GLsizei(dst.w()), GLsizei(dst.h()));
		glDisable(GL_DEPTH_TEST);
		glEnable(GL_BLEND);
		glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

		const sibr::Matrix4f viewproj = eye.viewproj();
		const sibr::Matrix4f metricFromScene = _manifest.sceneFromMetric.inverse();

		_shader.begin();
		_invSceneClip.set(sibr::Matrix4f(viewproj.inverse()));
		_metricFromScene.set(metricFromScene);
		_clipFromMetric.set(sibr::Matrix4f(viewproj * _manifest.sceneFromMetric));
		_boxMin.set(_manifest.boxMinM);
		_boxMax.set(_manifest.boxMaxM);
		_zCutParam.set(_zCut);
		_dbmRangeParam.set(_dbmRange);
		_cameraPos.set(eye.position());
		_step.set(_stepM);
		_alpha.set(_extinctionPerM);
		_method.set(_methodIndex);

		_volumeSampler.set(0);
		_proxyDepthSampler.set(1);
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_3D, _volumeTexture);
		glActiveTexture(GL_TEXTURE1);
		glBindTexture(GL_TEXTURE_2D, _depth->_depth_RT->handle());

		sibr::RenderUtility::renderScreenQuad();
		_shader.end();

		glActiveTexture(GL_TEXTURE0);
		glDisable(GL_BLEND);
		dst.unbind();
		CHECK_GL_ERROR;
	}

	void RFVolumeRenderer::method(int index)
	{
		if (index < 0 || index > 2) {
			SIBR_ERR << "RF Volume 방식은 0(raw), 1(plain idw), 2(residual idw) 중 하나여야 합니다: " << index;
		}
		_methodIndex = index;
	}

	const char* RFVolumeRenderer::methodName() const
	{
		static const char* names[3] = { "Raw Sionna", "Plain IDW", "Residual IDW" };
		return names[std::min(std::max(_methodIndex, 0), 2)];
	}

	void RFVolumeRenderer::cycleHeightPreset()
	{
		++_heightPresetIndex;
		if (_heightPresetIndex >= _manifest.nz) {
			_heightPresetIndex = -1;
		}
		if (_heightPresetIndex < 0) {
			// 전체 범위로 돌아간다.
			_zCut = sibr::Vector2f(_manifest.boxMinM.z(), _manifest.boxMaxM.z());
			return;
		}
		const float centerZ = _manifest.originM.z() + float(_heightPresetIndex) * _manifest.spacingM.z();
		const float halfBand = 0.5f * _manifest.spacingM.z();
		_zCut = sibr::Vector2f(centerZ - halfBand, centerZ + halfBand);
	}

	void RFVolumeRenderer::onGUI()
	{
		if (!ImGui::CollapsingHeader("RF Volume", ImGuiTreeNodeFlags_DefaultOpen)) {
			return;
		}
		ImGui::Checkbox("Show heatmap", &_enabled);
		ImGui::Combo("Method", &_methodIndex, "Raw Sionna\0Plain IDW\0Residual IDW\0\0");
		ImGui::SliderFloat("Opacity /m", &_extinctionPerM, 0.005f, 0.5f, "%.3f");
		ImGui::SliderFloat2("dBm range", &_dbmRange[0], _manifest.dbmRange.x(), _manifest.dbmRange.y());
		ImGui::SliderFloat2("Z cut (m)", &_zCut[0], _manifest.boxMinM.z(), _manifest.boxMaxM.z());
		ImGui::TextUnformatted("PROVISIONAL - not paper evidence");
		ImGui::TextUnformatted(_manifest.verticalResidualPolicy.c_str());
	}

} /*namespace sibr*/
