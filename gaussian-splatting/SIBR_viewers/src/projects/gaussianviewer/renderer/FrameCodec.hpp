/*
 * RFVisualizer: RFJF Frame의 Header와 Payload 형식.
 *
 * 22-byte big-endian Header는 INTERFACE.md §12의 공통 계약이며 바꾸지 않는다.
 * GL·OpenCV·SIBR에 의존하지 않으므로 Test가 이 Header 하나만 들고 컴파일한다.
 */
#pragma once

# include <zlib.h>

# include <cstdint>
# include <cstddef>
# include <string>
# include <vector>

namespace sibr {

	/** 송신 Payload 형식. rgb332-zlib이 기본, jpeg는 예비 경로다. */
	enum class StreamFormat { Rgb332Zlib, Jpeg };

	namespace rfjf {

		constexpr uint32_t MAGIC = 0x52464A46u;   // 'RFJF'
		constexpr uint8_t VERSION = 1;
		constexpr uint8_t FLAGS_JPEG = 0;
		constexpr uint8_t FLAGS_RGB332_ZLIB = 1;
		constexpr size_t HEADER_BYTES = 22;
		constexpr size_t MAX_PAYLOAD = 8u * 1024u * 1024u;

		/** Handheld LCD가 그대로 그리는 고정 크기. */
		constexpr unsigned RGB332_WIDTH = 800;
		constexpr unsigned RGB332_HEIGHT = 480;

		/** Bayer Ordered Dithering 기본 강도. 0이면 끈다. */
		constexpr float DITHER_DEFAULT = 0.4f;
		/**
		 * Blue는 2bit(4단계)라 같은 강도를 주면 계단이 커서 패턴이 도드라진다.
		 * 0.75배로 약하게 줘 기본 0.4에서 실효 0.3이 되게 한다.
		 *
		 * ponytail: 패널마다 따로 맞춰야 하면 그때 인자로 뺀다. 지금은 한 값으로 충분하다.
		 */
		constexpr float DITHER_BLUE_SCALE = 0.75f;

		/** 4x4 Bayer 행렬. 좌표는 최종 화면 x,y에 고정하고 Frame마다 바꾸지 않는다. */
		constexpr int BAYER4[16] = {
			 0,  8,  2, 10,
			12,  4, 14,  6,
			 3, 11,  1,  9,
			15,  7, 13,  5
		};

	} // namespace rfjf

	inline void putBigEndian(uint8_t* target, uint64_t value, int bytes)
	{
		for (int index = bytes - 1; index >= 0; --index) {
			target[index] = uint8_t(value & 0xFFu);
			value >>= 8;
		}
	}

	/** 22-byte RFJF Header를 채운다. header는 최소 HEADER_BYTES여야 한다. */
	inline void packHeader(uint8_t* header, uint8_t flags, uint32_t sequence,
		uint64_t timestampMs, uint32_t length)
	{
		putBigEndian(header + 0, rfjf::MAGIC, 4);
		header[4] = rfjf::VERSION;
		header[5] = flags;
		putBigEndian(header + 6, sequence, 4);
		putBigEndian(header + 10, timestampMs, 8);
		putBigEndian(header + 18, length, 4);
	}

	inline uint8_t streamFormatFlags(StreamFormat format)
	{
		return format == StreamFormat::Rgb332Zlib ? rfjf::FLAGS_RGB332_ZLIB : rfjf::FLAGS_JPEG;
	}

	inline const char* streamFormatName(StreamFormat format)
	{
		return format == StreamFormat::Rgb332Zlib ? "rgb332-zlib" : "jpeg";
	}

	inline bool parseStreamFormat(const std::string& name, StreamFormat& format)
	{
		if (name == "rgb332-zlib") { format = StreamFormat::Rgb332Zlib; return true; }
		if (name == "jpeg") { format = StreamFormat::Jpeg; return true; }
		return false;
	}

	/** 시작 전에 막아야 할 조합이면 사람이 읽을 이유를, 문제없으면 빈 문자열을 준다. */
	inline std::string streamOptionError(StreamFormat format, unsigned width, unsigned height)
	{
		if (format == StreamFormat::Rgb332Zlib
			&& (width != rfjf::RGB332_WIDTH || height != rfjf::RGB332_HEIGHT)) {
			return "--stream-format rgb332-zlib은 렌더 해상도가 정확히 "
				+ std::to_string(rfjf::RGB332_WIDTH) + "x" + std::to_string(rfjf::RGB332_HEIGHT)
				+ "여야 합니다. 지금은 " + std::to_string(width) + "x" + std::to_string(height)
				+ "입니다. --rendering-size 800 480을 주거나 --stream-format jpeg을 쓰세요.";
		}
		return std::string();
	}

	/** 한 채널을 levels 단계로 반올림한다. offset은 단계 단위 디더링 값이다. */
	inline uint8_t quantizeChannel(float value, int levels, float offset)
	{
		const float top = float(levels - 1);
		float scaled = value * top / 255.0f + offset;
		if (scaled < 0.0f) {
			scaled = 0.0f;
		} else if (scaled > top) {
			scaled = top;
		}
		return uint8_t(scaled + 0.5f);   // 여기서는 scaled >= 0이라 잘라도 반올림이다
	}

	/**
	 * Readback Buffer(BGR 3byte/pixel)를 픽셀당 1byte RRRGGGBB로 옮긴다.
	 * Buffer는 BGR 순서이므로 Red는 offset 2, Blue는 offset 0이다.
	 *
	 * dither가 0보다 크면 고정 4x4 Bayer Ordered Dithering을 건다. 위아래 반전이
	 * 끝난 최종 화면에 적용해야 Bayer 좌표가 LCD의 x,y와 일치한다. Frame마다
	 * 패턴을 바꾸지 않으므로 움직여도 반짝이지 않는다.
	 */
	inline void bgrToRgb332(const uint8_t* bgr, unsigned width, unsigned height,
		std::vector<uint8_t>& out, float dither = 0.0f)
	{
		out.resize(size_t(width) * height);
		for (unsigned row = 0; row < height; ++row) {
			for (unsigned column = 0; column < width; ++column) {
				const size_t index = size_t(row) * width + column;
				const uint8_t blue = bgr[index * 3 + 0];
				const uint8_t green = bgr[index * 3 + 1];
				const uint8_t red = bgr[index * 3 + 2];

				float offset = 0.0f;
				if (dither > 0.0f) {
					// 평균이 0이 되게 중심을 맞춘다. 안 그러면 화면 전체가 어두워진다.
					const float cell =
						(float(rfjf::BAYER4[(row & 3u) * 4 + (column & 3u)]) + 0.5f) / 16.0f - 0.5f;
					offset = cell * dither;
				}
				out[index] = uint8_t(
					  (quantizeChannel(float(red), 8, offset) << 5)
					| (quantizeChannel(float(green), 8, offset) << 2)
					|  quantizeChannel(float(blue), 4, offset * rfjf::DITHER_BLUE_SCALE));
			}
		}
	}

	/** 표준 zlib Stream으로 압축한다. out은 재사용 Buffer라 capacity를 유지한다. */
	inline bool zlibCompress(const std::vector<uint8_t>& input, std::vector<uint8_t>& out)
	{
		uLongf size = compressBound(uLong(input.size()));
		out.resize(size);
		// Handheld는 10 fps마다 inflate해야 하므로 압축률보다 속도를 택한다.
		if (compress2(out.data(), &size, input.data(), uLong(input.size()), Z_BEST_SPEED) != Z_OK) {
			out.clear();
			return false;
		}
		out.resize(size);
		return true;
	}

} /*namespace sibr*/
