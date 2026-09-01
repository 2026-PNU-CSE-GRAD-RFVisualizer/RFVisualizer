#include "HandheldControlClient.hpp"

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>

#include <chrono>
#include <cmath>
#include <iostream>

namespace beast = boost::beast;
namespace websocket = boost::beast::websocket;
namespace net = boost::asio;
using tcp = boost::asio::ip::tcp;

namespace sibr {

	namespace {

		const uint32_t HALF_SPAN = 0x80000000u;

		const picojson::value* member(const picojson::object& object, const char* name)
		{
			const picojson::object::const_iterator found = object.find(name);
			return found == object.end() ? nullptr : &found->second;
		}

		bool readString(const picojson::object& object, const char* name, std::string& out)
		{
			const picojson::value* value = member(object, name);
			if (value == nullptr || !value->is<std::string>()) {
				return false;
			}
			out = value->get<std::string>();
			return true;
		}

		bool readBool(const picojson::object& object, const char* name, bool& out)
		{
			const picojson::value* value = member(object, name);
			if (value == nullptr || !value->is<bool>()) {
				return false;
			}
			out = value->get<bool>();
			return true;
		}

		bool readFinite(const picojson::object& object, const char* name, double& out)
		{
			const picojson::value* value = member(object, name);
			if (value == nullptr || !value->is<double>()) {
				return false;
			}
			out = value->get<double>();
			return std::isfinite(out);
		}

		/** uint32 범위의 정수만 통과시킨다. picojson은 숫자를 전부 double로 준다. */
		bool readUint32(const picojson::object& object, const char* name, uint32_t& out)
		{
			double raw = 0.0;
			if (!readFinite(object, name, raw)) {
				return false;
			}
			if (raw < 0.0 || raw > 4294967295.0 || std::floor(raw) != raw) {
				return false;
			}
			out = uint32_t(raw);
			return true;
		}

		bool readInteger(const picojson::object& object, const char* name)
		{
			double raw = 0.0;
			return readFinite(object, name, raw) && std::floor(raw) == raw;
		}

	} // namespace

	struct HandheldControlClient::Connection
	{
		net::io_context io;
		tcp::resolver resolver{ io };
		std::unique_ptr<websocket::stream<tcp::socket>> ws;
		std::mutex mutex;      ///< ws 생성과 강제 종료를 _stop과 함께 묶는다.
	};

	// ---------------------------------------------------------------- 수학

