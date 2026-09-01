/*
 * RFVisualizer: HandheldControlClient의 계약·상태 규칙·WebSocket 동작 검증.
 *
 * 새 Test Framework를 넣지 않는다. assertion과 CTest만 쓴다.
 * Fake Backend도 별도 Python 의존성 없이 같은 실행 파일 안의 Boost.Beast Server다.
 */
#include "projects/gaussianviewer/renderer/HandheldControlClient.hpp"

#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <thread>
#include <vector>

namespace beast = boost::beast;
namespace websocket = boost::beast::websocket;
namespace http = boost::beast::http;
namespace net = boost::asio;
using tcp = boost::asio::ip::tcp;

using sibr::HandheldControlClient;
using sibr::HandheldQuat;

namespace {

	int g_failures = 0;

	void check(bool condition, const std::string& name)
	{
		if (!condition) {
			++g_failures;
			std::cerr << "FAIL: " << name << std::endl;
		} else {
			std::cout << "ok  : " << name << std::endl;
		}
	}

	HandheldControlClient::Options makeOptions()
	{
		HandheldControlClient::Options options;
		options.host = "";                 // Worker Thread 없이 Reducer만 쓴다.
		return options;
	}

	std::string boolText(bool value) { return value ? "true" : "false"; }

	std::string stateJson(uint32_t session, uint32_t sample,
		bool orientationValid, bool teleportHeld, bool heightCycleHeld, bool stale,
		double x, double y, double z, double w,
		const std::string& device = "handheld-01")
	{
		std::ostringstream out;
		out.precision(17);
		out << "{\"type\":\"handheld_state\",\"device_id\":\"" << device
			<< "\",\"session_id\":" << session
			<< ",\"sample_seq\":" << sample
			<< ",\"server_timestamp_ms\":1700000000000"
			<< ",\"orientation_valid\":" << boolText(orientationValid)
			<< ",\"teleport_button_held\":" << boolText(teleportHeld)
			<< ",\"height_cycle_button_held\":" << boolText(heightCycleHeld)
			<< ",\"stale\":" << boolText(stale)
			<< ",\"quaternion\":{\"x\":" << x << ",\"y\":" << y
			<< ",\"z\":" << z << ",\"w\":" << w << "}}";
		return out.str();
	}

	HandheldQuat quat(double x, double y, double z, double w)
	{
		HandheldQuat q; q.x = x; q.y = y; q.z = z; q.w = w; return q;
	}

	bool nearQuat(const HandheldQuat& a, const HandheldQuat& b, double tolerance)
	{
		return std::fabs(a.x - b.x) < tolerance && std::fabs(a.y - b.y) < tolerance
			&& std::fabs(a.z - b.z) < tolerance && std::fabs(a.w - b.w) < tolerance;
	}

	const HandheldQuat IDENTITY = quat(0.0, 0.0, 0.0, 1.0);

	/** 활성 상태로 만들고 기준을 identity로 잡는다. */
	void activate(HandheldControlClient& client, uint32_t session, uint32_t sample, uint64_t timeMs)
	{
		client.onMessage(stateJson(session, sample, true, false, false, false, 0, 0, 0, 1), timeMs);
		const HandheldControlClient::Frame frame = client.poll(timeMs, IDENTITY);
		check(frame.active && !frame.hasRotation, "첫 유효 자세는 활성만 하고 회전하지 않는다");
	}

	// ------------------------------------------------------------------ 계약

