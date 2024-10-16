
# DISCARDED FUNCTIONS

def color_map_rgb(value, cmap_name='hot', vmin=1, vmax=12):
    # norm = plt.Normalize(vmin, vmax)
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)
    cmap = cm.get_cmap(cmap_name)  # PiYG
    rgb = cmap(norm(abs(value)))[:3]  # will return rgba, we take only first 3 so we get rgb
    #color = matplotlib.colors.rgb2hex(rgb)
    return rgb

def convert_to_rgb(array):
        rgb_array = np.zeros([3,256,256])
        for i in range(len(array[0,:,0])):
                for j in range(len(array[0,0,:])):
                        rgb = color_map_rgb(array[:,i,j],cmap_name='hot',vmin=1,vmax=12)
                        #print(rgb)
                        rgb_array[:,i,j] = rgb[0,:3]
        return rgb_array   

        


def convert_to_deltaF_Fo(video):
        # Takes a single pixel mean for whole pixel's trace - only really good for visualization. 
        # Take the mean of each pixel across all frames and store it in a 256x256 ndarray. 
        mean_pixels = np.empty(shape=[256,256])

        for i in range(len(video[0,:,0])):
                for j in range(len(video[0,0,:])):

                        mean = np.mean(video[:,i,j])
                        mean_pixels[i,j] = mean

        #For each frame, subtract the mean of that frame from the total recording, 
        # then divide by the mean to get (F-Fo)/Fo

        #Reshape array so can subtract mean value
        mean_pixels = mean_pixels[np.newaxis,...]
        baseline_subtracted = (np.subtract(video,mean_pixels))
        deltaF_Fo = baseline_subtracted/mean_pixels

        return deltaF_Fo



def butter_highpass(cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = signal.butter(order, normal_cutoff, btype='high', analog=False)
    return b, a

def butter_highpass_filter(data, cutoff, fs, order=5):
    b, a = butter_highpass(cutoff, fs, order=order)
    y = signal.filtfilt(b, a, data)
    return y

def apply_butter_highpass(video,cutoff,fs):
        for i in range(len(video[0,:,0])):
                for j in range(len(video[0,0,:])):
                        video[:,i,j] = butter_highpass_filter(video[:,i,j],cutoff,fs,order=5)
        return video
