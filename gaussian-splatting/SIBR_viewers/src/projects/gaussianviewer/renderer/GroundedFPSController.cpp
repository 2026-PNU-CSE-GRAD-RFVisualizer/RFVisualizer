#include "GroundedFPSController.hpp"

#include <picojson/picojson.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <sstream>

namespace sibr {

	namespace {

		using grounded::BODY_RADIUS_M;
		using grounded::EPSILON_M;
		using grounded::EYE_HEIGHT_M;
		using grounded::MAX_RESOLVES;
		using grounded::MAX_SUBSTEPS;
		using grounded::MAX_SUBSTEP_M;

		bool finite2(const GroundedPoint2& p)
		{
			return std::isfinite(p.x) && std::isfinite(p.y);
		}

		/** p에서 선분 ab에 가장 가까운 점. */
		GroundedPoint2 closestOnSegment(const GroundedSegment& s, const GroundedPoint2& p)
		{
			const double ex = s.b.x - s.a.x, ey = s.b.y - s.a.y;
			const double lengthSq = ex * ex + ey * ey;
			if (lengthSq <= 0.0) {
				return s.a;
			}
			double t = ((p.x - s.a.x) * ex + (p.y - s.a.y) * ey) / lengthSq;
			t = std::min(1.0, std::max(0.0, t));
			GroundedPoint2 result;
			result.x = s.a.x + t * ex;
			result.y = s.a.y + t * ey;
			return result;
		}

		/** XY로 누른 삼각형 안에 있는지(경계 포함). */
		bool insideTriangle(const GroundedTriangle2& t, const GroundedPoint2& p)
		{
			const double d1 = (p.x - t.b.x) * (t.a.y - t.b.y) - (t.a.x - t.b.x) * (p.y - t.b.y);
			const double d2 = (p.x - t.c.x) * (t.b.y - t.c.y) - (t.b.x - t.c.x) * (p.y - t.c.y);
			const double d3 = (p.x - t.a.x) * (t.c.y - t.a.y) - (t.c.x - t.a.x) * (p.y - t.a.y);
			const bool negative = (d1 < 0.0) || (d2 < 0.0) || (d3 < 0.0);
			const bool positive = (d1 > 0.0) || (d2 > 0.0) || (d3 > 0.0);
			return !(negative && positive);
		}

		double distanceSq(const GroundedPoint2& a, const GroundedPoint2& b)
		{
			const double dx = a.x - b.x, dy = a.y - b.y;
			return dx * dx + dy * dy;
		}

		/** p에서 삼각형에 가장 가까운 점. 안에 있으면 p 자신이다. */
		GroundedPoint2 closestOnTriangle(const GroundedTriangle2& t, const GroundedPoint2& p)
		{
			if (insideTriangle(t, p)) {
				return p;
			}
			const GroundedSegment edges[3] = { { t.a, t.b }, { t.b, t.c }, { t.c, t.a } };
			GroundedPoint2 best = closestOnSegment(edges[0], p);
			double bestDistance = distanceSq(best, p);
			for (int index = 1; index < 3; ++index) {
				const GroundedPoint2 candidate = closestOnSegment(edges[index], p);
				const double distance = distanceSq(candidate, p);
				if (distance < bestDistance) {
					bestDistance = distance;
					best = candidate;
				}
			}
			return best;
		}

		GroundedPoint2 centroidOf(const GroundedTriangle2& t)
		{
			GroundedPoint2 result;
			result.x = (t.a.x + t.b.x + t.c.x) / 3.0;
			result.y = (t.a.y + t.b.y + t.c.y) / 3.0;
			return result;
		}

