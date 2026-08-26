/*
 * RFVisualizer: 포물선 텔레포트의 궤적·목적지 판정·press/hold/release 상태기계 검증.
 *
 * 새 Test Framework를 넣지 않는다. assertion과 CTest만 쓴다.
 * proxy 충돌은 실제 Embree Raycaster에 작은 mesh를 넣어 확인한다.
 */
#include "projects/gaussianviewer/renderer/ArcTeleportController.hpp"

#include <sys/stat.h>

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using sibr::ArcTeleportController;
using sibr::GroundedFPSController;
using sibr::TeleportAction;
using sibr::TeleportEndpoint;

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

	std::string g_root;
	std::string tempPath(const std::string& name) { return g_root + "/" + name; }

	void writeFile(const std::string& path, const std::string& body)
	{
		std::ofstream stream(path);
		stream << body;
	}

	/** 한 변 20 m 정사각 방. 바닥 z=0, 천장 z=3, 벽 4장. */
	std::string roomObj(double side)
	{
		std::ostringstream obj;
		const double top = 3.0;
		obj << "v 0 0 0\nv " << side << " 0 0\nv " << side << " " << side << " 0\nv 0 " << side << " 0\n";
		obj << "v 0 0 " << top << "\nv " << side << " 0 " << top << "\nv " << side << " " << side
			<< " " << top << "\nv 0 " << side << " " << top << "\n";
		obj << "f 1 2 3\nf 1 3 4\n";
		obj << "f 5 6 7\nf 5 7 8\n";
		obj << "f 1 2 6\nf 1 6 5\n";
		obj << "f 2 3 7\nf 2 7 6\n";
		obj << "f 3 4 8\nf 3 8 7\n";
		obj << "f 4 1 5\nf 4 5 8\n";
		return obj.str();
	}

	std::string manifestJson(bool rotated)
	{
		const double identity[16] = { 1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1 };
		// 90도 회전 + 2배 확대. metric과 scene이 다른 좌표계임을 흉내낸다.
		const double turned[16] = {
			 0.0, -2.0, 0.0,  1.0,
			 2.0,  0.0, 0.0, -3.0,
			 0.0,  0.0, 2.0,  0.5,
			 0.0,  0.0, 0.0,  1.0
		};
		const double* m = rotated ? turned : identity;
		std::ostringstream json;
		json.precision(17);
		json << "{\"T_scene_from_metric\":[";
		for (int row = 0; row < 4; ++row) {
			json << (row ? ",[" : "[");
			for (int col = 0; col < 4; ++col) {
				json << (col ? "," : "") << m[row * 4 + col];
			}
			json << "]";
		}
		json << "],\"occlusion_meshes\":[{\"file\":\"room_envelope_metric.obj\"}]}";
		return json.str();
	}

	GroundedFPSController::Ptr makeGrounded(bool rotated)
	{
		const std::string name = rotated ? "rotated.json" : "identity.json";
		writeFile(tempPath(name), manifestJson(rotated));
		return std::make_shared<GroundedFPSController>(tempPath(name));
	}

	/** metric 방향을 scene 방향으로 옮긴다. Camera는 scene 좌표로 말하기 때문이다. */
	sibr::Vector3f sceneDir(const GroundedFPSController& grounded,
		const double from[3], double dx, double dy, double dz)
	{
		const double to[3] = { from[0] + dx, from[1] + dy, from[2] + dz };
		double a[3], b[3];
		grounded.toScene(from, a);
		grounded.toScene(to, b);
		return sibr::Vector3f(float(b[0] - a[0]), float(b[1] - a[1]), float(b[2] - a[2]));
	}

	sibr::Vector3f scenePoint(const GroundedFPSController& grounded, const double metric[3])
	{
		double out[3];
		grounded.toScene(metric, out);
		return sibr::Vector3f(float(out[0]), float(out[1]), float(out[2]));
	}

	TeleportAction press()   { TeleportAction a; a.pressed = true;  a.active = true;  return a; }
	TeleportAction hold()    { TeleportAction a; a.active = true;   return a; }
	TeleportAction release() { TeleportAction a; a.released = true; return a; }

	/** press -> hold -> release 한 판. commit되면 target을 채운다. */
	bool runAim(ArcTeleportController& arc, const GroundedFPSController& grounded,
		const double eye[3], double dx, double dy, double dz,
		sibr::Vector3f& target, sibr::TeleportPreview& lastPreview)
	{
		const sibr::Vector3f origin = scenePoint(grounded, eye);
		const sibr::Vector3f forward = sceneDir(grounded, eye, dx, dy, dz);
		sibr::Vector3f ignored;
		arc.update(press(), true, origin, forward, ignored);
		arc.update(hold(), true, origin, forward, ignored);
		lastPreview = arc.preview();
		return arc.update(release(), true, origin, forward, target);
	}

	// ------------------------------------------------------------- 궤적

	void testHorizontalRange(bool rotated)
	{
		GroundedFPSController::Ptr grounded = makeGrounded(rotated);
		ArcTeleportController arc(grounded, nullptr);

		// 방 한가운데에서 +X 수평으로 조준한다. 1.7 m 높이, 8 m/s면 약 4.71 m 앞이다.
		const double eye[3] = { 5.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		const bool committed = runAim(arc, *grounded, eye, 1.0, 0.0, 0.0, target, preview);

		const std::string tag = rotated ? " (회전+배율 transform)" : " (identity transform)";
		check(preview.endpoint == TeleportEndpoint::Floor, "수평 조준은 바닥에서 끝난다" + tag);
		check(preview.valid, "방 한가운데 착지는 유효하다" + tag);
		check(committed, "유효한 release는 commit한다" + tag);

		const double expected = sibr::teleport::SPEED_MPS
			* std::sqrt(2.0 * sibr::grounded::EYE_HEIGHT_M / sibr::teleport::GRAVITY_MPS2);
		const double reached = preview.targetMetric[0] - eye[0];
		check(std::abs(reached - expected) < 0.05,
			"수평 사거리가 이론값(약 4.71 m)과 맞는다" + tag);
		check(std::abs(preview.targetMetric[1] - eye[1]) < 1e-6,
			"수평 조준은 옆으로 새지 않는다" + tag);

		// commit 지점의 눈높이는 항상 1.7 m다.
		double back[3];
		const double sceneTarget[3] = { target.x(), target.y(), target.z() };
		grounded->toMetric(sceneTarget, back);
		check(std::abs(back[2] - sibr::grounded::EYE_HEIGHT_M) < 1e-4,
			"commit 위치의 눈높이는 1.7 m다" + tag);
		check(std::abs(back[0] - preview.targetMetric[0]) < 1e-4
			&& std::abs(back[1] - preview.targetMetric[1]) < 1e-4,
			"commit 위치의 XY가 표시된 착지점과 같다" + tag);

		// 착지 마커는 몸 크기를 그대로 보여 주는 반경 0.25 m 고리다.
		check(preview.markerIsRing && preview.markerPoints.size() == 24,
			"착지에는 고리 마커가 붙는다" + tag);
		double ringMetric[3];
		const double ringScene[3] = { preview.markerPoints[0].x(),
			preview.markerPoints[0].y(), preview.markerPoints[0].z() };
		grounded->toMetric(ringScene, ringMetric);
		const double dx = ringMetric[0] - preview.targetMetric[0];
		const double dy = ringMetric[1] - preview.targetMetric[1];
		check(std::abs(std::sqrt(dx * dx + dy * dy) - sibr::grounded::BODY_RADIUS_M) < 1e-4,
			"고리 반지름이 몸 반경 0.25 m다" + tag);
		check(std::abs(ringMetric[2]) < 1e-4, "고리는 바닥(z=0)에 놓인다" + tag);
	}

	void testUpAndDownAim()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		const double eye[3] = { 5.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview up, down, steep;

		// 위/아래 10도. 이 범위는 8 m 길이 상한 안에서 바닥까지 닿는다.
		const double tilt = 0.1763;   // tan(10도)
		runAim(arc, *grounded, eye, 1.0, 0.0, tilt, target, up);
		runAim(arc, *grounded, eye, 1.0, 0.0, -tilt, target, down);

		check(up.endpoint == TeleportEndpoint::Floor && down.endpoint == TeleportEndpoint::Floor,
			"위/아래 10도 조준 모두 바닥에서 끝난다");
		check(up.valid && down.valid, "둘 다 유효한 착지다");
		check(up.targetMetric[0] > down.targetMetric[0],
			"위로 조준하면 아래로 조준할 때보다 멀리 간다");
		check(down.targetMetric[0] > eye[0], "아래로 조준해도 앞으로는 나간다");

		// 위로 45도는 착지 전에 8 m 누적 길이 상한에 먼저 걸린다. 사거리를 무한정
		// 늘리지 못하게 하는 의도된 한계다.
		runAim(arc, *grounded, eye, 1.0, 0.0, 1.0, target, steep);
		check(steep.endpoint == TeleportEndpoint::Cap,
			"위로 45도 조준은 바닥에 닿기 전에 길이 상한에 걸린다");
		check(!steep.valid, "길이 상한에 걸리면 착지점이 없다");
	}

	void testWallBeforeFloor()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		// x=0 벽에서 1 m 떨어져 벽을 향해 쏜다. 바닥보다 벽이 먼저다.
		const double eye[3] = { 1.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		const bool committed = runAim(arc, *grounded, eye, -1.0, 0.0, 0.0, target, preview);

		check(preview.endpoint == TeleportEndpoint::Wall, "벽이 바닥보다 먼저 궤적을 끊는다");
		check(!preview.markerIsRing && !preview.markerPoints.empty(),
			"막힌 지점에는 고리 대신 X 마커가 붙는다");
		check(!preview.valid, "벽에 막힌 궤적은 무효다");
		check(!committed, "무효한 release는 commit하지 않는다");
	}

	void testOutsideFloorAndClearance()
	{
		// 좁은 방(2 m). 수평으로 쏘면 4.7 m 지점은 방 밖이라 벽에 먼저 막힌다.
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);

		// 벽에서 0.1 m 앞 바닥을 노린다: 바닥이지만 몸이 안 들어간다.
		// 급하게 아래로 쏘아 x=20 벽 바로 앞에 떨어뜨린다.
		const double eye[3] = { 19.9 - 0.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		const bool committed = runAim(arc, *grounded, eye, 0.05, 0.0, -1.0, target, preview);
		check(!committed, "벽에서 0.25 m 이내 착지는 commit하지 않는다");
		if (preview.endpoint == TeleportEndpoint::Floor) {
			check(!preview.valid, "벽에 붙은 바닥 착지는 무효로 표시된다");
		} else {
			check(true, "벽에 붙은 조준은 벽에서 끊긴다");
		}
	}

	void testNoGroundCap()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		// 똑바로 위로 쏘면 1.5초/8 m 안에 바닥으로 못 돌아온다.
		const double eye[3] = { 10.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		const bool committed = runAim(arc, *grounded, eye, 0.0, 0.0, 1.0, target, preview);
		check(preview.endpoint != TeleportEndpoint::Floor, "위로 쏘면 착지점이 없다");
		check(!preview.valid && !committed, "착지점이 없으면 commit하지 않는다");
		check(!preview.scenePoints.empty(), "착지점이 없어도 그릴 궤적은 있다");
	}

	void testLengthCap()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		const double eye[3] = { 10.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		runAim(arc, *grounded, eye, 0.0, 0.0, 1.0, target, preview);

		double length = 0.0;
		for (size_t index = 1; index < preview.scenePoints.size(); ++index) {
			length += (preview.scenePoints[index] - preview.scenePoints[index - 1]).norm();
		}
		// identity transform이라 scene 길이 = metric 길이다.
		check(length <= sibr::teleport::MAX_LENGTH_M + 1e-3,
			"궤적 누적 길이가 8 m를 넘지 않는다");
		check(length > 1.0, "궤적이 실제로 그려진다");
	}

	void testNaNAim()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		const double eye[3] = { 10.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		const sibr::Vector3f origin = scenePoint(*grounded, eye);
		const sibr::Vector3f broken(std::nanf(""), 0.f, 0.f);
		sibr::Vector3f target;
		arc.update(press(), true, origin, broken, target);
		check(!arc.preview().valid, "NaN 시선은 무효다");
		const bool committed = arc.update(release(), true, origin, broken, target);
		check(!committed, "NaN 시선에서는 commit하지 않는다");
	}

	// --------------------------------------------------------- 상태기계

	void testStateMachine()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		const double eye[3] = { 5.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		const sibr::Vector3f origin = scenePoint(*grounded, eye);
		const sibr::Vector3f forward = sceneDir(*grounded, eye, 1.0, 0.0, 0.0);
		sibr::Vector3f target;

		check(!arc.aiming(), "처음에는 조준 중이 아니다");
		arc.update(hold(), true, origin, forward, target);
		check(!arc.aiming(), "press 없이 hold만 오면 시작하지 않는다");

		arc.update(press(), true, origin, forward, target);
		check(arc.aiming() && arc.preview().aiming, "press로 조준이 시작된다");

		arc.update(hold(), true, origin, forward, target);
		check(arc.aiming(), "hold 중에는 조준이 유지된다");

		check(arc.update(release(), true, origin, forward, target), "release에서 commit한다");
		check(!arc.aiming() && !arc.preview().aiming, "release 후 조준이 끝난다");

		// 두 번째 release는 아무 일도 하지 않는다.
		check(!arc.update(release(), true, origin, forward, target),
			"release는 정확히 한 번만 commit한다");
	}

	void testCancelPaths()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		ArcTeleportController arc(grounded, nullptr);
		const double eye[3] = { 5.0, 10.0, sibr::grounded::EYE_HEIGHT_M };
		const sibr::Vector3f origin = scenePoint(*grounded, eye);
		const sibr::Vector3f forward = sceneDir(*grounded, eye, 1.0, 0.0, 0.0);
		sibr::Vector3f target;

		// release 없이 눌림이 사라지면 취소한다.
		arc.update(press(), true, origin, forward, target);
		check(!arc.update(TeleportAction(), true, origin, forward, target),
			"release 없이 눌림이 사라지면 commit하지 않는다");
		check(!arc.aiming(), "눌림이 사라지면 조준이 취소된다");

		// 자격을 잃으면 취소한다.
		arc.update(press(), true, origin, forward, target);
		check(!arc.update(hold(), false, origin, forward, target),
			"자격을 잃으면 commit하지 않는다");
		check(!arc.aiming(), "자격을 잃으면 조준이 취소된다");

		// 취소 뒤에는 hold만으로 다시 시작되지 않는다.
		arc.update(hold(), true, origin, forward, target);
		check(!arc.aiming(), "취소 뒤에는 새로 눌러야 다시 시작한다");

		// 자격이 없으면 press도 무시한다.
		arc.update(press(), false, origin, forward, target);
		check(!arc.aiming(), "자격이 없으면 press를 무시한다");
	}

	// ------------------------------------------------------- proxy(Embree)

	/** 실제 Raycaster에 작은 상자를 넣어 proxy 충돌을 확인한다. */
	void testProxyObstacle()
	{
		GroundedFPSController::Ptr grounded = makeGrounded(false);
		const double eye[3] = { 5.0, 10.0, sibr::grounded::EYE_HEIGHT_M };

		// 궤적 앞 2 m 지점에 세로 판을 세운다. identity transform이라 metric=scene이다.
		sibr::Mesh wall;
		sibr::Mesh::Vertices vertices;
		sibr::Mesh::Triangles triangles;
		const float x = 7.0f;
		vertices.push_back(sibr::Vector3f(x, 8.0f, 0.0f));
		vertices.push_back(sibr::Vector3f(x, 12.0f, 0.0f));
		vertices.push_back(sibr::Vector3f(x, 12.0f, 3.0f));
		vertices.push_back(sibr::Vector3f(x, 8.0f, 3.0f));
		triangles.push_back(sibr::Vector3u(0, 1, 2));
		triangles.push_back(sibr::Vector3u(0, 2, 3));
		wall.vertices(vertices);
		wall.triangles(triangles);

		std::shared_ptr<sibr::Raycaster> raycaster = std::make_shared<sibr::Raycaster>();
		check(raycaster->init(), "Embree Raycaster를 초기화한다");
		check(raycaster->addMesh(wall) != sibr::Raycaster::InvalidGeomId, "proxy mesh를 넣는다");

		ArcTeleportController blocked(grounded, raycaster);
		sibr::Vector3f target;
		sibr::TeleportPreview preview;
		const bool committed = runAim(blocked, *grounded, eye, 1.0, 0.0, 0.0, target, preview);
		check(preview.endpoint == TeleportEndpoint::Obstacle, "proxy가 바닥보다 먼저 궤적을 끊는다");
		check(!preview.valid && !committed, "proxy에 막히면 commit하지 않는다");

		// 같은 조준이라도 proxy가 없으면 바닥까지 간다.
		ArcTeleportController free(grounded, nullptr);
		sibr::TeleportPreview open;
		const bool freeCommit = runAim(free, *grounded, eye, 1.0, 0.0, 0.0, target, open);
		check(open.endpoint == TeleportEndpoint::Floor && freeCommit,
			"proxy가 없으면 같은 조준이 바닥까지 간다");

		// 궤적보다 훨씬 뒤에 있는 proxy는 무시한다(Raycaster는 무한 ray라서 자르지 않으면 걸린다).
		sibr::Mesh farWall;
		sibr::Mesh::Vertices farVertices;
		sibr::Mesh::Triangles farTriangles;
		const float farX = 18.0f;
		farVertices.push_back(sibr::Vector3f(farX, 8.0f, 0.0f));
		farVertices.push_back(sibr::Vector3f(farX, 12.0f, 0.0f));
		farVertices.push_back(sibr::Vector3f(farX, 12.0f, 3.0f));
		farVertices.push_back(sibr::Vector3f(farX, 8.0f, 3.0f));
		farTriangles.push_back(sibr::Vector3u(0, 1, 2));
		farTriangles.push_back(sibr::Vector3u(0, 2, 3));
		farWall.vertices(farVertices);
		farWall.triangles(farTriangles);

		std::shared_ptr<sibr::Raycaster> farCaster = std::make_shared<sibr::Raycaster>();
		farCaster->init();
		farCaster->addMesh(farWall);
		ArcTeleportController beyond(grounded, farCaster);
		sibr::TeleportPreview far;
		const bool farCommit = runAim(beyond, *grounded, eye, 1.0, 0.0, 0.0, target, far);
		check(far.endpoint == TeleportEndpoint::Floor && farCommit,
			"구간 길이 밖의 proxy는 무시한다");
	}

} // namespace

int main()
{
	char pattern[] = "/tmp/arc_teleport_XXXXXX";
	const char* directory = mkdtemp(pattern);
	if (directory == nullptr) {
		std::cerr << "임시 디렉터리를 만들 수 없습니다." << std::endl;
		return 1;
	}
	g_root = directory;
	writeFile(tempPath("room_envelope_metric.obj"), roomObj(20.0));

	testHorizontalRange(false);
	testHorizontalRange(true);
	testUpAndDownAim();
	testWallBeforeFloor();
	testOutsideFloorAndClearance();
	testNoGroundCap();
	testLengthCap();
	testNaNAim();
	testStateMachine();
	testCancelPaths();
	testProxyObstacle();

	std::cout << (g_failures == 0 ? "arc_teleport: all ok" : "arc_teleport: FAILED") << std::endl;
	return g_failures == 0 ? 0 : 1;
}
