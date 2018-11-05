from __future__ import print_function
import caffe
from caffe.model_libs import *
from google.protobuf import text_format
import argparse
import math
import os
import shutil
import stat
import subprocess
import sys
import time
import numpy as np
from skimage import transform
import ctypes
from ctypes import *
import pickle
import glob, os
from PIL import Image
import re

so = ctypes.cdll.LoadLibrary
librbox = so("../librbox.so")
DecodeAndNMS = librbox.DecodeAndNMS
DecodeAndNMS.argtypes=(POINTER(c_double),POINTER(c_double),POINTER(c_int),POINTER(c_double),POINTER(c_int),c_double)
DecodeAndNMS.restype=None

NMS = librbox.NMS_airplane
NMS.argtypes=(POINTER(c_double),POINTER(c_int),POINTER(c_double),POINTER(c_int),c_double)
NMS.restype=None

#caffe.set_device(1)
caffe.set_mode_cpu()
caffemodel = 'RBOX_AIRPLANE_RBOX_300x300_AIRPLANE_VGG_iter_140000.caffemodel'
deploy = 'deploy.prototxt'
net = caffe.Net(deploy,caffemodel,caffe.TEST)

resolutionIn = 0.23
resolutionOut = [0.23,0.46,0.92]
widthOut = 300
heightOut = 300
widthStep = 0.65
heightStep = 0.65
batchsize = 16
score_threshold = 0.01
nms_threshold = 0.5
prior_var = [0.1, 0.1, 0.2, 0.2, 0.1]
label = 1

image = None
width = None
height = None


