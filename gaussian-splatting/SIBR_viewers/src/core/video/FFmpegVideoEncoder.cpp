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


#include "FFmpegVideoEncoder.hpp"

#ifndef HEADLESS
extern "C"
{
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
}
#endif

#define QQ(rat) (rat.num/(double)rat.den)

// Disable ffmpeg deprecation warning.
#pragma warning(disable : 4996)

namespace sibr {

	bool FFVideoEncoder::ffmpegInitDone = false;

	FFVideoEncoder::FFVideoEncoder(
		const std::string & _filepath,
		double _fps,
		const sibr::Vector2i & size,
		bool forceResize
	) : filepath(_filepath), fps(_fps), _forceResize(forceResize)
	{
	}

	bool FFVideoEncoder::isFine() const
	{
		return true;
	}

	void FFVideoEncoder::close()
	{
	}

	FFVideoEncoder::~FFVideoEncoder()
	{
	}

	void FFVideoEncoder::init(const sibr::Vector2i & size)
	{
	}


	bool FFVideoEncoder::operator<<(cv::Mat frame)
	{
		return true;
	}

	bool FFVideoEncoder::operator<<(const sibr::ImageRGB & frame){
		return true;
	}

#ifndef HEADLESS
	bool FFVideoEncoder::encode(AVFrame * frame)
	{
		return true;
	}
#endif

}
