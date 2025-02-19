'''
AUTHORS: Conor Lane & Veronica Tarka, November 2022.  Contact: conor.lane@mail.mcgill.ca
'''

from cmath import nan
import time
from datetime import timedelta
from timeit import repeat
from tkinter import Y
start_time = time.monotonic()

import json
import numpy as np
from mpl_toolkits.axes_grid1 import make_axes_locatable
from skimage.io import imread
from skimage.measure import block_reduce
import os
from matplotlib import pyplot as plt
import scipy.io as scio
import pickle
from matplotlib import cm

# load what we need from the config file
with open(os.path.abspath(os.path.dirname(__file__)) +'/../../config_widefield.json','r') as f:
    config = json.load(f)

BASE_PATH = config['RecordingFolder'] # folder with all of the files required to process recording. 
TIFF_PATH = config['TIFF']
CSV_PATH = config['Triggers'] # name of CSV (assumed to be in the folder given in line above) with the trigger voltages over the recording
CONDITIONS_PATH = config['Conditions'] # name of the CSV (assumed to be in folder given two lines above) with the condition types of each trial (freq, intensity, etc)
TIFF = BASE_PATH + TIFF_PATH

STIMULUS_FRAMERATE = config['TriggerFR'] # framerate of the trigger file
TRIGGER_DELAY_IN_MS = config['TriggerDelay'] # delay between TDT sending a trigger and the stimulus actually happening
RECORDING_FRAMERATE = config['RecordingFR'] # framerate of the fluorescence recording
EPOCH_START_IN_MS = config['EpochStart'] # time to include before trial onset for each epoch
EPOCH_END_IN_MS = config['EpochEnd'] # time to include after trial onset for each epoch
NO_BASELINE_FRAMES = config['BaselineFrames']
ZSCORE_THRESHOLD = config['ZscoreThreshold']
START = config['ResponseStart']
STOP = config['ResponseStop']

## PRE-PROCESSING ##

'''
Load the tiff stack of the recording as a single 3D array and downsample it from 512x512 to 256x256 (if recording is larger than 512x512, change block size).   
Note: The tiff stack must be the only thing in the folder.  It will try to load other items into the array.
@Param: Name of folder (paste path into FILESTOLOAD section)
Return: (N_frames x N_pixels x N_pixels) numpy array.
'''
def load_recording(TIFF):

        video = []
        images = [img for img in os.listdir(TIFF)]

        for img in images:
                im = imread(TIFF+img)
                downsamp_img = block_reduce(im,block_size=(2,2),func=np.mean)
                video.append(downsamp_img)
        video = np.array(video)

        return video

"""
Find the stimulus onsets from the trigger CSV and define as frames in the fluorescence recording
@param stimulus: 1D vector of the voltage trace of the stimulus triggers
@return onset_frames_at_recording_fr: a list of the frames in the fluo recording where the stim was presented
"""

def get_onset_frames(stimulus):
    # find the max voltage (this will be the value in the vector when the trigger was sent)
    max_voltage = max(stimulus, key=lambda x:x[1])
    max_voltage = max_voltage[1]

    onset_times = [] # empty list to append our onset frames into
    time_list_index = 0 # counter to keep track of our index in the onset_times list

    # for each frame in the stimulus file
    for stimulus_idx in range(len(stimulus)):
        (time,voltage) = stimulus[stimulus_idx] # unpack the voltage at that timepoint

        if voltage.round() == max_voltage.round(): # if the voltage was our trigger voltage
            if time_list_index == 0: # and if we're at the first index (so there's no previous index to compare with)
                trigger_time_in_sec = time/1000 + TRIGGER_DELAY_IN_MS/1000
                onset_times.append(trigger_time_in_sec) # add the time as an onset time in SECONDS
                time_list_index += 1

            # if we're not at index zero, we need to compare this voltage with the previous saved onset voltage
            # otherwise we save a bunch of voltages as separate triggers because they all match the max voltage
            # but we just want one timepoint per trigger
            elif time/1000 -  onset_times[time_list_index - 1] > 1: 
                trigger_time_in_sec = time/1000 + TRIGGER_DELAY_IN_MS/1000
                onset_times.append(trigger_time_in_sec) # want it in second not millisecond
                time_list_index += 1

    # get the onset times in terms of frames of our fluorescence trace
    onset_frames_at_recording_fr = np.multiply(onset_times,RECORDING_FRAMERATE) # s * f/s = f

    #Remove first three triggers, corresponding to start at frame zero, 
    onset_frames_at_recording_fr = onset_frames_at_recording_fr[3:]

    return onset_frames_at_recording_fr

