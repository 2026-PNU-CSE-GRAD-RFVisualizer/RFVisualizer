#include "TeleportOverlayRenderer.hpp"

#include <core/graphics/Shader.hpp>
#include <core/system/String.hpp>

#include <vector>

namespace sibr {

	TeleportOverlayRenderer::TeleportOverlayRenderer()
	{
		_shader.init("TeleportOverlay",
			sibr::loadFile(sibr::getShadersDirectory("gaussian") + "/teleport_overlay.vert"),
			sibr::loadFile(sibr::getShadersDirectory("gaussian") + "/teleport_overlay.frag"));
		_mvp.init(_shader, "MVP");
		_color.init(_shader, "overlayColor");

		glGenVertexArrays(1, &_vertexArray);
		glGenBuffers(1, &_vertexBuffer);
		glBindVertexArray(_vertexArray);
		glBindBuffer(GL_ARRAY_BUFFER, _vertexBuffer);
		glEnableVertexAttribArray(0);
		glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
		glBindVertexArray(0);
		glBindBuffer(GL_ARRAY_BUFFER, 0);
		CHECK_GL_ERROR;
	}

	TeleportOverlayRenderer::~TeleportOverlayRenderer()
	{
		if (_vertexBuffer != 0) {
			glDeleteBuffers(1, &_vertexBuffer);
		}
		if (_vertexArray != 0) {
			glDeleteVertexArrays(1, &_vertexArray);
		}
	}

	void TeleportOverlayRenderer::process(const TeleportPreview& preview, const sibr::Camera& eye,
		sibr::IRenderTarget& dst)
	{
		// 조준 중이 아니면 Buffer도 건드리지 않고 Draw도 하지 않는다.
		if (!preview.aiming || preview.scenePoints.size() < 2) {
			return;
		}

		// 호출한 쪽의 GL 상태를 그대로 돌려주기 위해 바꿀 것만 미리 읽어 둔다.
		GLint previousFramebuffer = 0, previousProgram = 0, previousVertexArray = 0, previousBuffer = 0;
		GLint previousViewport[4] = { 0, 0, 0, 0 };
		GLfloat previousLineWidth = 1.f;
		glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previousFramebuffer);
		glGetIntegerv(GL_CURRENT_PROGRAM, &previousProgram);
		glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &previousVertexArray);
		glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &previousBuffer);
		glGetIntegerv(GL_VIEWPORT, previousViewport);
		glGetFloatv(GL_LINE_WIDTH, &previousLineWidth);
		const GLboolean depthWasEnabled = glIsEnabled(GL_DEPTH_TEST);
		const GLboolean blendWasEnabled = glIsEnabled(GL_BLEND);

		std::vector<sibr::Vector3f> vertices = preview.scenePoints;
		const size_t arcCount = vertices.size();
		vertices.insert(vertices.end(), preview.markerPoints.begin(), preview.markerPoints.end());

		glBindVertexArray(_vertexArray);
		glBindBuffer(GL_ARRAY_BUFFER, _vertexBuffer);
		const size_t bytes = vertices.size() * 3 * sizeof(float);
		if (vertices.size() > _bufferCapacity) {
			glBufferData(GL_ARRAY_BUFFER, GLsizeiptr(bytes), vertices.data(), GL_DYNAMIC_DRAW);
			_bufferCapacity = vertices.size();
		} else {
			glBufferSubData(GL_ARRAY_BUFFER, 0, GLsizeiptr(bytes), vertices.data());
		}

		// Gaussian/RF 결과 위에 덧그린다. clear하지 않고, 벽 뒤라도 보이게 Depth만 잠시 끈다.
		dst.bind();
		glDisable(GL_DEPTH_TEST);
		glDisable(GL_BLEND);
		glLineWidth(2.f);

		_shader.begin();
		_mvp.set(eye.viewproj());
		// 유효하면 초록, 무효하면 빨강. 같은 geometry에 색만 바뀐다.
		_color.set(preview.valid ? sibr::Vector3f(0.15f, 0.9f, 0.25f)
			: sibr::Vector3f(0.95f, 0.2f, 0.2f));

		glDrawArrays(GL_LINE_STRIP, 0, GLsizei(arcCount));
		if (!preview.markerPoints.empty()) {
			glDrawArrays(preview.markerIsRing ? GL_LINE_LOOP : GL_LINES,
				GLsizei(arcCount), GLsizei(preview.markerPoints.size()));
		}
		_shader.end();

		// 호출 전 상태로 되돌린다. 이 다음에 오는 것은 FrameStreamer capture다.
		glLineWidth(previousLineWidth);
		if (depthWasEnabled) { glEnable(GL_DEPTH_TEST); } else { glDisable(GL_DEPTH_TEST); }
		if (blendWasEnabled) { glEnable(GL_BLEND); } else { glDisable(GL_BLEND); }
		glBindBuffer(GL_ARRAY_BUFFER, GLuint(previousBuffer));
		glBindVertexArray(GLuint(previousVertexArray));
		glUseProgram(GLuint(previousProgram));
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, GLuint(previousFramebuffer));
		glViewport(previousViewport[0], previousViewport[1], previousViewport[2], previousViewport[3]);
		CHECK_GL_ERROR;
	}

} /*namespace sibr*/
