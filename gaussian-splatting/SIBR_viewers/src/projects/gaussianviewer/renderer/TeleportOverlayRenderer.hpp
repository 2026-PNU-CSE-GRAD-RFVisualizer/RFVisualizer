/*
 * RFVisualizer: 텔레포트 포물선과 착지 마커만 그리는 최소 Renderer.
 *
 * 범용 debug renderer가 아니다. Gaussian/RF가 이미 그려진 화면 위에 덧그리므로 destination을
 * 절대 clear하지 않고, 항상 보이도록 Depth Test만 잠시 끈 뒤 원래 GL 상태로 되돌린다.
 * (core의 ColoredMeshRenderer는 target을 clear해서 여기 쓸 수 없다.)
 */
#pragma once

# include "Config.hpp"
# include "ArcTeleportController.hpp"

# include <core/graphics/Camera.hpp>
# include <core/graphics/RenderTarget.hpp>
# include <core/graphics/Shader.hpp>

namespace sibr {

	/**
	 * \class TeleportOverlayRenderer
	 * \brief 조준 중인 포물선(초록/빨강)과 착지 마커를 화면 위에 덧그린다.
	 */
	class SIBR_EXP_ULR_EXPORT TeleportOverlayRenderer
	{
	public:
		TeleportOverlayRenderer();
		~TeleportOverlayRenderer();

		/** 조준 중이 아니면 아무것도 하지 않는다(Buffer 갱신도 Draw도 없다).
		\param preview 이번 Frame에 그릴 것
		\param eye 현재 Camera
		\param dst Gaussian/RF가 이미 그려진 대상 */
		void process(const TeleportPreview& preview, const sibr::Camera& eye, sibr::IRenderTarget& dst);

	private:
		sibr::GLShader _shader;
		sibr::GLParameter _mvp, _color;
		GLuint _vertexArray = 0, _vertexBuffer = 0;
		size_t _bufferCapacity = 0;   ///< 지금까지 잡아 둔 vertex 수
	};

} /*namespace sibr*/