	void testMalformed()
	{
		HandheldControlClient client(makeOptions());
		client.onMessage("this is not json", 0);
		client.onMessage("[1,2,3]", 0);
		client.onMessage("{\"type\":\"who_knows\"}", 0);
		// session_id가 음수라 uint32가 아니다.
		client.onMessage("{\"type\":\"handheld_state\",\"device_id\":\"handheld-01\",\"session_id\":-1,"
			"\"sample_seq\":1,\"server_timestamp_ms\":0,\"orientation_valid\":true,"
			"\"teleport_button_held\":false,\"height_cycle_button_held\":false,\"stale\":false,"
			"\"quaternion\":{\"x\":0,\"y\":0,\"z\":0,\"w\":1}}", 0);
		// stale이 boolean이 아니다.
		client.onMessage("{\"type\":\"handheld_state\",\"device_id\":\"handheld-01\",\"session_id\":1,"
			"\"sample_seq\":1,\"server_timestamp_ms\":0,\"orientation_valid\":true,"
			"\"teleport_button_held\":false,\"height_cycle_button_held\":false,\"stale\":\"no\","
			"\"quaternion\":{\"x\":0,\"y\":0,\"z\":0,\"w\":1}}", 0);
		// quaternion 성분이 없다.
		client.onMessage("{\"type\":\"handheld_state\",\"device_id\":\"handheld-01\",\"session_id\":1,"
			"\"sample_seq\":1,\"server_timestamp_ms\":0,\"orientation_valid\":true,"
			"\"teleport_button_held\":false,\"height_cycle_button_held\":false,\"stale\":false,"
			"\"quaternion\":{\"x\":0,\"y\":0,\"z\":0}}", 0);
		// 예전 계약(position_update)은 이제 모르는 type이다.
		client.onMessage("{\"type\":\"position_update\",\"device_id\":\"handheld-01\",\"accepted\":true}", 0);
		check(client.stats().malformed == 7, "잘못된 Message 7개를 모두 폐기한다");
		check(!client.poll(0, IDENTITY).active, "잘못된 Message만으로는 활성화되지 않는다");

		// 다른 장치는 조용히 무시한다.
		client.onMessage(stateJson(1, 1, true, false, false, false, 0, 0, 0, 1, "handheld-02"), 0);
		check(client.stats().foreignDevice == 1 && client.stats().poseUpdates == 0,
			"허용하지 않는 device_id는 무시한다");

		// 그 뒤 정상 Message는 그대로 동작한다.
		client.onMessage(stateJson(1, 1, true, false, false, false, 0, 0, 0, 1), 0);
		check(client.stats().poseUpdates == 1, "잘못된 Message 뒤에도 정상 Message는 반영된다");
	}

	void testNormalize()
	{
		HandheldControlClient client(makeOptions());
		activate(client, 1, 1, 1000);
		// 길이 3인 90도 Z 회전.
		const double half = std::sqrt(0.5);
		client.onMessage(stateJson(1, 2, true, false, false, false, 0, 0, 3.0 * half, 3.0 * half), 1000);
		const HandheldControlClient::Frame frame = client.poll(1000, IDENTITY);
		check(frame.hasRotation && nearQuat(frame.rotation, quat(0, 0, half, half), 1e-9),
			"Quaternion을 정규화해 적용한다");

		client.onMessage(stateJson(1, 3, true, false, false, false, 0, 0, 0, 0), 1000);
		check(client.stats().malformed == 1, "길이 0 Quaternion은 폐기한다");
	}

	void testSampleOrdering()
	{
		HandheldControlClient client(makeOptions());
		client.onMessage(stateJson(1, 10, true, false, false, false, 0, 0, 0, 1), 1000);
		client.onMessage(stateJson(1, 10, true, false, false, false, 0, 0, 1, 0), 1000);
		client.onMessage(stateJson(1, 9, true, false, false, false, 0, 0, 1, 0), 1000);
		const HandheldControlClient::Stats stats = client.stats();
		check(stats.duplicateSample == 1 && stats.outOfOrderSample == 1 && stats.poseUpdates == 1,
			"duplicate와 out-of-order sample은 Camera에 반영하지 않는다");
	}

	void testSampleWrap()
	{
		HandheldControlClient client(makeOptions());
		client.onMessage(stateJson(1, 0xFFFFFFFFu, true, false, false, false, 0, 0, 0, 1), 1000);
		client.onMessage(stateJson(1, 0u, true, false, false, false, 0, 0, 0, 1), 1000);
		check(client.stats().poseUpdates == 2 && client.stats().outOfOrderSample == 0,
			"uint32 wrap은 정상 진행으로 본다");
	}

	void testSessionSwitch()
	{
		HandheldControlClient client(makeOptions());
		client.onMessage(stateJson(1, 100, true, false, false, false, 0, 0, 0, 1), 1000);
		client.onMessage(stateJson(2, 5, true, false, false, false, 0, 0, 0, 1), 1000);
		check(client.stats().poseUpdates == 2, "새 session은 sample 상태를 초기화하고 채택한다");
		client.onMessage(stateJson(1, 101, true, false, false, false, 0, 0, 0, 1), 1000);
		check(client.stats().retiredSession == 1 && client.stats().poseUpdates == 2,
			"물러난 session의 늦은 packet은 영구 거부한다");
	}

	// ------------------------------------------------------------------ 버튼 (레벨 상태)

