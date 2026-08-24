#include "JpegStreamer.hpp"

#include <core/system/String.hpp>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <fstream>
#include <numeric>

namespace sibr {

	namespace {

		constexpr uint32_t RFJF_MAGIC = 0x52464A46u;   // 'RFJF'
		constexpr uint8_t RFJF_VERSION = 1;
		constexpr uint8_t RFJF_FLAGS_JPEG = 0;
		constexpr size_t RFJF_HEADER_BYTES = 22;
		constexpr size_t RFJF_MAX_PAYLOAD = 8u * 1024u * 1024u;

		double nowSeconds()
		{
			using namespace std::chrono;
			return duration<double>(steady_clock::now().time_since_epoch()).count();
		}

		uint64_t nowMilliseconds()
		{
			using namespace std::chrono;
			return uint64_t(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
		}

		void putBigEndian(uint8_t* target, uint64_t value, int bytes)
		{
			for (int index = bytes - 1; index >= 0; --index) {
				target[index] = uint8_t(value & 0xFFu);
				value >>= 8;
			}
		}

		/** 22-byte RFJF Header. INTERFACE.md §12의 공통 계약이다. */
		void packHeader(uint8_t* header, uint32_t sequence, uint64_t timestampMs, uint32_t length)
		{
			putBigEndian(header + 0, RFJF_MAGIC, 4);
			header[4] = RFJF_VERSION;
			header[5] = RFJF_FLAGS_JPEG;
			putBigEndian(header + 6, sequence, 4);
			putBigEndian(header + 10, timestampMs, 8);
			putBigEndian(header + 18, length, 4);
		}

	} // namespace

	JpegStreamer::JpegStreamer(const Options& options, uint width, uint height)
		: _options(options), _width(width), _height(height)
	{
		if (_options.host.empty()) {
			return;
		}
		_frameBytes = size_t(width) * height * 3;
		glGenBuffers(2, _pbo);
		for (int slot = 0; slot < 2; ++slot) {
			glBindBuffer(GL_PIXEL_PACK_BUFFER, _pbo[slot]);
			glBufferData(GL_PIXEL_PACK_BUFFER, GLsizeiptr(_frameBytes), nullptr, GL_STREAM_READ);
		}
		glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
		CHECK_GL_ERROR;

		_active = true;
		_startSeconds = nowSeconds();
		_worker = std::thread(&JpegStreamer::workerLoop, this);
		SIBR_LOG << "[JpegStreamer] " << width << "x" << height << " -> " << _options.host
			<< ":" << _options.port << " at " << _options.fps << " fps, quality "
			<< _options.quality << std::endl;
	}

	JpegStreamer::~JpegStreamer()
	{
		if (!_active) {
			return;
		}
		_stop = true;
		_wake.notify_all();
		if (_worker.joinable()) {
			_worker.join();
		}
		if (_socket && _socket->is_open()) {
			boost::system::error_code ignored;
			_socket->close(ignored);
		}
		for (int slot = 0; slot < 2; ++slot) {
			if (_fence[slot]) {
				glDeleteSync(_fence[slot]);
			}
		}
		glDeleteBuffers(2, _pbo);
	}

	void JpegStreamer::overlay(const std::string& methodName, float dbmMin, float dbmMax, bool heatmapOn)
	{
		std::lock_guard<std::mutex> lock(_overlayMutex);
		_methodName = methodName;
		_dbmMin = dbmMin;
		_dbmMax = dbmMax;
		_heatmapOn = heatmapOn;
	}

