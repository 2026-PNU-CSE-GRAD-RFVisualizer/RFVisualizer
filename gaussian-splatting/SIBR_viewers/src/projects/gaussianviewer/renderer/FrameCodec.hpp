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
# include <cstring>
# include <string>
# include <vector>

namespace sibr {

	/** 송신 Payload 형식. rgb332-zlib이 기본, jpeg는 예비 경로다. */
	enum class StreamFormat { Rgb332Zlib, Palette256Zlib, Jpeg };

	namespace rfjf {

		constexpr uint32_t MAGIC = 0x52464A46u;   // 'RFJF'
		constexpr uint8_t VERSION = 1;
		constexpr uint8_t FLAGS_JPEG = 0;
		constexpr uint8_t FLAGS_RGB332_ZLIB = 1;
		constexpr uint8_t FLAGS_PALETTE256_ZLIB = 2;
		constexpr size_t HEADER_BYTES = 22;
		constexpr size_t MAX_PAYLOAD = 8u * 1024u * 1024u;

		/** Handheld LCD가 그대로 그리는 고정 크기. */
		constexpr unsigned RGB332_WIDTH = 800;
		constexpr unsigned RGB332_HEIGHT = 480;

		/** 팔레트256 형식. INTERFACE.md §12.3. */
		constexpr size_t PALETTE_ENTRIES = 256;
		constexpr size_t PALETTE_BYTES = PALETTE_ENTRIES * 2;   // entry당 uint16 RGB565
		constexpr size_t PALETTE_INDEX_BYTES = size_t(RGB332_WIDTH) * RGB332_HEIGHT;
		constexpr size_t PALETTE_PAYLOAD_BYTES = PALETTE_BYTES + PALETTE_INDEX_BYTES;
		/** 최근접 팔레트 색을 미리 구해 두는 색 큐브의 한 축 길이. */
		constexpr unsigned PALETTE_CUBE = 32;

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
		switch (format) {
			case StreamFormat::Rgb332Zlib: return rfjf::FLAGS_RGB332_ZLIB;
			case StreamFormat::Palette256Zlib: return rfjf::FLAGS_PALETTE256_ZLIB;
			default: return rfjf::FLAGS_JPEG;
		}
	}

	inline const char* streamFormatName(StreamFormat format)
	{
		switch (format) {
			case StreamFormat::Rgb332Zlib: return "rgb332-zlib";
			case StreamFormat::Palette256Zlib: return "palette256-zlib";
			default: return "jpeg";
		}
	}

	/** 픽셀당 1 byte라 LCD 고정 크기를 요구하는 형식인지. */
	inline bool isIndexedFormat(StreamFormat format)
	{
		return format == StreamFormat::Rgb332Zlib || format == StreamFormat::Palette256Zlib;
	}

	inline bool parseStreamFormat(const std::string& name, StreamFormat& format)
	{
		if (name == "rgb332-zlib") { format = StreamFormat::Rgb332Zlib; return true; }
		if (name == "palette256-zlib") { format = StreamFormat::Palette256Zlib; return true; }
		if (name == "jpeg") { format = StreamFormat::Jpeg; return true; }
		return false;
	}

