#include "PaletteChooser.hpp"

#include <opencv2/core.hpp>

#include <algorithm>

namespace sibr {

	namespace {
		/** 표본 순서와 무관하게 같은 팔레트가 나오도록 고정한다. */
		constexpr uint64_t PALETTE_RNG_SEED = 0x5F3759DFull;
		constexpr int PALETTE_ENTRIES = 256;
	}

	void appendPaletteSamples(const uint8_t* bgr, unsigned width, unsigned height,
		unsigned step, std::vector<uint8_t>& out)
	{
		if (bgr == nullptr || width == 0 || height == 0) {
			return;
		}
		const size_t pixels = size_t(width) * height;
		const size_t stride = std::max<size_t>(step, 1);
		out.reserve(out.size() + (pixels / stride + 1) * 3);
		for (size_t index = 0; index < pixels; index += stride) {
			out.push_back(bgr[index * 3 + 0]);
			out.push_back(bgr[index * 3 + 1]);
			out.push_back(bgr[index * 3 + 2]);
		}
	}

	bool choosePalette(const std::vector<uint8_t>& bgrSamples, uint8_t rgb888[PALETTE_ENTRIES * 3])
	{
		const size_t count = bgrSamples.size() / 3;
		if (count < PALETTE_MIN_SAMPLES) {
			return false;
		}

		cv::Mat samples(int(count), 3, CV_32F);
		for (size_t index = 0; index < count; ++index) {
			float* row = samples.ptr<float>(int(index));
			row[0] = float(bgrSamples[index * 3 + 2]);   // red
			row[1] = float(bgrSamples[index * 3 + 1]);   // green
			row[2] = float(bgrSamples[index * 3 + 0]);   // blue
		}

		cv::Mat labels, centers;
		try {
			cv::theRNG().state = PALETTE_RNG_SEED;
			const cv::TermCriteria criteria(cv::TermCriteria::EPS + cv::TermCriteria::MAX_ITER, 12, 1.0);
			cv::kmeans(samples, PALETTE_ENTRIES, labels, criteria, 1, cv::KMEANS_PP_CENTERS, centers);
		} catch (const cv::Exception&) {
			return false;
		}
		if (centers.rows != PALETTE_ENTRIES || centers.cols != 3) {
			return false;
		}

		for (int index = 0; index < PALETTE_ENTRIES; ++index) {
			const float* center = centers.ptr<float>(index);
			for (int channel = 0; channel < 3; ++channel) {
				const float value = center[channel];
				rgb888[index * 3 + channel] =
					uint8_t(std::min(255.0f, std::max(0.0f, value)) + 0.5f);
			}
		}
		return true;
	}

} /*namespace sibr*/
