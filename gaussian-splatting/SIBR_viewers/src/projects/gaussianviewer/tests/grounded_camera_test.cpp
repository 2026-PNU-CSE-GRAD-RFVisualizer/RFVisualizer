/*
 * RFVisualizer: FPSCamera의 grounded seam 검증. 실제 FPSCamera를 그대로 돌린다.
 *
 * Window도 GL Context도 만들지 않는다. FPSCamera가 키를 읽을 때 ImGui의 원본 상태를 보므로
 * ImGui Context만 하나 만들어 두고 io.KeysDown을 직접 채운다.
 *
 * 새 Test Framework를 넣지 않는다. assertion과 CTest만 쓴다.
 */
#include <core/graphics/Input.hpp>
#include <core/view/FPSCamera.hpp>
#include <imgui/imgui.h>

#include <cmath>
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

	const float DELTA_TIME = 0.5f;
	/** FPSCamera가 한 Frame에 옮기는 거리: 2 * deltaTime * _speedFpsCam(기본 0.3). */
	const float STEP = 2.f * DELTA_TIME * 0.3f;

	void pressOnly(const std::vector<sibr::Key::Code>& keys)
	{
		ImGuiIO& io = ImGui::GetIO();
		for (int index = 0; index < IM_ARRAYSIZE(io.KeysDown); ++index) {
			io.KeysDown[index] = false;
		}
		for (sibr::Key::Code key : keys) {
			io.KeysDown[int(key)] = true;
		}
	}

	/** worldUp이 +Y인, 수평을 보는 Camera. pitchDegrees 만큼 아래를 보게 만든다. */
	sibr::InputCamera makeCamera(float pitchDegrees)
	{
		sibr::InputCamera camera(sibr::Camera(), 800, 600);
		camera.position(sibr::Vector3f(0.f, 10.f, 0.f));
		// 기본 자세는 dir=-Z, up=+Y, right=+X. 거기서 right축으로 pitch만 준다.
		camera.rotation(sibr::Quaternionf(
			Eigen::AngleAxisf(-pitchDegrees * float(M_PI) / 180.f, sibr::Vector3f(1.f, 0.f, 0.f))));
		return camera;
	}

	/** 제약이 걸린 FPSCamera 하나를 만든다. 제약은 후보를 그대로 통과시킨다. */
	sibr::FPSCamera makeGrounded(float pitchDegrees, int* callCount = nullptr)
	{
		sibr::FPSCamera camera;
		// _worldUp은 **처음** fromCamera에서 한 번만 정해진다. 실제 Viewer도 똑바로 선 입력
		// 카메라로 시작한 뒤 시점을 돌리므로, 여기서도 수평 카메라로 기준을 잡고 나서 pitch를 준다.
		camera.fromCamera(makeCamera(0.f));
		camera.fromCamera(makeCamera(pitchDegrees));
		camera.setGoalAltitude(-1.f);
		camera.setPositionConstraint(
			[callCount](const sibr::Vector3f&, const sibr::Vector3f& candidate) {
				if (callCount != nullptr) { ++(*callCount); }
				return candidate;
			});
		return camera;
	}

	void testForwardIsHorizontal()
	{
		sibr::FPSCamera camera = makeGrounded(0.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::W });
		camera.update(sibr::Input(), DELTA_TIME);
		const sibr::Vector3f moved = camera.getCamera().position() - start;

		check(std::abs(moved.y()) < 1e-5f, "W는 높이를 바꾸지 않는다");
		check(moved.z() < -1e-3f, "W는 카메라가 보는 앞쪽(-Z)으로 간다");
		check(std::abs(moved.norm() - STEP) < 1e-4f, "W 한 Frame의 이동 거리가 기존 속도와 같다");
	}

	void testPitchedViewKeepsSpeed()
	{
		// 80도 아래를 봐도 수평 이동 거리는 같아야 한다(자유비행이면 여기서 바닥으로 파고든다).
		sibr::FPSCamera camera = makeGrounded(80.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::W });
		camera.update(sibr::Input(), DELTA_TIME);
		const sibr::Vector3f moved = camera.getCamera().position() - start;

		check(std::isfinite(moved.x()) && std::isfinite(moved.y()) && std::isfinite(moved.z()),
			"80도 pitch에서도 유한한 이동을 만든다");
		check(std::abs(moved.y()) < 1e-5f, "80도 pitch에서도 높이가 그대로다");
		check(std::abs(moved.norm() - STEP) < 1e-4f, "80도 pitch에서도 수평 속도가 같다");
		check(moved.z() < -1e-3f, "80도 pitch에서도 W는 앞쪽으로 간다");
	}

	void testStrafe()
	{
		sibr::FPSCamera camera = makeGrounded(0.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::D });
		camera.update(sibr::Input(), DELTA_TIME);
		const sibr::Vector3f moved = camera.getCamera().position() - start;

		check(moved.x() > 1e-3f && std::abs(moved.y()) < 1e-5f, "D는 오른쪽으로 수평 이동한다");
	}

	void testVerticalKeysIgnored()
	{
		for (sibr::Key::Code key : { sibr::Key::Q, sibr::Key::E }) {
			sibr::FPSCamera camera = makeGrounded(0.f);
			const sibr::Vector3f start = camera.getCamera().position();
			pressOnly({ key });
			camera.update(sibr::Input(), DELTA_TIME);
			const sibr::Vector3f moved = camera.getCamera().position() - start;
			check(moved.norm() < 1e-6f,
				std::string("grounded에서 ") + (key == sibr::Key::Q ? "Q" : "E") + "는 무시된다");
		}
	}

	void testConstraintWins()
	{
		// 제약이 마지막 안전 위치를 돌려주면 카메라는 그대로 남는다.
		sibr::FPSCamera camera;
		camera.fromCamera(makeCamera(0.f));
		camera.setGoalAltitude(-1.f);
		int calls = 0;
		camera.setPositionConstraint(
			[&calls](const sibr::Vector3f& current, const sibr::Vector3f&) {
				++calls;
				return current;
			});
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::W });
		camera.update(sibr::Input(), DELTA_TIME);
		check(calls == 1, "이동 키가 눌리면 제약이 정확히 한 번 불린다");
		check((camera.getCamera().position() - start).norm() < 1e-6f,
			"제약이 last-safe를 돌려주면 카메라가 제자리에 남는다");

		// NaN을 돌려줘도 pose가 깨지지 않는다.
		camera.setPositionConstraint(
			[](const sibr::Vector3f&, const sibr::Vector3f&) {
				return sibr::Vector3f(std::nan(""), 0.f, 0.f);
			});
		camera.update(sibr::Input(), DELTA_TIME);
		check(camera.getCamera().position().allFinite(), "제약이 NaN을 줘도 pose는 유한하다");
	}

	void testNoKeyNoConstraintCall()
	{
		int calls = 0;
		sibr::FPSCamera camera = makeGrounded(0.f, &calls);
		pressOnly({});
		camera.update(sibr::Input(), DELTA_TIME);
		check(calls == 0, "이동 키가 없으면 제약을 부르지 않는다");
	}

	void testEmptyConstraintKeepsNoclip()
	{
		// 제약이 없으면 기존 자유비행 그대로다. Q/E가 계속 위아래로 움직여야 한다.
		sibr::FPSCamera camera;
		camera.fromCamera(makeCamera(0.f));
		camera.setGoalAltitude(-1.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::E });
		camera.update(sibr::Input(), DELTA_TIME);
		const sibr::Vector3f moved = camera.getCamera().position() - start;
		check(moved.y() > 1e-3f, "제약이 없으면 E가 기존대로 위로 올린다");

		sibr::FPSCamera down;
		down.fromCamera(makeCamera(0.f));
		down.setGoalAltitude(-1.f);
		const sibr::Vector3f downStart = down.getCamera().position();
		pressOnly({ sibr::Key::Q });
		down.update(sibr::Input(), DELTA_TIME);
		check((down.getCamera().position() - downStart).y() < -1e-3f,
			"제약이 없으면 Q가 기존대로 아래로 내린다");
	}

	void testLookDoesNotMove()
	{
		sibr::FPSCamera camera = makeGrounded(0.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::L });   // 시점 회전 키
		camera.update(sibr::Input(), DELTA_TIME);
		check((camera.getCamera().position() - start).norm() < 1e-6f,
			"시점 회전은 위치를 바꾸지 않는다");
		check(camera.getCamera().dir().allFinite(), "시점 회전 뒤에도 자세가 유한하다");
	}

	// ------------------------------------------- 한 프레임 안의 탭 (원격 데스크톱)

	/** RustDesk는 키 반복을 눌린 시간 0 ms인 press+release 쌍으로 보낸다.
	 * Input::poll()이 swapStates() 뒤에 이벤트를 한꺼번에 처리하므로, 미루지 않으면
	 * 프레임이 그 누름을 한 번도 보지 못한다. */
	void testSubFrameTap()
	{
		sibr::Input input;

		input.swapStates();                       // 프레임 N 시작
		input.key().press(sibr::Key::W);
		input.key().release(sibr::Key::W);        // 같은 poll 안에서 뗌
		check(input.key().isActivated(sibr::Key::W),
			"한 프레임 안의 탭도 그 프레임에는 눌린 것으로 보인다");
		check(input.key().isPressed(sibr::Key::W), "탭은 isPressed로도 한 번 잡힌다");

		input.swapStates();                       // 프레임 N+1
		check(!input.key().isActivated(sibr::Key::W), "다음 프레임에는 떼진 상태다");
		check(input.key().isReleased(sibr::Key::W), "다음 프레임에 isReleased가 한 번 뜬다");

		input.swapStates();                       // 프레임 N+2
		check(!input.key().isActivated(sibr::Key::W) && !input.key().isReleased(sibr::Key::W),
			"그 다음 프레임에는 아무 상태도 남지 않는다");
	}

	/** 평범하게 눌러 두는 경우가 망가지지 않아야 한다. */
	void testNormalHoldUnchanged()
	{
		sibr::Input input;

		input.swapStates();
		input.key().press(sibr::Key::A);
		check(input.key().isActivated(sibr::Key::A) && input.key().isPressed(sibr::Key::A),
			"누른 프레임에 isActivated와 isPressed가 뜬다");

		input.swapStates();
		check(input.key().isActivated(sibr::Key::A), "계속 누르고 있으면 다음 프레임도 눌림이다");
		check(!input.key().isPressed(sibr::Key::A), "isPressed는 한 프레임만 뜬다");

		input.key().release(sibr::Key::A);        // 이전 프레임에 눌린 키를 뗀다
		check(!input.key().isActivated(sibr::Key::A), "떼면 바로 눌림이 풀린다");
		check(input.key().isReleased(sibr::Key::A), "뗀 프레임에 isReleased가 뜬다");

		input.swapStates();
		check(!input.key().isActivated(sibr::Key::A) && !input.key().isReleased(sibr::Key::A),
			"뗀 다음 프레임에는 아무 상태도 남지 않는다");
	}

	/** 한 프레임에 탭이 여러 번 와도(30 ms 반복 < 프레임 시간) 눌림이 유지된다. */
	void testRepeatedTapsInOneFrame()
	{
		sibr::Input input;
		input.swapStates();
		for (int repeat = 0; repeat < 5; ++repeat) {
			input.key().press(sibr::Key::D);
			input.key().release(sibr::Key::D);
		}
		check(input.key().isActivated(sibr::Key::D), "한 프레임에 탭이 여러 번 와도 눌림이다");

		input.swapStates();
		check(!input.key().isActivated(sibr::Key::D), "다음 프레임에는 풀린다");
	}

	/** 탭 뒤에 다시 눌러 두면 미뤄둔 뗌이 취소돼야 한다. */
	void testTapThenHold()
	{
		sibr::Input input;
		input.swapStates();
		input.key().press(sibr::Key::S);
		input.key().release(sibr::Key::S);
		input.key().press(sibr::Key::S);          // 같은 프레임에 다시 눌림
		input.swapStates();
		check(input.key().isActivated(sibr::Key::S),
			"탭 뒤 다시 누르면 미뤄둔 뗌이 취소되고 눌린 채로 남는다");
	}

	/** 마우스 버튼도 같은 규칙을 탄다. */
	void testMouseSubFrameClick()
	{
		sibr::Input input;
		input.swapStates();
		input.mouseButton().press(sibr::Mouse::Left);
		input.mouseButton().release(sibr::Mouse::Left);
		check(input.mouseButton().isActivated(sibr::Mouse::Left),
			"한 프레임 안의 클릭도 그 프레임에는 눌린 것으로 보인다");
		input.swapStates();
		check(input.mouseButton().isReleased(sibr::Mouse::Left),
			"다음 프레임에 마우스 isReleased가 뜬다");
	}

	/** 실제 증상 재현: 탭만 흘려보내도 카메라가 앞으로 나아가야 한다. */
	void testGroundedMovesOnTaps()
	{
		sibr::FPSCamera camera = makeGrounded(0.f);
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({});                            // ImGui 경로는 비워 둔다
		sibr::Input input;
		for (int frame = 0; frame < 3; ++frame) {
			input.swapStates();                   // Input::poll()과 같은 순서
			input.key().press(sibr::Key::W);
			input.key().release(sibr::Key::W);
			camera.update(input, DELTA_TIME);
		}
		const sibr::Vector3f moved = camera.getCamera().position() - start;
		check(moved.norm() > 1e-3f, "0 ms 탭만으로도 grounded 이동이 일어난다");
		check(std::abs(moved.y()) < 1e-5f, "탭 이동도 수평을 유지한다");
	}

	// --------------------------------------------- 조준 중 위치 잠금 (텔레포트)

	/** 텔레포트 조준 중 main은 제약이 current를 그대로 돌려주게 한다. 그때 W/A/S/D는
	 * 막히고 우클릭 시점 회전은 계속돼야 한다. */
	void testAimFreezesMovementNotLook()
	{
		sibr::FPSCamera camera;
		camera.fromCamera(makeCamera(0.f));
		camera.setGoalAltitude(-1.f);
		bool aiming = false;
		camera.setPositionConstraint(
			[&aiming](const sibr::Vector3f& current, const sibr::Vector3f& candidate) {
				return aiming ? current : candidate;
			});

		// 조준 전에는 평소대로 움직인다.
		const sibr::Vector3f start = camera.getCamera().position();
		pressOnly({ sibr::Key::W });
		camera.update(sibr::Input(), DELTA_TIME);
		check((camera.getCamera().position() - start).norm() > 1e-3f,
			"조준 전에는 W가 평소대로 움직인다");

		// 조준 중에는 W를 눌러도 제자리다.
		aiming = true;
		const sibr::Vector3f held = camera.getCamera().position();
		const sibr::Quaternionf beforeRotation = camera.getCamera().rotation();
		for (int frame = 0; frame < 3; ++frame) {
			pressOnly({ sibr::Key::W });
			camera.update(sibr::Input(), DELTA_TIME);
		}
		check((camera.getCamera().position() - held).norm() < 1e-6f,
			"조준 중에는 W를 눌러도 위치가 고정된다");

		// 조준 중에도 시점 회전 키는 먹는다(우클릭 mouse-look과 같은 경로다).
		pressOnly({ sibr::Key::L });
		camera.update(sibr::Input(), DELTA_TIME);
		check((camera.getCamera().position() - held).norm() < 1e-6f,
			"조준 중 시점 회전은 위치를 바꾸지 않는다");
		check(camera.getCamera().rotation().coeffs() != beforeRotation.coeffs(),
			"조준 중에도 시점은 계속 돌아간다");

		// 조준이 끝나면 다시 걷는다.
		aiming = false;
		pressOnly({ sibr::Key::W });
		camera.update(sibr::Input(), DELTA_TIME);
		check((camera.getCamera().position() - held).norm() > 1e-3f,
			"조준이 끝나면 W 이동이 되살아난다");
	}

} // namespace

int main()
{
	ImGui::CreateContext();
	ImGuiIO& io = ImGui::GetIO();
	io.DisplaySize = ImVec2(800.f, 600.f);
	io.Fonts->AddFontDefault();
	io.Fonts->Build();

	testForwardIsHorizontal();
	testPitchedViewKeepsSpeed();
	testStrafe();
	testVerticalKeysIgnored();
	testConstraintWins();
	testNoKeyNoConstraintCall();
	testEmptyConstraintKeepsNoclip();
	testLookDoesNotMove();
	testSubFrameTap();
	testNormalHoldUnchanged();
	testRepeatedTapsInOneFrame();
	testTapThenHold();
	testMouseSubFrameClick();
	testGroundedMovesOnTaps();
	testAimFreezesMovementNotLook();

	std::cout << (g_failures == 0 ? "grounded_camera: all ok" : "grounded_camera: FAILED") << std::endl;
	return g_failures == 0 ? 0 : 1;
}