def epoch_trials(video,onset_frames):

        # Get length of trial in seconds
        trial_length_in_ms = EPOCH_END_IN_MS - EPOCH_START_IN_MS # this gives us length in ms
        trial_length_in_sec = trial_length_in_ms/1000 # now we have it in second

        # Convert this to length in frames
        trial_length_in_frames = int(trial_length_in_sec * RECORDING_FRAMERATE) # s * f/s = f

        # Initialize an array to store the epoched traces
        # nTrials x nFrames x nPixels x nPixels

        epoched_pixels = np.zeros((len(onset_frames),(trial_length_in_frames), len(video[0,:,0]), len(video[0,0,:])))

        #Start filling the empty matrix:
        # Loop through the onset frames
        for onset in range(len(onset_frames)-1):

                #Get the trial starting and ending frames
                trial_starting_frame = np.round(onset_frames[onset]) + (EPOCH_START_IN_MS/1000*RECORDING_FRAMERATE)
                trial_ending_frame = np.round(onset_frames[onset]) + (EPOCH_END_IN_MS/1000*RECORDING_FRAMERATE)


                #Grab this range of frames from the recording and store in epoched matrix
                epoch = video[int(trial_starting_frame):int(trial_ending_frame),:,:]
                epoched_pixels[onset,:,:] = epoch

        return epoched_pixels

'''
Normalize each trial to it's local pre-stimulus baseline by subtracting the mean of the pre-stim from each timepoint in the trial. 
@Param epoched pixels =  N_trials x N_frames x N_pixels x N_pixels array.
@param n_baseline_frames = The number of pre-stimulus baseline frames to use in the normalization. 
@Returns:  Ntrials x N_frames x N_pixels x N_pixels array of baseline adjusted trials. e.g. [0,:,0,0] is the normalized trace of the 
first trial at pixel 0,0. 
'''

def baseline_adjust_pixels(epoched_pixels):
        # Create an empty array to store the baseline adjusted trials in. Same shape as epoched pixels.
        baseline_adjusted_epoched = np.empty(shape=epoched_pixels.shape)

        # Iterate through the trials (i) and each x any y pixel coordinate (j and K)
        for i in range(len(epoched_pixels)):
                for j in range(len(epoched_pixels[0][0])):
                        for k in range(len(epoched_pixels[0][0])):

                                # Extract the specific trial to be normalized
                                test_trace = epoched_pixels[i,:,j,k]
                                # compute the average of the number of baseline frames
                                baseline_average = np.average(test_trace[0:NO_BASELINE_FRAMES])
                                # Subtract the baseline frames from the test trace 
                                normalized_trace = np.subtract(test_trace,baseline_average)
                                
                                baseline_adjusted_epoched[i,:,j,k] = normalized_trace

        return baseline_adjusted_epoched

def format_trials(baseline_adjusted_epoched,conditions):

        #Format the trials into a dict, arranged by frequency.
        #Each trace should be a nFrames by relative fluorescence array
        # format the dictionary so we get this structure:
        #     # freq_f{
        #       repetition{ 
        #           [x,x,x,x,...] }}}

        freq_dict = dict.fromkeys(np.unique(conditions[:,0]))

        # make empty dictionaries so we can index properly later
        for freq in freq_dict:
                freq_dict[freq] = {}

        # make a temporary map so we can keep track of how many repetitions of this trial we've seen
        # just going to add together the frequency and intensity to index it
        # biggest element we'll need is max(frequency)
        max_element = max(conditions[:,0]) + 10
        temp_map = [0] * max_element

        # for each trial
        for trial in range(len(conditions)):

                # trial's frequency
                f = conditions[trial,0]

                # access the map to see how many repetitions of the frequency we've already seen
                # this way we don't overwrite a trial with the same stimulus type
                num_rep = temp_map[f]+1
                temp_map[f] += 1

                # using the frequency and intensity to index our dictionary to store our trace
                freq_dict[f][num_rep] = baseline_adjusted_epoched[trial,:,:,:]

        return freq_dict



