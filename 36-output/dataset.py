import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils
import cv2
from scipy import signal, stats
import matplotlib
from matplotlib import pyplot as plt

from tqdm import tqdm # Displays a progress bar

import pandas as pd
import numpy as np

import os
import torchvision.transforms.functional as F


import librosa

import librosa.display


class EnableDataset(Dataset):
    '''
    dataDir: path to folder containing data
    subject_list: the subjects to be included in dataset
    data_range: the specified circuit trials for each subject
    window_size: how many samples to consider for a label
    time_series: when true, use time_series method
    label: when specified, the dataset will only contain data with the given label value
    transform: optional transform to apply to the data
    '''
    def __init__(self, dataDir='./Data/' ,subject_list=['156'], data_range=(1, 10), window_size=500, time_series=False, output_type="6", sensors=["imu","emg", "goin"], mode="bilateral", label=None, transform=None,bands=None,hop_length=None):

        print("    range: [%d, %d)" % (data_range[0], data_range[1]))
        self.dataset = []
        self.prev_label = np.array([], dtype=np.int64)
        self.img_data_stack=np.empty((51, 3, 4, 51), dtype=np.int64)
        self.transform = transform

        for subjects in subject_list:
            for i in range(data_range[0], data_range[1]):
                filename = dataDir +'AB' + subjects+'/Processed/'+'AB' + subjects+ '_Circuit_%03d_post.csv'% i
                if not os.path.exists(filename):
                    print(filename, 'not found')
                    continue
                raw_data = pd.read_csv(filename)

                segmented_data = np.array([], dtype=np.int64).reshape(0,window_size,48)
                labels = np.array([], dtype=np.int64)
                timesteps = []
                triggers = []
                index = 0
                gait_event_types = []

                gait_events = ['Right_Heel_Contact','Right_Toe_Off','Left_Heel_Contact','Left_Toe_Off']
                for event in gait_events:
                    while not pd.isnull(raw_data.loc[index, event]):
                        trigger = raw_data.loc[index, event+'_Trigger']
                        trigger=str(int(trigger))
                        if float(trigger[2]) != 6 and float(trigger[0]) !=6:
                            timesteps.append(raw_data.loc[index, event])
                            trigger = raw_data.loc[index, event+'_Trigger']
                            trigger=str(int(trigger))
                            triggers.append(trigger) # triggers can be used to compare translational and steady-state error

                            if output_type =="6":
                                labels = np.append(labels,[float(trigger[2])], axis =0)
                            else:
                                labels = np.append(labels, [float(trigger[0])*6 + float(trigger[2])], axis=0)
                            if "right" in event.lower():
                                gait_event_types.append("Right")
                            else:
                                gait_event_types.append("Left")
                                
                            self.prev_label = np.append(self.prev_label,[float(trigger[0])], axis =0)
                        index += 1
                    index = 0

                for idx,timestep in enumerate(timesteps):
                    data = raw_data.loc[timestep-window_size-1:timestep-2,:]
                    if timestep-window_size-1 >= 0:
                        if mode == "ipsilateral":
                            data = data.filter(regex='(?=.*'+ gait_event_types[idx] + '|Mode|Waist)(?!.*Toe)(?!.*Heel)(.+)', axis=1)
                        elif mode == "contralateral":
                            opposite = "Left" if gait_event_types[idx] == "Right" else "Right"
                            data = data.filter(regex='(?=.*'+ opposite + '|Mode|Waist)(?!.*Toe)(?!.*Heel)(.+)', axis=1)
                        else:
                            data = data.filter(regex="^((?!Heel|Toe).)*$", axis=1)

                        regex = "(?=Mode|.*Ankle.*|.*Knee.*"
                        # regex = "(?=Mode)"
                        if "imu" in sensors:
                            regex += "|.*A[xyz].*"
                        if "goin" in sensors:
                            regex += "|.*G[xyz].*"
                        if "emg" in sensors:
                            regex += "|.*TA.*|.*MG.*|.*SOL.*|.*BF.*|.*ST.*|.*VL.*|.*RF.*"
                        # if "goin" in sensors:
                        regex += ")"
                        data = data.filter(regex=regex, axis=1)

                        data = np.array(data)
                        if not time_series:
                            img= self.melspectrogram(data,bands=bands ,hop_length=hop_length)
                            self.dataset.append((img,labels[idx]))
                        else:
                            self.dataset.append((data.T,labels[idx]))
        print("load dataset done")


    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, index):
        img, label = self.dataset[index]
        if self.transform:
            img = F.to_pil_image(np.uint8(img))
            img = self.transform(img)
            img = np.array(img)
        return torch.FloatTensor(img), torch.LongTensor(np.array(label) )

    def spectrogram2(self, segmented_data, fs=500,hamming_windowsize=30, overlap = 15):
        vals = []
        for i in range(0,17):
	        for x in range(3*i,3*(i+1)):
	            row = segmented_data[:,x]
	            f, t, Sxx = signal.spectrogram(row, fs, window=signal.windows.hamming(hamming_windowsize, True), noverlap=5)
	            tmp, _ = stats.boxcox(Sxx.reshape(-1,1))
	            Sxx = tmp.reshape(Sxx.shape)-np.min(tmp)
	            Sxx = Sxx/np.max(Sxx)*255
	            vals.append(Sxx)
        # the way of stacking should be fixed
        out = np.stack(vals, axis=0)
        # out=out.astype(np.uint8)
        return out

    def melspectrogram(self, segmented_data, fs=500,bands=64 ,hop_length=50):

        ###### STACKING UP MULTIPLE SPECTOGRAM APPROACH!

        vals = []
        # vals2 =[]
        for i in range(0,17):
            for x in range(3*i,3*(i+1)):
                row = segmented_data[:,x]
                melspec_full = librosa.feature.melspectrogram(y=row,sr=fs,n_fft=hop_length*2, hop_length=hop_length,n_mels=bands)
                logspec_full = librosa.amplitude_to_db(melspec_full)
                logspec_delta = librosa.feature.delta(logspec_full) # add derivative
                # librosa.display.specshow(logspec_full, x_axis='time',y_axis='mel', sr=fs,fmax=fs/2)
                # plt.colorbar(format='%+02.0f dB')
                # plt.imshow(logspec_full)
                # plt.show()
                # plt.close()

                vals.append(logspec_full)
                # vals2.append(logspec_delta)
        # out = np.stack(vals, axis=0)
        # out = out.astype(np.uint8)

        # features = np.concatenate((vals,vals2),axis=2)

        # out = np.asarray(out).reshape(len(out),bands,frames, 1)

        return vals


    def cwt(self, segmented_data, fs=500,hamming_windowsize=30, overlap = 15):
        vals = []
        for i in range(0,17):
            for x in range(3*i,3*(i+1)):
                row = segmented_data[:,x]
                widths = np.arange(1,101)
                cwtmatr = signal.cwt(row, signal.ricker, widths)
                print(cwtmatr.shape, np.min(cwtmatr), np.max(cwtmatr))
                cwtmatr = cwtmatr-np.min(cwtmatr)
                cwtmatr = cwtmatr/np.max(cwtmatr)*255
                vals.append(cwtmatr)


        out = np.stack(vals, axis=0)
        out=out.astype(np.uint8)
        return out


    def spectrogram(self, segmented_data, fs=500, hamming_windowsize=10):
        vals1 = []
        for x in range(3):
            row = segmented_data[y,:,x]
            f, t, Sxx = signal.spectrogram(row, fs, window=signal.windows.hamming(100, True), noverlap=50)
            fig = plt.figure()
            ax = fig.add_axes([0.,0.,1.,1.])
            fig.set_size_inches((5,5))
            ax.pcolormesh(t, f, Sxx, cmap='gray')
            ax.axis('off')
            fig.add_axes(ax)
            fig.canvas.draw()
            # this rasterized the figure
            X = np.array(fig.canvas.renderer._renderer)
            X = 0.2989*X[:,1] + 0.5870*X[:,2] + 0.1140*X[:,3]
            vals1.append(X)
            plt.close()
        vals2 = []
        for x in range(6,9):
            row = segmented_data[y,:,x]
            f, t, Sxx = signal.spectrogram(row, fs, window=signal.windows.hamming(100, True), noverlap=50)
            fig = plt.figure()
            ax = fig.add_axes([0.,0.,1.,1.])
            fig.set_size_inches((5,5))
            ax.pcolormesh(t, f, Sxx, cmap='gray')
            ax.axis('off')
            fig.add_axes(ax)
            fig.canvas.draw()
            # this rasterized the figure
            X = np.array(fig.canvas.renderer._renderer)
            X = 0.2989*X[:,1] + 0.5870*X[:,2] + 0.1140*X[:,3]
            vals2.append(X)
            plt.close()

        out1 = np.stack(vals1, axis=2).astype(np.uint8)
        out2 = np.stack(vals2, axis=2).astype(np.uint8)
        out = np.hstack((out1, out2))
        cv2.imshow("ret", out)
        cv2.waitKey(0)
        return ret