		// ponytail: 벽을 매번 전부 훑는 O(n) 스캔이고, 삼각형이 공유하는 변은 중복으로 들어
		// 있다. 실제 corridor Bundle이 864개라 한 Frame에 수천 번 거리 계산으로 끝난다.
		// 벽이 수만 개로 늘거나 Frame이 흔들리면 그때 uniform grid나 중복 제거를 넣는다.
		/** 한 substep 안에서 모든 벽 밖으로 밀어낸다. 못 풀면 false. */
		bool pushOut(const std::vector<GroundedSegment>& walls, const GroundedPoint2& prev,
			GroundedPoint2& target)
		{
			for (int pass = 0; pass < MAX_RESOLVES; ++pass) {
				const GroundedSegment* worst = nullptr;
				GroundedPoint2 worstFoot;
				double worstPenetration = 0.0;
				for (const GroundedSegment& wall : walls) {
					const GroundedPoint2 foot = closestOnSegment(wall, target);
					const double dx = target.x - foot.x, dy = target.y - foot.y;
					const double penetration = BODY_RADIUS_M - std::sqrt(dx * dx + dy * dy);
					if (penetration > worstPenetration) {
						worstPenetration = penetration;
						worstFoot = foot;
						worst = &wall;
					}
				}
				if (worst == nullptr) {
					return true;               // 어느 벽에도 닿지 않는다.
				}

				double nx = target.x - worstFoot.x, ny = target.y - worstFoot.y;
				double length = std::sqrt(nx * nx + ny * ny);
				if (length <= EPSILON_M) {
					// 후보가 벽 선 위에 정확히 올라앉았다. 이전 안전 위치가 있던 쪽으로 민다.
					const double ex = worst->b.x - worst->a.x, ey = worst->b.y - worst->a.y;
					nx = -ey;
					ny = ex;
					length = std::sqrt(nx * nx + ny * ny);
					if (length <= 0.0) {
						return false;
					}
					nx /= length;
					ny /= length;
					const double side = (prev.x - worstFoot.x) * nx + (prev.y - worstFoot.y) * ny;
					if (std::abs(side) <= EPSILON_M) {
						return false;          // 어느 쪽이 바깥인지 정할 수 없다.
					}
					if (side < 0.0) {
						nx = -nx;
						ny = -ny;
					}
				} else {
					nx /= length;
					ny /= length;
				}

				// 법선 성분만 되돌린다. 접선 성분이 남아서 벽을 따라 미끄러진다.
				target.x += nx * (worstPenetration + EPSILON_M);
				target.y += ny * (worstPenetration + EPSILON_M);
				if (!finite2(target)) {
					return false;
				}
			}
			return false;                      // 모서리 등에서 수렴하지 않았다.
		}

		std::string baseName(const std::string& path)
		{
			const size_t cut = path.find_last_of("/\\");
			return (cut == std::string::npos) ? path : path.substr(cut + 1);
		}

		std::string directoryOf(const std::string& path)
		{
			const size_t cut = path.find_last_of("/\\");
			return (cut == std::string::npos) ? std::string(".") : path.substr(0, cut);
		}

		struct ObjMesh
		{
			std::vector<double> vertices;      ///< x,y,z 3개씩
			std::vector<int> indices;          ///< 3개씩, 0-based
		};

		/** OBJ의 v/f 줄만 읽는다. normal·texture·material은 쓰지 않는다. */
		ObjMesh loadObj(const std::string& path)
		{
			std::ifstream stream(path);
			if (!stream.good()) {
				throw std::runtime_error("--grounded-fps: navigation mesh를 열 수 없습니다: " + path);
			}
			ObjMesh mesh;
			std::string line;
			while (std::getline(stream, line)) {
				if (line.size() < 2) {
					continue;
				}
				std::istringstream fields(line);
				std::string tag;
				fields >> tag;
				if (tag == "v") {
					double x = 0.0, y = 0.0, z = 0.0;
					fields >> x >> y >> z;
					mesh.vertices.push_back(x);
					mesh.vertices.push_back(y);
					mesh.vertices.push_back(z);
				} else if (tag == "f") {
					std::vector<int> face;
					std::string token;
					while (fields >> token) {
						const int raw = std::atoi(token.substr(0, token.find('/')).c_str());
						if (raw == 0) {
							continue;
						}
						const int total = int(mesh.vertices.size() / 3);
						face.push_back((raw > 0) ? (raw - 1) : (total + raw));
					}
					for (size_t corner = 2; corner < face.size(); ++corner) {
						mesh.indices.push_back(face[0]);
						mesh.indices.push_back(face[corner - 1]);
						mesh.indices.push_back(face[corner]);
					}
				}
			}
			return mesh;
		}

