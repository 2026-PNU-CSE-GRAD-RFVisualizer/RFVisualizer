/*
 * Copyright (C) 2020, Inria
 * GRAPHDECO research group, https://team.inria.fr/graphdeco
 * All rights reserved.
 *
 * This software is free for non-commercial, research and evaluation use 
 * under the terms of the LICENSE.md file.
 *
 * For inquiries contact sibr@inria.fr and/or George.Drettakis@inria.fr
 */


#include "FPSCamera.hpp"
#include <boost/filesystem.hpp>
#include "core/graphics/Input.hpp"
#include "core/graphics/Viewport.hpp"
#include "core/graphics/Window.hpp"
#include "core/view/UIShortcuts.hpp"
#include "core/graphics/GUI.hpp"


# define IBRVIEW_CAMSPEED 1.f

namespace sibr {

	FPSCamera::FPSCamera(void) : _hasBeenInitialized(false) 
	{ 
		UIShortcuts::global().add("[FPS camera] j", "rotate camera -Y (look left)");
		UIShortcuts::global().add("[FPS camera] l", "rotate camera +Y (look right)");
		UIShortcuts::global().add("[FPS camera] i", "rotate camera +X (look up)");
		UIShortcuts::global().add("[FPS camera] k", "rotate camera -X (look down)");
		UIShortcuts::global().add("[FPS camera] u", "rotate camera +Z ");
		UIShortcuts::global().add("[FPS camera] o", "rotate camera -Z ");
		UIShortcuts::global().add("[FPS camera] w", "move camera -Z (move forward)");
		UIShortcuts::global().add("[FPS camera] s", "move camera +Z (move backward)");
		UIShortcuts::global().add("[FPS camera] a", "move camera -X (strafe left)");
		UIShortcuts::global().add("[FPS camera] d", "move camera +X (strafe right)");
		UIShortcuts::global().add("[FPS camera] q", "move camera -Y (move down)");
		UIShortcuts::global().add("[FPS camera] e", "move camera +Y (move up)");
	/*
		_speedFpsCam = 1.0f;
		_speedRotFpsCam = 1.0f;
		_useAcceleration = true; */
		_speedFpsCam = 0.3f;
		_speedRotFpsCam = 1.0f;
		_useAcceleration = false; 
	}

	void FPSCamera::fromCamera( const sibr::InputCamera & cam)
	{
		_currentCamera = cam;
		_hasBeenInitialized = true;
		// 수평 기준 축은 씬마다 다르다(이 Fork의 PGSR 씬은 -Y가 위다). 처음 카메라의 up을
		// 가장 가까운 좌표축으로 스냅해서 쓴다. 그래야 마우스로 계속 돌려도 화면이 기울지 않는다.
		// **딱 한 번만 정한다.** fromCamera 는 Mode 전환 등으로 나중에도 불리는데, 그때 카메라가
		// 위나 아래를 많이 보고 있으면 up 의 주축이 바뀌어 기준이 통째로 뒤집힌다.
		if (_worldUpResolved) {
			return;
		}
		_worldUpResolved = true;
		const sibr::Vector3f up = cam.up();
		int axis = 0;
		for (int index = 1; index < 3; ++index) {
			if (std::abs(up[index]) > std::abs(up[axis])) {
				axis = index;
			}
		}
		_worldUp = sibr::Vector3f(0.f, 0.f, 0.f);
		_worldUp[axis] = (up[axis] >= 0.f) ? 1.f : -1.f;
	}

	void FPSCamera::update(const sibr::Input & input, float deltaTime) {
	
		if (!_hasBeenInitialized) { return; }
		_lastInput = input;   // onGUI의 키 상태 표시에 쓴다.
		// Read input and update camera.
		moveUsingWASD(input, deltaTime);
		// 오른쪽 버튼을 잡고 있는 동안은 마우스가 시점 회전이고, 그 외에는 기존 Pan이다.
		// Grounded mode에서는 Pan이 바닥을 벗어나게 하므로 시점 회전만 남긴다.
		if (!lookUsingMouse() && !_positionConstraint) {
			moveUsingMousePan(input, deltaTime);
		}
	}