	void JpegStreamer::capture(IRenderTarget& source)
	{
		if (!_active) {
			return;
		}
		const double now = nowSeconds();
		const double period = (_options.fps > 0.f) ? (1.0 / _options.fps) : 0.0;
		// 목표 시각을 누적해야 평균 FPS가 목표에 수렴한다. "직전 capture 이후 period 경과"로
		// 재면 렌더 주기(vsync 16.7ms)의 배수로 반올림돼 12fps 목표가 11.1fps로 떨어진다.
		if (_nextCaptureSeconds <= 0.0) {
			_nextCaptureSeconds = now + period;
		} else if (now < _nextCaptureSeconds) {
			return;
		} else {
			// 한참 밀렸으면 밀린 만큼 몰아 보내지 않고 현재 시각으로 다시 맞춘다.
			_nextCaptureSeconds = std::max(_nextCaptureSeconds + period, now - period);
		}
		if (source.w() != _width || source.h() != _height) {
			SIBR_WRG << "[JpegStreamer] rendertarget이 " << source.w() << "x" << source.h()
				<< "라 송신 크기 " << _width << "x" << _height << "와 다릅니다. 이 Frame은 건너뜁니다."
				<< std::endl;
			return;
		}
		{
			std::lock_guard<std::mutex> lock(_overlayMutex);
			if (_lastCaptureSeconds > 0.0) {
				const float instant = float(1.0 / std::max(now - _lastCaptureSeconds, 1e-6));
				_renderFps = (_renderFps <= 0.f) ? instant : (0.9f * _renderFps + 0.1f * instant);
			}
		}
		_lastCaptureSeconds = now;

		// 이번 Frame 읽기를 걸어 두고, 지난 Frame이 준비됐으면 그것만 가져간다.
		glBindBuffer(GL_PIXEL_PACK_BUFFER, _pbo[_slot]);
		glGetTextureImage(source.handle(), 0, GL_BGR, GL_UNSIGNED_BYTE, GLsizei(_frameBytes), nullptr);
		if (_fence[_slot]) {
			glDeleteSync(_fence[_slot]);
		}
		_fence[_slot] = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);

		const int other = 1 - _slot;
		if (_fence[other] != nullptr) {
			const GLenum status = glClientWaitSync(_fence[other], 0, 0);
			if (status == GL_ALREADY_SIGNALED || status == GL_CONDITION_SATISFIED) {
				glBindBuffer(GL_PIXEL_PACK_BUFFER, _pbo[other]);
				const void* mapped = glMapBufferRange(GL_PIXEL_PACK_BUFFER, 0, GLsizeiptr(_frameBytes), GL_MAP_READ_BIT);
				if (mapped != nullptr) {
					auto frame = std::unique_ptr<Frame>(new Frame());
					frame->bgr.resize(_frameBytes);
					std::memcpy(frame->bgr.data(), mapped, _frameBytes);
					frame->timestampMs = nowMilliseconds();
					frame->sequence = _sequence++;
					glUnmapBuffer(GL_PIXEL_PACK_BUFFER);
					{
						std::lock_guard<std::mutex> lock(_mutex);
						if (_pending) {
							// 최신 Frame만 남긴다. 오래된 Frame을 밀어 보내지 않는다.
							std::lock_guard<std::mutex> metrics(_metricsMutex);
							++_metrics.droppedStale;
						}
						_pending = std::move(frame);
					}
					{
						std::lock_guard<std::mutex> metrics(_metricsMutex);
						++_metrics.captured;
						_metrics.queueDepthMax = std::max<size_t>(_metrics.queueDepthMax, 1);
					}
					_wake.notify_one();
				}
				glDeleteSync(_fence[other]);
				_fence[other] = nullptr;
			}
		}
		glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
		_slot = other;
	}