'''
Takes the formatted individual trials, converts them to a z-score and finds the median value of the average of each response period.  
Stores this median value in a dictionary where keys are stim frequencies, values are a 1 x Npixels x Npixels 3D array. 
@Param: freq_dict - dict of all the raw trials, with keys being presentation frequencies, containing each rep as an inner key. 
e.g. the first rep of a given frequency is freq_dict[freq][rep]
Values are the raw response traces for each trial.
@Param: conditions - Array containing the order of frequencies presented. Used to make the dict to store z-scores.
@Param: start - Frame number at which "response period" begins e.g. 5
@Param: stop - Frame number at which "response period" ends. 

'''

def get_zscored_response(trial):
    baseline = trial[:NO_BASELINE_FRAMES]
    #response = trial[n_baseline_frames:]

    baseline_mean = np.average(baseline)
    baseline_std = np.std(baseline)

    zscorer = lambda x: (x-baseline_mean)/baseline_std
    zscore_response = np.array([zscorer(xi) for xi in trial])

    return zscore_response


def zscore_and_median(freq_dict,conditions):
        # Create the empty dictionary that will store median values
        median_zscore_dict = dict.fromkeys(np.unique(conditions[:,0]))

        for freq in freq_dict:
                # Create empty numpy arrays to store each individual trial, it's z-scored version, the average value of the response period,
                #  and the median value across all trials. 
                freq_array = np.empty([len(freq_dict[freq]),25,256,256])
                zscore_array = np.empty([len(freq_dict[freq]),25,256,256])
                ave_zscore_array = np.empty([len(freq_dict[freq]),256,256])
                median_zscore_array = np.empty([1,256,256])
                median_zscore_dict[freq] = {}


                #  Iterate through each rep in the given frequency key and convert it to a z-score.
                for rep in range(1,len(freq_dict[freq])):
                        freq_array[rep-1,:,:,:] = freq_dict[freq][rep]
                        for i in range(len(freq_array[0,0,:,0])):
                                for j in range(len(freq_array[0,0,0,:])):
                                        zscore_array[rep-1,:,i,j] = get_zscored_response(freq_array[rep-1,:,i,j])
                                        # Extract the frames corresponding to the response period and find the mean value. 
                                        ave_zscore_array[rep-1,i,j] = np.mean(zscore_array[rep-1,START:STOP,i,j])
                #  iterate through the mean values for each pixel, and find the median value across all trials for that pixel. 
                for i in range(len(ave_zscore_array[0,:,0])):
                        for j in range(len(ave_zscore_array[0,0,:])):
                                median_zscore_array[:,i,j] = np.median(ave_zscore_array[:,i,j])

                median_zscore_dict[freq] = median_zscore_array

        return median_zscore_dict

## PLOTTING FUNCTIONS ##


# def plot_median(median_zscore_dict):

#         threshold = {key : np.clip(median_zscore_dict[key],a_min=ZSCORE_THRESHOLD,a_max=None) for key in median_zscore_dict}
#         rounded = {key : np.around(threshold[key], 1) for key in threshold}

#         fig,axes = plt.subplots(nrows=3, ncols=4, constrained_layout=True)
#         axes = axes.ravel()
#         for i, (key, value) in enumerate(rounded.items()):
#                 axes[i].imshow(np.squeeze(value),cmap = cm.viridis)
#                 axes[i].title.set_text(key)
#                 if i != 0:
#                        axes[i].set_xticks([])  # Hide x ticks
#                        axes[i].set_yticks([])  # Hide y ticks
#         plt.suptitle('Median Amplitude, ' + str(TIFF_PATH[:20]) + ' Response Frame = ' + str(START) + ':' + str(STOP) + 
#         ' ZscoreThreshold = ' + str(ZSCORE_THRESHOLD))
#         plt.show()
#         return fig,axes


import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize

