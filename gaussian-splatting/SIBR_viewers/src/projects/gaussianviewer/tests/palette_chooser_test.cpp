/*
 * RFVisualizer: 팔레트 선정 검증.
 *
 * GL 없이 OpenCV만 링크해 돌린다. Viewer를 실행할 수 없는 환경에서도
 * 팔레트 품질과 결정성을 확인하기 위한 것이다.
 */
#include "projects/gaussianviewer/renderer/PaletteChooser.hpp"
#include "projects/gaussianviewer/renderer/FrameCodec.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

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

	/** 팔레트에서 가장 가까운 색까지의 거리. */
	double nearestError(const uint8_t palette[768], int red, int green, int blue)
	{
		double best = 1e18;
		for (int index = 0; index < 256; ++index) {
			const double dr = red - palette[index * 3 + 0];
			const double dg = green - palette[index * 3 + 1];
			const double db = blue - palette[index * 3 + 2];
			best = std::min(best, std::sqrt(dr * dr + dg * dg + db * db));
		}
		return best;
	}

	/** 지정한 색들을 반복해 채운 BGR Frame. */
	std::vector<uint8_t> frameOfColors(const std::vector<std::array<int, 3>>& colors,
		unsigned width, unsigned height)
	{
		std::vector<uint8_t> bgr(size_t(width) * height * 3);
		for (size_t index = 0; index < size_t(width) * height; ++index) {
			const auto& color = colors[index % colors.size()];
			bgr[index * 3 + 0] = uint8_t(color[2]);   // blue
			bgr[index * 3 + 1] = uint8_t(color[1]);
			bgr[index * 3 + 2] = uint8_t(color[0]);   // red
		}
		return bgr;
	}

	void testTooFewSamples()
	{
		uint8_t palette[768];
		std::memset(palette, 0x5A, sizeof(palette));
		std::vector<uint8_t> tiny(300, 128);
		check(!sibr::choosePalette(tiny, palette), "표본이 모자라면 false");
		check(palette[0] == 0x5A, "실패 시 팔레트를 건드리지 않는다");
	}

	void testSampling()
	{
		const unsigned width = 80, height = 60;
		std::vector<uint8_t> bgr(size_t(width) * height * 3, 7);
		std::vector<uint8_t> samples;
		sibr::appendPaletteSamples(bgr.data(), width, height, 1, samples);
		check(samples.size() == size_t(width) * height * 3, "step 1이면 모든 픽셀");
		samples.clear();
		sibr::appendPaletteSamples(bgr.data(), width, height, 7, samples);
		check(samples.size() / 3 == (size_t(width) * height + 6) / 7, "step 7이면 1/7");
		// 여러 Frame을 이어 붙일 수 있어야 워밍업이 성립한다.
		sibr::appendPaletteSamples(bgr.data(), width, height, 7, samples);
		check(samples.size() / 3 == 2 * ((size_t(width) * height + 6) / 7), "표본이 누적된다");
	}

	void testCapturesSceneColors()
	{
		// 256칸 안에 들어가는 색 수라면 거의 정확히 담겨야 한다.
		std::vector<std::array<int, 3>> colors;
		for (int index = 0; index < 12; ++index) {
			colors.push_back({ 20 + index * 19, 200 - index * 13, 40 + index * 7 });
		}
		const std::vector<uint8_t> bgr = frameOfColors(colors, 200, 120);
		std::vector<uint8_t> samples;
		sibr::appendPaletteSamples(bgr.data(), 200, 120, 1, samples);

		uint8_t palette[768];
		check(sibr::choosePalette(samples, palette), "팔레트 선정 성공");

		double worst = 0.0;
		for (const auto& color : colors) {
			worst = std::max(worst, nearestError(palette, color[0], color[1], color[2]));
		}
		check(worst < 2.0, "장면의 색이 거의 그대로 담긴다");
	}

	void testBeatsRgb332OnGradient()
	{
		// 좁은 색역의 그라데이션. RGB332가 가장 불리하고 팔레트가 가장 유리한 경우다.
		const unsigned width = 160, height = 120;
		std::vector<uint8_t> bgr(size_t(width) * height * 3);
		for (unsigned row = 0; row < height; ++row) {
			for (unsigned column = 0; column < width; ++column) {
				const size_t index = size_t(row) * width + column;
				bgr[index * 3 + 0] = uint8_t(120 + column / 8);   // blue
				bgr[index * 3 + 1] = uint8_t(110 + row / 6);      // green
				bgr[index * 3 + 2] = uint8_t(100 + column / 10);  // red
			}
		}
		std::vector<uint8_t> samples;
		sibr::appendPaletteSamples(bgr.data(), width, height, 1, samples);

		uint8_t chosen[768], fixed[768];
		check(sibr::choosePalette(samples, chosen), "그라데이션 팔레트 선정 성공");
		sibr::defaultRgb332Palette(fixed);

		double chosenTotal = 0.0, fixedTotal = 0.0;
		const size_t pixels = size_t(width) * height;
		for (size_t index = 0; index < pixels; ++index) {
			const int red = bgr[index * 3 + 2], green = bgr[index * 3 + 1], blue = bgr[index * 3 + 0];
			chosenTotal += nearestError(chosen, red, green, blue);
			fixedTotal += nearestError(fixed, red, green, blue);
		}
		std::cout << "      평균 색오차: 팔레트 " << (chosenTotal / double(pixels))
			<< " vs RGB332 " << (fixedTotal / double(pixels)) << std::endl;
		check(chosenTotal < fixedTotal, "팔레트가 RGB332보다 색오차가 작다");
	}

	void testDeterministic()
	{
		std::vector<std::array<int, 3>> colors;
		for (int index = 0; index < 40; ++index) {
			colors.push_back({ (index * 37) % 256, (index * 91) % 256, (index * 53) % 256 });
		}
		const std::vector<uint8_t> bgr = frameOfColors(colors, 120, 100);
		std::vector<uint8_t> samples;
		sibr::appendPaletteSamples(bgr.data(), 120, 100, 1, samples);

		uint8_t first[768], second[768];
		check(sibr::choosePalette(samples, first), "1회차 성공");
		check(sibr::choosePalette(samples, second), "2회차 성공");
		check(std::memcmp(first, second, sizeof(first)) == 0,
			"같은 표본에 같은 팔레트 (색 일렁임 방지)");
	}

} // namespace

int main()
{
	testTooFewSamples();
	testSampling();
	testCapturesSceneColors();
	testBeatsRgb332OnGradient();
	testDeterministic();

	if (g_failures > 0) {
		std::cerr << g_failures << " check(s) failed." << std::endl;
		return 1;
	}
	std::cout << "all palette chooser checks passed." << std::endl;
	return 0;
}