	void FPSCamera::snap(const std::vector<InputCamera::Ptr> & cams){
		sibr::Vector3f sumDir(0.f, 0.f, 0.f);
		sibr::Vector3f sumUp(0.f, 0.f, 0.f);
		for (const auto& cam: cams)
		{
			float dist = 1.0f/std::max(1e-6f,distance(_currentCamera.position(), cam->position()));
			sumDir += dist * cam->dir();
			sumUp  += dist * cam->up();
		}
		Matrix4f m = lookAt(Vector3f(0, 0, 0), sumDir, sumUp);
		_currentCamera.rotation(quatFromMatrix(m));
	}

	void FPSCamera::update(const sibr::Input & input, const float deltaTime, const Viewport & viewport)
	{
		if (!viewport.isEmpty()) {
			_viewport = viewport;
		}
		update(input, deltaTime);
	}

	const sibr::InputCamera & FPSCamera::getCamera( void ) const
	{
		if( !_hasBeenInitialized ){
			SIBR_ERR << " FPS Camera : camera not initialized before use" << std::endl
				<< "\t you should use either fromMesh(), fromCamera() or load() " << std::endl;
		}
		return _currentCamera;
	}

	void FPSCamera::setSpeed(const float speed, const float angular) {
		_speedFpsCam = speed;
		if(angular != 0.0f) {
			_speedRotFpsCam = angular;
		}
	}

	void FPSCamera::setGoalAltitude(const float& goalAltitude) {
		_goalAltitude = goalAltitude;
	}

	void FPSCamera::onGUI(const std::string& suffix) {
		if(ImGui::Begin(suffix.c_str())) {
			ImGui::PushScaledItemWidth(130);
			ImGui::Checkbox("Acceleration", &_useAcceleration);
			ImGui::SameLine();
			if(!_useAcceleration) {
				ImGui::InputFloat("Speed", &_speedFpsCam, 0.1f, 0.5f);
				ImGui::SameLine();
			}
			ImGui::InputFloat("Rot. speed", &_speedRotFpsCam, 0.1f, 0.5f);
			ImGui::PopItemWidth();

			// 원격 데스크톱처럼 입력 경로가 의심스러울 때, 키가 앱까지 오는지 바로 보이게 한다.
			const ImGuiIO& io = ImGui::GetIO();
			std::string pressed;
			const std::pair<sibr::Key::Code, const char*> watched[] = {
				{ sibr::Key::W, "W" }, { sibr::Key::A, "A" }, { sibr::Key::S, "S" },
				{ sibr::Key::D, "D" }, { sibr::Key::Q, "Q" }, { sibr::Key::E, "E" },
				{ sibr::Key::LeftControl, "Ctrl" },
			};
			for (const auto& entry : watched) {
				const bool viaSibr = _lastInput.key().isActivated(entry.first);
				const bool viaImGui = io.KeysDown[int(entry.first)];
				if (viaSibr || viaImGui) {
					pressed += std::string(entry.second) + (viaSibr ? "" : "(imgui)") + " ";
				}
			}
			ImGui::Text("keys: %s", pressed.empty() ? "-" : pressed.c_str());
			ImGui::Text("mouse R: %s   look: %s   focus-free keys: on",
				io.MouseDown[1] ? "down" : "up", _looking ? "yes" : "no");
		}
		ImGui::End();
	}


