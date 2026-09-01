/*
 * RFVisualizer: Backend WebSocket `/handheld/control`을 구독해 Camera·버튼 상태를 뽑아낸다.
 *
 * Backend 송신 계약은 INTERFACE.md §11.6이며 여기서 바꾸지 않는다. WebSocket은 순서·중복·
 * 재연결을 보장하지 않으므로 Session/Sample 방어는 전부 이 파일 안에서 끝낸다.
 *
 * 텔레포트·Height-cycle 버튼은 2026-08-28부터 레벨 상태로만 온다(RFHC bit1·bit2). 이
 * 파일은 그 순간 값을 그대로 poll()에 실어 보낼 뿐, press/hold/release edge 판정은
 * 호출자(main.cpp)가 키보드 입력과 동일한 방식으로 계산한다.
 *
 * Worker Thread가 onMessage()로 상태를 채우고 Render Thread가 poll()로 가져간다.
 * Camera 객체는 Render Thread만 만진다.
 *
 * SIBR 로깅 대신 std::cerr를 쓴다. Test 실행 파일이 sibr_system 링크 없이 이 .cpp 하나만
 * 컴파일해 검증하기 때문이다.
 */
#pragma once

# include "Config.hpp"

# include <picojson/picojson.hpp>

# include <atomic>
# include <condition_variable>
# include <cstdint>
# include <memory>
# include <mutex>
# include <string>
# include <thread>
# include <unordered_set>

namespace sibr {

	/** Camera와 Device가 함께 쓰는 최소 Quaternion. Eigen 정렬 옵션에 얽히지 않게 POD로 둔다. */
	struct HandheldQuat
	{
		double x = 0.0, y = 0.0, z = 0.0, w = 1.0;
	};

	/**
	 * \class HandheldControlClient
	 * \brief `/handheld/control` 구독 + Session/Sample Reducer + Camera 자세·버튼 상태 계산.
	 *
	 * host가 비면 Worker Thread를 만들지 않는다. 그때 poll()은 항상 비활성을 돌려주므로
	 * Viewer는 기존 FPS 동작을 그대로 쓴다.
	 */
	class SIBR_EXP_ULR_EXPORT HandheldControlClient
	{
	public:
		using Ptr = std::shared_ptr<HandheldControlClient>;

		struct Options
		{
			std::string host;                 ///< 비면 아무것도 하지 않는다.
			int port = 8000;
			std::string deviceId = "handheld-01";
			uint64_t orientationTimeoutMs = 750;
		};

		/** 이번 Frame에 Camera에 적용할 것. */
		struct Frame
		{
			bool active = false;        ///< true면 Handheld가 Camera를 전담한다(handler NONE).
			bool hasRotation = false;   ///< false면 이번 Frame에는 회전을 건드리지 않는다.
			HandheldQuat rotation;      ///< 절대 Camera rotation
			/** 텔레포트 버튼의 그 순간 레벨 상태. edge 판정은 호출자가 한다(키보드와 동일 패턴). */
			bool teleportButtonHeld = false;
			/** Height-cycle 버튼의 그 순간 레벨 상태. */
			bool heightCycleButtonHeld = false;
		};

		struct Stats
		{
			uint64_t malformed = 0;         ///< JSON/type/range 위반으로 버린 수
			uint64_t foreignDevice = 0;     ///< 허용하지 않는 device_id
			uint64_t retiredSession = 0;    ///< 이미 물러난 session의 늦은 packet
			uint64_t duplicateSample = 0;
			uint64_t outOfOrderSample = 0;
			uint64_t poseUpdates = 0;
			uint64_t connects = 0;          ///< handshake 성공 횟수
			uint64_t disconnects = 0;
		};

		/** host가 있으면 Worker Thread를 띄운다. */
		explicit HandheldControlClient(const Options& options);
		~HandheldControlClient();

		/** Backend Message 한 개를 반영한다(Worker Thread. Test는 직접 부른다). */
		void onMessage(const std::string& text, uint64_t nowMs);
		/** WebSocket handshake 성공. */
		void onConnected();
		/** 연결이 끊겼다. */
		void onDisconnected();

		/** Render Thread에서 매 Frame 부른다. cameraRotation은 현재 Camera 회전이다. */
		Frame poll(uint64_t nowMs, const HandheldQuat& cameraRotation);

		Stats stats() const;
		bool enabled() const { return !_options.host.empty(); }

		/** steady_clock 기준 ms. */
		static uint64_t nowMs();
		static HandheldQuat multiply(const HandheldQuat& a, const HandheldQuat& b);
		static HandheldQuat inverseUnit(const HandheldQuat& q);
		/** 실패하면(0에 가까우면) false. */
		static bool normalize(HandheldQuat& q);

	private:
		void handleState(const picojson::object& object, uint64_t nowMs);
		/** 이미 mutex를 잡은 상태에서 부른다. */
		bool adoptSession(uint32_t sessionId);
		void warnOnce(bool& flag, const std::string& message);

		void workerLoop();
		bool connectOnce();
		void readLoop();
		void closeSocket();

		Options _options;

		mutable std::mutex _mutex;          ///< 아래 상태 전부를 덮는다.
		bool _haveSession = false;
		uint32_t _session = 0;
		std::unordered_set<uint32_t> _retired;
		bool _haveSample = false;
		uint32_t _lastSample = 0;
		bool _havePose = false;
		HandheldQuat _pose;                 ///< 마지막 유효·비 stale 자세
		uint64_t _poseMs = 0;
		bool _stale = true;
		bool _teleportHeld = false;          ///< 마지막으로 받은 레벨 상태 그대로.
		bool _heightCycleHeld = false;
		Stats _stats;
		bool _warnedMalformed = false;

		// Render Thread 전용.
		bool _active = false;
		HandheldQuat _cameraAnchor;
		HandheldQuat _deviceAnchor;

		// Worker Thread.
		struct Connection;
		std::unique_ptr<Connection> _connection;
		std::atomic<bool> _stop{ false };
		std::mutex _wakeMutex;
		std::condition_variable _wake;
		std::thread _worker;
	};

} /*namespace sibr*/