	void JpegStreamer::drawOverlay(void* bgrMat) const
	{
		cv::Mat& image = *reinterpret_cast<cv::Mat*>(bgrMat);
		std::string method;
		float dbmMin = 0.f, dbmMax = 0.f, fps = 0.f;
		bool heatmapOn = false;
		{
			std::lock_guard<std::mutex> lock(_overlayMutex);
			method = _methodName;
			dbmMin = _dbmMin;
			dbmMax = _dbmMax;
			heatmapOn = _heatmapOn;
			fps = _renderFps;
		}

		const int barWidth = 220, barHeight = 14;
		const int left = 16, top = image.rows - 46;

		// dBm 색상 막대는 Shader와 같은 Viridis를 쓴다.
		cv::Mat ramp(1, barWidth, CV_8UC1);
		for (int column = 0; column < barWidth; ++column) {
			ramp.at<uint8_t>(0, column) = uint8_t(255 * column / std::max(barWidth - 1, 1));
		}
		cv::Mat colored;
		cv::applyColorMap(ramp, colored, cv::COLORMAP_VIRIDIS);
		cv::resize(colored, colored, cv::Size(barWidth, barHeight), 0, 0, cv::INTER_NEAREST);
		if (heatmapOn) {
			colored.copyTo(image(cv::Rect(left, top, barWidth, barHeight)));
			cv::rectangle(image, cv::Rect(left, top, barWidth, barHeight), cv::Scalar(255, 255, 255), 1);
		}

		const cv::Scalar white(255, 255, 255), black(0, 0, 0);
		auto label = [&](const std::string& text, int x, int y, double scale) {
			cv::putText(image, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, scale, black, 3, cv::LINE_AA);
			cv::putText(image, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, scale, white, 1, cv::LINE_AA);
		};
		if (heatmapOn) {
			label(sibr::sprint("%.0f dBm", dbmMin), left, top - 4, 0.4);
			label(sibr::sprint("%.0f dBm", dbmMax), left + barWidth - 60, top - 4, 0.4);
			label(method, left, top + barHeight + 14, 0.45);
		} else {
			label("heatmap off", left, top + barHeight + 14, 0.45);
		}
		label(sibr::sprint("%.1f fps", fps), image.cols - 90, 22, 0.45);
		label("PROVISIONAL", left, 22, 0.5);
	}

	bool JpegStreamer::connect()
	{
		try {
			_socket.reset(new boost::asio::ip::tcp::socket(_io));
			boost::asio::ip::tcp::resolver resolver(_io);
			const auto endpoints = resolver.resolve(_options.host, std::to_string(_options.port));
			boost::asio::connect(*_socket, endpoints);
			_socket->set_option(boost::asio::ip::tcp::no_delay(true));
			std::lock_guard<std::mutex> lock(_metricsMutex);
			++_metrics.reconnects;
			return true;
		} catch (const std::exception& error) {
			_socket.reset();
			SIBR_WRG << "[JpegStreamer] Relay 연결 실패, 1초 뒤 다시 시도합니다: " << error.what() << std::endl;
			return false;
		}
	}

	bool JpegStreamer::sendFrame(const std::vector<uint8_t>& jpeg, uint64_t timestampMs, uint32_t sequence)
	{
		uint8_t header[RFJF_HEADER_BYTES];
		packHeader(header, sequence, timestampMs, uint32_t(jpeg.size()));
		try {
			std::array<boost::asio::const_buffer, 2> buffers = {
				boost::asio::buffer(header, RFJF_HEADER_BYTES),
				boost::asio::buffer(jpeg.data(), jpeg.size())
			};
			boost::asio::write(*_socket, buffers);
			return true;
		} catch (const std::exception& error) {
			SIBR_WRG << "[JpegStreamer] 송신 실패, 재연결합니다: " << error.what() << std::endl;
			boost::system::error_code ignored;
			_socket->close(ignored);
			_socket.reset();
			return false;
		}
	}

