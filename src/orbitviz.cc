// __BEGIN_LICENSE__
// 
// Copyright (C) 2008 United States Government as represented by the
// Administrator of the National Aeronautics and Space Administration
// (NASA).  All Rights Reserved.
// 
// Copyright 2008 Carnegie Mellon University. All rights reserved.
// 
// This software is distributed under the NASA Open Source Agreement
// (NOSA), version 1.3.  The NOSA has been approved by the Open Source
// Initiative.  See the file COPYING at the top of the distribution
// directory tree for the complete NOSA document.
// 
// THE SUBJECT SOFTWARE IS PROVIDED "AS IS" WITHOUT ANY WARRANTY OF ANY
// KIND, EITHER EXPRESSED, IMPLIED, OR STATUTORY, INCLUDING, BUT NOT
// LIMITED TO, ANY WARRANTY THAT THE SUBJECT SOFTWARE WILL CONFORM TO
// SPECIFICATIONS, ANY IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR
// A PARTICULAR PURPOSE, OR FREEDOM FROM INFRINGEMENT, ANY WARRANTY THAT
// THE SUBJECT SOFTWARE WILL BE ERROR FREE, OR ANY WARRANTY THAT
// DOCUMENTATION, IF PROVIDED, WILL CONFORM TO THE SUBJECT SOFTWARE.
//
// __END_LICENSE__

/// \file orbitviz.cc
///

/************************************************************************
 *     File: orbitviz.cc
 ************************************************************************/
#include <boost/algorithm/string.hpp>
#include <boost/program_options.hpp>
#include <boost/filesystem/path.hpp>
#include <boost/filesystem/operations.hpp>
#include <boost/filesystem/convenience.hpp>
#include <boost/filesystem/fstream.hpp>
using namespace boost;
namespace po = boost::program_options;
namespace fs = boost::filesystem;

#include <vw/Core.h>
#include <vw/Image.h>
#include <vw/Math.h>
#include <vw/FileIO.h>
#include <vw/Camera.h>
#include <vw/Stereo.h>
#include <vw/Cartography.h>
using namespace vw;
using namespace vw::camera;
using namespace vw::stereo;
using namespace vw::cartography;

#include "stereo.h"
#include "StereoSession.h"
#include "SurfaceNURBS.h"
#include "MRO/DiskImageResourceDDD.h"	   // support for Malin DDD image files
#include "KML.h"

#if defined(ASP_HAVE_PKG_ISIS) && ASP_HAVE_PKG_ISIS == 1 
#include "Isis/DiskImageResourceIsis.h"
#include "Isis/StereoSessionIsis.h"
#endif

#if defined(ASP_HAVE_PKG_SPICE) && ASP_HAVE_PKG_SPICE == 1
#include "HRSC/StereoSessionHRSC.h"
#include "MOC/StereoSessionMOC.h"
#include "MRO/StereoSessionCTX.h"
#endif

using namespace std;

// Allows FileIO to correctly read/write these pixel types
namespace vw {
  template<> struct PixelFormatID<Vector3>   { static const PixelFormatEnum value = VW_PIXEL_GENERIC_3_CHANNEL; };
  template<> struct PixelFormatID<PixelDisparity<float> >   { static const PixelFormatEnum value = VW_PIXEL_GENERIC_3_CHANNEL; };
}

//***********************************************************************
// MAIN
//***********************************************************************