def training():

  net.forward()
  prior_boxes = net.blobs['mbox_priorbox_plane'].data[...]
  prior_boxes = prior_boxes[0][0]
  prior_boxes = prior_boxes.reshape(len(prior_boxes)/5,5)
  inputfile = open('prior_boxes.pkl','wb')
  pickle.dump(prior_boxes, inputfile)
  inputfile.close()
  ########### Comment the above five lines and uncomment the following ############
  ########### 3 lines to deploy the network into any caffe environment #############
  #inputfile = open('prior_boxes.pkl','rb')
  #prior_boxes = pickle.load(inputfile)
  #inputfile.close()


  print('Start detection')
  count = 0
  islast = 0
  inputdata = np.zeros((batchsize,3,heightOut,widthOut))
  inputloc = np.zeros((batchsize,3))
  rboxlist = []
  scorelist = []
  start = time.time()
  time_spent = 0
  for i in range(len(resolutionOut)):
    xBegin, yBegin = 0, 0
    width_i = int(round(width * resolutionIn / resolutionOut[i]))
    height_i = int(round(height * resolutionIn / resolutionOut[i]))
    transformer = caffe.io.Transformer({'data': [1,3,height_i,width_i]})
    print('{}'.format(net.blobs['data'].data.shape))
    transformer.set_transpose('data',(2,0,1))
    transformer.set_channel_swap('data',(2,1,0))
    transformer.set_raw_scale('data',255)
    start_inner = time.time()
    image_i = transformer.preprocess('data',image)
    end_inner = time.time()
    print('Pre-processing time = {}'.format(end_inner-start_inner))
    while 1:
      if islast == 0:
        width_S = int(round(widthOut * resolutionOut[i] / resolutionIn))
        height_S = int(round(heightOut * resolutionOut[i] / resolutionIn))
        xEnd = xBegin + width_S
        yEnd = yBegin + height_S
        xEnd = min(xEnd, width)
        yEnd = min(yEnd, height)
        xBeginHat = int(round(xBegin * resolutionIn / resolutionOut[i]))
        yBeginHat = int(round(yBegin * resolutionIn / resolutionOut[i]))
        xEndHat = int(round(xEnd * resolutionIn / resolutionOut[i]))
        yEndHat = int(round(yEnd * resolutionIn / resolutionOut[i]))
        #print('{} {} {} {}'.format(xBegin, yBegin, xEnd, yEnd))
        subimage = np.zeros((3,heightOut,widthOut))
        subimage[0:3,0:yEndHat-yBeginHat,0:xEndHat-xBeginHat] = image_i[0:3,yBeginHat:yEndHat,xBeginHat:xEndHat]
        inputdata[count] = subimage
        inputloc[count] = [xBegin,yBegin,resolutionOut[i]/resolutionIn]
      
        count = count + 1
      if count == batchsize - 1 or islast == 1:
        
        net.blobs['data'].data[...] = inputdata
        
        start_inner = time.time()
        net.forward()
        end_inner = time.time()
        time_spent = time_spent + end_inner - start_inner
        print('Inner time = {}'.format(end_inner-start_inner))
        start_inner = time.time()
        loc_preds = net.blobs['mbox_loc_plane'].data[...]
        conf_preds = net.blobs['mbox_conf_plane_flatten'].data[...]
        
        #print('prior.shape={}'.format(prior_boxes.shape))
        #print('{} and {}'.format(loc_preds.shape,conf_preds.shape))
        for j in range(batchsize):
        
          conf_preds_j = conf_preds[j][1::2]
          index = np.arange(len(conf_preds_j))
          index = index[conf_preds_j > nms_threshold]
          conf_preds_j = conf_preds_j[index]
          #print('Number of positives: {}'.format(len(index)))
          
          loc_preds_j = loc_preds[j].reshape(len(loc_preds[j])/5, 5)      ###############Loc preds output 5 number##################
          loc_preds_j = loc_preds_j[index]
          loc_preds_j = loc_preds_j.reshape(loc_preds_j.shape[0] * 5)
          
          prior_boxes_j = prior_boxes[index].reshape(len(index) * 5)
          
          if len(loc_preds_j) > 0:
            loc_c = (c_double * len(loc_preds_j))()
            prior_c = (c_double * len(prior_boxes_j))()
            conf_c = (c_double * len(conf_preds_j))()
            indices_c = (c_int * len(index))()
            for k in range(len(index)):
              loc_c[5*k] = c_double(loc_preds_j[5*k] * prior_var[0])
              loc_c[5*k+1] = c_double(loc_preds_j[5*k+1] * prior_var[1])
              loc_c[5*k+2] = c_double(loc_preds_j[5*k+2] * prior_var[2])
              loc_c[5*k+3] = c_double(loc_preds_j[5*k+3] * prior_var[3])
              loc_c[5*k+4] = c_double(loc_preds_j[5*k+4] * prior_var[4])
              indices_c[k] = c_int(-1)
              conf_c[k] = c_double(conf_preds_j[k])
            for k in range(len(index)*5):
              prior_c[k] = c_double(prior_boxes_j[k])
        
            pind = cast(indices_c, POINTER(c_int))
            pconf = cast(conf_c, POINTER(c_double))
            num_preds = c_int(len(index))
            DecodeAndNMS(loc_c, prior_c, pind, pconf, byref(num_preds), c_double(nms_threshold))
            #print('Num={}'.format(num_preds.value))
            inputloc_i = inputloc[j]
            for k in range(num_preds.value):
              index_k = indices_c[k]
              area = loc_c[5*index_k + 2] * loc_c[5*index_k + 3] * heightOut * widthOut
              if area < 1250 or area > 10000:
                continue
              rboxlist.append(loc_c[5*index_k] * widthOut * inputloc_i[2] + inputloc_i[0])
              rboxlist.append(loc_c[5*index_k + 1] * heightOut * inputloc_i[2] + inputloc_i[1])
              rboxlist.append(loc_c[5*index_k + 2] * widthOut * inputloc_i[2])
              rboxlist.append(loc_c[5*index_k + 3] * heightOut * inputloc_i[2])
              rboxlist.append(loc_c[5*index_k + 4])
              scorelist.append(conf_c[index_k])
        end_inner = time.time()
        print('Read time = {}'.format(end_inner-start_inner))
        
        count = 0
      if islast == 1:
        break
      xBegin = xBegin + int(round(widthStep * width_S))
      if xBegin >= width:
        xBegin = 0
        yBegin = yBegin + int(round(heightStep * height_S))
        if yBegin >= height:
          if i == len(resolutionOut) - 1:
            islast = 1
          else:
            break

  loc_c = (c_double * len(rboxlist))()
  score_c = (c_double * len(scorelist))()
  indices_c = (c_int * len(scorelist))()
  for i in range(len(rboxlist)):
    loc_c[i] = c_double(rboxlist[i])
  for i in range(len(scorelist)):
    score_c[i] = c_double(scorelist[i])
    indices_c[i] = c_int(-1)
  num_preds = c_int(len(scorelist))
  NMS(loc_c, indices_c, score_c, byref(num_preds), c_double(nms_threshold))
  end = time.time()

  return loc_c, score_c, indices_c, num_preds
  # fid = open('output.rbox.score','w')
  # for i in range(num_preds.value):
  #   index_i = indices_c[i]
  #   fid.write('{} {} {} {} {} {} {}\n'.format(loc_c[5*index_i],loc_c[5*index_i+1],loc_c[5*index_i+2],loc_c[5*index_i+3],label,loc_c[5*index_i+4],score_c[index_i]))
  #   print('{} {} {} {} {} {}'.format(loc_c[5*index_i],loc_c[5*index_i+1],loc_c[5*index_i+2],loc_c[5*index_i+3],loc_c[5*index_i+4],score_c[index_i]))
  # fid.close()
  # print('classification time: %f s' % (end-start))
  # print('Total inner time: %f s' % time_spent)


