#version 420

uniform vec3 overlayColor;

out vec4 out_color;

void main(void) {
	out_color = vec4(overlayColor, 1.0);
}
