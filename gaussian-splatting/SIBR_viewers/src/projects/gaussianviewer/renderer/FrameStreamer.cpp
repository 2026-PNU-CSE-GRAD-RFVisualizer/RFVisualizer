#include "FrameStreamer.hpp"

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

	} // namespace

	FrameStreamer::FrameStreamer(const Options& options, uint width, uint height)
		: _options(options), _width(width), _height(height)
	{
		if (_options.host.empty()) {
			return;
		}
		// RGB332은 Handheld가 그대로 그리는 고정 크기라 시작 전에 막는다.
		const std::string optionError = streamOptionError(_options.format, width, height);
		if (!optionError.empty()) {
			SIBR_ERR << "[FrameStreamer] " << optionError;
		}
		_frameBytes = size_t(width) * height * 3;
		if (_options.format == StreamFormat::Palette256Zlib) {
			// 워밍업 동안에는 RGB332와 같은 256색을 쓴다. Frame 0부터 형식상 유효하고
			// 화면도 flags=1과 같아 보인다. 표본이 다 모이면 한 번만 갈아탄다.
			defaultRgb332Palette(_paletteRgb888);
			packPalette565(_paletteRgb888, _palette565);
			buildPaletteLut(_paletteRgb888, _paletteLut);
		}
		glGenBuffers(2, _pbo);
		for (int slot = 0; slot < 2; ++slot) {
			glBindBuffer(GL_PIXEL_PACK_BUFFER, _pbo[slot]);
			glBufferData(GL_PIXEL_PACK_BUFFER, GLsizeiptr(_frameBytes), nullptr, GL_STREAM_READ);
		}
		glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
		CHECK_GL_ERROR;

		_active = true;
		_startSeconds = nowSeconds();
		_worker = std::thread(&FrameStreamer::workerLoop, this);
		SIBR_LOG << "[FrameStreamer] " << width << "x" << height << " -> " << _options.host
			<< ":" << _options.port << " at " << _options.fps << " fps, format "
			<< streamFormatName(_options.format)
			<< (_options.format == StreamFormat::Jpeg
				? sibr::sprint(", quality %d", _options.quality)
				: _options.format == StreamFormat::Palette256Zlib
					? sibr::sprint(", palette warm-up %d frames", _options.paletteFrames)
					: sibr::sprint(", dither %.2f", _options.dither))
			<< std::endl;
	}

	FrameStreamer::~FrameStreamer()
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

	void FrameStreamer::overlay(const std::string& methodName, float dbmMin, float dbmMax, bool heatmapOn)
	{
		std::lock_guard<std::mutex> lock(_overlayMutex);
		_methodName = methodName;
		_dbmMin = dbmMin;
		_dbmMax = dbmMax;
		_heatmapOn = heatmapOn;
	}

	void FrameStreamer::capture(IRenderTarget& source)
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
			SIBR_WRG << "[FrameStreamer] rendertarget이 " << source.w() << "x" << source.h()
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

	void FrameStreamer::drawOverlay(void* bgrMat) const
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

	bool FrameStreamer::connect()
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
			SIBR_WRG << "[FrameStreamer] Relay 연결 실패, 1초 뒤 다시 시도합니다: " << error.what() << std::endl;
			return false;
		}
	}

	bool FrameStreamer::sendFrame(const std::vector<uint8_t>& payload, uint64_t timestampMs, uint32_t sequence)
	{
		uint8_t header[rfjf::HEADER_BYTES];
		packHeader(header, streamFormatFlags(_options.format), sequence, timestampMs, uint32_t(payload.size()));
		try {
			std::array<boost::asio::const_buffer, 2> buffers = {
				boost::asio::buffer(header, rfjf::HEADER_BYTES),
				boost::asio::buffer(payload.data(), payload.size())
			};
			boost::asio::write(*_socket, buffers);
			return true;
		} catch (const std::exception& error) {
			SIBR_WRG << "[FrameStreamer] 송신 실패, 재연결합니다: " << error.what() << std::endl;
			boost::system::error_code ignored;
			_socket->close(ignored);
			_socket.reset();
			return false;
		}
	}

	PaletteScene FrameStreamer::currentScene() const
	{
		std::lock_guard<std::mutex> lock(_overlayMutex);
		PaletteScene scene;
		scene.method = _methodName;
		scene.dbmMin = _dbmMin;
		scene.dbmMax = _dbmMax;
		scene.heatmapOn = _heatmapOn;
		return scene;
	}

	void FrameStreamer::updatePalette(const uint8_t* bgr, unsigned width, unsigned height)
	{
		const double now = nowSeconds();

		// 1) 뒷 Thread에서 돌던 계산이 끝났으면 갈아끼운다. 그동안 송신은 멈추지 않았다.
		if (_paletteState == PaletteState::Computing) {
			if (_paletteJob.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
				return;
			}
			const PaletteResult result = _paletteJob.get();
			if (result.ok) {
				std::memcpy(_paletteRgb888, result.rgb888, sizeof(_paletteRgb888));
				std::memcpy(_palette565, result.packed, sizeof(_palette565));
				_paletteLut = result.lut;
				SIBR_LOG << "[FrameStreamer] 팔레트 256색 갱신 (누적 "
					<< (_metrics.paletteRebuilds + 1) << "회)." << std::endl;
			} else {
				// 실패해도 화면은 죽지 않는다. 쓰던 팔레트를 그대로 둔다.
				SIBR_WRG << "[FrameStreamer] 팔레트 선정 실패. 쓰던 팔레트를 유지합니다." << std::endl;
			}
			_paletteScene = currentScene();
			_paletteAppliedSeconds = now;
			_paletteError = 0.0f;
			_paletteState = PaletteState::Ready;
			std::lock_guard<std::mutex> lock(_metricsMutex);
			_metrics.paletteReady = true;
			++_metrics.paletteRebuilds;
			return;
		}

		// 2) 표본을 모으는 중이면 채우고, 다 차면 계산을 걸어 둔다.
		if (_paletteState == PaletteState::Collecting) {
			appendPaletteSamples(bgr, width, height,
				paletteSampleStep(width, height, _options.paletteFrames), _paletteSamples);
			if (++_paletteFrameCount < std::max(_options.paletteFrames, 1)) {
				return;
			}
			_paletteJob = std::async(std::launch::async,
				[samples = std::move(_paletteSamples)]() {
					PaletteResult result;
					result.ok = choosePalette(samples, result.rgb888);
					if (result.ok) {
						packPalette565(result.rgb888, result.packed);
						buildPaletteLut(result.rgb888, result.lut);
					}
					return result;
				});
			_paletteSamples.clear();
			_paletteFrameCount = 0;
			_paletteState = PaletteState::Computing;
			return;
		}

		// 3) 쓰던 팔레트가 화면에 안 맞게 됐는지 본다.
		const PaletteScene scene = currentScene();
		const bool sceneChanged = paletteSceneChanged(_paletteScene, scene);
		const bool drifted = _paletteError > PALETTE_REFIT_ERROR
			&& (now - _paletteAppliedSeconds) >= PALETTE_REFIT_INTERVAL;
		if (!sceneChanged && !drifted) {
			return;
		}
		SIBR_LOG << "[FrameStreamer] 팔레트를 다시 고릅니다 ("
			<< (sceneChanged ? "장면 설정 변경" : sibr::sprint("적합도 %.1f > %.1f",
				_paletteError, PALETTE_REFIT_ERROR))
			<< ")." << std::endl;
		// 표본을 다시 모으는 동안에도 직전 팔레트를 계속 쓴다. 화면이 한 번 더 튀지 않는다.
		_paletteState = PaletteState::Collecting;
		_paletteFrameCount = 0;
		_paletteSamples.clear();
	}

	/** 상하 반전과 Overlay까지 끝난 BGR Mat을 형식에 맞는 Payload로 만든다. */
	bool FrameStreamer::encode(void* bgrMat, std::vector<uint8_t>& payload)
	{
		cv::Mat& image = *reinterpret_cast<cv::Mat*>(bgrMat);
		if (_options.format == StreamFormat::Jpeg) {
			const std::vector<int> parameters = { cv::IMWRITE_JPEG_QUALITY, _options.quality };
			payload.clear();
			return cv::imencode(".jpg", image, payload, parameters);
		}
		// cv::Mat은 row마다 padding을 둘 수 있으므로 연속 Buffer임을 확인하고 옮긴다.
		if (!image.isContinuous()) {
			image = image.clone();
		}
		if (_options.format == StreamFormat::Palette256Zlib) {
			updatePalette(image.data, unsigned(image.cols), unsigned(image.rows));
			encodePalette256(image.data, unsigned(image.cols), unsigned(image.rows),
				_palette565, _paletteLut, _rgb332);
			// 표본 100픽셀당 1개. LUT 결과를 이미 들고 있어 비교만 하면 된다.
			const float fit = paletteFitError(image.data,
				size_t(image.cols) * image.rows, _rgb332.data() + rfjf::PALETTE_BYTES,
				_paletteRgb888, 97);
			// 한 Frame의 튐으로 재계산이 돌지 않게 완만하게 따라가게 한다.
			_paletteError = (_paletteError <= 0.0f) ? fit : (0.8f * _paletteError + 0.2f * fit);
			{
				std::lock_guard<std::mutex> lock(_metricsMutex);
				_metrics.paletteErrorLast = _paletteError;
			}
		} else {
			bgrToRgb332(image.data, unsigned(image.cols), unsigned(image.rows), _rgb332, _options.dither);
		}
		return zlibCompress(_rgb332, payload);
	}

	/** 5초마다 최근 Frame과 누계를 한 줄로 남긴다. */
	void FrameStreamer::logProgress()
	{
		const double now = nowSeconds();
		if (_nextLogSeconds <= 0.0) {
			_nextLogSeconds = now + 5.0;
			return;
		}
		if (now < _nextLogSeconds) {
			return;
		}
		_nextLogSeconds = now + 5.0;
		const Metrics values = metrics();
		SIBR_LOG << "[FrameStreamer] seq " << values.sequenceLast
			<< " " << streamFormatName(_options.format)
			<< " in " << values.inputBytes << "B -> payload " << values.payloadBytesLast << "B"
			<< sibr::sprint(" encode %.1fms send %.1fms", values.encodeMillisecondsMean, values.sendMillisecondsMean)
			<< " sent " << values.sent
			<< " drop(stale/encode/oversize/offline) " << values.droppedStale
			<< "/" << values.droppedEncode << "/" << values.droppedOversize << "/" << values.droppedOffline
			<< " connects " << values.reconnects << std::endl;
	}

	void FrameStreamer::workerLoop()
	{
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
			const bool encoded = encode(&image, _payload);
			const double encodeMilliseconds = 1000.0 * (nowSeconds() - encodeStart);

			// 인코딩 실패와 과대 Payload는 그 Frame만 버리고 렌더링은 계속한다.
			if (!encoded) {
				SIBR_WRG << "[FrameStreamer] seq " << frame->sequence << " 인코딩 실패, 이 Frame은 버립니다."
					<< std::endl;
				std::lock_guard<std::mutex> lock(_metricsMutex);
				++_metrics.droppedEncode;
				continue;
			}
			if (_payload.size() > rfjf::MAX_PAYLOAD) {
				std::lock_guard<std::mutex> lock(_metricsMutex);
				++_metrics.droppedOversize;
				continue;
			}

			const double sendStart = nowSeconds();
			const bool ok = sendFrame(_payload, frame->timestampMs, frame->sequence);
			const double sendMilliseconds = 1000.0 * (nowSeconds() - sendStart);
			{
				std::lock_guard<std::mutex> lock(_metricsMutex);
				_encodeMillisecondsTotal += encodeMilliseconds;
				_sendMillisecondsTotal += sendMilliseconds;
				_metrics.inputBytes = _frameBytes;
				_metrics.payloadBytesLast = _payload.size();
				_metrics.payloadBytesMax = std::max(_metrics.payloadBytesMax, _payload.size());
				_metrics.sequenceLast = frame->sequence;
				if (ok) {
					++_metrics.sent;
					_latencies.push_back(double(nowMilliseconds() - frame->timestampMs));
				} else {
					++_metrics.droppedOffline;
				}
			}
			logProgress();
		}
	}

	FrameStreamer::Metrics FrameStreamer::metrics() const
	{
		std::lock_guard<std::mutex> lock(_metricsMutex);
		Metrics result = _metrics;
		result.elapsedSeconds = nowSeconds() - _startSeconds;
		const uint64_t attempted = result.sent + result.droppedOffline;
		result.encodeMillisecondsMean = attempted ? (_encodeMillisecondsTotal / double(attempted)) : 0.0;
		result.sendMillisecondsMean = attempted ? (_sendMillisecondsTotal / double(attempted)) : 0.0;
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

	void FrameStreamer::writeMetrics(const std::string& path) const
	{
		const Metrics values = metrics();
		std::ofstream stream(path);
		if (!stream.good()) {
			SIBR_WRG << "[FrameStreamer] 측정값을 쓸 수 없습니다: " << path << std::endl;
			return;
		}
		const double sentFps = values.elapsedSeconds > 0.0 ? double(values.sent) / values.elapsedSeconds : 0.0;
		stream << "{\n"
			<< "  \"schema_version\": \"2.0\",\n"
			<< "  \"format\": \"" << streamFormatName(_options.format) << "\",\n"
			<< "  \"rfjf_flags\": " << int(streamFormatFlags(_options.format)) << ",\n"
			<< "  \"width\": " << _width << ",\n"
			<< "  \"height\": " << _height << ",\n"
			<< "  \"target_fps\": " << _options.fps << ",\n"
			<< "  \"jpeg_quality\": " << _options.quality << ",\n"
			<< "  \"dither\": " << _options.dither << ",\n"
			<< "  \"palette_warmup_frames\": " << _options.paletteFrames << ",\n"
			<< "  \"palette_ready\": " << (values.paletteReady ? "true" : "false") << ",\n"
			<< "  \"palette_rebuilds\": " << values.paletteRebuilds << ",\n"
			<< "  \"palette_fit_error\": " << values.paletteErrorLast << ",\n"
			<< "  \"elapsed_seconds\": " << values.elapsedSeconds << ",\n"
			<< "  \"frames_captured\": " << values.captured << ",\n"
			<< "  \"frames_sent\": " << values.sent << ",\n"
			<< "  \"sent_fps\": " << sentFps << ",\n"
			<< "  \"dropped_stale\": " << values.droppedStale << ",\n"
			<< "  \"dropped_encode\": " << values.droppedEncode << ",\n"
			<< "  \"dropped_oversize\": " << values.droppedOversize << ",\n"
			<< "  \"dropped_offline\": " << values.droppedOffline << ",\n"
			<< "  \"connect_successes\": " << values.reconnects << ",\n"
			<< "  \"queue_depth_max\": " << values.queueDepthMax << ",\n"
			<< "  \"input_bytes\": " << values.inputBytes << ",\n"
			<< "  \"payload_bytes_last\": " << values.payloadBytesLast << ",\n"
			<< "  \"payload_bytes_max\": " << values.payloadBytesMax << ",\n"
			<< "  \"encode_ms_mean\": " << values.encodeMillisecondsMean << ",\n"
			<< "  \"send_ms_mean\": " << values.sendMillisecondsMean << ",\n"
			<< "  \"capture_to_send_ms_mean\": " << values.captureToSendMillisecondsMean << ",\n"
			<< "  \"capture_to_send_ms_p95\": " << values.captureToSendMillisecondsP95 << "\n"
			<< "}\n";
	}

} /*namespace sibr*/