		const picojson::value& field(const picojson::value& node, const std::string& name)
		{
			if (!node.is<picojson::object>() || node.get(name).is<picojson::null>()) {
				throw std::runtime_error("--grounded-fps: RF Volume manifest에 '" + name + "' 항목이 없습니다.");
			}
			return node.get(name);
		}

	} // namespace

	GroundedPoint2 groundedResolve(const std::vector<GroundedSegment>& walls,
		const GroundedPoint2& from, const GroundedPoint2& to)
	{
		if (!finite2(from)) {
			return GroundedPoint2();
		}
		if (!finite2(to)) {
			return from;
		}
		const double dx = to.x - from.x, dy = to.y - from.y;
		const double distance = std::sqrt(dx * dx + dy * dy);
		if (distance <= EPSILON_M) {
			return from;
		}
		if (distance > MAX_SUBSTEPS * MAX_SUBSTEP_M) {
			return from;                       // 한 Frame에 8 m 넘게 옮기지 않는다.
		}

		// 매 substep은 원래 직선이 아니라 **직전 안전 위치**에서 한 칸 나아간다. 그래야 벽에
		// 눌려 멈춘 뒤 다음 칸이 벽 반대편으로 뛰어넘지 않고, 접선 이동만 이어서 쌓인다.
		const int steps = std::max(1, int(std::ceil(distance / MAX_SUBSTEP_M)));
		const double stepX = dx / steps, stepY = dy / steps;
		GroundedPoint2 safe = from;
		for (int step = 0; step < steps; ++step) {
			GroundedPoint2 target;
			target.x = safe.x + stepX;
			target.y = safe.y + stepY;
			if (!pushOut(walls, safe, target)) {
				return safe;
			}
			safe = target;
		}
		return safe;
	}

	GroundedFPSController::GroundedFPSController(const Eigen::Matrix4d& sceneFromMetric,
		std::vector<GroundedSegment> walls, std::vector<GroundedTriangle2> floor)
		: _walls(std::move(walls)), _floor(std::move(floor))
	{
		setTransform(sceneFromMetric);
	}