	bool FPSCamera::keyHeld(const sibr::Input& input, sibr::Key::Code code) const
	{
		if (input.key().isActivated(code)) {
			return true;
		}
		// 렌더 화면은 ImGui 창 안에 그려지는데, ImGui는 **왼쪽 클릭에만** 창에 Focus를 준다.
		// Focus가 없으면 MultiViewBase가 이 View에 빈 Input을 넘겨서 이동 키가 전부 죽는다.
		// 그래서 ImGui의 원본 키 상태에서도 한 번 더 본다. 글자를 입력 중일 때는 넘긴다.
		const ImGuiIO& io = ImGui::GetIO();
		if (io.WantTextInput) {
			return false;
		}
		const int index = int(code);
		return index >= 0 && index < IM_ARRAYSIZE(io.KeysDown) && io.KeysDown[index];
	}

	void FPSCamera::moveGrounded(const sibr::Input& input, float camSpeed, float camRotSpeed)
	{
		// _worldUp 평면 위의 forward/right basis. Camera는 right=+X, up=+Y, dir=-Z 규약이라
		// up x right = dir 이다. right는 항상 dir과 수직이므로 위/아래를 똑바로 봐도(그때는
		// dir이 _worldUp과 나란해진다) right가 수평으로 남아 basis가 무너지지 않는다.
		sibr::Vector3f right = _currentCamera.right();
		right -= right.dot(_worldUp) * _worldUp;
		sibr::Vector3f forward;
		if (right.squaredNorm() > 1e-8f) {
			right.normalize();
			forward = _worldUp.cross(right);
		} else {
			// Camera가 90도 굴러 right가 _worldUp과 나란한 예외. 이때는 dir이 수평이다.
			forward = _currentCamera.dir();
			forward -= forward.dot(_worldUp) * _worldUp;
			if (!(forward.squaredNorm() > 1e-8f)) {
				return;                       // basis를 만들 수 없다. 이번 Frame은 움직이지 않는다.
			}
			forward.normalize();
			right = forward.cross(_worldUp);
		}

		// Q/E(수직 이동)는 읽지 않는다. 바닥을 걷는 모드이기 때문이다.
		const float strafe = (keyHeld(input, sibr::Key::D) ? 1.f : 0.f)
			- (keyHeld(input, sibr::Key::A) ? 1.f : 0.f);
		const float advance = (keyHeld(input, sibr::Key::W) ? 1.f : 0.f)
			- (keyHeld(input, sibr::Key::S) ? 1.f : 0.f);
		if (strafe != 0.f || advance != 0.f) {
			const sibr::Vector3f current = _currentCamera.position();
			const sibr::Vector3f candidate = current
				+ (camSpeed * _speedFpsCam) * (advance * forward + strafe * right);
			const sibr::Vector3f settled = _positionConstraint(current, candidate);
			if (settled.allFinite()) {
				_currentCamera.position(settled);
			}
		}

		// 시점 회전 키(I/J/K/L/U/O)는 grounded에서도 그대로 둔다.
		sibr::Vector3f pivot(0, 0, 0);
		pivot[1] += keyHeld(input, sibr::Key::J) ? camRotSpeed : 0.f;
		pivot[1] -= keyHeld(input, sibr::Key::L) ? camRotSpeed : 0.f;
		pivot[0] -= keyHeld(input, sibr::Key::K) ? camRotSpeed : 0.f;
		pivot[0] += keyHeld(input, sibr::Key::I) ? camRotSpeed : 0.f;
		pivot[2] -= keyHeld(input, sibr::Key::O) ? camRotSpeed : 0.f;
		pivot[2] += keyHeld(input, sibr::Key::U) ? camRotSpeed : 0.f;
		_currentCamera.rotate(pivot, _currentCamera.transform());
	}

