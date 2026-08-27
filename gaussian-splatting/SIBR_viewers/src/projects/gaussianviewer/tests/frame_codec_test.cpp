/*
 * RFVisualizer: RFJF Frame 형식 변환 검증.
 *
 * 새 Test Framework를 넣지 않는다. assertion과 CTest만 쓴다.
 * FrameCodec.hpp는 GL·OpenCV에 의존하지 않으므로 Header 하나만 들고 컴파일한다.
 */
#include "projects/gaussianviewer/renderer/FrameCodec.hpp"

#include <cmath>
#include <cstring>
#include <iostream>
#include <set>
#include <string>
#include <vector>

using sibr::StreamFormat;

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

	/** OpenGL Readback과 같은 BGR 한 픽셀. */
	uint8_t convertOne(uint8_t blue, uint8_t green, uint8_t red)
	{
		const uint8_t bgr[3] = { blue, green, red };
		std::vector<uint8_t> out;
		sibr::bgrToRgb332(bgr, 1, 1, out);
		return out.size() == 1 ? out[0] : 0;
	}

	void testChannelOrder()
	{
		// BGR Buffer를 RGB로 정확히 해석해야 한다. 순서를 뒤집으면 Red와 Blue가 바뀐다.
		check(convertOne(0, 0, 255) == 0xE0, "red -> 0xE0");
		check(convertOne(0, 255, 0) == 0x1C, "green -> 0x1C");
		check(convertOne(255, 0, 0) == 0x03, "blue -> 0x03");
		check(convertOne(255, 255, 255) == 0xFF, "white -> 0xFF");
		check(convertOne(0, 0, 0) == 0x00, "black -> 0x00");
	}

	void testFullFrameRoundTrip()
	{
		const size_t width = sibr::rfjf::RGB332_WIDTH, height = sibr::rfjf::RGB332_HEIGHT;
		const size_t pixels = width * height;

		// row마다 다른 색을 넣어 순서가 밀리면 바로 드러나게 한다.
		std::vector<uint8_t> bgr(pixels * 3);
		for (size_t row = 0; row < height; ++row) {
			for (size_t column = 0; column < width; ++column) {
				uint8_t* pixel = bgr.data() + (row * width + column) * 3;
				pixel[0] = uint8_t(column);          // blue
				pixel[1] = uint8_t(row);             // green
				pixel[2] = uint8_t(row + column);    // red
			}
		}

		std::vector<uint8_t> rgb332;
		sibr::bgrToRgb332(bgr.data(), unsigned(width), unsigned(height), rgb332);
		check(rgb332.size() == 384000, "rgb332 payload is 384000 bytes");

		std::vector<uint8_t> compressed;
		check(sibr::zlibCompress(rgb332, compressed), "zlib compress succeeds");
		check(!compressed.empty() && compressed.size() < rgb332.size(), "compressed is smaller than raw");

		// Host 수신 도구가 하는 그대로 표준 zlib으로 되돌린다.
		std::vector<uint8_t> restored(pixels + 16, 0xAA);
		uLongf restoredSize = uLongf(restored.size());
		check(uncompress(restored.data(), &restoredSize, compressed.data(), uLong(compressed.size())) == Z_OK,
			"zlib uncompress succeeds");
		check(restoredSize == 384000, "inflated size is exactly 384000 bytes");
		check(std::memcmp(restored.data(), rgb332.data(), rgb332.size()) == 0, "row-major order preserved");
	}

	uint64_t readBigEndian(const uint8_t* source, int bytes)
	{
		uint64_t value = 0;
		for (int index = 0; index < bytes; ++index) {
			value = (value << 8) | source[index];
		}
		return value;
	}

	void testHeader()
	{
		check(sibr::rfjf::HEADER_BYTES == 22, "header is 22 bytes");

		uint8_t header[sibr::rfjf::HEADER_BYTES];
		sibr::packHeader(header, sibr::rfjf::FLAGS_RGB332_ZLIB, 0x01020304u, 0x0102030405060708ull, 384000u);
		check(readBigEndian(header + 0, 4) == 0x52464A46ull, "magic is 'RFJF'");
		check(header[4] == 1, "version is 1");
		check(header[5] == 1, "flags is 1 for rgb332-zlib");
		check(readBigEndian(header + 6, 4) == 0x01020304ull, "seq at offset 6 big-endian");
		check(readBigEndian(header + 10, 8) == 0x0102030405060708ull, "ts_ms at offset 10 big-endian");
		check(readBigEndian(header + 18, 4) == 384000ull, "length at offset 18 big-endian");

		sibr::packHeader(header, sibr::rfjf::FLAGS_JPEG, 0, 0, 0);
		check(header[5] == 0, "flags is 0 for jpeg");
	}

	void testOptionValidation()
	{
		StreamFormat format = StreamFormat::Jpeg;
		check(sibr::parseStreamFormat("rgb332-zlib", format) && format == StreamFormat::Rgb332Zlib,
			"rgb332-zlib parses");
		check(sibr::parseStreamFormat("jpeg", format) && format == StreamFormat::Jpeg, "jpeg parses");
		check(!sibr::parseStreamFormat("png", format), "unknown format is rejected");
		check(!sibr::parseStreamFormat("", format), "empty format is rejected");

		// RGB332은 Handheld LCD가 그대로 그리는 고정 크기라 다른 해상도를 시작 전에 막는다.
		check(sibr::streamOptionError(StreamFormat::Rgb332Zlib, 800, 480).empty(), "rgb332 accepts 800x480");
		check(!sibr::streamOptionError(StreamFormat::Rgb332Zlib, 1200, 800).empty(), "rgb332 rejects 1200x800");
		check(!sibr::streamOptionError(StreamFormat::Rgb332Zlib, 800, 481).empty(), "rgb332 rejects 800x481");
		check(sibr::streamOptionError(StreamFormat::Jpeg, 1200, 800).empty(), "jpeg accepts any size");
	}

	/** 한 색으로 꽉 찬 BGR Frame. */
	std::vector<uint8_t> flatFrame(size_t width, size_t height, uint8_t blue, uint8_t green, uint8_t red)
	{
		std::vector<uint8_t> bgr(width * height * 3);
		for (size_t index = 0; index < width * height; ++index) {
			bgr[index * 3 + 0] = blue;
			bgr[index * 3 + 1] = green;
			bgr[index * 3 + 2] = red;
		}
		return bgr;
	}

	void testDithering()
	{
		const size_t width = 64, height = 64, pixels = width * height;
		// 91은 red 3bit로 2.498단계다. 반올림 경계에 걸쳐 있어 디더링이 실제로 작동한다.
		const uint8_t level = 91;
		const std::vector<uint8_t> bgr = flatFrame(width, height, level, level, level);

		std::vector<uint8_t> plain, dithered;
		sibr::bgrToRgb332(bgr.data(), width, height, plain, 0.0f);
		sibr::bgrToRgb332(bgr.data(), width, height, dithered, sibr::rfjf::DITHER_DEFAULT);

		// 디더링을 끄면 단색은 한 값으로만 나온다.
		bool plainUniform = true;
		for (size_t index = 1; index < pixels; ++index) {
			plainUniform = plainUniform && (plain[index] == plain[0]);
		}
		check(plainUniform, "dither off: 단색은 한 값으로만 양자화된다");

		// 켜면 이웃 단계가 섞여 계조를 만든다.
		std::set<uint8_t> values(dithered.begin(), dithered.end());
		check(values.size() > 1, "dither on: 단색이 여러 단계로 흩어진다");

		// 흩뿌려도 평균 밝기는 원본에 더 가까워야 한다. 아니면 화면이 어두워지거나 밝아진다.
		auto meanRed = [&](const std::vector<uint8_t>& packed) {
			double total = 0.0;
			for (uint8_t value : packed) {
				total += double((value >> 5) * 255 / 7);
			}
			return total / double(packed.size());
		};
		const double plainError = std::fabs(meanRed(plain) - double(level));
		const double ditherError = std::fabs(meanRed(dithered) - double(level));
		check(ditherError < plainError, "dither on: 평균 밝기 오차가 줄어든다");

		// 같은 입력은 언제나 같은 출력이어야 한다. 아니면 정지 화면이 반짝인다.
		std::vector<uint8_t> again;
		sibr::bgrToRgb332(bgr.data(), width, height, again, sibr::rfjf::DITHER_DEFAULT);
		check(again == dithered, "dither on: 같은 입력은 항상 같은 출력(패턴 고정)");

		// 순수 검정·흰색에는 잡음이 끼면 안 된다.
		const std::vector<uint8_t> black = flatFrame(width, height, 0, 0, 0);
		const std::vector<uint8_t> white = flatFrame(width, height, 255, 255, 255);
		std::vector<uint8_t> blackOut, whiteOut;
		sibr::bgrToRgb332(black.data(), width, height, blackOut, sibr::rfjf::DITHER_DEFAULT);
		sibr::bgrToRgb332(white.data(), width, height, whiteOut, sibr::rfjf::DITHER_DEFAULT);
		check(std::set<uint8_t>(blackOut.begin(), blackOut.end()) == std::set<uint8_t>{ 0x00 },
			"dither on: 순수 검정은 그대로 0x00");
		check(std::set<uint8_t>(whiteOut.begin(), whiteOut.end()) == std::set<uint8_t>{ 0xFF },
			"dither on: 순수 흰색은 그대로 0xFF");

		// 강도 0.4는 경계 근처에서만 흩뿌린다. 이미 정확히 표현되는 값은 건드리지 않으므로
		// 평평한 면에 불필요한 잡음이 끼지 않는다.
		const std::vector<uint8_t> settled = flatFrame(width, height, 100, 100, 100);
		std::vector<uint8_t> settledOut;
		sibr::bgrToRgb332(settled.data(), width, height, settledOut, sibr::rfjf::DITHER_DEFAULT);
		check(std::set<uint8_t>(settledOut.begin(), settledOut.end()).size() == 1,
			"dither on: 경계에서 먼 값은 흩뿌리지 않는다");

		// 강도를 올리면 흩뿌리는 범위가 넓어진다.
		std::vector<uint8_t> strong;
		sibr::bgrToRgb332(settled.data(), width, height, strong, 1.0f);
		check(std::set<uint8_t>(strong.begin(), strong.end()).size() > 1,
			"강도 1.0은 같은 값도 흩뿌린다");

		// 크기와 압축 계약은 강도와 무관하게 그대로다.
		std::vector<uint8_t> full, payload;
		const std::vector<uint8_t> frame = flatFrame(sibr::rfjf::RGB332_WIDTH, sibr::rfjf::RGB332_HEIGHT,
			level, level, level);
		sibr::bgrToRgb332(frame.data(), sibr::rfjf::RGB332_WIDTH, sibr::rfjf::RGB332_HEIGHT, full,
			sibr::rfjf::DITHER_DEFAULT);
		check(full.size() == 384000, "dither on: payload는 여전히 384000 bytes");
		check(sibr::zlibCompress(full, payload), "dither on: zlib 압축 성공");
	}

} // namespace

int main()
{
	testChannelOrder();
	testFullFrameRoundTrip();
	testHeader();
	testOptionValidation();
	testDithering();

	if (g_failures > 0) {
		std::cerr << g_failures << " check(s) failed." << std::endl;
		return 1;
	}
	std::cout << "all frame codec checks passed." << std::endl;
	return 0;
}
