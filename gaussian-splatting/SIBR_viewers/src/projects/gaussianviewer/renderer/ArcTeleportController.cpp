#include "ArcTeleportController.hpp"

#define _USE_MATH_DEFINES
#include <algorithm>
#include <cmath>
#include <limits>

namespace sibr {

	namespace {

		using teleport::GRAVITY_MPS2;
		using teleport::MAX_LENGTH_M;
		using teleport::SEGMENTS;
		using teleport::SPEED_MPS;
		using teleport::TIE_EPSILON_M;

		bool finite3(const double p[3])
		{
			return std::isfinite(p[0]) && std::isfinite(p[1]) && std::isfinite(p[2]);
		}

		/** 2D 선분 ab와 cd의 교차 parameter(ab 기준). 없으면 false. */
		bool segmentCross(double ax, double ay, double bx, double by,
			const GroundedSegment& wall, double& outT)
		{
			const double rx = bx - ax, ry = by - ay;
			const double sx = wall.b.x - wall.a.x, sy = wall.b.y - wall.a.y;
			const double denom = rx * sy - ry * sx;
			if (std::abs(denom) < 1e-12) {
				return false;                  // 평행하다.
			}
			const double qx = wall.a.x - ax, qy = wall.a.y - ay;
			const double t = (qx * sy - qy * sx) / denom;
			const double u = (qx * ry - qy * rx) / denom;
			if (t < 0.0 || t > 1.0 || u < 0.0 || u > 1.0) {
				return false;
			}
			outT = t;
			return true;
		}

	} // namespace

	ArcTeleportController::ArcTeleportController(GroundedFPSController::Ptr grounded,
		std::shared_ptr<sibr::Raycaster> raycaster)
		: _grounded(std::move(grounded)), _raycaster(std::move(raycaster))
	{
		if (!_grounded) {
			throw std::runtime_error("텔레포트는 --grounded-fps의 바닥·벽 정보가 있어야 합니다.");
		}
	}

	void ArcTeleportController::cancel()
	{
		_aiming = false;
		_preview = TeleportPreview();
	}

	bool ArcTeleportController::update(const TeleportAction& action, bool eligible,
		const sibr::Vector3f& sceneOrigin, const sibr::Vector3f& sceneForward,
		sibr::Vector3f& outSceneTarget)
	{
		beginFrame(action, eligible);
		return endFrame(action, sceneOrigin, sceneForward, outSceneTarget);
	}

	void ArcTeleportController::beginFrame(const TeleportAction& action, bool eligible)
	{
		// 조준할 자격을 잃으면 즉시 취소한다. 다시 하려면 새로 눌러야 한다.
		if (!eligible) {
			cancel();
			return;
		}
		if (!_aiming && action.pressed) {
			_aiming = true;                    // 새 press가 있어야 시작한다.
		}
	}

	bool ArcTeleportController::endFrame(const TeleportAction& action,
		const sibr::Vector3f& sceneOrigin, const sibr::Vector3f& sceneForward,
		sibr::Vector3f& outSceneTarget)
	{
		if (!_aiming) {
			return false;
		}

		recompute(sceneOrigin, sceneForward);

		if (action.released) {
			const bool commit = _preview.valid;
			if (commit) {
				const double target[3] = { _preview.targetMetric[0], _preview.targetMetric[1],
					grounded::EYE_HEIGHT_M };
				double scene[3];
				_grounded->toScene(target, scene);
				outSceneTarget = sibr::Vector3f(float(scene[0]), float(scene[1]), float(scene[2]));
				if (!outSceneTarget.allFinite()) {
					cancel();
					return false;
				}
			}
			cancel();
			return commit;                     // release에서만, 정확히 한 번.
		}

		if (!action.active) {
			cancel();                          // release 없이 눌림이 사라졌다.
			return false;
		}
		return false;
	}