	GroundedFPSController::GroundedFPSController(const std::string& manifestPath)
	{
		std::ifstream stream(manifestPath);
		if (!stream.good()) {
			throw std::runtime_error("--grounded-fps: RF Volume manifest를 열 수 없습니다: " + manifestPath);
		}
		picojson::value root;
		const std::string error = picojson::parse(root, stream);
		if (!error.empty()) {
			throw std::runtime_error("--grounded-fps: RF Volume manifest를 읽을 수 없습니다: " + error);
		}

		const picojson::value& transform = field(root, "T_scene_from_metric");
		if (!transform.is<picojson::array>() || transform.get<picojson::array>().size() != 4) {
			throw std::runtime_error("--grounded-fps: T_scene_from_metric은 4x4 행렬이어야 합니다.");
		}
		Eigen::Matrix4d sceneFromMetric;
		const picojson::array& rows = transform.get<picojson::array>();
		for (int row = 0; row < 4; ++row) {
			if (!rows[row].is<picojson::array>() || rows[row].get<picojson::array>().size() != 4) {
				throw std::runtime_error("--grounded-fps: T_scene_from_metric은 4x4 행렬이어야 합니다.");
			}
			const picojson::array& values = rows[row].get<picojson::array>();
			for (int column = 0; column < 4; ++column) {
				if (!values[column].is<double>()) {
					throw std::runtime_error("--grounded-fps: T_scene_from_metric에 숫자가 아닌 값이 있습니다.");
				}
				sceneFromMetric(row, column) = values[column].get<double>();
			}
		}
		setTransform(sceneFromMetric);

		// Bundle 안에서 파일명이 room_envelope_metric.obj인 mesh 하나만 navigation에 쓴다.
		// manifest 순서나 marker 파일명 제외 목록에 기대지 않는다.
		const std::string wanted = "room_envelope_metric.obj";
		const std::string directory = directoryOf(manifestPath);
		std::vector<std::string> matches;
		const picojson::value& meshes = field(root, "occlusion_meshes");
		if (!meshes.is<picojson::array>()) {
			throw std::runtime_error("--grounded-fps: occlusion_meshes가 배열이 아닙니다.");
		}
		for (const picojson::value& mesh : meshes.get<picojson::array>()) {
			const std::string file = field(mesh, "file").to_str();
			if (baseName(file) == wanted) {
				matches.push_back(directory + "/" + file);
			}
		}
		if (matches.size() != 1) {
			std::ostringstream message;
			message << "--grounded-fps: Bundle에 " << wanted << "가 정확히 하나 있어야 하는데 "
				<< matches.size() << "개입니다.";
			throw std::runtime_error(message.str());
		}

		const ObjMesh mesh = loadObj(matches[0]);
		for (size_t base = 0; base + 2 < mesh.indices.size(); base += 3) {
			double corner[3][3];
			bool usable = true;
			for (int point = 0; point < 3; ++point) {
				const int index = mesh.indices[base + point];
				if (index < 0 || index * 3 + 2 >= int(mesh.vertices.size())) {
					usable = false;
					break;
				}
				for (int axis = 0; axis < 3; ++axis) {
					corner[point][axis] = mesh.vertices[index * 3 + axis];
					usable = usable && std::isfinite(corner[point][axis]);
				}
			}
			if (!usable) {
				continue;
			}

			double edge1[3], edge2[3], normal[3];
			for (int axis = 0; axis < 3; ++axis) {
				edge1[axis] = corner[1][axis] - corner[0][axis];
				edge2[axis] = corner[2][axis] - corner[0][axis];
			}
			normal[0] = edge1[1] * edge2[2] - edge1[2] * edge2[1];
			normal[1] = edge1[2] * edge2[0] - edge1[0] * edge2[2];
			normal[2] = edge1[0] * edge2[1] - edge1[1] * edge2[0];
			const double area2 = std::sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
			if (!(area2 > 1e-12)) {
				continue;                      // 찌그러진 삼각형.
			}
			const double normalZ = normal[2] / area2;

			double minZ = corner[0][2], maxZ = corner[0][2];
			double maxAbsZ = std::abs(corner[0][2]);
			for (int point = 1; point < 3; ++point) {
				minZ = std::min(minZ, corner[point][2]);
				maxZ = std::max(maxZ, corner[point][2]);
				maxAbsZ = std::max(maxAbsZ, std::abs(corner[point][2]));
			}

			if (std::abs(normalZ) <= 0.1) {
				// 수직면만 벽이다. 몸이 지나는 높이 [0, 1.7]과 겹칠 때만 쓴다.
				if (maxZ < 0.0 || minZ > EYE_HEIGHT_M) {
					continue;
				}
				for (int point = 0; point < 3; ++point) {
					const int next = (point + 1) % 3;
					GroundedSegment wall;
					wall.a.x = corner[point][0];
					wall.a.y = corner[point][1];
					wall.b.x = corner[next][0];
					wall.b.y = corner[next][1];
					const double ex = wall.b.x - wall.a.x, ey = wall.b.y - wall.a.y;
					if (std::sqrt(ex * ex + ey * ey) > 1e-4) {
						_walls.push_back(wall);
					}
				}
			} else if (std::abs(normalZ) >= 0.9 && maxAbsZ <= 0.05) {
				// z=0 근처의 수평면만 바닥이다. 천장은 여기서 걸러진다.
				GroundedTriangle2 triangle;
				triangle.a.x = corner[0][0]; triangle.a.y = corner[0][1];
				triangle.b.x = corner[1][0]; triangle.b.y = corner[1][1];
				triangle.c.x = corner[2][0]; triangle.c.y = corner[2][1];
				_floor.push_back(triangle);
			}
		}

		if (_walls.empty()) {
			throw std::runtime_error("--grounded-fps: navigation mesh에 벽으로 쓸 수직면이 없습니다.");
		}
		if (_floor.empty()) {
			throw std::runtime_error("--grounded-fps: navigation mesh에 metric z=0 바닥면이 없습니다.");
		}
	}

