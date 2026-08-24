#version 420

// RF dBm Volume을 Metric 좌표계에서 Ray Marching으로 합성한다.
// 결과는 premultiplied alpha라서 glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)로 섞는다.

in vec2 vertex_uv;
out vec4 out_color;

uniform sampler3D volume;      // RGB=dBm*mask(premultiplied), A=valid mask
uniform sampler2D proxyDepth;  // Proxy Mesh의 NDC depth, 1.0이면 가리는 것이 없다

uniform mat4 invSceneClip;         // sceneClipFromScene의 역행렬
uniform mat4 metricFromScene;
uniform mat4 clipFromMetric;       // sceneClipFromScene * sceneFromMetric

uniform vec3 boxMinM;          // Volume AABB (metric)
uniform vec3 boxMaxM;
uniform vec2 zCutM;            // 표시할 metric z 범위
uniform vec2 dbmRange;
uniform vec3 cameraPosScene;
uniform float stepM;           // metric sampling step
uniform float extinctionPerM;  // 1 m를 지날 때 흡수되는 정도
uniform int method;            // 0=raw, 1=plain idw, 2=residual idw

const float ALPHA_TERMINATE = 0.98;
const int MAX_STEPS = 512;

// Viridis 다항식 근사 (Matplotlib 색상표와 눈으로 구분되지 않는 수준).
vec3 viridis(float t) {
	t = clamp(t, 0.0, 1.0);
	const vec3 c0 = vec3(0.2777273272, 0.0054929071, 0.3340998053);
	const vec3 c1 = vec3(0.1050930431, 1.4041130090, 1.3838529480);
	const vec3 c2 = vec3(-0.3308618287, 0.2148069155, 0.0951729760);
	const vec3 c3 = vec3(-4.6340841690, -5.7991383780, -19.3324110500);
	const vec3 c4 = vec3(6.2280298450, 14.1799931900, 56.6905030000);
	const vec3 c5 = vec3(4.7763934750, -13.7451150600, -65.3532564000);
	const vec3 c6 = vec3(-5.4354827630, 4.6459544060, 26.3124352000);
	return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}

// Ray와 축 정렬 상자의 교차 구간. 없으면 x > y로 돌려준다.
vec2 slab(vec3 origin, vec3 direction, vec3 lo, vec3 hi) {
	vec3 inverse = 1.0 / direction;
	vec3 a = (lo - origin) * inverse;
	vec3 b = (hi - origin) * inverse;
	vec3 near = min(a, b);
	vec3 far = max(a, b);
	return vec2(max(max(near.x, near.y), near.z), min(min(far.x, far.y), far.z));
}

void main(void) {
	// 화면 픽셀을 scene 좌표의 Ray로 되돌린다.
	vec4 farPoint = invSceneClip * vec4(vertex_uv * 2.0 - 1.0, 1.0, 1.0);
	vec3 sceneDirection = normalize(farPoint.xyz / farPoint.w - cameraPosScene);

	// Volume은 metric 좌표에서만 축 정렬이라 Ray를 metric으로 옮겨 진행한다.
	vec3 origin = (metricFromScene * vec4(cameraPosScene, 1.0)).xyz;
	vec3 direction = mat3(metricFromScene) * sceneDirection;
	float unitLength = length(direction);
	if (unitLength <= 0.0) {
		discard;
	}
	direction /= unitLength;   // 이제 t는 metric meter다.

	vec3 lo = vec3(boxMinM.xy, max(boxMinM.z, zCutM.x));
	vec3 hi = vec3(boxMaxM.xy, min(boxMaxM.z, zCutM.y));
	if (any(greaterThanEqual(lo, hi))) {
		discard;
	}
	vec2 span = slab(origin, direction, lo, hi);
	span.x = max(span.x, 0.0);
	if (span.x >= span.y) {
		discard;
	}

	float occluder = texture(proxyDepth, vertex_uv).r;
	vec3 extent = boxMaxM - boxMinM;
	vec3 accumulated = vec3(0.0);
	float alpha = 0.0;

	for (int index = 0; index < MAX_STEPS; ++index) {
		float t = span.x + (float(index) + 0.5) * stepM;
		if (t >= span.y || alpha >= ALPHA_TERMINATE) {
			break;
		}
		vec3 position = origin + t * direction;

		// Proxy Mesh보다 뒤면 벽 반대편이므로 그 뒤는 전부 버린다.
		vec4 clip = clipFromMetric * vec4(position, 1.0);
		if (clip.w > 0.0 && (clip.z / clip.w) > occluder) {
			break;
		}

		vec4 sampled = texture(volume, (position - boxMinM) / extent);
		float validity = sampled.a;
		if (validity < 0.02) {
			continue;
		}
		// premultiplied로 저장했으므로 mask로 나눠야 유효 voxel만의 평균이 된다.
		float dbm = sampled[method] / validity;
		float normalized = (dbm - dbmRange.x) / max(dbmRange.y - dbmRange.x, 1e-6);
		// 걸어간 거리에 비례한 흡수라야 sampling step을 바꿔도 밝기가 그대로다.
		float sampleAlpha = (1.0 - exp(-extinctionPerM * stepM)) * clamp(validity, 0.0, 1.0);
		accumulated += (1.0 - alpha) * sampleAlpha * viridis(normalized);
		alpha += (1.0 - alpha) * sampleAlpha;
	}

	if (alpha <= 0.0) {
		discard;
	}
	out_color = vec4(accumulated, alpha);
}