int main(int argc, char* argv[]) {

  // Register the DDD file handler with the Vision Workbench
  // DiskImageResource system.  DDD is the proprietary format used by
  // Malin Space Science Systems.
  DiskImageResource::register_file_type(".ddd",
                                        DiskImageResourceDDD::type_static(),
                                        &DiskImageResourceDDD::construct_open,
                                        &DiskImageResourceDDD::construct_create);
  
#if defined(ASP_HAVE_PKG_ISIS) && ASP_HAVE_PKG_ISIS == 1 
  // Register the Isis file handler with the Vision Workbench
  // DiskImageResource system.
  DiskImageResource::register_file_type(".cub",
                                        DiskImageResourceIsis::type_static(),
                                        &DiskImageResourceIsis::construct_open,
                                        &DiskImageResourceIsis::construct_create);
#endif 

  // Register all stereo session types
#if defined(ASP_HAVE_PKG_SPICE) && ASP_HAVE_PKG_SPICE == 1
  StereoSession::register_session_type( "hrsc", &StereoSessionHRSC::construct);
  StereoSession::register_session_type( "moc", &StereoSessionMOC::construct);
  StereoSession::register_session_type( "ctx", &StereoSessionCTX::construct);
#endif
#if defined(ASP_HAVE_PKG_ISIS) && ASP_HAVE_PKG_ISIS == 1 
  StereoSession::register_session_type( "isis", &StereoSessionIsis::construct);
#endif

  /*************************************/
  /* Parsing of command line arguments */
  /*************************************/

  // Boost has a nice command line parsing utility, which we use here
  // to specify the type, size, help string, etc, of the command line
  // arguments.
  std::string stereo_session_string;
  std::string in_file1, in_file2, cam_file1, cam_file2, out_file;
  double scale;

  po::options_description visible_options("Options");
  visible_options.add_options()
    ("help,h", "Display this help message")
    ("session-type,t", "Select the stereo session type to use for processing. [default: pinhole]")
    ("scale", po::value<double>(&scale)->default_value(1.0), "Scale the size of the coordinate axes by this amount");

  po::options_description positional_options("Positional Options");
  positional_options.add_options()
    ("left-input-image", po::value<std::string>(&in_file1), "Left Input Image")
    ("right-input-image", po::value<std::string>(&in_file2), "Right Input Image")
    ("left-camera-model", po::value<std::string>(&cam_file1), "Left Camera Model File")
    ("right-camera-model", po::value<std::string>(&cam_file2), "Right Camera Model File")
    ("output-file", po::value<std::string>(&out_file)->default_value("orbit.kml"), "Output filename");
  po::positional_options_description positional_options_desc;
  positional_options_desc.add("left-input-image", 1);
  positional_options_desc.add("right-input-image", 1);
  positional_options_desc.add("left-camera-model", 1);
  positional_options_desc.add("right-camera-model", 1);
  positional_options_desc.add("output-file", 1);

  po::options_description all_options;
  all_options.add(visible_options).add(positional_options);

  po::variables_map vm;
  po::store( po::command_line_parser( argc, argv ).options(all_options).positional(positional_options_desc).run(), vm );
  po::notify( vm );

  // If the command line wasn't properly formed or the user requested
  // help, we print an usage message.
  std::ostringstream help;
  help << "\nUsage: " << argv[0] << " [options] <Left_input_image> <Right_input_image> <Left_camera_file> <Right_camera_file> <output_file_prefix>\n"
       << "  the extensions are automaticaly added to the output files\n"
       << "  the parameters should be in stereo.default\n\n";
  help << visible_options << std::endl;
  std::cout << "HI I EXIST HERE\n";
  if( vm.count("help") ||
      !vm.count("left-input-image") || !vm.count("right-input-image")) {
    std::cout << "Hit1" << std::endl;
    std::cout << help.str();
    return 1;
  }

  // Look up for session type based on file extensions
  if (stereo_session_string.size() == 0) {
    if ( (boost::iends_with(cam_file1, ".cahvor") && boost::iends_with(cam_file2, ".cahvor")) || 
         (boost::iends_with(cam_file1, ".cahv") && boost::iends_with(cam_file2, ".cahv")) ||
         (boost::iends_with(cam_file1, ".pin") && boost::iends_with(cam_file2, ".pin")) ||
         (boost::iends_with(cam_file1, ".tsai") && boost::iends_with(cam_file2, ".tsai")) ) {
         vw_out(0) << "\t--> Detected pinhole camera files.  Executing pinhole stereo pipeline.\n";
         stereo_session_string = "pinhole";
    } 

    else if (boost::iends_with(in_file1, ".cub") && boost::iends_with(in_file2, ".cub")) {
      vw_out(0) << "\t--> Detected ISIS cube files.  Executing ISIS stereo pipeline.\n";
      stereo_session_string = "isis";
    } 
   
    else {
      vw_out(0) << "\n\n******************************************************************\n";
      vw_out(0) << "Could not determine stereo session type.   Please set it explicitly\n";
      vw_out(0) << "using the -t switch.  Options include: [pinhole isis].\n";
      vw_out(0) << "******************************************************************\n\n";
      exit(0);
    }
  }

  // Special handling for Isis Cubes that also contain camera model
  if ( stereo_session_string == "isis" ) {
    std::cout << "Hit2\n";
    if ( out_file.size() == 0 && vm.count("left-camera-model") 
	 && !vm.count("right-camera-model")) 
      out_file = cam_file1;
  } else {
    if (!vm.count("left-camera-model") || vm.count("right-camera-model") ) {
      std::cout << "Hit3\n";
      std::cout << help.str();
      return 1;
    }
  }

  StereoSession* session = StereoSession::create(stereo_session_string);
  session->initialize(in_file1, in_file2, cam_file1, cam_file2, 
                      out_file, "", "", "", "");

  // Generate some camera models
  boost::shared_ptr<camera::CameraModel> camera_model1, camera_model2;
  session->camera_models(camera_model1, camera_model2);


  // Create the KML file.
  KMLStateVectorViz kml(out_file, "test", scale);
  kml.append_body_state("Camera 1", camera_model1->camera_center(Vector2()), camera_model1->camera_pose(Vector2()));
  kml.append_body_state("Camera 2", camera_model2->camera_center(Vector2()), camera_model2->camera_pose(Vector2()));
  kml.close();
  exit(0);
}
