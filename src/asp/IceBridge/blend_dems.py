#!/usr/bin/env python
# __BEGIN_LICENSE__
#  Copyright (c) 2009-2013, United States Government as represented by the
#  Administrator of the National Aeronautics and Space Administration. All
#  rights reserved.
#
#  The NGT platform is licensed under the Apache License, Version 2.0 (the
#  "License"); you may not use this file except in compliance with the
#  License. You may obtain a copy of the License at
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# __END_LICENSE__

# For each DEM, blend it, within its footprint, with neighboring DEMs.
# That is to say, make several mosaics. First the DEM alone. Then
# blended with the one on the right. Then also with the one on the
# left. Then with second on the right. Then with second on the left.
# Keep the result with the lowest mean error to lidar.

# It creates files of the form:
# processed/batch_2489_2490_2/out-blend-DEM.tif 
# processed/batch_2489_2490_2/out-blend-DEM-diff.csv

# Operate in the range [startFrame, stopFrame) so does not include the
# last one.

# See usage below.

# TODO: Find a better way of picking DEMs to blend. For example,
# include only those which decrease the mean error. Then compare
# if this approach gives lower error than the current way
# which keeps on adding DEMs left and right. 

import os, sys, argparse, datetime, time, subprocess, logging, multiprocessing, re, glob
import traceback
import os.path as P

# The path to the ASP python files and tools
basepath      = os.path.dirname(os.path.realpath(__file__))  # won't change, unlike syspath
pythonpath    = os.path.abspath(basepath + '/../Python')     # for dev ASP
libexecpath   = os.path.abspath(basepath + '/../libexec')    # for packaged ASP
binpath       = os.path.abspath(basepath + '/../bin')        # for packaged ASP
icebridgepath = os.path.abspath(basepath + '/../IceBridge')  # IceBridge tools
toolspath     = os.path.abspath(basepath + '/../Tools')      # ASP Tools

# Prepend to Python path
sys.path.insert(0, basepath)
sys.path.insert(0, pythonpath)
sys.path.insert(0, libexecpath)
sys.path.insert(0, icebridgepath)

import icebridge_common
import asp_system_utils, asp_alg_utils, asp_geo_utils

asp_system_utils.verify_python_version_is_supported()

# Prepend to system PATH
os.environ["PATH"] = basepath       + os.pathsep + os.environ["PATH"]
os.environ["PATH"] = pythonpath     + os.pathsep + os.environ["PATH"]
os.environ["PATH"] = libexecpath    + os.pathsep + os.environ["PATH"]
os.environ["PATH"] = icebridgepath  + os.pathsep + os.environ["PATH"]
os.environ["PATH"] = toolspath      + os.pathsep + os.environ["PATH"]
os.environ["PATH"] = binpath        + os.pathsep + os.environ["PATH"]

def frame2dem(frame, processFolder, bundleLength):
    
    # We count here on the convention for writing batch folders
    batchFolderGlob = os.path.join(processFolder, 'batch_' + str(frame) + \
                                   '_*' + '_' + str(bundleLength))
    
    batchFolder = glob.glob(batchFolderGlob)

    if len(batchFolder) == 0:
        #print("Error: No directories matching: " + batchFolderGlob + ". Will skip this frame.")
        return "", ""
        
    if len(batchFolder) > 1:
        print("Error: Found more than one directory matching: " + batchFolderGlob + ".")
        return "", ""
    
    batchFolder = batchFolder[0] # extract from list
    demFile = os.path.join(batchFolder, 'out-align-DEM.tif')
    if not os.path.exists(demFile):
        return "", ""

    return demFile, batchFolder

