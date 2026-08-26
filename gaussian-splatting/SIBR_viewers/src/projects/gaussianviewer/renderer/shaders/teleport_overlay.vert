#version 420

layout(location = 0) in vec3 in_vertex;

uniform mat4 MVP;

void main(void) {
	gl_Position = MVP * vec4(in_vertex, 1.0);
}