	void GroundedFPSController::setTransform(const Eigen::Matrix4d& sceneFromMetric)
	{
		if (!sceneFromMetric.allFinite()) {
			throw std::runtime_error("--grounded-fps: T_scene_from_metric에 유한하지 않은 값이 있습니다.");
		}
		const Eigen::Vector4d lastRow = sceneFromMetric.row(3).transpose();
		const Eigen::Vector4d affine(0.0, 0.0, 0.0, 1.0);
		if ((lastRow - affine).cwiseAbs().maxCoeff() > 1e-6) {
			throw std::runtime_error("--grounded-fps: T_scene_from_metric의 마지막 행이 [0 0 0 1]이 아닙니다.");
		}
		const Eigen::Matrix3d linear = sceneFromMetric.topLeftCorner<3, 3>();
		if (!(std::abs(linear.determinant()) > 1e-8)) {
			throw std::runtime_error("--grounded-fps: T_scene_from_metric을 뒤집을 수 없습니다(특이 행렬).");
		}
		_sceneFromMetric = sceneFromMetric;
		_metricFromScene = sceneFromMetric.inverse();
		if (!_metricFromScene.allFinite()) {
			throw std::runtime_error("--grounded-fps: T_scene_from_metric의 역행렬이 유한하지 않습니다.");
		}

		// 원점과 단위 축이 왕복해서 제자리로 돌아오는지 본다.
		const double probes[4][3] = { {0,0,0}, {1,0,0}, {0,1,0}, {0,0,1} };
		for (const auto& probe : probes) {
			double scene[3], back[3];
			toScene(probe, scene);
			toMetric(scene, back);
			for (int axis = 0; axis < 3; ++axis) {
				if (!std::isfinite(back[axis]) || std::abs(back[axis] - probe[axis]) > 1e-4) {
					throw std::runtime_error("--grounded-fps: metric↔scene 좌표 왕복 오차가 1e-4 m를 넘습니다.");
				}
			}
		}
	}

	void GroundedFPSController::toScene(const double metric[3], double scene[3]) const
	{
		const Eigen::Vector4d out = _sceneFromMetric * Eigen::Vector4d(metric[0], metric[1], metric[2], 1.0);
		scene[0] = out.x(); scene[1] = out.y(); scene[2] = out.z();
	}

	void GroundedFPSController::toMetric(const double scene[3], double metric[3]) const
	{
		const Eigen::Vector4d out = _metricFromScene * Eigen::Vector4d(scene[0], scene[1], scene[2], 1.0);
		metric[0] = out.x(); metric[1] = out.y(); metric[2] = out.z();
	}

	bool GroundedFPSController::insideFloor(const GroundedPoint2& p) const
	{
		if (!finite2(p)) {
			return false;
		}
		for (const GroundedTriangle2& triangle : _floor) {
			if (insideTriangle(triangle, p)) {
				return true;
			}
		}
		return false;
	}

	double GroundedFPSController::clearance(const GroundedPoint2& p) const
	{
		double best = std::numeric_limits<double>::infinity();
		for (const GroundedSegment& wall : _walls) {
			const GroundedPoint2 foot = closestOnSegment(wall, p);
			const double dx = p.x - foot.x, dy = p.y - foot.y;
			best = std::min(best, std::sqrt(dx * dx + dy * dy));
		}
		return best;
	}

	bool GroundedFPSController::isValidStand(const GroundedPoint2& p) const
	{
		return insideFloor(p) && clearance(p) >= grounded::BODY_RADIUS_M;
	}