	void testTeleportButtonLevel()
	{
		HandheldControlClient client(makeOptions());
		activate(client, 1, 1, 1000);

		client.onMessage(stateJson(1, 2, true, true, false, false, 0, 0, 0, 1), 1000);
		check(client.poll(1000, IDENTITY).teleportButtonHeld,
			"텔레포트 버튼이 눌리면 그 순간 값을 그대로 돌려준다");

		client.onMessage(stateJson(1, 3, true, true, false, false, 0, 0, 0, 1), 1000);
		check(client.poll(1000, IDENTITY).teleportButtonHeld,
			"계속 누르고 있으면(dedup 없이) 계속 held다");

		client.onMessage(stateJson(1, 4, true, false, false, false, 0, 0, 0, 1), 1000);
		check(!client.poll(1000, IDENTITY).teleportButtonHeld,
			"떼면 바로 false로 돌아온다");
	}

	void testHeightCycleButtonLevel()
	{
		HandheldControlClient client(makeOptions());
		activate(client, 1, 1, 1000);

		client.onMessage(stateJson(1, 2, true, false, true, false, 0, 0, 0, 1), 1000);
		const HandheldControlClient::Frame pressed = client.poll(1000, IDENTITY);
		check(pressed.heightCycleButtonHeld && !pressed.teleportButtonHeld,
			"두 버튼은 서로 독립적인 레벨 상태다");
	}

	void testButtonsFalseWhenInactive()
	{
		HandheldControlClient client(makeOptions());
		activate(client, 1, 1, 1000);
		client.onMessage(stateJson(1, 2, true, true, true, false, 0, 0, 0, 1), 1000);
		check(client.poll(1000, IDENTITY).teleportButtonHeld, "활성 중에는 눌림이 반영된다");

		// stale=true는 즉시 비활성으로 처리한다 — 버튼 상태도 같이 꺼진다고 봐야 한다.
		client.onMessage(stateJson(1, 3, true, true, true, true, 0, 0, 0, 1), 1000);
		const HandheldControlClient::Frame frame = client.poll(1000, IDENTITY);
		check(!frame.active && !frame.teleportButtonHeld && !frame.heightCycleButtonHeld,
			"stale이면 버튼도 눌리지 않은 것으로 취급한다");
	}

	void testFallback()
	{
		HandheldControlClient client(makeOptions());
		activate(client, 1, 1, 1000);
		client.onMessage(stateJson(1, 2, true, false, false, false, 0, 0, 0, 1), 1000);
		check(client.poll(1750, IDENTITY).active, "750 ms까지는 Handheld가 Camera를 잡는다");
		check(!client.poll(1751, IDENTITY).active, "750 ms를 넘기면 FPS로 돌아간다");

		// 같은 sample_seq여도 stale은 즉시 처리한다.
		client.onMessage(stateJson(1, 3, true, false, false, false, 0, 0, 0, 1), 2000);
		check(client.poll(2000, IDENTITY).active, "새 자세로 다시 활성화된다");
		client.onMessage(stateJson(1, 3, true, false, false, true, 0, 0, 0, 1), 2000);
		check(!client.poll(2000, IDENTITY).active, "같은 sample_seq의 stale=true도 즉시 반영한다");
	}

	// ------------------------------------------------------------------ Fake Backend

	/** 같은 실행 파일 안에서 도는 최소 WebSocket Server. 연결마다 script를 그대로 흘린다. */
	class FakeServer
	{
	public:
		FakeServer()
			: _acceptor(_io, tcp::endpoint(net::ip::make_address("127.0.0.1"), 0))
		{
			_port = _acceptor.local_endpoint().port();
			_thread = std::thread(&FakeServer::run, this);
		}

		~FakeServer()
		{
			_stop = true;
			// blocking accept를 깨우려면 실제로 한 번 붙는 수밖에 없다.
			boost::system::error_code ignored;
			net::io_context waker;
			tcp::socket socket(waker);
			socket.connect(tcp::endpoint(net::ip::make_address("127.0.0.1"), _port), ignored);
			socket.close(ignored);
			if (_thread.joinable()) {
				_thread.join();
			}
			_acceptor.close(ignored);
		}

		unsigned short port() const { return _port; }
		int connections() const { return _connections; }
		bool pathSeen() const { return _pathSeen; }

	private:
		void run()
		{
			while (!_stop) {
				boost::system::error_code error;
				tcp::socket socket(_io);
				_acceptor.accept(socket, error);
				if (error || _stop) {
					return;
				}
				serve(std::move(socket));
			}
		}

		void serve(tcp::socket socket)
		{
			try {
				websocket::stream<tcp::socket> ws(std::move(socket));
				beast::flat_buffer buffer;
				http::request<http::string_body> request;
				http::read(ws.next_layer(), buffer, request);
				if (request.target() != "/handheld/control") {
					return;
				}
				_pathSeen = true;
				ws.accept(request);
				const int index = _connections++;
				ws.text(true);
				for (const std::string& message : script(index)) {
					ws.write(net::buffer(message));
					std::this_thread::sleep_for(std::chrono::milliseconds(5));
				}
				std::this_thread::sleep_for(std::chrono::milliseconds(50));
				boost::system::error_code ignored;
				ws.close(websocket::close_code::normal, ignored);
			} catch (const std::exception&) {
				// 연결이 끊긴 것뿐이다. 다음 연결을 받는다.
			}
		}

