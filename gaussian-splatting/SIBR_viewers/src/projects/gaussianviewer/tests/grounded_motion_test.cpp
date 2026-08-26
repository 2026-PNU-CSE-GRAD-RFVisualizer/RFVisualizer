/*
 * RFVisualizer: --grounded-fps 의 2D 충돌 solver·navigation geometry·좌표 계약 검증.
 *
 * 새 Test Framework를 넣지 않는다. assertion과 CTest만 쓴다.
 * GL/CUDA/SIBR 라이브러리 없이 GroundedFPSController.cpp 하나만 컴파일해 돌린다.
 */
#include "projects/gaussianviewer/renderer/GroundedFPSController.hpp"

#include <sys/stat.h>

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using sibr::GroundedFPSController;
using sibr::GroundedPoint2;
using sibr::GroundedSegment;
using sibr::GroundedTriangle2;
using sibr::groundedResolve;

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

	const double RADIUS = sibr::grounded::BODY_RADIUS_M;
	const double EPS = sibr::grounded::EPSILON_M;

	GroundedSegment segment(double ax, double ay, double bx, double by)
	{
		GroundedSegment s;
		s.a.x = ax; s.a.y = ay; s.b.x = bx; s.b.y = by;
		return s;
	}

	GroundedPoint2 point(double x, double y)
	{
		GroundedPoint2 p;
		p.x = x; p.y = y;
		return p;
	}

	double distanceToSegment(const GroundedSegment& s, const GroundedPoint2& p)
	{
		const double ex = s.b.x - s.a.x, ey = s.b.y - s.a.y;
		const double lengthSq = ex * ex + ey * ey;
		double t = (lengthSq > 0.0) ? (((p.x - s.a.x) * ex + (p.y - s.a.y) * ey) / lengthSq) : 0.0;
		t = std::min(1.0, std::max(0.0, t));
		const double dx = p.x - (s.a.x + t * ex), dy = p.y - (s.a.y + t * ey);
		return std::sqrt(dx * dx + dy * dy);
	}

	// ---------------------------------------------------------------- solver

	/** y=0에 놓인 아주 긴 벽 하나. 몸은 y>0 쪽에 있다. */
	std::vector<GroundedSegment> singleWall()
	{
		return { segment(-100.0, 0.0, 100.0, 0.0) };
	}

	void testFreeMove()
	{
		const GroundedPoint2 end = groundedResolve(singleWall(), point(0.0, 5.0), point(1.0, 5.0));
		check(std::abs(end.x - 1.0) < 1e-6 && std::abs(end.y - 5.0) < 1e-6,
			"벽에서 먼 이동은 그대로 통과한다");
	}

	void testFrontalStop()
	{
		const std::vector<GroundedSegment> walls = singleWall();
		const GroundedPoint2 end = groundedResolve(walls, point(0.0, 1.0), point(0.0, -1.0));
		check(distanceToSegment(walls[0], end) >= RADIUS - EPS, "정면 충돌은 반경 앞에서 멈춘다");
		check(end.y > 0.0, "정면 충돌이 벽 반대편으로 넘어가지 않는다");
		check(std::abs(end.y - RADIUS) < 5.0 * EPS, "정면 충돌은 정확히 반경 거리에 선다");
	}

	void testDiagonalSlide()
	{
		const std::vector<GroundedSegment> walls = singleWall();
		// W+D 처럼 벽 쪽으로 45도로 밀어붙인다. 접선(x) 성분은 살아 있어야 한다.
		const GroundedPoint2 start = point(0.0, RADIUS);
		const GroundedPoint2 end = groundedResolve(walls, start, point(1.0, RADIUS - 1.0));
		check(distanceToSegment(walls[0], end) >= RADIUS - EPS, "대각선 충돌도 벽을 뚫지 않는다");
		check(end.x > 0.9, "대각선 충돌은 접선 방향 이동을 유지한다(wall slide)");
	}

	void testCornerStop()
	{
		// x=0과 y=0 두 벽이 만드는 안쪽 모서리. 몸은 (+,+) 사분면에 있다.
		const std::vector<GroundedSegment> walls = {
			segment(0.0, -100.0, 0.0, 100.0),
			segment(-100.0, 0.0, 100.0, 0.0),
		};
		const GroundedPoint2 end = groundedResolve(walls, point(2.0, 2.0), point(-1.0, -1.0));
		check(std::isfinite(end.x) && std::isfinite(end.y), "모서리에서도 유한한 위치를 돌려준다");
		check(distanceToSegment(walls[0], end) >= RADIUS - EPS
			&& distanceToSegment(walls[1], end) >= RADIUS - EPS, "두 벽 모서리에서 멈춘다");
		check(end.x > 0.0 && end.y > 0.0, "모서리를 지나 반대편으로 새지 않는다");
	}

	void testNoTunneling()
	{
		const std::vector<GroundedSegment> walls = singleWall();
		// 한 Frame에 2 m를 제안해도 두께 0인 벽을 지나칠 수 없다.
		const GroundedPoint2 end = groundedResolve(walls, point(0.0, 1.0), point(0.0, -1.0));
		check(end.y >= RADIUS - EPS, "2 m 제안 이동에서도 벽을 통과하지 않는다");

		// 얇은 벽 조각도 같다. 벽 조각이 이동 경로 중간에 있어도 지나칠 수 없다.
		const std::vector<GroundedSegment> shortWall = { segment(-0.5, 0.0, 0.5, 0.0) };
		const GroundedPoint2 through = groundedResolve(shortWall, point(0.0, 1.5), point(0.0, -0.5));
		check(through.y >= RADIUS - EPS, "짧은 벽 조각도 한 번에 지나치지 않는다");
	}

	void testOversizedAndNaN()
	{
		const std::vector<GroundedSegment> walls = singleWall();
		const GroundedPoint2 start = point(0.0, 5.0);

		const GroundedPoint2 far = groundedResolve(walls, start, point(0.0, 200.0));
		check(std::abs(far.y - 5.0) < 1e-9, "8 m를 넘는 제안 이동은 마지막 안전 위치에 남는다");

		const double nan = std::nan("");
		const GroundedPoint2 broken = groundedResolve(walls, start, point(nan, 5.0));
		check(std::abs(broken.y - 5.0) < 1e-9 && std::isfinite(broken.x),
			"NaN 후보는 마지막 안전 위치에 남는다");

		const GroundedPoint2 tiny = groundedResolve(walls, start, point(0.0, 5.0 + 1e-9));
		check(std::isfinite(tiny.x) && std::isfinite(tiny.y), "0에 가까운 이동도 유한하다");
	}

	// ------------------------------------------------------- bundle fixtures

	std::string g_tempRoot;

	std::string tempPath(const std::string& name)
	{
		return g_tempRoot + "/" + name;
	}

	void writeFile(const std::string& path, const std::string& body)
	{
		std::ofstream stream(path);
		stream << body;
	}

	/** 한 변 10 m 정사각 방. 바닥(z=0)·천장(z=3)·벽 4장 + 바닥 안의 마커 상자 하나. */
	std::string roomObj()
	{
		std::ostringstream obj;
		const double side = 10.0, top = 3.0;
		// 1..4 바닥, 5..8 천장
		obj << "v 0 0 0\nv " << side << " 0 0\nv " << side << " " << side << " 0\nv 0 " << side << " 0\n";
		obj << "v 0 0 " << top << "\nv " << side << " 0 " << top << "\nv " << side << " " << side
			<< " " << top << "\nv 0 " << side << " " << top << "\n";
		obj << "f 1 2 3\nf 1 3 4\n";        // 바닥
		obj << "f 5 6 7\nf 5 7 8\n";        // 천장 (충돌에서 빠져야 한다)
		obj << "f 1 2 6\nf 1 6 5\n";        // y=0 벽
		obj << "f 2 3 7\nf 2 7 6\n";        // x=side 벽
		obj << "f 3 4 8\nf 3 8 7\n";        // y=side 벽
		obj << "f 4 1 5\nf 4 5 8\n";        // x=0 벽
		obj << "f 1 1 2\n";                 // 찌그러진 삼각형 (빠져야 한다)
		return obj.str();
	}

	std::string manifestJson(const std::vector<std::string>& meshFiles, bool identityTransform)
	{
		std::ostringstream json;
		json.precision(17);
		json << "{\"T_scene_from_metric\":[";
		// 회전+배율이 섞인 transform으로도 왕복이 맞아야 한다.
		const double rotated[16] = {
			 0.0, -2.0,  0.0,  1.0,
			 2.0,  0.0,  0.0, -3.0,
			 0.0,  0.0,  2.0,  0.5,
			 0.0,  0.0,  0.0,  1.0
		};
		const double identity[16] = { 1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1 };
		const double* m = identityTransform ? identity : rotated;
		for (int row = 0; row < 4; ++row) {
			json << (row ? ",[" : "[");
			for (int column = 0; column < 4; ++column) {
				json << (column ? "," : "") << m[row * 4 + column];
			}
			json << "]";
		}
		json << "],\"occlusion_meshes\":[";
		for (size_t index = 0; index < meshFiles.size(); ++index) {
			json << (index ? "," : "") << "{\"file\":\"" << meshFiles[index] << "\"}";
		}
		json << "]}";
		return json.str();
	}

	bool constructionFails(const std::string& manifestPath, const std::string& name)
	{
		try {
			GroundedFPSController controller(manifestPath);
		} catch (const std::runtime_error& error) {
			std::cout << "      진단: " << error.what() << std::endl;
			check(true, name);
			return true;
		}
		check(false, name);
		return false;
	}

	void testBundleContract()
	{
		writeFile(tempPath("room_envelope_metric.obj"), roomObj());
		// marker mesh는 이름이 달라 선택되지 않는다. 안에 벽 같은 면이 있어도 무시된다.
		writeFile(tempPath("proxy_objects_metric.obj"), roomObj());

		// manifest 순서를 뒤집어도 같은 mesh를 고른다.
		writeFile(tempPath("ordered.json"),
			manifestJson({ "room_envelope_metric.obj", "proxy_objects_metric.obj" }, true));
		writeFile(tempPath("reversed.json"),
			manifestJson({ "proxy_objects_metric.obj", "room_envelope_metric.obj" }, true));
		GroundedFPSController ordered(tempPath("ordered.json"));
		GroundedFPSController reversed(tempPath("reversed.json"));
		check(ordered.walls().size() == reversed.walls().size()
			&& ordered.floor().size() == reversed.floor().size(),
			"manifest 순서가 바뀌어도 같은 navigation mesh를 고른다");

		// 벽 4장 x 2삼각형 x 3변 중 XY 길이가 0인 수직 변은 빠진다 => 장당 4개.
		check(ordered.walls().size() == 16, "수직면의 XY 변만 벽이 된다");
		check(ordered.floor().size() == 2, "바닥 삼각형만 남고 천장은 빠진다");
		check(ordered.insideFloor(point(5.0, 5.0)), "방 안은 바닥 안이다");
		check(!ordered.insideFloor(point(-1.0, 5.0)), "방 밖은 바닥 밖이다");

		writeFile(tempPath("missing.json"), manifestJson({ "proxy_objects_metric.obj" }, true));
		constructionFails(tempPath("missing.json"), "room envelope가 없으면 시작 오류다");

		writeFile(tempPath("duplicate.json"),
			manifestJson({ "room_envelope_metric.obj", "a/room_envelope_metric.obj" }, true));
		constructionFails(tempPath("duplicate.json"), "room envelope가 둘이면 시작 오류다");

		writeFile(tempPath("singular.json"), "{\"T_scene_from_metric\":"
			"[[0,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],"
			"\"occlusion_meshes\":[{\"file\":\"room_envelope_metric.obj\"}]}");
		constructionFails(tempPath("singular.json"), "특이 transform은 시작 오류다");

		writeFile(tempPath("nan.json"), "{\"T_scene_from_metric\":"
			"[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,1,1]],"
			"\"occlusion_meshes\":[{\"file\":\"room_envelope_metric.obj\"}]}");
		constructionFails(tempPath("nan.json"), "affine이 아닌 마지막 행은 시작 오류다");

		// 바닥만 있고 수직면이 없으면 시작 오류다.
		mkdir(tempPath("flat").c_str(), 0700);
		writeFile(tempPath("flat/room_envelope_metric.obj"), "v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n");
		writeFile(tempPath("wallless.json"), manifestJson({ "flat/room_envelope_metric.obj" }, true));
		constructionFails(tempPath("wallless.json"), "벽으로 쓸 수직면이 없으면 시작 오류다");
	}

	void testTransformRoundTrip()
	{
		writeFile(tempPath("rotated.json"),
			manifestJson({ "room_envelope_metric.obj" }, false));
		GroundedFPSController controller(tempPath("rotated.json"));

		const double metric[3] = { 5.0, 4.0, 1.7 };
		double scene[3], back[3];
		controller.toScene(metric, scene);
		controller.toMetric(scene, back);
		check(std::abs(back[0] - metric[0]) < 1e-4 && std::abs(back[1] - metric[1]) < 1e-4
			&& std::abs(back[2] - metric[2]) < 1e-4,
			"회전+배율 transform도 metric↔scene 왕복이 맞는다");
	}

	void testStartAndConstrain()
	{
		writeFile(tempPath("rotated.json"),
			manifestJson({ "room_envelope_metric.obj" }, false));
		GroundedFPSController controller(tempPath("rotated.json"));

		// 방 한가운데. 높이는 아무 값이나 줘도 1.7 m로 스냅되고 XY는 그대로다.
		const double insideMetric[3] = { 5.0, 5.0, 12.0 };
		double insideScene[3], snapped[3], snappedMetric[3];
		controller.toScene(insideMetric, insideScene);
		check(!controller.snapStart(insideScene, snapped), "유효한 시작 위치는 옮기지 않는다");
		controller.toMetric(snapped, snappedMetric);
		check(std::abs(snappedMetric[2] - sibr::grounded::EYE_HEIGHT_M) < 1e-4,
			"시작 pose는 눈높이 1.7 m로 스냅된다");
		check(std::abs(snappedMetric[0] - 5.0) < 1e-4 && std::abs(snappedMetric[1] - 5.0) < 1e-4,
			"시작 스냅이 XY를 옮기지 않는다");

		// 바닥 밖(방 왼쪽 5 m 바깥)에서 시작하면 가장 가까운 유효 위치로 옮긴다.
		const double outsideMetric[3] = { -5.0, 5.0, 1.7 };
		double outsideScene[3], movedScene[3], movedMetric[3];
		controller.toScene(outsideMetric, outsideScene);
		check(controller.snapStart(outsideScene, movedScene), "바닥 밖 시작 위치는 옮겼다고 알린다");
		controller.toMetric(movedScene, movedMetric);
		const GroundedPoint2 moved = point(movedMetric[0], movedMetric[1]);
		check(controller.insideFloor(moved), "옮긴 위치는 바닥 안이다");
		check(controller.clearance(moved) >= RADIUS - EPS, "옮긴 위치는 벽에서 반경 이상 떨어져 있다");
		check(std::abs(movedMetric[2] - sibr::grounded::EYE_HEIGHT_M) < 1e-4,
			"옮긴 위치도 눈높이 1.7 m다");
		// x=0 벽 바로 안쪽이 가장 가깝다. y는 거의 그대로여야 한다.
		check(std::abs(movedMetric[0] - RADIUS) < 0.5, "가장 가까운 쪽(왼쪽 벽 안)으로 옮긴다");
		check(std::abs(movedMetric[1] - 5.0) < 1.0, "옮길 때 엉뚱하게 먼 곳으로 가지 않는다");

		// 벽에 박힌 채 시작해도 같은 방식으로 빠져나온다.
		const double insideWallMetric[3] = { 0.05, 5.0, 1.7 };   // 벽에서 0.05 m
		double insideWallScene[3], freedScene[3], freedMetric[3];
		controller.toScene(insideWallMetric, insideWallScene);
		check(controller.snapStart(insideWallScene, freedScene), "벽에 박힌 시작 위치는 옮겼다고 알린다");
		controller.toMetric(freedScene, freedMetric);
		check(controller.clearance(point(freedMetric[0], freedMetric[1])) >= RADIUS - EPS,
			"벽에서 빠져나온 위치는 반경 이상 떨어져 있다");

		// 옮긴 자리에서 바로 걸어도 벽을 뚫지 않는다.
		double walkScene[3];
		const double walkTarget[3] = { movedMetric[0] - 2.0, movedMetric[1], sibr::grounded::EYE_HEIGHT_M };
		double walkTargetScene[3];
		controller.toScene(walkTarget, walkTargetScene);
		controller.constrain(movedScene, walkTargetScene, walkScene);
		double walkMetric[3];
		controller.toMetric(walkScene, walkMetric);
		check(controller.clearance(point(walkMetric[0], walkMetric[1])) >= RADIUS - EPS,
			"옮긴 자리에서 벽 쪽으로 걸어도 벽을 뚫지 않는다");

		// scene 좌표로 들어가 scene 좌표로 나오는 제약. x=0 벽을 향해 밀어붙인다.
		const double fromMetric[3] = { 1.0, 5.0, 1.7 };
		const double toMetric[3] = { -1.0, 5.0, 1.7 };
		double fromScene[3], toScene[3], fixedScene[3], fixedMetric[3];
		controller.toScene(fromMetric, fromScene);
		controller.toScene(toMetric, toScene);
		controller.constrain(fromScene, toScene, fixedScene);
		controller.toMetric(fixedScene, fixedMetric);
		check(fixedMetric[0] >= RADIUS - EPS, "scene 좌표 제약이 벽 앞에서 멈춘다");
		check(std::abs(fixedMetric[2] - sibr::grounded::EYE_HEIGHT_M) < 1e-4,
			"제약 결과의 높이는 항상 1.7 m다");

		// NaN 후보가 들어와도 pose가 깨지지 않는다.
		const double brokenScene[3] = { std::nan(""), toScene[1], toScene[2] };
		double keptScene[3];
		controller.constrain(fromScene, brokenScene, keptScene);
		check(std::isfinite(keptScene[0]) && std::isfinite(keptScene[1]) && std::isfinite(keptScene[2]),
			"NaN 후보에서도 유한한 pose를 유지한다");
	}

	/** 실제 Bundle이 있으면 같이 본다. 없으면 건너뛴다. */
	void testRealBundle()
	{
		const char* fromEnv = std::getenv("RF_VOLUME_MANIFEST");
		const std::string path = fromEnv ? fromEnv
			: "/data/RFVisualizer_Workspace/experiments/0821_lounge_201729/analysis/viewer_volume/manifest.json";
		std::ifstream probe(path);
		if (!probe.good()) {
			std::cout << "skip: 실제 RF Bundle이 없어 건너뜁니다 (" << path << ")" << std::endl;
			return;
		}
		probe.close();
		try {
			GroundedFPSController controller(path);
			check(!controller.walls().empty() && !controller.floor().empty(),
				"실제 Bundle에서 바닥과 벽을 얻는다");
			std::cout << "      실제 Bundle: 벽 " << controller.walls().size()
				<< "개, 바닥 " << controller.floor().size() << "개" << std::endl;

			// 복도에서 한참 떨어진 곳에서 시작해도 유효 위치를 찾고, 시작할 때 한 번 도는
			// 비용이라 오래 걸리지 않아야 한다.
			const auto began = std::chrono::steady_clock::now();
			GroundedPoint2 rescued;
			const bool ok = controller.nearestValidStand(point(-500.0, -500.0), rescued);
			const double milliseconds = std::chrono::duration<double, std::milli>(
				std::chrono::steady_clock::now() - began).count();
			check(ok, "실제 Bundle에서 멀리 떨어진 시작 위치도 유효 위치를 찾는다");
			if (ok) {
				check(controller.insideFloor(rescued) && controller.clearance(rescued) >= RADIUS - EPS,
					"실제 Bundle에서 찾은 위치는 바닥 안이고 벽에서 반경 이상 떨어져 있다");
				std::cout << "      옮긴 위치 metric XY (" << rescued.x << ", " << rescued.y
					<< "), 탐색 " << milliseconds << " ms" << std::endl;
			}
			check(milliseconds < 500.0, "시작 위치 탐색이 0.5초 안에 끝난다");
		} catch (const std::runtime_error& error) {
			check(false, std::string("실제 Bundle 구성 실패: ") + error.what());
		}
	}

} // namespace

int main()
{
	char pattern[] = "/tmp/grounded_motion_XXXXXX";
	const char* directory = mkdtemp(pattern);
	if (directory == nullptr) {
		std::cerr << "임시 디렉터리를 만들 수 없습니다." << std::endl;
		return 1;
	}
	g_tempRoot = directory;

	testFreeMove();
	testFrontalStop();
	testDiagonalSlide();
	testCornerStop();
	testNoTunneling();
	testOversizedAndNaN();
	testBundleContract();
	testTransformRoundTrip();
	testStartAndConstrain();
	testRealBundle();

	std::cout << (g_failures == 0 ? "grounded_motion: all ok" : "grounded_motion: FAILED") << std::endl;
	return g_failures == 0 ? 0 : 1;
}
