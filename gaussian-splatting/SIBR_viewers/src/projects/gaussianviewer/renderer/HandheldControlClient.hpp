/*
 * RFVisualizer: Backend WebSocket `/handheld/control`을 구독해 Camera에 줄 값만 뽑아낸다.
 *
 * Backend 송신 계약은 INTERFACE.md §11.6이며 여기서 바꾸지 않는다. WebSocket은 순서·중복·
 * 재연결을 보장하지 않으므로 Session/Sample/Event 방어는 전부 이 파일 안에서 끝낸다.
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
# include <deque>
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
	 * \brief `/handheld/control` 구독 + Session/Sample/Event Reducer + Camera 자세 계산.
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
			std::string frameId;              ///< RF Volume manifest의 frame_id
			/// RF Volume manifest의 T_scene_from_metric (row-major 4x4).
			double sceneFromMetric[16] = { 1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1 };
			uint64_t orientationTimeoutMs = 750;
		};

		/** 이번 Frame에 Camera에 적용할 것. */
		struct Frame
		{
			bool active = false;        ///< true면 Handheld가 Camera를 전담한다(handler NONE).
			bool hasRotation = false;   ///< false면 이번 Frame에는 회전을 건드리지 않는다.
			HandheldQuat rotation;      ///< 절대 Camera rotation
			bool recentered = false;    ///< 이번 Frame에 Recenter 기준을 새로 잡았다.
			bool hasPosition = false;
			float position[3] = { 0.0f, 0.0f, 0.0f };   ///< Gaussian Scene 좌표
		};

		struct Stats
		{
			uint64_t malformed = 0;         ///< JSON/type/range 위반으로 버린 수
			uint64_t foreignDevice = 0;     ///< 허용하지 않는 device_id
			uint64_t retiredSession = 0;    ///< 이미 물러난 session의 늦은 packet
			uint64_t duplicateSample = 0;
			uint64_t outOfOrderSample = 0;
			uint64_t poseUpdates = 0;
			uint64_t recenterEdges = 0;     ///< 실제로 만든 Recenter edge 수
			uint64_t positionEdges = 0;     ///< 실제로 만든 Position edge 수
			uint64_t droppedEdges = 0;      ///< Queue가 가득 차 버린 edge 수
			uint64_t droppedJoins = 0;      ///< 16개를 넘겨 버린 Position join 수
			uint64_t connects = 0;          ///< handshake 성공 횟수
			uint64_t disconnects = 0;
		};

		/** host가 있으면 Worker Thread를 띄운다. */
		explicit HandheldControlClient(const Options& options);
		~HandheldControlClient();

		/** Backend Message 한 개를 반영한다(Worker Thread. Test는 직접 부른다). */
		void onMessage(const std::string& text, uint64_t nowMs);
		/** WebSocket handshake 성공. connection epoch를 올린다. */
		void onConnected();
		/** 연결이 끊겼다. 완성되지 않은 Position join만 버린다. */
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
		enum EventKind { EVENT_RECENTER = 0, EVENT_POSITION = 1, EVENT_KIND_COUNT = 2 };

		struct EventEdge
		{
			int kind = EVENT_RECENTER;
			HandheldQuat quat;                          ///< Recenter 기준이 될 device 자세
			double position[3] = { 0.0, 0.0, 0.0 };     ///< Scene 좌표
		};

		struct PositionJoin
		{
			uint64_t epoch = 0;
			uint32_t eventSeq = 0;
			uint32_t sessionId = 0;
			bool haveState = false;
			bool haveResponse = false;
			bool usable = false;        ///< accepted + finite + frame_id 일치
			double metric[3] = { 0.0, 0.0, 0.0 };
		};

		void handleState(const picojson::object& object, uint64_t nowMs);
		void handlePositionUpdate(const picojson::object& object);
		/** 이미 mutex를 잡은 상태에서 부른다. */
		bool adoptSession(uint32_t sessionId);
		bool newerEvent(int kind, uint32_t eventSeq);
		void pushEdge(const EventEdge& edge);
		size_t findJoin(uint32_t eventSeq);
		void completeJoin(size_t index);
		void sceneFromMetric(const double metric[3], double scene[3]) const;
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
		bool _haveEvent[EVENT_KIND_COUNT] = { false, false };
		uint32_t _lastEvent[EVENT_KIND_COUNT] = { 0, 0 };
		bool _havePose = false;
		HandheldQuat _pose;                 ///< 마지막 유효·비 stale 자세
		uint64_t _poseMs = 0;
		bool _stale = true;
		uint64_t _epoch = 0;
		std::deque<EventEdge> _edges;       ///< 최대 16개
		std::deque<PositionJoin> _joins;    ///< 최대 16개
		Stats _stats;
		bool _warnedMalformed = false;
		bool _warnedEdgeQueue = false;
		bool _warnedJoinQueue = false;

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