def plot_median(median_zscore_dict, background_image_path):
    # Load background image
    background_image = plt.imread(background_image_path)
    background_image = block_reduce(background_image, block_size=(2, 2), func=np.mean)
    
    # Ensure background image is grayscale if it is not
    if background_image.ndim == 3 and background_image.shape[2] == 3:
        background_image = np.mean(background_image, axis=2)

    # Apply the threshold: set values below 2 to zero
    threshold = {key: np.where(median_zscore_dict[key] < 2, 0, median_zscore_dict[key]) for key in median_zscore_dict}
    rounded = {key: np.around(threshold[key], 1) for key in threshold}

    fig, axes = plt.subplots(nrows=2, ncols=6, constrained_layout=True, figsize=(12, 4))  # Adjust figsize as needed
    axes = axes.ravel()
    
    for i, (key, value) in enumerate(rounded.items()):
        overlay_image = np.nan_to_num(np.squeeze(value), nan=0.0)

        # Normalize overlay image
        if np.max(overlay_image) != np.min(overlay_image):  # Avoid division by zero
            norm_overlay_image = (overlay_image - np.min(overlay_image)) / (np.max(overlay_image) - np.min(overlay_image))
        else:
            norm_overlay_image = overlay_image

        # Create an RGBA overlay with transparency where values are low
        rgba_overlay = np.zeros((overlay_image.shape[0], overlay_image.shape[1], 4))
        rgba_overlay[..., :3] = cm.viridis(norm_overlay_image)[..., :3]  # Apply colormap
        rgba_overlay[..., 3] = (overlay_image >= 2).astype(float)  # Alpha channel

        # Display background image, ensuring it covers the entire subplot
        axes[i].imshow(background_image, cmap='gray', aspect='auto', extent=(0, background_image.shape[1], background_image.shape[0], 0))
        
        # Overlay the RGBA image
        im = axes[i].imshow(rgba_overlay, aspect='auto', extent=(0, background_image.shape[1], background_image.shape[0], 0))
        axes[i].set_title(f"{key} Hz",fontsize=20)  # Set title with frequency unit

        axes[i].set_xticks([])  # Hide x ticks
        axes[i].set_yticks([])  # Hide y ticks

    # Add a single colorbar for the entire figure
    norm = Normalize(vmin=np.min(value), vmax=np.max(value))  # Normalization based on actual Z-score values
    sm = cm.ScalarMappable(cmap=cm.viridis, norm=norm)
    sm.set_array([])  # Dummy array for the ScalarMappable
    cbar = fig.colorbar(sm, ax=axes, orientation='vertical', fraction=0.02, pad=0.04)
    cbar.set_label('Z-score',fontsize=18)  # Set colorbar label
    cbar.set_ticks([np.min(value), np.max(value)])  # Set ticks at min and max values
    cbar.set_ticklabels(['min', 'max'],fontsize=18)  # Set tick labels as 'min' and 'max'

    # plt.suptitle('Median Amplitude, ' + str(TIFF_PATH[:20]) + ' Response Frame = ' + str(START) + ':' + str(STOP) + 
    #              ' ZscoreThreshold = ' + str(ZSCORE_THRESHOLD))
    plt.show()
    return fig, axes

# Example usage (assuming required variables are defined and background_image_path is provided)
# plot_median(median_zscore_dict, background_image_path)


'''
MAIN:
'''

 # load our files
def main():
        stimulus = np.genfromtxt(BASE_PATH + CSV_PATH,delimiter=',',skip_header=True) # voltage values of the trigger software over the recording
        conditions_mat = scio.loadmat(BASE_PATH + CONDITIONS_PATH) # conditition type of each trial in chronological order
        conditions = conditions_mat["stim_data"]
        conditions = conditions[3:]  #Remove the first silent stim as this corresponds to frame 0

        # # get an array of all the stimulus onset times 
        # # converted to be frames at the recording frame rate
        # onset_frames = get_onset_frames(stimulus)

        # #Load the recording to be analyzed
        # video = load_recording(TIFF)

        # # #separate recording into individual trials using onset frames 
        # epoched_pixels = epoch_trials(video,onset_frames)

        # # # #Baseline adjust each trial (subtract 5 pre-stimulus frames from response)
        # baseline_adjusted_epoched = baseline_adjust_pixels(epoched_pixels)

        # # #Format trials into a dictionary arranged by frequency
        # freq_dict = format_trials(baseline_adjusted_epoched,conditions)

        # # Zscore the individual trials, and return a dict of single median value of the trial period, for each pixel.    
        # median_zscore_dict = zscore_and_median(freq_dict,conditions)

        with open(BASE_PATH+"median_zscore_dict.pkl", 'rb') as f:
                median_zscore_dict = pickle.load(f)

        # # save the recording information 
        # with open(BASE_PATH+"median_zscore_dict.pkl",'wb') as f:
        #         pickle.dump(median_zscore_dict,f)

        plot = plot_median(median_zscore_dict,'C:/Users/Conor/Documents/thesis/figure_parts_man2/ID543_24042024_1_00001.png')

        # How Long does it take to run the script? 
        end_time = time.monotonic()
        print(timedelta(seconds=end_time - start_time))

      

if __name__=='__main__':
        main()