	/** 시작 전에 막아야 할 조합이면 사람이 읽을 이유를, 문제없으면 빈 문자열을 준다. */
	inline std::string streamOptionError(StreamFormat format, unsigned width, unsigned height)
	{
		if (isIndexedFormat(format)
			&& (width != rfjf::RGB332_WIDTH || height != rfjf::RGB332_HEIGHT)) {
			return std::string("--stream-format ") + streamFormatName(format)
				+ "은 렌더 해상도가 정확히 "
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

	// ------------------------------------------------------------ 팔레트 256색

	/**
	 * RGB332와 똑같은 256색을 담은 팔레트. 워밍업 동안 이걸 실어 보내면
	 * 화면이 `flags=1`과 같아 보이고, 팔레트 계산이 실패해도 이 값으로 계속 돈다.
	 */
	inline void defaultRgb332Palette(uint8_t rgb888[rfjf::PALETTE_ENTRIES * 3])
	{
		for (size_t index = 0; index < rfjf::PALETTE_ENTRIES; ++index) {
			rgb888[index * 3 + 0] = uint8_t((index >> 5) * 255 / 7);
			rgb888[index * 3 + 1] = uint8_t(((index >> 2) & 7) * 255 / 7);
			rgb888[index * 3 + 2] = uint8_t((index & 3) * 255 / 3);
		}
	}

	/** 팔레트를 Wire 형식(entry당 uint16 RGB565 big-endian)으로 편다. */
	inline void packPalette565(const uint8_t rgb888[rfjf::PALETTE_ENTRIES * 3],
		uint8_t out[rfjf::PALETTE_BYTES])
	{
		for (size_t index = 0; index < rfjf::PALETTE_ENTRIES; ++index) {
			const uint16_t value = uint16_t(
				  ((rgb888[index * 3 + 0] >> 3) << 11)
				| ((rgb888[index * 3 + 1] >> 2) << 5)
				|  (rgb888[index * 3 + 2] >> 3));
			out[index * 2 + 0] = uint8_t(value >> 8);
			out[index * 2 + 1] = uint8_t(value & 0xFF);
		}
	}

	/**
	 * 32x32x32 색 큐브의 각 칸에 가장 가까운 팔레트 번호를 미리 채운다.
	 *
	 * 픽셀마다 256색을 뒤지면 10 fps를 못 맞춘다. 시작 시 32768칸을 한 번 채워 두면
	 * 그 뒤로는 픽셀당 테이블 조회 한 번이다.
	 */
	inline void buildPaletteLut(const uint8_t rgb888[rfjf::PALETTE_ENTRIES * 3],
		std::vector<uint8_t>& lut)
	{
		const unsigned cube = rfjf::PALETTE_CUBE;
		lut.resize(size_t(cube) * cube * cube);
		for (unsigned r = 0; r < cube; ++r) {
			for (unsigned g = 0; g < cube; ++g) {
				for (unsigned b = 0; b < cube; ++b) {
					const int red = int(r * 255 / (cube - 1));
					const int green = int(g * 255 / (cube - 1));
					const int blue = int(b * 255 / (cube - 1));
					int best = 0, bestDistance = 1 << 30;
					for (size_t index = 0; index < rfjf::PALETTE_ENTRIES; ++index) {
						const int dr = red - rgb888[index * 3 + 0];
						const int dg = green - rgb888[index * 3 + 1];
						const int db = blue - rgb888[index * 3 + 2];
						const int distance = dr * dr + dg * dg + db * db;
						if (distance < bestDistance) {
							bestDistance = distance;
							best = int(index);
						}
					}
					lut[(size_t(r) << 10) | (size_t(g) << 5) | b] = uint8_t(best);
				}
			}
		}
	}

	/**
	 * BGR Readback을 [512 byte 팔레트][384,000 byte 인덱스] payload로 만든다.
	 * INTERFACE.md §12.3. 팔레트는 Frame마다 들어간다.
	 */
	inline void encodePalette256(const uint8_t* bgr, unsigned width, unsigned height,
		const uint8_t palette565[rfjf::PALETTE_BYTES], const std::vector<uint8_t>& lut,
		std::vector<uint8_t>& out)
	{
		const size_t pixels = size_t(width) * height;
		out.resize(rfjf::PALETTE_BYTES + pixels);
		std::memcpy(out.data(), palette565, rfjf::PALETTE_BYTES);
		uint8_t* indices = out.data() + rfjf::PALETTE_BYTES;
		for (size_t index = 0; index < pixels; ++index) {
			const size_t cell =
				  (size_t(bgr[index * 3 + 2] >> 3) << 10)   // red
				| (size_t(bgr[index * 3 + 1] >> 3) << 5)    // green
				|  size_t(bgr[index * 3 + 0] >> 3);         // blue
			indices[index] = lut[cell];
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