	void ArcTeleportController::recompute(const sibr::Vector3f& sceneOrigin,
		const sibr::Vector3f& sceneForward)
	{
		_preview = TeleportPreview();
		_preview.aiming = true;
		_preview.endpoint = TeleportEndpoint::Cap;

		// scene 시선을 metric 방향으로 옮긴다. 두 점을 각각 변환해야 회전·배율이 반영된다.
		const double originScene[3] = { sceneOrigin.x(), sceneOrigin.y(), sceneOrigin.z() };
		const sibr::Vector3f aheadScene = sceneOrigin + sceneForward;
		const double forwardScene[3] = { aheadScene.x(), aheadScene.y(), aheadScene.z() };
		double origin[3], ahead[3];
		_grounded->toMetric(originScene, origin);
		_grounded->toMetric(forwardScene, ahead);
		if (!finite3(origin) || !finite3(ahead)) {
			return;
		}
		double dir[3] = { ahead[0] - origin[0], ahead[1] - origin[1], ahead[2] - origin[2] };
		const double dirLength = std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
		if (!(dirLength > 1e-9)) {
			return;
		}
		for (int axis = 0; axis < 3; ++axis) {
			dir[axis] /= dirLength;
		}

		const double velocity[3] = { SPEED_MPS * dir[0], SPEED_MPS * dir[1], SPEED_MPS * dir[2] };
		const double step = teleport::DURATION_S / SEGMENTS;

		auto pointAt = [&](double t, double out[3]) {
			out[0] = origin[0] + velocity[0] * t;
			out[1] = origin[1] + velocity[1] * t;
			out[2] = origin[2] + velocity[2] * t - 0.5 * GRAVITY_MPS2 * t * t;
		};
		auto pushScene = [&](const double metric[3]) {
			double scene[3];
			_grounded->toScene(metric, scene);
			_preview.scenePoints.push_back(
				sibr::Vector3f(float(scene[0]), float(scene[1]), float(scene[2])));
		};

		double current[3];
		pointAt(0.0, current);
		pushScene(current);

		double travelled = 0.0;
		double landing[3] = { 0.0, 0.0, 0.0 };
		bool landed = false;

		for (int index = 0; index < SEGMENTS; ++index) {
			const double t0 = index * step, t1 = (index + 1) * step;
			double next[3];
			pointAt(t1, next);
			if (!finite3(next)) {
				break;
			}

			const double dx = next[0] - current[0], dy = next[1] - current[1], dz = next[2] - current[2];
			const double segmentLength = std::sqrt(dx * dx + dy * dy + dz * dz);

			// 이번 구간에서 가장 먼저 일어나는 사건을 고른다. s는 구간 내 0..1 위치다.
			double bestS = std::numeric_limits<double>::infinity();
			TeleportEndpoint bestKind = TeleportEndpoint::Cap;

			// 1) 내려가면서 바닥(z=0)을 지나는가. 포물선 그대로 푼다.
			//    z(t) = z0 + vz t - 0.5 g t^2 = 0
			{
				const double a = -0.5 * GRAVITY_MPS2, b = velocity[2], c = origin[2];
				const double disc = b * b - 4.0 * a * c;
				if (disc >= 0.0) {
					const double root = std::sqrt(disc);
					const double candidates[2] = { (-b + root) / (2.0 * a), (-b - root) / (2.0 * a) };
					for (const double hit : candidates) {
						if (!std::isfinite(hit) || hit < t0 || hit > t1) {
							continue;
						}
						if (velocity[2] - GRAVITY_MPS2 * hit >= 0.0) {
							continue;          // 올라가는 중이면 착지가 아니다.
						}
						const double s = (t1 > t0) ? (hit - t0) / (t1 - t0) : 0.0;
						if (s < bestS) {
							bestS = s;
							bestKind = TeleportEndpoint::Floor;
						}
					}
				}
			}

			// 2) 벽을 XY로 가로지르는가.
			for (const GroundedSegment& wall : _grounded->walls()) {
				double s = 0.0;
				if (segmentCross(current[0], current[1], next[0], next[1], wall, s) && s < bestS) {
					bestS = s;
					bestKind = TeleportEndpoint::Wall;
				}
			}

			// 3) proxy mesh(AP·가구 등)에 막히는가. Raycaster는 무한 ray라 구간 길이로 자른다.
			if (_raycaster && segmentLength > 1e-9) {
				double currentScene[3], nextScene[3];
				_grounded->toScene(current, currentScene);
				_grounded->toScene(next, nextScene);
				// 중괄호 초기화를 쓴다. 괄호 + float(...)는 함수 선언으로 해석된다.
				const sibr::Vector3f rayFrom{ float(currentScene[0]), float(currentScene[1]), float(currentScene[2]) };
				const sibr::Vector3f rayTo{ float(nextScene[0]), float(nextScene[1]), float(nextScene[2]) };
				const sibr::Vector3f delta = rayTo - rayFrom;
				const float sceneLength = delta.norm();
				if (sceneLength > 1e-9f) {
					const sibr::Vector3f direction = delta / sceneLength;
					const sibr::RayHit hit = _raycaster->intersect(sibr::Ray(rayFrom, direction));
					if (hit.hitSomething() && hit.dist() <= sceneLength) {
						const double s = double(hit.dist() / sceneLength);
						// 바닥과 거의 같은 자리면 바닥을 택한다. proxy 바닥면과 겹칠 때가 있다.
						const bool floorWins = (bestKind == TeleportEndpoint::Floor)
							&& (std::abs(s - bestS) * segmentLength <= TIE_EPSILON_M);
						if (!floorWins && s < bestS) {
							bestS = s;
							bestKind = TeleportEndpoint::Obstacle;
						}
					}
				}
			}

			// 4) 누적 길이 상한. 위 사건들보다 먼저 걸리면 여기서 자른다.
			if (travelled + segmentLength * std::min(bestS, 1.0) > MAX_LENGTH_M) {
				const double remaining = MAX_LENGTH_M - travelled;
				const double s = (segmentLength > 1e-12) ? (remaining / segmentLength) : 0.0;
				if (s < bestS) {
					bestS = s;
					bestKind = TeleportEndpoint::Cap;
				}
			}

			if (bestS <= 1.0) {
				double end[3];
				for (int axis = 0; axis < 3; ++axis) {
					end[axis] = current[axis] + (next[axis] - current[axis]) * bestS;
				}
				pushScene(end);
				_preview.endpoint = bestKind;
				if (bestKind == TeleportEndpoint::Floor) {
					landing[0] = end[0];
					landing[1] = end[1];
					landing[2] = end[2];
					landed = true;
				}
				break;
			}

			pushScene(next);
			travelled += segmentLength;
			current[0] = next[0]; current[1] = next[1]; current[2] = next[2];
		}

		if (!_preview.scenePoints.empty()) {
			_preview.sceneEnd = _preview.scenePoints.back();
		}
		if (landed) {
			const GroundedPoint2 spot{ landing[0], landing[1] };
			// 바닥 안이고 몸이 들어갈 만큼 벽에서 떨어진 곳만 승인한다. 보정하지 않는다.
			_preview.valid = _grounded->isValidStand(spot);
			_preview.targetMetric[0] = landing[0];
			_preview.targetMetric[1] = landing[1];

			// 몸 크기를 그대로 보여 주는 반경 0.25 m 고리를 바닥에 놓는다.
			_preview.markerIsRing = true;
			const int ringPoints = 24;
			for (int step = 0; step < ringPoints; ++step) {
				const double angle = 2.0 * M_PI * step / ringPoints;
				const double ring[3] = {
					landing[0] + grounded::BODY_RADIUS_M * std::cos(angle),
					landing[1] + grounded::BODY_RADIUS_M * std::sin(angle),
					0.0
				};
				double scene[3];
				_grounded->toScene(ring, scene);
				_preview.markerPoints.push_back(
					sibr::Vector3f(float(scene[0]), float(scene[1]), float(scene[2])));
			}
		} else if (!_preview.scenePoints.empty()) {
			// 막혔거나 착지점이 없다. 끝난 자리에 작은 X를 놓는다.
			_preview.markerIsRing = false;
			double endMetric[3];
			const double endScene[3] = { _preview.scenePoints.back().x(),
				_preview.scenePoints.back().y(), _preview.scenePoints.back().z() };
			_grounded->toMetric(endScene, endMetric);
			if (finite3(endMetric)) {
				const double arm = 0.15;
				const double axes[3][3] = { {arm,0,0}, {0,arm,0}, {0,0,arm} };
				for (const auto& axis : axes) {
					for (int side = -1; side <= 1; side += 2) {
						const double tip[3] = { endMetric[0] + side * axis[0],
							endMetric[1] + side * axis[1], endMetric[2] + side * axis[2] };
						double scene[3];
						_grounded->toScene(tip, scene);
						_preview.markerPoints.push_back(
							sibr::Vector3f(float(scene[0]), float(scene[1]), float(scene[2])));
					}
				}
			}
		}
	}

} /*namespace sibr*/