def runBlend(frame, processFolder, lidarFile, bundleLength, threadText, redo, suppressOutput):

    # This will run as multiple processes. Hence have to catch all exceptions:
    try:
        
        demFile, batchFolder = frame2dem(frame, processFolder, bundleLength)
        lidarCsvFormatString = icebridge_common.getLidarCsvFormat(lidarFile)

        if demFile == "":
            print("Could not find DEM for frame: " + str(frame))
            return

        # The names for the final results
        finalOutputPrefix = os.path.join(batchFolder, 'out-blend-DEM')
        finalBlend        = finalOutputPrefix + '.tif'
        finalDiff         = finalOutputPrefix + "-diff.csv"

        if os.path.exists(finalBlend) and os.path.exists(finalDiff) and not redo:
            print("Files exist: " + finalBlend + " " + finalDiff + ".")
            return

        # We will blend the dems with frame offsets within frameOffsets[0:index]
        filesToWipe = []
        bestMean = 1.0e+100
        bestBlend  = ''
        bestVals = ''
        bestDiff = ''
        
        # Look at frames with these offsets when blending
        frameOffsets = [0, 1, -1, 2, -2]

        for index in range(len(frameOffsets)):

            # Find all the DEMs up to the current index
            dems = []
            currDemFile = ""
            for val in range(0, index+1):
                offset = frameOffsets[val]
                currDemFile, currBatchFolder = \
                             frame2dem(frame + offset, processFolder, bundleLength)
                if currDemFile == "":
                    continue
                dems.append(currDemFile)

            if currDemFile == "":
                # The last DEM was not present. Hence this iteration will add nothing new.
                continue

            demString = " ".join(dems)
            outputPrefix = os.path.join(batchFolder, 'out-blend-' + str(index))
            cmd = ('dem_mosaic --first-dem-as-reference %s %s -o %s' 
                   % (demString, threadText, outputPrefix))
            
            blendOutput = outputPrefix + '-tile-0.tif'
            filesToWipe.append(blendOutput)
            
            print(cmd) # to make it go to the log, not just on screen
            asp_system_utils.executeCommand(cmd, blendOutput, suppressOutput, redo)
            
            diffPath = outputPrefix + "-diff.csv"
            filesToWipe.append(diffPath)
            
            cmd = ('geodiff --absolute --csv-format %s %s %s -o %s' % 
                   (lidarCsvFormatString, blendOutput, lidarFile, outputPrefix))
            print(cmd)
            asp_system_utils.executeCommand(cmd, diffPath, suppressOutput, redo)
                
            # Read in and examine the results
            results = icebridge_common.readGeodiffOutput(diffPath)
            print("Current mean error to lidar is " + str(results['Mean']))

            if  bestMean > float(results['Mean']):
                bestMean  = float(results['Mean'])
                bestBlend = blendOutput
                bestVals  = demString
                bestDiff  = diffPath

            logFiles = glob.glob(outputPrefix + "*" + "-log-" + "*")
            filesToWipe += logFiles
        
        print("Best mean error to lidar is " + str(bestMean) + " when blending " + bestVals)
        cmd = "mv " + bestBlend + " " + finalBlend
        print(cmd)
        asp_system_utils.executeCommand(cmd, finalBlend, suppressOutput, redo)
        
        cmd = "mv " + bestDiff   + " " + finalDiff
        print(cmd)
        asp_system_utils.executeCommand(cmd, finalDiff, suppressOutput, redo)
        
        for fileName in filesToWipe:
            if os.path.exists(fileName):
                print("Will wipe: " + fileName)
                os.remove(fileName)
                
    except Exception as e:
        print('Blending failed!\n' + str(e) + ". " + str(traceback.print_exc()))
            
    sys.stdout.flush()
         