path = '/e/tmp/Airplane/train_data/'
save_path = '/e/tmp/Airplane/crop/'
rate = 0


def expand_square(img, background_color):
    w, h = img.size
    result = img
    if w > h:
        result = Image.new(img.mode, (w, w), background_color)
        result.paste(img, (0, (w - h) // 2))
    else:
        result = Image.new(img.mode, (h, h), background_color)
        result.paste(img, ((h - w) // 2, 0))
    return result


def crop_image(loc_c, score_c, indices_c, num_preds, file):
  filename = os.path.basename(file)
  name, ext = os.path.splitext(filename)
  print(filename)
  img = Image.open(file)
  img = expand_square(img,(0,0,0))

  result = True 
  for i in range(num_preds.value):
    filename_tmp = name+'_'+str('{0:02d}'.format(i+1))+ext
    index = indices_c[i]
    cx, cy, w, h, angle = loc_c[5*index]*rate,loc_c[5*index+1]*rate,loc_c[5*index+2]*rate,loc_c[5*index+3]*rate,loc_c[5*index+4]
    img_copy = img_clip_r(img,angle,cx,cy,w,h)
    print('{} {} {} {} {}'.format(cx,cy,w,h,angle)) 
    img_copy.save(save_path+''+filename_tmp,quality=95)

  if num_preds.value==0:
  	with open(save_path+'not_contained.txt', mode='a') as f:
            f.write(file + '\n')


def img_clip_r(img, angle, cx, cy, w, h):
    img = img.rotate(-angle,center=(cx, cy))
    x, y = cx-w/2,cy-h/2
    return img.crop((x, y, x+w,y+h))


list1 = glob.glob(path +'*.tif') 
croped_file = [re.sub(r'_[0-9]{2}.tif', '', os.path.basename(f)+'.tif') for f in glob.glob(save_path + '*.*')]
croped_path = [glob.glob(path + f) for f in croped_file][0]
list2 = list(set(list1) - set(croped_path)) 
if os.path.isfile(path):
  with open(save_path + 'not_contained.txt','r') as f:
    list2 = list(set(list2) - set(f)) 


for file in list2:
  img = Image.open(file)
  img = expand_square(img,(0,0,0))
  w = img.size[0]
  rate = w/300 
  img = img.resize((300,300))
  #img_copy.save(file,quality=95) 

  image = np.asarray(img).astype(np.float32)
  #image = caffe.io.load_image(file)
  print('Input Image Size={}'.format(image.shape))
  width = image.shape[1]
  height = image.shape[0]

  loc_c, score_c, indices_c, num_preds = training()
  crop_image(loc_c, score_c, indices_c, num_preds,file)

