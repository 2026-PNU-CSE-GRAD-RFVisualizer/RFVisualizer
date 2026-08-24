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


#pragma once

#include <memory>
#include <fstream>

#include "Config.hpp"
#include "core/graphics/Shader.hpp"
#include "core/assets/InputCamera.hpp"
#include "ICameraHandler.hpp"


namespace sibr {

	class Viewport;
	class Mesh;
	class Input;

	/** Interactive camera that can be moved using WASD keys.
	* \ingroup sibr_view
	*/
	class SIBR_VIEW_EXPORT FPSCamera : public ICameraHandler
	{
	
	public:

		/**
		 Default constructor.
		*/
		FPSCamera( void );

		/**
			Setup the FPS camera so that it has the same pose as the argument camera. 
		\param cam the reference camera
		*/
		void fromCamera(const sibr::InputCamera & cam);

		/**
			Update the FPS camera based on the user input (keyboard). 
		\param input the user input
		\param deltaTime time elapsed since last update
		*/
		void update( const sibr::Input & input, float deltaTime);

		/** Move to a camera position/orientation that is a distance-wieghted combination of the given cameras.
		\param cams the cameras list.
		*/
		void snap(const std::vector<InputCamera::Ptr> & cams);

		// ICameraHandler interface

		/** Update the FPS camera based on the user input.
		\param input the user input
		\param deltaTime time elapsed since last update
		\param viewport the view viewport
		*/
		virtual void update(const sibr::Input & input, const float deltaTime, const Viewport & viewport) override;

		/** \return the current camera */
		virtual const sibr::InputCamera & getCamera( void ) const override;

		/** Set the camera speed.
		\param speed translation speed
		\param angular rotation speed
		*/
		void setSpeed(const float speed, const float angular = 0.0);

		/** Dispaly GUI.
		\param suffix Panel title suffix
		*/
		virtual void onGUI(const std::string& suffix) override;

		void setGoalAltitude(const float& goalAltitude);

	private:

		float _speedFpsCam, _speedRotFpsCam; ///< Camera speeds.
		bool _hasBeenInitialized; ///< Has the camera been initialized.
		sibr::InputCamera _currentCamera; ///< Current camera.
		bool _useAcceleration; ///< Should the camera accelerate the longer keys are pressed.
		float _goalAltitude;
		float _mouseLookSpeed = 0.15f;    ///< 마우스 1 px 당 회전 각도(도).
		bool _looking = false;            ///< 오른쪽 버튼 드래그로 시점을 돌리는 중인지.
		sibr::Viewport _viewport;         ///< 이 카메라가 그려지는 화면 영역.
		bool _worldUpResolved = false;    ///< world up 을 이미 정했는지.
		sibr::Vector3f _worldUp = sibr::Vector3f(0.f, 1.f, 0.f); ///< 수평을 유지할 기준 축.

		/** Update camera pose based on keys. 
		\param input user input
		\param deltaTime elapsed time
		*/
		void moveUsingWASD( const sibr::Input& input, float deltaTime);

		/** Update camera pose based on mouse.
		\param input user input
		\param deltaTime elapsed time
		*/
		void moveUsingMousePan( const sibr::Input& input, float deltaTime);

		/** 오른쪽 버튼 드래그로 시점을 돌린다(Unity Scene View 방식).
		\param input user input
		\return 이번 Frame에 시점을 돌렸으면 true */
		bool lookUsingMouse();
	
	};

}
