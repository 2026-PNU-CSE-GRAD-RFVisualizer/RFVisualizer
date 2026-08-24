#version 420

layout(location = 0) in vec3 in_vertex;

out vec2 vertex_uv;

void main(void) {
	vertex_uv = in_vertex.xy * 0.5 + 0.5;
	gl_Position = vec4(in_vertex.xy, 0.0, 1.0);
}
