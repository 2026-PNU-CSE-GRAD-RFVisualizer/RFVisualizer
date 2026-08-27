/*
 * RFVisualizer: 장면에서 256색 팔레트를 고른다.
 *
 * OpenCV만 쓰고 GL·SIBR에는 의존하지 않는다. Viewer를 띄우지 않고도
 * `SIBR_palette_chooser_test`로 검증할 수 있어야 하기 때문이다.
 * 형식(패킹·LUT·인코딩)은 FrameCodec.hpp에 있고 여기는 색 선정만 한다.
 */
#pragma once

# include <cmath>
# include <cstdint>
# include <string>
# include <vector>

namespace sibr {

	/**
	 * 팔레트를 고를 때의 장면 조건.
	 *
	 * 히트맵을 켜거나 dBm 범위를 바꾸면 화면에 없던 색이 갑자기 등장한다. 그때 이전
	 * 팔레트를 그대로 쓰면 그 색을 표현할 칸이 없다. 실측에서 히트맵을 나중에 켰을 때
	 * 히트맵 영역의 평균 색오차가 dE 1.87에서 12.02로 뛰었다.
	 */
	struct PaletteScene
	{
		std::string method;
		float dbmMin = 0.0f, dbmMax = 0.0f;
		bool heatmapOn = false;
	};

	/** 팔레트를 다시 골라야 하는 변화인지. dBm은 UI 조작이라 미세한 차이는 무시한다. */
	inline bool paletteSceneChanged(const PaletteScene& chosen, const PaletteScene& current)
	{
		return chosen.heatmapOn != current.heatmapOn
			|| chosen.method != current.method
			|| std::fabs(chosen.dbmMin - current.dbmMin) > 0.01f
			|| std::fabs(chosen.dbmMax - current.dbmMax) > 0.01f;
	}

	/**
	 * 팔레트를 다시 골라야 한다고 볼 적합도 오차(RGB 거리 평균).
	 *
	 * 실측: 팔레트를 고른 그 화면 2.7, 살짝 이동 5.5, 중간 이동 24.2, 많이 이동 54.0.
	 * 12는 정상 범위와 충분히 떨어져 있으면서 실제 드리프트는 확실히 잡는 값이다.
	 */
	constexpr float PALETTE_REFIT_ERROR = 12.0f;

	/** 다시 고르는 최소 간격(초). 걸어 다녀도 이보다 자주 돌지 않는다. */
	constexpr double PALETTE_REFIT_INTERVAL = 3.0;

	/** kmeans에 넣기 전 최소 표본 수. 256개 군집을 나누려면 이보다는 많아야 한다. */
	constexpr size_t PALETTE_MIN_SAMPLES = 4096;

	/**
	 * 워밍업 전체에서 모을 표본 수의 목표치.
	 *
	 * kmeans는 표본 수에 비례해 느려진다. 800x480을 7픽셀마다 훑으면 Frame당 5만 개가
	 * 쌓여 20 Frame이면 백만 개가 넘고, 그만큼 Worker가 한 번에 멈춘다. 색 분포를 잡는
	 * 데는 이 정도면 충분하다.
	 */
	constexpr size_t PALETTE_TARGET_SAMPLES = 200000;

	/** 목표 표본 수에 맞는 픽셀 건너뛰기 간격. */
	inline unsigned paletteSampleStep(unsigned width, unsigned height, int frames)
	{
		const size_t total = size_t(width) * height * size_t(frames < 1 ? 1 : frames);
		const size_t step = total / PALETTE_TARGET_SAMPLES;
		return unsigned(step < 1 ? 1 : step);
	}

	/**
	 * BGR Frame에서 step 픽셀마다 하나씩 표본을 모아 out 뒤에 붙인다.
	 * 800x480을 step 7로 훑으면 Frame당 약 54,000색이 쌓인다.
	 */
	void appendPaletteSamples(const uint8_t* bgr, unsigned width, unsigned height,
		unsigned step, std::vector<uint8_t>& out);

	/**
	 * 표본에서 256색을 고른다. 표본이 모자라거나 kmeans가 실패하면 false를 주고
	 * rgb888은 건드리지 않는다. 호출 측은 그때 기본 RGB332 팔레트를 유지한다.
	 *
	 * 같은 표본에 같은 결과가 나오도록 RNG를 고정한다. 팔레트가 흔들리면
	 * 화면 색이 프레임마다 일렁인다.
	 */
	bool choosePalette(const std::vector<uint8_t>& bgrSamples, uint8_t rgb888[256 * 3]);

} /*namespace sibr*/
