/*
 * RFVisualizer: Grounded FPS 전용 포물선 텔레포트. R을 누르는 동안 조준하고 떼면 이동한다.
 *
 * 바닥·벽·눈높이 판정은 GroundedFPSController를 그대로 쓴다. 새 물리엔진도, 새 mesh loader도,
 * 새 CLI도 만들지 않는다. 무효한 지점을 가까운 바닥으로 몰래 보정하지 않는다.
 *
 * 입력은 TeleportAction 하나로만 들어온다. 지금은 main.cpp가 키보드 R을 이 값으로 바꾸고,
 * 후속 작업에서 임베디드 버튼이 같은 값을 채우면 이 상태기계를 그대로 쓸 수 있다.
 */
#pragma once

# include "Config.hpp"
# include "GroundedFPSController.hpp"

# include <core/raycaster/Raycaster.hpp>
# include <core/system/Vector.hpp>

# include <memory>
# include <vector>

namespace sibr {

	/** 입력원과 무관한 텔레포트 동작. keyboard/embedded 어느 쪽이든 이것만 채운다. */
	struct TeleportAction
	{
		bool pressed = false;   ///< 이번 Frame에 눌리기 시작했다.
		bool active = false;    ///< 지금 누르고 있다.
		bool released = false;  ///< 이번 Frame에 뗐다.
	};

	/** 포물선이 무엇에 막혀 끝났는지. */
	enum class TeleportEndpoint
	{
		Floor,      ///< metric z=0 바닥에 내려앉았다.
		Wall,       ///< room envelope의 벽에 막혔다.
		Obstacle,   ///< proxy mesh(Raycaster)에 막혔다.
		Cap         ///< 최대 시간이나 누적 길이에 걸렸다. 착지점이 없다.
	};

	/** 이번 Frame에 그릴 것. Renderer는 이 값만 보고 그린다. */
	struct TeleportPreview
	{
		bool aiming = false;                     ///< false면 아무것도 그리지 않는다.
		bool valid = false;                      ///< 초록(true) / 빨강(false)
		TeleportEndpoint endpoint = TeleportEndpoint::Cap;
		std::vector<sibr::Vector3f> scenePoints; ///< 포물선 polyline (scene 좌표)
		sibr::Vector3f sceneEnd = sibr::Vector3f(0.f, 0.f, 0.f);
		/** valid일 때만 의미 있다. 착지 지점의 metric XY. */
		double targetMetric[2] = { 0.0, 0.0 };
		/** 착지 마커. ring이면 LINE_LOOP, cross면 LINES로 그린다. */
		std::vector<sibr::Vector3f> markerPoints;
		bool markerIsRing = false;
	};

	/** 씬과 무관한 고정값. 조절 손잡이로 열지 않는다. */
	namespace teleport
	{
		const double SPEED_MPS      = 8.0;    ///< 발사 속도
		const double GRAVITY_MPS2   = 9.81;   ///< metric -Z 방향
		const double DURATION_S     = 1.5;    ///< 최대 비행 시간
		const int    SEGMENTS       = 64;     ///< 65 points
		const double MAX_LENGTH_M   = 8.0;    ///< 누적 polyline 길이 상한
		const double TIE_EPSILON_M  = 0.05;   ///< 바닥과 proxy가 비기면 바닥이 이긴다.
	}

	/**
	 * \class ArcTeleportController
	 * \brief 포물선 계산 + 목적지 판정 + press/hold/release 상태기계.
	 */
	class SIBR_EXP_ULR_EXPORT ArcTeleportController
	{
	public:
		using Ptr = std::shared_ptr<ArcTeleportController>;

		/** \param grounded 바닥·벽·좌표 변환 (필수)
		 * \param raycaster proxy mesh 충돌용. 없으면 proxy는 무시한다. */
		ArcTeleportController(GroundedFPSController::Ptr grounded,
			std::shared_ptr<sibr::Raycaster> raycaster);

		/** 한 Frame 진행한다.
		 * \param action 이번 Frame의 입력
		 * \param eligible 지금 텔레포트를 받아도 되는지(FPS mode, handheld 비활성 등)
		 * \param sceneOrigin 현재 Camera 위치 (scene 좌표)
		 * \param sceneForward 현재 Camera 시선 방향 (scene 좌표, 정규화 불필요)
		 * \param outSceneTarget commit할 때 새 Camera 위치가 담긴다
		 * \return 이번 Frame에 위치를 옮겨야 하면 true (release에서 정확히 한 번) */
		bool update(const TeleportAction& action, bool eligible,
			const sibr::Vector3f& sceneOrigin, const sibr::Vector3f& sceneForward,
			sibr::Vector3f& outSceneTarget);

		/** Frame 앞부분: press로 조준을 시작하고 자격을 잃으면 취소한다.
		 * Camera가 갱신되기 **전에** 불러야 press한 Frame부터 WASD가 잠긴다.
		\param action 이번 Frame의 입력
		\param eligible 지금 텔레포트를 받아도 되는지 */
		void beginFrame(const TeleportAction& action, bool eligible);

		/** Frame 뒷부분: 갱신된 Camera로 포물선을 다시 그리고 release면 commit한다.
		\param action 이번 Frame의 입력
		\param sceneOrigin 갱신된 Camera 위치
		\param sceneForward 갱신된 Camera 시선
		\param outSceneTarget commit할 새 위치
		eturn 이번 Frame에 위치를 옮겨야 하면 true */
		bool endFrame(const TeleportAction& action, const sibr::Vector3f& sceneOrigin,
			const sibr::Vector3f& sceneForward, sibr::Vector3f& outSceneTarget);

		/** 조준 중인지. main이 grounded 위치 제약을 얼려야 하는지 판단하는 데 쓴다. */
		bool aiming() const { return _aiming; }

		const TeleportPreview& preview() const { return _preview; }

	private:
		/** 포물선을 다시 계산해 _preview를 채운다. */
		void recompute(const sibr::Vector3f& sceneOrigin, const sibr::Vector3f& sceneForward);
		void cancel();

		GroundedFPSController::Ptr _grounded;
		std::shared_ptr<sibr::Raycaster> _raycaster;
		TeleportPreview _preview;
		bool _aiming = false;
	};

} /*namespace sibr*/