	uint64_t HandheldControlClient::nowMs()
	{
		return uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
			std::chrono::steady_clock::now().time_since_epoch()).count());
	}

	HandheldQuat HandheldControlClient::multiply(const HandheldQuat& a, const HandheldQuat& b)
	{
		HandheldQuat out;
		out.w = a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z;
		out.x = a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y;
		out.y = a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x;
		out.z = a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w;
		return out;
	}

	HandheldQuat HandheldControlClient::inverseUnit(const HandheldQuat& q)
	{
		HandheldQuat out;
		out.x = -q.x; out.y = -q.y; out.z = -q.z; out.w = q.w;
		return out;
	}

	bool HandheldControlClient::normalize(HandheldQuat& q)
	{
		const double norm = std::sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
		if (!std::isfinite(norm) || norm < 1e-6) {
			return false;
		}
		q.x /= norm; q.y /= norm; q.z /= norm; q.w /= norm;
		return true;
	}

	// ---------------------------------------------------------------- 수명

	HandheldControlClient::HandheldControlClient(const Options& options)
		: _options(options)
	{
		if (_options.host.empty()) {
			return;
		}
		_connection.reset(new Connection());
		_worker = std::thread(&HandheldControlClient::workerLoop, this);
	}

	HandheldControlClient::~HandheldControlClient()
	{
		_stop = true;
		{
			// wait_for가 술어를 다시 보게 한다.
			std::lock_guard<std::mutex> lock(_wakeMutex);
		}
		_wake.notify_all();
		if (_connection) {
			closeSocket();
		}
		if (_worker.joinable()) {
			_worker.join();
		}
	}

	// ---------------------------------------------------------------- Reducer

	void HandheldControlClient::warnOnce(bool& flag, const std::string& message)
	{
		if (flag) {
			return;
		}
		flag = true;
		std::cerr << "[Handheld] " << message << std::endl;
	}

	void HandheldControlClient::onMessage(const std::string& text, uint64_t nowMs)
	{
		picojson::value root;
		const std::string error = picojson::parse(root, text);

		std::lock_guard<std::mutex> lock(_mutex);
		if (!error.empty() || !root.is<picojson::object>()) {
			++_stats.malformed;
			warnOnce(_warnedMalformed, "읽을 수 없는 Message가 왔습니다. 폐기하고 연결은 유지합니다.");
			return;
		}
		const picojson::object& object = root.get<picojson::object>();
		std::string type;
		if (!readString(object, "type", type)) {
			++_stats.malformed;
			warnOnce(_warnedMalformed, "type이 없는 Message가 왔습니다. 폐기하고 연결은 유지합니다.");
			return;
		}
		if (type == "handheld_state") {
			handleState(object, nowMs);
		} else {
			++_stats.malformed;
			warnOnce(_warnedMalformed, "모르는 Message type이 왔습니다: " + type);
		}
	}

	void HandheldControlClient::handleState(const picojson::object& object, uint64_t nowMs)
	{
		std::string deviceId;
		uint32_t session = 0, sample = 0;
		bool orientationValid = false, teleportHeld = false, heightCycleHeld = false, stale = false;
		const picojson::value* quaternion = member(object, "quaternion");
		double qx = 0.0, qy = 0.0, qz = 0.0, qw = 0.0;

		const bool parsed =
			readString(object, "device_id", deviceId)
			&& readUint32(object, "session_id", session)
			&& readUint32(object, "sample_seq", sample)
			&& readInteger(object, "server_timestamp_ms")
			&& readBool(object, "orientation_valid", orientationValid)
			&& readBool(object, "teleport_button_held", teleportHeld)
			&& readBool(object, "height_cycle_button_held", heightCycleHeld)
			&& readBool(object, "stale", stale)
			&& quaternion != nullptr && quaternion->is<picojson::object>()
			&& readFinite(quaternion->get<picojson::object>(), "x", qx)
			&& readFinite(quaternion->get<picojson::object>(), "y", qy)
			&& readFinite(quaternion->get<picojson::object>(), "z", qz)
			&& readFinite(quaternion->get<picojson::object>(), "w", qw);
		if (!parsed) {
			++_stats.malformed;
			warnOnce(_warnedMalformed, "handheld_state의 필드가 계약과 다릅니다. 폐기합니다.");
			return;
		}
		if (deviceId != _options.deviceId) {
			++_stats.foreignDevice;
			return;
		}
		if (!adoptSession(session)) {
			return;
		}

		// stale은 순서와 무관하게 먼저 본다. 즉시 FPS로 돌아가야 하기 때문이다.
		if (stale) {
			_stale = true;
		}

		if (_haveSample) {
			const uint32_t delta = sample - _lastSample;
			if (delta == 0) {
				++_stats.duplicateSample;
				return;
			}
			if (delta >= HALF_SPAN) {
				++_stats.outOfOrderSample;
				return;
			}
		}
		_lastSample = sample;
		_haveSample = true;
		_stale = stale;
		// 레벨 상태다 — 값이 뭐든 그대로 저장한다. dedup·edge 판정은 poll() 호출자가 한다.
		_teleportHeld = teleportHeld;
		_heightCycleHeld = heightCycleHeld;

		HandheldQuat sampleQuat;
		sampleQuat.x = qx; sampleQuat.y = qy; sampleQuat.z = qz; sampleQuat.w = qw;
		const bool usableQuat = normalize(sampleQuat);

		if (orientationValid && !stale) {
			if (usableQuat) {
				_pose = sampleQuat;
				_poseMs = nowMs;
				_havePose = true;
				++_stats.poseUpdates;
			} else {
				++_stats.malformed;
				warnOnce(_warnedMalformed, "Quaternion 길이가 0에 가깝습니다. 폐기합니다.");
			}
		}
	}

	bool HandheldControlClient::adoptSession(uint32_t sessionId)
	{
		if (_retired.find(sessionId) != _retired.end()) {
			++_stats.retiredSession;
			return false;
		}
		if (_haveSession && sessionId == _session) {
			return true;
		}
		if (!_haveSession) {
			// 처음 본 session이다.
			_session = sessionId;
			_haveSession = true;
			return true;
		}
		_retired.insert(_session);
		_session = sessionId;
		_haveSample = false;
		_havePose = false;
		_stale = true;
		return true;
	}

	void HandheldControlClient::onConnected()
	{
		std::lock_guard<std::mutex> lock(_mutex);
		++_stats.connects;
	}

	void HandheldControlClient::onDisconnected()
	{
		std::lock_guard<std::mutex> lock(_mutex);
		++_stats.disconnects;
	}

	HandheldControlClient::Stats HandheldControlClient::stats() const
	{
		std::lock_guard<std::mutex> lock(_mutex);
		return _stats;
	}

	// ---------------------------------------------------------------- Render Thread

	HandheldControlClient::Frame HandheldControlClient::poll(uint64_t nowMs, const HandheldQuat& cameraRotation)
	{
		Frame frame;
		bool havePose = false, stale = true, teleportHeld = false, heightCycleHeld = false;
		HandheldQuat pose;
		uint64_t poseMs = 0;
		{
			std::lock_guard<std::mutex> lock(_mutex);
			havePose = _havePose;
			pose = _pose;
			poseMs = _poseMs;
			stale = _stale;
			teleportHeld = _teleportHeld;
			heightCycleHeld = _heightCycleHeld;
		}

		const uint64_t age = nowMs > poseMs ? nowMs - poseMs : 0;
		frame.active = havePose && !stale && age <= _options.orientationTimeoutMs;
		if (!frame.active) {
			// 비활성(연결 전/끊김/stale/timeout)이면 버튼도 안 눌린 것으로 본다 —
			// 눌림이 이어졌다고 오판하지 않는다.
			_active = false;
			return frame;
		}
		frame.teleportButtonHeld = teleportHeld;
		frame.heightCycleButtonHeld = heightCycleHeld;

		if (!_active) {
			// 첫 유효 자세다. 이번 Frame에는 돌리지 않고 기준만 잡는다.
			_active = true;
			_cameraAnchor = cameraRotation;
			_deviceAnchor = pose;
			return frame;
		}
		frame.rotation = multiply(multiply(_cameraAnchor, inverseUnit(_deviceAnchor)), pose);
		normalize(frame.rotation);
		frame.hasRotation = true;
		return frame;
	}

	// ---------------------------------------------------------------- WebSocket

	void HandheldControlClient::workerLoop()
	{
		while (!_stop) {
			if (connectOnce()) {
				onConnected();
				readLoop();
				onDisconnected();
			}
			closeSocket();
			if (_stop) {
				break;
			}
			std::unique_lock<std::mutex> lock(_wakeMutex);
			_wake.wait_for(lock, std::chrono::seconds(1), [this] { return _stop.load(); });
		}
	}

	bool HandheldControlClient::connectOnce()
	{
		const std::string port = std::to_string(_options.port);
		// would_block을 "아직 안 끝났다"는 표시로 쓴다.
		boost::system::error_code result = net::error::would_block;
		{
			std::lock_guard<std::mutex> lock(_connection->mutex);
			if (_stop) {
				return false;
			}
			_connection->io.restart();
			_connection->ws.reset(new websocket::stream<tcp::socket>(_connection->io));
			_connection->ws->read_message_max(64 * 1024);
		}
		websocket::stream<tcp::socket>& ws = *_connection->ws;

		_connection->resolver.async_resolve(_options.host, port,
			[&](const boost::system::error_code& resolveError, tcp::resolver::results_type results) {
				if (resolveError) { result = resolveError; return; }
				net::async_connect(ws.next_layer(), results,
					[&](const boost::system::error_code& connectError, const tcp::endpoint&) {
						if (connectError) { result = connectError; return; }
						ws.async_handshake(_options.host + ":" + port, "/handheld/control",
							[&](const boost::system::error_code& handshakeError) { result = handshakeError; });
					});
			});
		_connection->io.run_for(std::chrono::seconds(2));
		if (result == net::error::would_block) {
			// 시간 안에 못 붙었다. Handler가 지역 변수를 참조하므로 여기서 다 정리하고 나간다.
			closeSocket();
			_connection->io.run();
			result = net::error::timed_out;
		}
		if (result) {
			if (!_stop) {
				std::cerr << "[Handheld] Backend 연결 실패, 1초 뒤 다시 시도합니다: "
					<< result.message() << std::endl;
			}
			return false;
		}
		return true;
	}

	void HandheldControlClient::readLoop()
	{
		beast::flat_buffer buffer;
		while (!_stop) {
			boost::system::error_code error;
			_connection->ws->read(buffer, error);
			if (error) {
				if (!_stop) {
					std::cerr << "[Handheld] 연결이 끊겼습니다: " << error.message()
						<< ", 1초 뒤 다시 붙습니다." << std::endl;
				}
				return;
			}
			onMessage(beast::buffers_to_string(buffer.data()), nowMs());
			buffer.consume(buffer.size());
		}
	}

	void HandheldControlClient::closeSocket()
	{
		// ponytail: blocking read를 깨우는 방법은 다른 Thread에서의 shutdown이다.
		// Linux에서 확실히 깨어난다. 더 얌전하게 하려면 read도 async로 바꿔야 한다.
		std::lock_guard<std::mutex> lock(_connection->mutex);
		if (!_connection->ws) {
			return;
		}
		boost::system::error_code ignored;
		_connection->ws->next_layer().shutdown(tcp::socket::shutdown_both, ignored);
		_connection->ws->next_layer().close(ignored);
	}

} /*namespace sibr*/