		std::vector<std::string> script(int index) const
		{
			std::vector<std::string> messages;
			if (index == 0) {
				messages.push_back("{ this is not json");
				messages.push_back("{\"type\":\"weather_report\"}");
				messages.push_back(stateJson(9, 0xFFFFFFFEu, true, false, false, false, 0, 0, 0, 1));
				messages.push_back(stateJson(9, 0xFFFFFFFFu, true, true, false, false, 0, 0, 0, 1));
				messages.push_back(stateJson(9, 0u, true, false, true, false, 0, 0, 0, 1));
			} else {
				const uint32_t base = uint32_t(index) * 10u;
				messages.push_back(stateJson(9, base, true, true, false, false, 0, 0, 0, 1));
				messages.push_back(stateJson(9, base + 1u, true, false, false, false, 0, 0, 0, 1));
			}
			return messages;
		}

		net::io_context _io;
		tcp::acceptor _acceptor;
		unsigned short _port = 0;
		std::thread _thread;
		std::atomic<bool> _stop{ false };
		std::atomic<int> _connections{ 0 };
		std::atomic<bool> _pathSeen{ false };
	};

	void testWebSocketRoundTrip()
	{
		FakeServer server;
		HandheldControlClient::Options options = makeOptions();
		options.host = "127.0.0.1";
		options.port = server.port();
		HandheldControlClient client(options);

		const std::chrono::steady_clock::time_point deadline =
			std::chrono::steady_clock::now() + std::chrono::seconds(15);
		while (std::chrono::steady_clock::now() < deadline) {
			if (client.stats().connects >= 2 && client.stats().disconnects >= 1
				&& server.connections() >= 2) {
				break;
			}
			std::this_thread::sleep_for(std::chrono::milliseconds(20));
		}
		std::this_thread::sleep_for(std::chrono::milliseconds(300));

		const HandheldControlClient::Stats stats = client.stats();
		check(server.pathSeen(), "요청 경로는 /handheld/control이다");
		check(stats.connects >= 2 && stats.disconnects >= 1, "끊기면 다시 붙는다");
		check(stats.malformed >= 2, "잘못된 Message를 받아도 연결을 끊지 않는다");
		check(stats.poseUpdates >= 3, "재접속 뒤에도 자세를 계속 받는다");
		check(stats.outOfOrderSample == 0, "sample wrap을 out-of-order로 오해하지 않는다");

		const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
		{
			HandheldControlClient::Options dead = makeOptions();
			dead.host = "127.0.0.1";
			dead.port = 1;                 // 아무도 듣지 않는 Port
			HandheldControlClient offline(dead);
			std::this_thread::sleep_for(std::chrono::milliseconds(100));
		}
		const double seconds = std::chrono::duration<double>(
			std::chrono::steady_clock::now() - start).count();
		check(seconds < 2.0, "붙지 못한 상태에서도 2초 안에 끝난다");
	}

	void testShutdownWhileConnected()
	{
		FakeServer server;
		HandheldControlClient::Options options = makeOptions();
		options.host = "127.0.0.1";
		options.port = server.port();
		const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
		{
			HandheldControlClient client(options);
			const std::chrono::steady_clock::time_point deadline =
				std::chrono::steady_clock::now() + std::chrono::seconds(5);
			while (client.stats().connects == 0 && std::chrono::steady_clock::now() < deadline) {
				std::this_thread::sleep_for(std::chrono::milliseconds(10));
			}
		}
		const double seconds = std::chrono::duration<double>(
			std::chrono::steady_clock::now() - start).count();
		check(seconds < 5.0, "연결 중에 종료해도 blocking read에서 멈추지 않는다");
	}

} // namespace

int main()
{
	testMalformed();
	testNormalize();
	testSampleOrdering();
	testSampleWrap();
	testSessionSwitch();
	testTeleportButtonLevel();
	testHeightCycleButtonLevel();
	testButtonsFalseWhenInactive();
	testFallback();
	testWebSocketRoundTrip();
	testShutdownWhileConnected();

	if (g_failures != 0) {
		std::cerr << g_failures << "개 실패" << std::endl;
		return EXIT_FAILURE;
	}
	std::cout << "handheld_control: 전부 통과" << std::endl;
	return EXIT_SUCCESS;
}