def main(argsIn):

    try:
        # Sample usage:
        # python ~/projects/StereoPipeline/src/asp/IceBridge/blend_dems.py --site GR   \
        #   --yyyymmdd 20120315 --start-frame 2490 --stop-frame 2491 --bundle-length 2 \
        #   --num-threads 8 --num-processes 10
        usage = '''blend_dems.py <options>'''
                      
        parser = argparse.ArgumentParser(usage=usage)

        # Run selection
        parser.add_argument("--yyyymmdd",  dest="yyyymmdd", required=True,
                          help="Specify the year, month, and day in one YYYYMMDD string.")
        parser.add_argument("--site",  dest="site", required=True,
                          help="Name of the location of the images (AN, GR, or AL)")

        parser.add_argument("--output-folder",  dest="outputFolder", default=None,
                          help="Name of the output folder. If not specified, " + \
                          "use something like AN_YYYYMMDD.")

        # Processing options
        parser.add_argument('--bundle-length', dest='bundleLength', default=2,
                          type=int, help="The number of images to bundle adjust and process " + \
                          "in a single batch.")

        parser.add_argument('--start-frame', dest='startFrame', type=int,
                          default=icebridge_common.getSmallestFrame(),
                          help="Frame to start with.  Leave this and stop-frame blank to " + \
                          "process all frames.")
        parser.add_argument('--stop-frame', dest='stopFrame', type=int,
                          default=icebridge_common.getLargestFrame(),
                          help='Frame to stop on. This frame will also be processed.')

        parser.add_argument("--processing-subfolder",  dest="processingSubfolder", default=None,
                          help="Specify a subfolder name where the processing outputs will go. "+\
                            "The default is no additional folder.")

        # Performance options  
        parser.add_argument('--num-processes', dest='numProcesses', default=1,
                          type=int, help='The number of simultaneous processes to run.')
        parser.add_argument('--num-threads', dest='numThreads', default=8,
                          type=int, help='The number of threads per process.')
        options = parser.parse_args(argsIn)

    except argparse.ArgumentError, msg:
        parser.error(msg)
        
    if len(options.yyyymmdd) != 8 and len(options.yyyymmdd) != 9:
        # Make an exception for 20100422a
        raise Exception("The --yyyymmdd field must have length 8 or 9.")

    if options.outputFolder is None:
        options.outputFolder = icebridge_common.outputFolder(options.site, options.yyyymmdd)
        
    os.system('mkdir -p ' + options.outputFolder)
    logLevel = logging.INFO # Make this an option??
    logger   = icebridge_common.setUpLogger(options.outputFolder, logLevel,
                                            'icebridge_processing_log')

    (status, out, err) = asp_system_utils.run_return_outputs(['uname', '-a'], verbose=False)
    logger.info("Running on machine: " + out)
    
    processFolder = os.path.join(options.outputFolder, 'processed')
    
    # Handle subfolder option.  This is useful for comparing results with different parameters!
    if options.processingSubfolder:
        processFolder = os.path.join(processFolder, options.processingSubfolder)
        logger.info('Reading from processing subfolder: ' + options.processingSubfolder)

    orthoFolder = os.path.join(options.outputFolder, 'ortho')
    orthoIndexPath = icebridge_common.csvIndexFile(orthoFolder)
    if not os.path.exists(orthoIndexPath):
        raise Exception("Error: Missing ortho index file: " + orthoIndexPath + ".")
    
    (orthoFrameDict, orthoUrlDict) = icebridge_common.readIndexFile(orthoIndexPath)
    
    lidarFolder = os.path.join(options.outputFolder, 'lidar')
    
    threadText = ''
    if options.numThreads:
        threadText = '--threads ' + str(options.numThreads)
    
    redo = False
    suppressOutput = True
    taskHandles  = []
    if options.numProcesses > 1:    
        pool = multiprocessing.Pool(options.numProcesses)
        
    for frame in range(options.startFrame, options.stopFrame):

        if not frame in orthoFrameDict:
            logger.info("Error: Missing ortho file for frame: " + str(frame) + ".")
            continue
        
        orthoFile = orthoFrameDict[frame]
        lidarFile = icebridge_common.findMatchingLidarFile(orthoFile, lidarFolder)

        args = (frame, processFolder, lidarFile, options.bundleLength, threadText,
                redo, suppressOutput)

        # Run things sequentially if only one process, to make it easy to debug
        if options.numProcesses > 1:
            taskHandles.append(pool.apply_async(runBlend, args))
        else:
            runBlend(*args)
        
    if options.numProcesses > 1:
        icebridge_common.waitForTaskCompletionOrKeypress(taskHandles, logger, interactive = False, 
                                                         quitKey='q', sleepTime=20)
        icebridge_common.stopTaskPool(pool)
    
# Run main function if file used from shell
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