	void JpegStreamer::workerLoop()
	{
		const std::vector<int> encodeParameters = { cv::IMWRITE_JPEG_QUALITY, _options.quality };
		std::vector<uint8_t> jpeg;

		while (!_stop) {
			std::unique_ptr<Frame> frame;
			{
				std::unique_lock<std::mutex> lock(_mutex);
				_wake.wait_for(lock, std::chrono::milliseconds(200), [&] { return _stop || _pending != nullptr; });
				frame = std::move(_pending);
			}
			if (_stop) {
				break;
			}
			if (!frame) {
				continue;
			}
			if (!_socket || !_socket->is_open()) {
				if (!connect()) {
					std::lock_guard<std::mutex> lock(_metricsMutex);
					++_metrics.droppedOffline;
					// Viewer 렌더링은 그대로 두고 1초 뒤 다시 붙는다.
					std::this_thread::sleep_for(std::chrono::seconds(1));
					continue;
				}
			}

			const double encodeStart = nowSeconds();
			cv::Mat image(int(_height), int(_width), CV_8UC3, frame->bgr.data());
			cv::flip(image, image, 0);   // OpenGL은 아래에서 위로 읽힌다.
			drawOverlay(&image);
			jpeg.clear();
			cv::imencode(".jpg", image, jpeg, encodeParameters);
			const double encodeMilliseconds = 1000.0 * (nowSeconds() - encodeStart);

			if (jpeg.size() > RFJF_MAX_PAYLOAD) {
				std::lock_guard<std::mutex> lock(_metricsMutex);
				++_metrics.droppedOversize;
				continue;
			}
			const bool ok = sendFrame(jpeg, frame->timestampMs, frame->sequence);
			std::lock_guard<std::mutex> lock(_metricsMutex);
			_encodeMillisecondsTotal += encodeMilliseconds;
			_metrics.jpegBytesMax = std::max(_metrics.jpegBytesMax, jpeg.size());
			if (ok) {
				++_metrics.sent;
				_latencies.push_back(double(nowMilliseconds() - frame->timestampMs));
			} else {
				++_metrics.droppedOffline;
			}
		}
	}

	JpegStreamer::Metrics JpegStreamer::metrics() const
	{
		std::lock_guard<std::mutex> lock(_metricsMutex);
		Metrics result = _metrics;
		result.elapsedSeconds = nowSeconds() - _startSeconds;
		const uint64_t encoded = result.sent + result.droppedOversize;
		result.encodeMillisecondsMean = encoded ? (_encodeMillisecondsTotal / double(encoded)) : 0.0;
		if (!_latencies.empty()) {
			std::vector<double> sorted = _latencies;
			std::sort(sorted.begin(), sorted.end());
			result.captureToSendMillisecondsMean =
				std::accumulate(sorted.begin(), sorted.end(), 0.0) / double(sorted.size());
			const size_t index = std::min(sorted.size() - 1, size_t(0.95 * double(sorted.size())));
			result.captureToSendMillisecondsP95 = sorted[index];
		}
		return result;
	}

	void JpegStreamer::writeMetrics(const std::string& path) const
	{
		const Metrics values = metrics();
		std::ofstream stream(path);
		if (!stream.good()) {
			SIBR_WRG << "[JpegStreamer] 측정값을 쓸 수 없습니다: " << path << std::endl;
			return;
		}
		const double sentFps = values.elapsedSeconds > 0.0 ? double(values.sent) / values.elapsedSeconds : 0.0;
		stream << "{\n"
			<< "  \"schema_version\": \"1.0\",\n"
			<< "  \"width\": " << _width << ",\n"
			<< "  \"height\": " << _height << ",\n"
			<< "  \"target_fps\": " << _options.fps << ",\n"
			<< "  \"jpeg_quality\": " << _options.quality << ",\n"
			<< "  \"elapsed_seconds\": " << values.elapsedSeconds << ",\n"
			<< "  \"frames_captured\": " << values.captured << ",\n"
			<< "  \"frames_sent\": " << values.sent << ",\n"
			<< "  \"sent_fps\": " << sentFps << ",\n"
			<< "  \"dropped_stale\": " << values.droppedStale << ",\n"
			<< "  \"dropped_oversize\": " << values.droppedOversize << ",\n"
			<< "  \"dropped_offline\": " << values.droppedOffline << ",\n"
			<< "  \"connect_successes\": " << values.reconnects << ",\n"
			<< "  \"queue_depth_max\": " << values.queueDepthMax << ",\n"
			<< "  \"jpeg_bytes_max\": " << values.jpegBytesMax << ",\n"
			<< "  \"encode_ms_mean\": " << values.encodeMillisecondsMean << ",\n"
			<< "  \"capture_to_send_ms_mean\": " << values.captureToSendMillisecondsMean << ",\n"
			<< "  \"capture_to_send_ms_p95\": " << values.captureToSendMillisecondsP95 << "\n"
			<< "}\n";
	}

} /*namespace sibr*/
