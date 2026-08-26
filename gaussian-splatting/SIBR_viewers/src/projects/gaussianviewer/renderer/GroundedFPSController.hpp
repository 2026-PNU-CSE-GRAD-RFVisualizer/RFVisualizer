/*
 * RFVisualizer: --grounded-fps 전용. metric XY 평면에서 반경 0.25 m 원을 벽에 대고 미끄러뜨린다.
 *
 * Physics engine도 범용 Character Controller도 넣지 않는다. 바닥은 metric z=0 평지이고
 * 눈높이는 1.7 m 고정이다. 계단·경사·중력·점프·동적 물체는 다루지 않는다.
 *
 * SIBR Mesh/로깅 대신 OBJ의 v/f 줄만 직접 읽고 std::runtime_error를 던진다. Test 실행 파일이
 * sibr 라이브러리 링크 없이 이 .cpp 하나만 컴파일해 검증하기 때문이다(HandheldControlClient와
 * 같은 이유).
 */
#pragma once

# include "Config.hpp"

# include <Eigen/Dense>
# include <memory>
# include <stdexcept>
# include <string>
# include <vector>

namespace sibr {

	/** metric XY 한 점. */
	struct GroundedPoint2
	{
		double x = 0.0, y = 0.0;
	};

	/** 벽 면을 XY로 눌러 만든 선분. */
	struct GroundedSegment
	{
		GroundedPoint2 a, b;
	};

	/** 바닥 면을 XY로 눌러 만든 삼각형. */
	struct GroundedTriangle2
	{
		GroundedPoint2 a, b, c;
	};

	/** 씬과 무관한 고정값. 조절 손잡이로 열지 않는다. */
	namespace grounded
	{
		const double EYE_HEIGHT_M  = 1.7;    ///< 눈높이 (metric +Z)
		const double BODY_RADIUS_M = 0.25;   ///< 몸체 반경
		const double MAX_SUBSTEP_M = 0.125;  ///< 반경보다 작아야 벽을 지나치지 않는다.
		const int    MAX_SUBSTEPS  = 64;     ///< 한 Frame 최대 이동 = 8 m
		const int    MAX_RESOLVES  = 4;      ///< substep 당 push-out 반복
		const double EPSILON_M     = 1e-4;
	}

	/** walls에 반경만큼 걸리지 않는 최종 위치.
	 *
	 * from은 이미 안전하다고 본다. 정면 충돌은 벽 앞에서 멈추고 비스듬한 충돌은 접선 성분이
	 * 남는다. 모서리 비수렴·과도한 이동·비유한 입력은 from을 그대로 돌려준다. */
	GroundedPoint2 groundedResolve(const std::vector<GroundedSegment>& walls,
		const GroundedPoint2& from, const GroundedPoint2& to);

	/**
	 * \class GroundedFPSController
	 * \brief RF Bundle의 room envelope에서 바닥·벽을 뽑아 FPS 위치를 제약한다.
	 */
	class SIBR_EXP_ULR_EXPORT GroundedFPSController
	{
	public:
		using Ptr = std::shared_ptr<GroundedFPSController>;

		/** RF Volume manifest를 읽어 유일한 room_envelope_metric.obj에서 geometry를 만든다.
		 * 계약 위반은 std::runtime_error다. */
		explicit GroundedFPSController(const std::string& manifestPath);

		/** Test용: 이미 만든 geometry로 바로 구성한다. */
		GroundedFPSController(const Eigen::Matrix4d& sceneFromMetric,
			std::vector<GroundedSegment> walls, std::vector<GroundedTriangle2> floor);

		/** 시작 pose를 눈높이로 스냅한다. 바닥 밖이거나 벽에 박혀 있으면 가장 가까운 유효
		 * 위치로 옮긴다. 옮겼으면 true. 바닥 어디에도 몸이 들어갈 자리가 없으면 던진다. */
		bool snapStart(const double scene[3], double outScene[3]) const;

		/** 후보 scene 위치를 확정 scene 위치로 바꾼다. z는 항상 눈높이다. */
		void constrain(const double currentScene[3], const double candidateScene[3],
			double outScene[3]) const;

		void toMetric(const double scene[3], double metric[3]) const;
		void toScene(const double metric[3], double scene[3]) const;

		const std::vector<GroundedSegment>& walls() const { return _walls; }
		const std::vector<GroundedTriangle2>& floor() const { return _floor; }
		bool insideFloor(const GroundedPoint2& p) const;
		/** 바닥 안이면서 벽에서 반경 이상 떨어져 있는지. 시작 위치의 유효 조건이다. */
		bool isValidStand(const GroundedPoint2& p) const;
		/** p에서 가장 가까운 유효 위치. 하나도 없으면 false. */
		bool nearestValidStand(const GroundedPoint2& p, GroundedPoint2& out) const;
		/** 가장 가까운 벽까지의 거리. 벽이 없으면 무한대. */
		double clearance(const GroundedPoint2& p) const;

	private:
		void setTransform(const Eigen::Matrix4d& sceneFromMetric);

		Eigen::Matrix4d _sceneFromMetric = Eigen::Matrix4d::Identity();
		Eigen::Matrix4d _metricFromScene = Eigen::Matrix4d::Identity();
		std::vector<GroundedSegment> _walls;
		std::vector<GroundedTriangle2> _floor;
	};

} /*namespace sibr*/
