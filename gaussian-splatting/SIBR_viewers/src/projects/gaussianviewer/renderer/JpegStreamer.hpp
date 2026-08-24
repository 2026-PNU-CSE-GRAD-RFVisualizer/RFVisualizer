/*
 * RFVisualizer: 렌더 결과를 JPEG로 인코딩해 Network image_relay(TCP 9101)로 보낸다.
 *
 * 22-byte big-endian RFJF Header는 INTERFACE.md §12의 공통 계약이며 바꾸지 않는다.
 */
#pragma once

# include "Config.hpp"
# include <core/graphics/RenderTarget.hpp>

# include <boost/asio.hpp>

# include <atomic>
# include <condition_variable>
# include <cstdint>
# include <deque>
# include <memory>
# include <mutex>
# include <string>
# include <thread>
# include <vector>

namespace sibr {

	/**
	 * \class JpegStreamer
	 * \brief PBO 비동기 Readback + Worker Thread JPEG 인코딩 + RFJF TCP 송신.
	 *
	 * Render Thread는 capture()에서 절대 GPU를 기다리지 않는다. CPU Queue는 항상
	 * 최신 Frame 1개만 들고 있으므로 느린 연결에서도 오래된 Frame이 쌓이지 않는다.
	 */
	class SIBR_EXP_ULR_EXPORT JpegStreamer
	{
	public:
		using Ptr = std::shared_ptr<JpegStreamer>;

		struct Options
		{
			std::string host;
			int port = 9101;
			float fps = 12.0f;
			int quality = 80;
		};

		struct Metrics
		{
			uint64_t captured = 0;         ///< PBO에서 CPU로 내려온 Frame 수
			uint64_t sent = 0;             ///< Relay로 실제 보낸 Frame 수
			uint64_t droppedStale = 0;     ///< Queue에서 최신 Frame에 밀려난 수
			uint64_t droppedOversize = 0;  ///< 8 MiB를 넘겨 버린 수
			uint64_t droppedOffline = 0;   ///< 연결이 없어 버린 수
			uint64_t reconnects = 0;      ///< 연결에 성공한 횟수(첫 연결 포함)
			double elapsedSeconds = 0.0;
			double encodeMillisecondsMean = 0.0;
			double captureToSendMillisecondsMean = 0.0;
			double captureToSendMillisecondsP95 = 0.0;
			size_t queueDepthMax = 0;
			size_t jpegBytesMax = 0;
		};

		/** Worker Thread와 연결을 시작한다. host가 비면 아무것도 하지 않는다. */
		JpegStreamer(const Options& options, uint width, uint height);
		~JpegStreamer();

		/** 범례에 찍을 현재 상태를 갱신한다(Render Thread에서 호출). */
		void overlay(const std::string& methodName, float dbmMin, float dbmMax, bool heatmapOn);

		/** 이번 Frame을 비동기로 읽어 온다. GPU를 기다리지 않는다. */
		void capture(IRenderTarget& source);

		bool active() const { return _active; }
		Metrics metrics() const;
		/** 측정값을 JSON 한 개로 남긴다. */
		void writeMetrics(const std::string& path) const;

	private:
		struct Frame
		{
			std::vector<uint8_t> bgr;
			uint64_t timestampMs = 0;
			uint32_t sequence = 0;
		};

		void workerLoop();
		bool connect();
		bool sendFrame(const std::vector<uint8_t>& jpeg, uint64_t timestampMs, uint32_t sequence);
		void drawOverlay(void* bgrMat) const;

		Options _options;
		uint _width = 0, _height = 0;
		size_t _frameBytes = 0;
		bool _active = false;

		GLuint _pbo[2] = { 0, 0 };
		GLsync _fence[2] = { nullptr, nullptr };
		int _slot = 0;
		double _lastCaptureSeconds = 0.0;
		double _nextCaptureSeconds = 0.0;
		uint32_t _sequence = 0;

		mutable std::mutex _mutex;
		std::condition_variable _wake;
		std::unique_ptr<Frame> _pending;   ///< 항상 최신 1개
		std::atomic<bool> _stop{ false };
		std::thread _worker;

		boost::asio::io_context _io;
		std::unique_ptr<boost::asio::ip::tcp::socket> _socket;

		mutable std::mutex _metricsMutex;
		Metrics _metrics;
		std::vector<double> _latencies;
		double _encodeMillisecondsTotal = 0.0;
		double _startSeconds = 0.0;

		mutable std::mutex _overlayMutex;
		std::string _methodName = "Residual IDW";
		float _dbmMin = -110.0f, _dbmMax = -30.0f;
		bool _heatmapOn = true;
		float _renderFps = 0.0f;
	};

} /*namespace sibr*/