	void FPSCamera::moveUsingWASD(const sibr::Input& input, float deltaTime)
	{


		// 여기는 keyHeld를 쓰지 않는다. keyHeld는 이동을 **켜는** 쪽으로만 써야 한다.
		// 원격 데스크톱(RustDesk 등)에서는 Ctrl이 눌린 채로 남는 일이 있는데, 그 상태를
		// 여기서 받아들이면 이동이 통째로 죽어 버린다.
		if (input.key().isActivated(sibr::Key::LeftControl)) { return; }

		float camSpeed = 2.f * deltaTime		* IBRVIEW_CAMSPEED;
		if (_currentCamera.ortho()) {
			camSpeed *= 5.0f;
		}
		float camRotSpeed = 30.f * deltaTime	* IBRVIEW_CAMSPEED;
		//float camSpeed = 0.1f;
		//float camRotSpeed = 1.f;

		if (_positionConstraint) {
			moveGrounded(input, camSpeed, camRotSpeed * _speedRotFpsCam);
			return;
		}

		sibr::Vector3f move(0, 0, 0);

		move.x() -= keyHeld(input, sibr::Key::A) ? camSpeed : 0.f;
		move.x() += keyHeld(input, sibr::Key::D) ? camSpeed : 0.f;
		move.z() -= keyHeld(input, sibr::Key::W) ? camSpeed : 0.f;
		move.z() += keyHeld(input, sibr::Key::S) ? camSpeed : 0.f;
		move.y() -= keyHeld(input, sibr::Key::Q) ? camSpeed : 0.f;
		move.y() += keyHeld(input, sibr::Key::E) ? camSpeed : 0.f;

		// If the acceleration effect is enabled, we alter the speed along a move.
		if(_useAcceleration) {
			if (move.isNull() == true) {
				_speedFpsCam = 1.f;
			} else {
				_speedFpsCam *= 1.02f;
			}
		}


		sibr::Vector3f pivot(0, 0, 0);

		camRotSpeed *= _speedRotFpsCam;
		pivot[1] += keyHeld(input, sibr::Key::J) ? camRotSpeed : 0.f;
		pivot[1] -= keyHeld(input, sibr::Key::L) ? camRotSpeed : 0.f;
		pivot[0] -= keyHeld(input, sibr::Key::K) ? camRotSpeed : 0.f;
		pivot[0] += keyHeld(input, sibr::Key::I) ? camRotSpeed : 0.f;
		pivot[2] -= keyHeld(input, sibr::Key::O) ? camRotSpeed : 0.f;
		pivot[2] += keyHeld(input, sibr::Key::U) ? camRotSpeed : 0.f;

		if (_currentCamera.ortho()) {
			if (input.key().isActivated(sibr::Key::Z)) {
				_currentCamera.orthoRight(_currentCamera.orthoRight()/1.1f);
				_currentCamera.orthoTop(_currentCamera.orthoTop()/1.1f);
				_speedRotFpsCam /= 1.1f;
			}
			else if (input.key().isActivated(sibr::Key::X)) {
				_currentCamera.orthoRight(_currentCamera.orthoRight()*1.1f);
				_currentCamera.orthoTop(_currentCamera.orthoTop()*1.1f);
				_speedRotFpsCam *= 1.1f;
			}
		}

		// Try to keep the same altitude as cameras around.
		if (_goalAltitude != -1) {
			sibr::Vector3f worldUp(0., 0., 1.);
			const sibr::Vector3f custom_forward = _currentCamera.right().cross(worldUp);
			const sibr::Vector3f translation_right = (_speedFpsCam * move.x()) * _currentCamera.right();

			sibr::Vector3f translation = _speedFpsCam * (move.z() * custom_forward) + translation_right;
			//const float altitudeDiff = _goalAltitude - _currentCamera.position().z();
			translation[2] = _goalAltitude - _currentCamera.position().z();

			_currentCamera.translate(translation);
		}
		else {
			_currentCamera.translate(move * _speedFpsCam, _currentCamera.transform());
		}

		_currentCamera.rotate(pivot, _currentCamera.transform());
	}