	bool GroundedFPSController::nearestValidStand(const GroundedPoint2& p, GroundedPoint2& out) const
	{
		if (!finite2(p)) {
			return false;
		}
		double bestDistance = std::numeric_limits<double>::infinity();
		bool found = false;
		for (const GroundedTriangle2& triangle : _floor) {
			// 이 삼각형에서 p에 가장 가까운 점. 삼각형 안의 어떤 점도 이보다 가까울 수 없으므로
			// 이미 찾은 답보다 멀면 통째로 건너뛴다.
			const GroundedPoint2 nearest = closestOnTriangle(triangle, p);
			if (distanceSq(nearest, p) >= bestDistance) {
				continue;
			}

			GroundedPoint2 candidate = nearest;
			if (clearance(nearest) < grounded::BODY_RADIUS_M) {
				// 벽에 너무 붙었다. 삼각형 안쪽(무게중심)으로 당겨 몸이 들어가는 첫 지점을 찾는다.
				// 무게중심조차 좁으면 이 삼각형에는 설 자리가 없다.
				const GroundedPoint2 inward = centroidOf(triangle);
				if (clearance(inward) < grounded::BODY_RADIUS_M) {
					continue;
				}
				double low = 0.0, high = 1.0;   // low는 좁은 쪽, high는 늘 넉넉한 쪽이다.
				for (int step = 0; step < 12; ++step) {
					const double mid = 0.5 * (low + high);
					GroundedPoint2 probe;
					probe.x = nearest.x + (inward.x - nearest.x) * mid;
					probe.y = nearest.y + (inward.y - nearest.y) * mid;
					if (clearance(probe) >= grounded::BODY_RADIUS_M) {
						high = mid;
					} else {
						low = mid;
					}
				}
				candidate.x = nearest.x + (inward.x - nearest.x) * high;
				candidate.y = nearest.y + (inward.y - nearest.y) * high;
				if (clearance(candidate) < grounded::BODY_RADIUS_M) {
					continue;                  // 수렴하지 못했다. 이 삼각형은 버린다.
				}
			}

			const double distance = distanceSq(candidate, p);
			if (distance < bestDistance) {
				bestDistance = distance;
				out = candidate;
				found = true;
			}
		}
		return found;
	}

	bool GroundedFPSController::snapStart(const double scene[3], double outScene[3]) const
	{
		double metric[3];
		toMetric(scene, metric);
		if (!std::isfinite(metric[0]) || !std::isfinite(metric[1]) || !std::isfinite(metric[2])) {
			throw std::runtime_error("--grounded-fps: 시작 Camera 위치를 metric으로 옮길 수 없습니다.");
		}
		// 원점·단위 축뿐 아니라 실제 시작 위치에서도 왕복이 맞아야 한다. 씬이 원점에서 멀면
		// float 자리수가 모자라 여기서만 어긋날 수 있다.
		double back[3];
		toScene(metric, back);
		double roundTrip[3];
		toMetric(back, roundTrip);
		for (int axis = 0; axis < 3; ++axis) {
			if (!std::isfinite(roundTrip[axis]) || std::abs(roundTrip[axis] - metric[axis]) > 1e-4) {
				throw std::runtime_error(
					"--grounded-fps: 시작 위치에서 metric↔scene 왕복 오차가 1e-4 m를 넘습니다.");
			}
		}
		GroundedPoint2 start{ metric[0], metric[1] };
		bool relocated = false;
		if (!isValidStand(start)) {
			// 시작 Camera가 바닥 밖이거나 벽에 박혀 있다. 여기서 멈추는 대신 가장 가까운
			// 유효 위치로 옮긴다. 옮겼다는 사실은 호출한 쪽이 알려 준다.
			GroundedPoint2 moved;
			if (!nearestValidStand(start, moved)) {
				throw std::runtime_error(
					"--grounded-fps: 바닥 어디에도 반경 0.25 m 몸이 들어갈 자리가 없습니다. "
					"room_envelope_metric.obj의 바닥·벽이 서로 맞는지 확인해 주세요.");
			}
			start = moved;
			relocated = true;
		}
		const double snapped[3] = { start.x, start.y, grounded::EYE_HEIGHT_M };
		toScene(snapped, outScene);
		return relocated;
	}

	void GroundedFPSController::constrain(const double currentScene[3], const double candidateScene[3],
		double outScene[3]) const
	{
		double currentMetric[3], candidateMetric[3];
		toMetric(currentScene, currentMetric);
		toMetric(candidateScene, candidateMetric);

		const GroundedPoint2 from{ currentMetric[0], currentMetric[1] };
		const GroundedPoint2 to{ candidateMetric[0], candidateMetric[1] };
		const GroundedPoint2 fixed = groundedResolve(_walls, from, to);

		const double metric[3] = { fixed.x, fixed.y, grounded::EYE_HEIGHT_M };
		toScene(metric, outScene);
		for (int axis = 0; axis < 3; ++axis) {
			if (!std::isfinite(outScene[axis])) {
				// 어떤 경우에도 NaN pose를 만들지 않는다. 마지막 안전 위치에 남는다.
				outScene[0] = currentScene[0];
				outScene[1] = currentScene[1];
				outScene[2] = currentScene[2];
				return;
			}
		}
	}

} /*namespace sibr*/