	bool FPSCamera::lookUsingMouse()
	{
		// sibr::Input의 마우스 상태는 커서가 ImGui 창 위에 있으면 비워진다. 그런데 렌더 화면
		// 자체가 ImGui 창 안에 그려지므로, 여기서는 ImGui의 원본 마우스 상태를 직접 읽는다.
		const ImGuiIO& io = ImGui::GetIO();
		if (!io.MouseDown[1]) {
			_looking = false;
			return false;
		}
		if (!_looking) {
			// 드래그를 이 View 안에서 시작했을 때만 받는다. 한 번 시작하면 커서가 밖으로
			// 나가도 버튼을 뗄 때까지 계속 돌린다.
			if (!_viewport.isEmpty() && !_viewport.contains(io.MousePos.x, io.MousePos.y)) {
				return false;
			}
			_looking = true;
			return true;   // 누른 첫 Frame의 delta는 튀므로 쓰지 않는다.
		}
		// 휠로 이동 속도를 바꾼다. Unity Scene View와 같은 조작이다.
		if (io.MouseWheel != 0.0f) {
			_speedFpsCam = sibr::clamp(_speedFpsCam * std::pow(1.2f, io.MouseWheel), 0.01f, 100.f);
		}
		if (io.MouseDelta.x == 0.0f && io.MouseDelta.y == 0.0f) {
			return true;
		}
		// 커서가 창 밖으로 나갔다 다른 자리로 되돌아오면 ImGui가 그 간격을 한 Frame의 이동량으로
		// 준다. 그대로 쓰면 화면이 확 튄다. 사람 손으로 한 Frame에 나올 수 있는 크기로 자른다.
		const float maxDelta = 150.f;
		const float deltaX = sibr::clamp(io.MouseDelta.x, -maxDelta, maxDelta);
		const float deltaY = sibr::clamp(io.MouseDelta.y, -maxDelta, maxDelta);
		const float yaw = -deltaX * _mouseLookSpeed * float(M_PI) / 180.f;
		const float pitch = -deltaY * _mouseLookSpeed * float(M_PI) / 180.f;

		// Yaw는 world up 기준, Pitch는 **카메라 자신의 오른쪽 축** 기준으로 돌린다.
		// 이 조합이라야 계속 돌려도 roll(수평 기울어짐)이 새로 쌓이지 않는다.
		//
		// lookAt으로 자세를 통째로 다시 만들지 않는 이유: 원래 카메라가 조금 기울어져 있으면
		// (손으로 찍은 입력 카메라는 대개 기울어져 있다) 마우스를 1픽셀 움직인 순간 수평이
		// 강제로 맞춰지면서 화면이 확 튄다. 증분 회전은 지금 자세를 그대로 이어받는다.
		const sibr::Vector3f direction = _currentCamera.dir().normalized();
		const sibr::Vector3f right = _currentCamera.right().normalized();

		// 천장·바닥을 지나 뒤집히지 않도록 수직 근처에서는 Pitch를 버린다.
		const sibr::Vector3f pitched = Eigen::AngleAxisf(pitch, right) * direction;
		if (std::abs(pitched.normalized().dot(_worldUp)) < 0.995f) {
			_currentCamera.rotate(sibr::Quaternionf(Eigen::AngleAxisf(pitch, right)));
		}
		_currentCamera.rotate(sibr::Quaternionf(Eigen::AngleAxisf(yaw, _worldUp)));
		return true;
	}

	void FPSCamera::moveUsingMousePan( const sibr::Input& input, float deltaTime )
	{
		
		float speed = 0.05f*deltaTime;
		sibr::Vector3f move(
			input.mouseButton().isActivated(sibr::Mouse::Left)? input.mouseDeltaPosition().x()*speed : 0.f,
			input.mouseButton().isActivated(sibr::Mouse::Right)? input.mouseDeltaPosition().y()*speed : 0.f,
			input.mouseButton().isActivated(sibr::Mouse::Middle)? input.mouseDeltaPosition().y()*speed : 0.f
			);
		_currentCamera.translate(move, _currentCamera.transform());

	}
}
